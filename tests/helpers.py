"""Shared test helpers for voice consent (A-005) setup."""

from __future__ import annotations

from fastapi.testclient import TestClient

from koebinar.integrations.service import IntegrationsService
from koebinar.integrations.voice_consent import VoiceConsentService
from koebinar.models import (
    VOICE_ATTESTATION_VERSION,
    VoiceConsentSource,
    VoiceConsentStatus,
    VoiceRef,
    utcnow,
)
from koebinar.storage import Store

# Voice IDs exposed by the ElevenLabs mock (see tests/mocks/providers.py).
CLONE_VOICE_ID = "voice_clone_ja_en_01"
PREMADE_VOICE_ID = "voice_system_demo"


def sync_and_attest(
    integrations: IntegrationsService,
    voice_id: str = CLONE_VOICE_ID,
) -> None:
    """Service-level equivalent of an operator syncing voices and consenting."""
    integrations.get_voices()
    integrations.attest_voice_consent(
        voice_id,
        accepted=True,
        attestation_version=VOICE_ATTESTATION_VERSION,
        attested_by=integrations.tenant_id,
    )


def seed_attested_voice_ref(
    store: Store,
    voice_id: str,
    *,
    tenant_id: str = "default",
    integration_id: str = "int_seed",
) -> VoiceRef:
    """Seed an already-attested voice ref for voices the mock provider lacks."""
    ref = VoiceRef(
        tenant_id=tenant_id,
        integration_id=integration_id,
        voice_id=voice_id,
        name=voice_id,
        category="cloned",
        active=True,
        consent_status=VoiceConsentStatus.ATTESTED,
        consent_source=VoiceConsentSource.OPERATOR_ATTESTATION,
        attested_at=utcnow(),
        attested_by=tenant_id,
        attestation_version=VOICE_ATTESTATION_VERSION,
    )
    service = VoiceConsentService(store=store, tenant_id=tenant_id)
    store.voice_refs[service._key(voice_id)] = ref.model_dump(mode="json")
    return ref


def attest_voice(client: TestClient, voice_id: str = CLONE_VOICE_ID) -> dict:
    """API-level equivalent: GET voices (read-only sync) then POST consent."""
    listed = client.get("/api/v1/integrations/elevenlabs/voices")
    assert listed.status_code == 200, listed.text
    response = client.post(
        f"/api/v1/integrations/elevenlabs/voices/{voice_id}/consent",
        json={"accepted": True, "attestation_version": VOICE_ATTESTATION_VERSION},
    )
    assert response.status_code == 200, response.text
    return response.json()
