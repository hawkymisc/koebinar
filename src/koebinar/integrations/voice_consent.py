"""Tenant-scoped voice consent state and the fail-closed usage policy.

Voice 一覧の取得 (read-only sync) と同意状態の変更を分離するための単一の窓口。
生成経路 (webinar 作成 / pipeline 実行 / TTS 直前) は必ず
:meth:`VoiceConsentService.assert_usable` を通す。
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from koebinar.integrations.errors import IntegrationError
from koebinar.models import (
    SUPPORTED_ATTESTATION_VERSIONS,
    Provider,
    VoiceConsentSource,
    VoiceConsentStatus,
    VoiceInfo,
    VoiceRef,
    consent_status_for_category,
    utcnow,
)
from koebinar.storage import Store, get_store


class VoiceConsentError(IntegrationError):
    """Voice が同意ポリシー上使用できない / 同意操作が不正。

    ``IntegrationError`` を継承しているので、既存の API / pipeline の
    エラーハンドラがそのまま ``status_code`` 付きで HTTP に変換する。
    """

    def __init__(self, message: str, code: str | None = None, status_code: int = 403) -> None:
        super().__init__(message, code=code, status_code=status_code)


class VoiceConsentService:
    """Read/write access to ``store.voice_refs`` for a single tenant."""

    def __init__(
        self,
        store: Optional[Store] = None,
        tenant_id: str = "default",
        provider: Provider = Provider.ELEVENLABS,
    ) -> None:
        self.store = store or get_store()
        self.tenant_id = tenant_id
        self.provider = provider

    # --- keying -------------------------------------------------------

    def _key(self, voice_id: str) -> str:
        """Storage key. Kept identical to the pre-A-005 layout for compatibility."""
        if self.tenant_id == "default":
            return voice_id
        return f"{self.tenant_id}:{voice_id}"

    def _load(self, voice_id: str) -> VoiceRef | None:
        raw = self.store.voice_refs.get(self._key(voice_id))
        if raw is None:
            return None
        ref = VoiceRef.from_stored(raw)
        # 別テナントのキー衝突を弾く (default テナントは prefix 無しキーを使うため)。
        if ref.tenant_id != self.tenant_id or ref.voice_id != voice_id:
            return None
        return ref

    def _save(self, ref: VoiceRef) -> VoiceRef:
        self.store.voice_refs[self._key(ref.voice_id)] = ref.model_dump(mode="json")
        return ref

    # --- read ---------------------------------------------------------

    def get(self, voice_id: str) -> VoiceRef | None:
        return self._load(voice_id)

    def list_refs(self) -> list[VoiceRef]:
        refs: list[VoiceRef] = []
        for raw in self.store.voice_refs.values():
            if not isinstance(raw, dict):
                continue
            ref = VoiceRef.from_stored(raw)
            if ref.tenant_id == self.tenant_id and ref.provider == self.provider:
                refs.append(ref)
        refs.sort(key=lambda r: (r.name or "", r.voice_id))
        return refs

    # --- read-only provider sync --------------------------------------

    def sync(self, voices: Iterable[dict[str, Any]], *, integration_id: str) -> list[VoiceInfo]:
        """Mirror provider metadata into voice refs without granting consent.

        同一tenant・同一 ``voice_id`` の既存 ``attested`` は、APIキーや
        integration recordが差し替わっても保持する。同期後のVoiceRefは新しい
        integration IDへ付け替える。Provider側から消えたVoiceは
        ``active=False`` にする。
        """
        seen: set[str] = set()
        result: list[VoiceInfo] = []
        for payload in voices:
            voice_id = payload.get("voice_id") or payload.get("id") or ""
            if not voice_id:
                continue
            seen.add(voice_id)
            category = payload.get("category") or "unknown"
            labels = payload.get("labels") or {}
            existing = self._load(voice_id)
            ref = VoiceRef(
                tenant_id=self.tenant_id,
                integration_id=integration_id,
                provider=self.provider,
                voice_id=voice_id,
                name=payload.get("name") or "unnamed",
                category=category,
                labels={str(k): str(v) for k, v in labels.items()},
                active=True,
                consent_status=consent_status_for_category(category),
                synced_at=utcnow(),
            )
            if existing is not None:
                ref = self._carry_over_attestation(existing, ref)
            result.append(self._save(ref).to_voice_info())

        # Voices the provider no longer exposes for this tenant.
        for stale in self.list_refs():
            if stale.voice_id in seen or not stale.active:
                continue
            stale.active = False
            stale.synced_at = utcnow()
            self._save(stale)
        return result

    def _carry_over_attestation(self, existing: VoiceRef, fresh: VoiceRef) -> VoiceRef:
        """Preserve consent for the same tenant and stable provider voice ID.

        ``fresh`` already carries the currently active integration ID, so key
        rotation updates credential provenance without changing the consented
        Voice subject.
        """
        if existing.consent_status != VoiceConsentStatus.ATTESTED:
            return fresh
        if not existing.is_usable():
            return fresh
        if fresh.consent_status == VoiceConsentStatus.NOT_REQUIRED:
            # premade になった場合は同意不要状態が優先 (証跡は残さない)。
            return fresh
        fresh.consent_status = VoiceConsentStatus.ATTESTED
        fresh.consent_source = existing.consent_source
        fresh.attested_at = existing.attested_at
        fresh.attested_by = existing.attested_by
        fresh.attestation_version = existing.attestation_version
        return fresh

    # --- consent mutations --------------------------------------------

    def attest(
        self,
        voice_id: str,
        *,
        accepted: bool,
        attestation_version: str,
        attested_by: str,
        active_integration_id: str | None,
    ) -> VoiceRef:
        if not accepted:
            raise VoiceConsentError(
                "explicit consent is required: accepted must be true",
                code="consent_not_accepted",
                status_code=400,
            )
        if attestation_version not in SUPPORTED_ATTESTATION_VERSIONS:
            raise VoiceConsentError(
                f"unsupported attestation_version: {attestation_version}",
                code="unsupported_attestation_version",
                status_code=400,
            )
        ref = self._require_ref(voice_id)
        if active_integration_id is None:
            raise VoiceConsentError(
                "no active elevenlabs integration for this workspace",
                code="integration_inactive",
                status_code=409,
            )
        if ref.integration_id and ref.integration_id != active_integration_id:
            raise VoiceConsentError(
                "voice does not belong to the active integration",
                code="voice_integration_mismatch",
                status_code=409,
            )
        if not ref.active:
            raise VoiceConsentError(
                f"voice is not active: {voice_id}",
                code="voice_inactive",
                status_code=409,
            )
        if ref.consent_status == VoiceConsentStatus.NOT_REQUIRED:
            # premade などは同意不要。証跡は作らず現状を返す。
            return ref
        ref.consent_status = VoiceConsentStatus.ATTESTED
        ref.consent_source = VoiceConsentSource.OPERATOR_ATTESTATION
        ref.attested_at = utcnow()
        ref.attested_by = attested_by
        ref.attestation_version = attestation_version
        ref.revoked_at = None
        return self._save(ref)

    def revoke(self, voice_id: str) -> VoiceRef:
        ref = self._require_ref(voice_id)
        if ref.consent_status == VoiceConsentStatus.NOT_REQUIRED:
            raise VoiceConsentError(
                f"voice does not carry a consent attestation: {voice_id}",
                code="consent_not_attested",
                status_code=409,
            )
        ref.consent_status = VoiceConsentStatus.REQUIRED
        ref.consent_source = None
        ref.attested_at = None
        ref.attested_by = None
        ref.attestation_version = None
        ref.revoked_at = utcnow()
        return self._save(ref)

    def deactivate_for_integration(self, integration_id: str) -> None:
        """Integration 削除時に、その integration 由来の Voice を使用不能にする。"""
        for ref in self.list_refs():
            if ref.integration_id and ref.integration_id != integration_id:
                continue
            if not ref.active:
                continue
            ref.active = False
            ref.synced_at = utcnow()
            self._save(ref)

    # --- policy -------------------------------------------------------

    def _require_ref(self, voice_id: str) -> VoiceRef:
        ref = self._load(voice_id)
        if ref is None:
            raise VoiceConsentError(
                f"unknown voice for this workspace: {voice_id}",
                code="voice_not_registered",
                status_code=404,
            )
        return ref

    def assert_usable(self, voice_id: str) -> VoiceRef:
        """Fail closed unless the voice is this tenant's, active, and consented."""
        if not voice_id or not voice_id.strip():
            raise VoiceConsentError(
                "voice_id is required",
                code="voice_not_registered",
                status_code=400,
            )
        ref = self._load(voice_id)
        if ref is None:
            raise VoiceConsentError(
                f"voice is not registered for this workspace: {voice_id}. "
                "Sync the ElevenLabs voice list and record consent first.",
                code="voice_not_registered",
                status_code=403,
            )
        if not ref.active:
            raise VoiceConsentError(
                f"voice is no longer active: {voice_id}",
                code="voice_inactive",
                status_code=403,
            )
        if not ref.is_usable():
            raise VoiceConsentError(
                f"voice consent is required before generation: {voice_id} "
                f"(category={ref.category}, consent_status={ref.consent_status.value})",
                code="voice_consent_required",
                status_code=403,
            )
        return ref
