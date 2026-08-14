"""BYOK integrations service for OrcaRouter and ElevenLabs."""

from __future__ import annotations

from typing import Any, Callable, Optional

import httpx

from koebinar.config import Settings, get_settings
from koebinar.crypto import decrypt_secret, encrypt_secret, generate_id, mask_key
from koebinar.integrations.elevenlabs import ElevenLabsClient, ElevenLabsError
from koebinar.integrations.errors import IntegrationError
from koebinar.integrations.voice_consent import VoiceConsentError, VoiceConsentService
from koebinar.llm.client import LLMError, OrcaRouterClient
from koebinar.models import (
    IntegrationRegisterRequest,
    IntegrationStatus,
    IntegrationView,
    Provider,
    VoiceInfo,
    VoiceRef,
    utcnow,
)
from koebinar.storage import IntegrationRecord, Store, get_store


__all__ = ["IntegrationError", "IntegrationsService", "VoiceConsentError", "HttpClientFactory"]


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
        self.voice_consent = VoiceConsentService(store=self.store, tenant_id=tenant_id)

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
        # Integration が消えた以上、その配下の Voice は即時に使用不能にする。
        if provider == Provider.ELEVENLABS:
            self.voice_consent.deactivate_for_integration(rec.id)
        # keep record for audit but mark deleted
        self.store.integrations[self._storage_key(provider)] = rec

    def active_integration_id(self, provider: Provider = Provider.ELEVENLABS) -> str | None:
        rec = self._get_record(provider)
        if rec is None or rec.status != IntegrationStatus.ACTIVE:
            return None
        return rec.id

    def get_voices(self) -> list[VoiceInfo]:
        """Read-only: fetch provider metadata and mirror it into voice refs.

        同意状態は一切変更しない。cloned/custom/不明 category は ``required`` の
        まま返り、明示的な attestation (``attest_voice_consent``) を経ない限り
        生成には使えない。
        """
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

        payloads = [v for v in (data.get("voices") or []) if isinstance(v, dict)]
        integration_id = self.active_integration_id(Provider.ELEVENLABS)
        if integration_id is None:
            # System-fallback key: no tenant-owned integration to attach consent to.
            # Surface metadata without persisting any consent-bearing state.
            return [
                VoiceInfo(
                    voice_id=v.get("voice_id") or v.get("id") or "",
                    name=v.get("name") or "unnamed",
                    category=v.get("category") or "unknown",
                    labels=v.get("labels") or {},
                    active=False,
                    usable=False,
                )
                for v in payloads
            ]
        return self.voice_consent.sync(payloads, integration_id=integration_id)

    def list_voice_refs(self) -> list[VoiceRef]:
        return self.voice_consent.list_refs()

    def attest_voice_consent(
        self,
        voice_id: str,
        *,
        accepted: bool,
        attestation_version: str,
        attested_by: str,
    ) -> VoiceRef:
        return self.voice_consent.attest(
            voice_id,
            accepted=accepted,
            attestation_version=attestation_version,
            attested_by=attested_by,
            active_integration_id=self.active_integration_id(Provider.ELEVENLABS),
        )

    def revoke_voice_consent(self, voice_id: str) -> VoiceRef:
        return self.voice_consent.revoke(voice_id)

    def assert_voice_usable(self, voice_id: str) -> VoiceRef:
        """Fail-closed gate used by webinar creation, pipeline runs, and TTS."""
        return self.voice_consent.assert_usable(voice_id)

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
            raise IntegrationError(
                "OrcaRouter APIキーを検証できませんでした",
                code="provider_validation_failed",
                status_code=422,
            ) from exc
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
        sub: dict[str, Any] | None = None
        try:
            # Voice access proves that the key is usable for Koebinar without
            # spending TTS credits. Subscription access is optional metadata.
            client.list_voices()
            try:
                sub = client.get_subscription()
            except ElevenLabsError as exc:
                if exc.status_code in (401, 403):
                    warnings.append(
                        "User Read権限がないため、プランと使用量を表示できません。"
                        "Voice一覧の接続は継続できます。TTS権限は初回生成時に検証されます。"
                    )
                elif exc.status_code == 429:
                    warnings.append(
                        "ElevenLabsのレート制限によりプランと使用量を取得できませんでした。"
                        "時間をおいて再登録すると表示できる場合があります。"
                    )
                else:
                    warnings.append(
                        "ElevenLabsの一時的な応答エラーによりプランと使用量を取得できませんでした。"
                    )
        except ElevenLabsError as exc:
            raise IntegrationError(
                self._elevenlabs_voice_validation_message(exc),
                code="provider_validation_failed",
                status_code=422,
            ) from exc
        finally:
            if self.http_client is None:
                client.close()

        if sub is None:
            return {"subscription_access": False}, warnings

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
            "subscription_access": True,
            "tier": tier,
            "status": status,
            "character_count": char_count,
            "character_limit": char_limit,
        }
        return meta, warnings

    @staticmethod
    def _elevenlabs_voice_validation_message(exc: ElevenLabsError) -> str:
        if exc.status_code == 401:
            message = (
                "ElevenLabs APIキーが無効・期限切れ、またはVoices Read権限がありません。"
                "キーの有効性とVoices Read権限を確認してください。"
            )
        elif exc.status_code == 403:
            message = (
                "ElevenLabsのVoice一覧へのアクセスが拒否されました。"
                "Voices Read権限とIP allowlistを確認してください。"
            )
        elif exc.status_code == 429:
            message = (
                "ElevenLabs APIのレート制限に達したため、キーを検証できませんでした。"
                "時間をおいて再試行してください。"
            )
        elif exc.status_code is not None and exc.status_code >= 500:
            message = "ElevenLabsの一時的な障害により、APIキーを検証できませんでした。"
        elif exc.status_code is None:
            message = "ElevenLabsに接続できないため、APIキーを検証できませんでした。"
        else:
            message = f"ElevenLabsのVoice一覧を取得できませんでした（HTTP {exc.status_code}）。"

        details: list[str] = []
        if exc.provider_code:
            details.append(f"code={exc.provider_code}")
        if exc.provider_message:
            details.append(exc.provider_message)
        if details:
            message += f" ElevenLabs応答: {' / '.join(details)}"
        return message

    def _to_view(self, rec: IntegrationRecord) -> IntegrationView:
        return IntegrationView(
            id=rec.id,
            provider=rec.provider,
            key_mask=rec.key_mask,
            status=rec.status,
            validated_at=rec.validated_at,
            meta=dict(rec.meta),
        )
