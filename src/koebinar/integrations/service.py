"""BYOK integrations service for OrcaRouter and ElevenLabs."""

from __future__ import annotations

from typing import Any, Callable, Optional

import httpx

from koebinar.config import Settings, get_settings
from koebinar.crypto import decrypt_secret, encrypt_secret, generate_id, mask_key
from koebinar.integrations.elevenlabs import ElevenLabsClient, ElevenLabsError
from koebinar.llm.client import LLMError, OrcaRouterClient
from koebinar.models import (
    IntegrationRegisterRequest,
    IntegrationStatus,
    IntegrationView,
    Provider,
    VoiceInfo,
    utcnow,
)
from koebinar.storage import IntegrationRecord, Store, get_store


class IntegrationError(Exception):
    def __init__(self, message: str, code: str | None = None, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


HttpClientFactory = Callable[[], httpx.Client]


class IntegrationsService:
    def __init__(
        self,
        store: Optional[Store] = None,
        settings: Optional[Settings] = None,
        http_client: Optional[httpx.Client] = None,
        tenant_id: str = "default",
    ) -> None:
        self.store = store or get_store()
        self.settings = settings or get_settings()
        self.http_client = http_client
        self.tenant_id = tenant_id

    def _storage_key(self, provider: Provider) -> Provider | str:
        if self.tenant_id == "default":
            return provider
        return f"{self.tenant_id}:{provider.value}"

    def _get_record(self, provider: Provider) -> IntegrationRecord | None:
        record = self.store.integrations.get(self._storage_key(provider))
        if record is None or record.tenant_id != self.tenant_id:
            return None
        return record

    def register(self, provider: Provider, req: IntegrationRegisterRequest) -> IntegrationView:
        if provider not in (Provider.ORCAROUTER, Provider.ELEVENLABS):
            raise IntegrationError(f"unsupported provider: {provider}", code="unsupported_provider", status_code=400)
        if not req.api_key or not req.api_key.strip():
            raise IntegrationError("api_key is required", code="missing_key", status_code=400)

        meta: dict[str, Any] = {}
        warnings: list[str] = []

        if provider == Provider.ORCAROUTER:
            meta = self._validate_orcarouter(req.api_key)
        else:
            meta, warnings = self._validate_elevenlabs(req.api_key, accept_free_tier=req.accept_free_tier)

        encrypted = encrypt_secret(req.api_key, self.settings.master_key)
        record = IntegrationRecord(
            id=generate_id("int_"),
            tenant_id=self.tenant_id,
            provider=provider,
            encrypted_api_key=encrypted,
            key_mask=mask_key(req.api_key),
            status=IntegrationStatus.ACTIVE,
            validated_at=utcnow(),
            meta={**meta, "warnings": warnings},
        )
        self.store.integrations[self._storage_key(provider)] = record
        return self._to_view(record)

    def list_all(self) -> list[IntegrationView]:
        return [
            self._to_view(record)
            for record in self.store.integrations.values()
            if record.tenant_id == self.tenant_id and record.status != IntegrationStatus.DELETED
        ]

    def delete(self, provider: Provider) -> None:
        rec = self._get_record(provider)
        if rec is None:
            raise IntegrationError(f"no integration for {provider.value}", code="not_found", status_code=404)
        rec.status = IntegrationStatus.DELETED
        rec.encrypted_api_key = ""
        # invalidate voice refs for EL (re-assign for durable store write-through)
        if provider == Provider.ELEVENLABS:
            for vid, vr in list(self.store.voice_refs.items()):
                if vr.get("integration_id") == rec.id:
                    updated = dict(vr)
                    updated["active"] = False
                    self.store.voice_refs[vid] = updated
        # keep record for audit but mark deleted
        self.store.integrations[self._storage_key(provider)] = rec

    def get_voices(self) -> list[VoiceInfo]:
        key = self.resolve_api_key(Provider.ELEVENLABS, require=True)
        client = ElevenLabsClient(
            key,
            base_url=self.settings.elevenlabs_base_url,
            settings=self.settings,
            client=self.http_client,
        )
        try:
            data = client.list_voices()
        except ElevenLabsError as exc:
            raise IntegrationError(str(exc), code="voices_failed", status_code=exc.status_code or 502) from exc
        finally:
            if self.http_client is None:
                client.close()
        voices = []
        for v in data.get("voices", []):
            voices.append(
                VoiceInfo(
                    voice_id=v.get("voice_id") or v.get("id") or "",
                    name=v.get("name") or "unnamed",
                    category=v.get("category") or "cloned",
                    labels=v.get("labels") or {},
                )
            )
            # track voice refs
            rec = self._get_record(Provider.ELEVENLABS)
            if rec and rec.status == IntegrationStatus.ACTIVE:
                voice_key = (
                    voices[-1].voice_id
                    if self.tenant_id == "default"
                    else f"{self.tenant_id}:{voices[-1].voice_id}"
                )
                self.store.voice_refs[voice_key] = {
                    "tenant_id": self.tenant_id,
                    "integration_id": rec.id,
                    "provider": Provider.ELEVENLABS.value,
                    "voice_id": voices[-1].voice_id,
                    "active": True,
                    "consent_flag": True,
                }
        return voices

    def resolve_api_key(self, provider: Provider, *, require: bool = False) -> str:
        """Key resolution: ① registered BYOK → ② system fallback if flag allows."""
        rec = self._get_record(provider)
        if rec and rec.status == IntegrationStatus.ACTIVE and rec.encrypted_api_key:
            try:
                return decrypt_secret(rec.encrypted_api_key, self.settings.master_key)
            except ValueError:
                rec.status = IntegrationStatus.INVALID
                self.store.integrations[self._storage_key(provider)] = rec
                if require:
                    raise IntegrationError(
                        f"{provider.value} key decrypt failed",
                        code="invalid_key",
                        status_code=401,
                    )
                return ""

        if provider == Provider.ORCAROUTER and self.settings.allow_system_llm_key and self.settings.orcarouter_api_key:
            return self.settings.orcarouter_api_key
        if provider == Provider.ELEVENLABS and self.settings.allow_system_tts_key and self.settings.elevenlabs_api_key:
            return self.settings.elevenlabs_api_key

        if require:
            raise IntegrationError(
                f"no API key available for {provider.value}",
                code="missing_key",
                status_code=401,
            )
        return ""

    def mark_invalid(self, provider: Provider) -> None:
        rec = self._get_record(provider)
        if rec:
            rec.status = IntegrationStatus.INVALID
            self.store.integrations[self._storage_key(provider)] = rec

    def _validate_orcarouter(self, api_key: str) -> dict[str, Any]:
        client = OrcaRouterClient(
            api_key,
            base_url=self.settings.orcarouter_base_url,
            settings=self.settings,
            client=self.http_client,
        )
        try:
            models = client.list_models()
        except LLMError as exc:
            raise IntegrationError(str(exc), code="validation_failed", status_code=exc.status_code or 400) from exc
        finally:
            if self.http_client is None:
                client.close()
        data = models.get("data") or []
        return {"model_count": len(data), "models_sample": [m.get("id") for m in data[:5]]}

    def _validate_elevenlabs(self, api_key: str, *, accept_free_tier: bool) -> tuple[dict[str, Any], list[str]]:
        client = ElevenLabsClient(
            api_key,
            base_url=self.settings.elevenlabs_base_url,
            settings=self.settings,
            client=self.http_client,
        )
        warnings: list[str] = []
        try:
            sub = client.get_subscription()
            client.list_voices()  # scope check
        except ElevenLabsError as exc:
            raise IntegrationError(str(exc), code="validation_failed", status_code=exc.status_code or 400) from exc
        finally:
            if self.http_client is None:
                client.close()

        tier = str(sub.get("tier") or sub.get("plan") or "unknown")
        status = str(sub.get("status") or "active")
        char_count = int(sub.get("character_count") or 0)
        char_limit = int(sub.get("character_limit") or 0)
        if tier.lower() == "free":
            warnings.append(
                "Free tier: commercial use restricted; public content may require attribution."
            )
            if not accept_free_tier:
                raise IntegrationError(
                    "Free tier requires accept_free_tier=true confirmation",
                    code="free_tier_confirm",
                    status_code=400,
                )
        meta = {
            "tier": tier,
            "status": status,
            "character_count": char_count,
            "character_limit": char_limit,
        }
        return meta, warnings

    def _to_view(self, rec: IntegrationRecord) -> IntegrationView:
        return IntegrationView(
            id=rec.id,
            provider=rec.provider,
            key_mask=rec.key_mask,
            status=rec.status,
            validated_at=rec.validated_at,
            meta=dict(rec.meta),
        )
