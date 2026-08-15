"""A-005: cloned voice consent is explicit, tenant-scoped, and fail closed.

Spec under test (GitHub issue #9):
  1. Voice 一覧取得は同意状態を変更しない (read-only)。
  2. cloned/custom/不明 category は明示 attestation なしに使用不可。
  3. 同意は tenant / server timestamp / 文面 version / source を記録する。
  4. webinar 作成時と TTS 直前の双方で再検証する。
  5. 同意取消・integration 削除後は即座に拒否する。
  6. 旧実装が書いた推定 true (``consent_flag``) を有効な同意として引き継がない。
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from koebinar.config import Settings
from koebinar.integrations.service import IntegrationsService
from koebinar.integrations.voice_consent import VoiceConsentError, VoiceConsentService
from koebinar.models import (
    VOICE_ATTESTATION_VERSION,
    IntegrationRegisterRequest,
    Provider,
    VoiceConsentSource,
    VoiceConsentStatus,
    VoiceRef,
    WebinarCreateRequest,
)
from koebinar.pipeline.orchestrator import PipelineOrchestrator
from koebinar.pipeline.tts import TTSAdapter
from koebinar.storage import Store
from tests.helpers import CLONE_VOICE_ID, PREMADE_VOICE_ID, attest_voice, sync_and_attest
from tests.mocks.providers import VALID_EL_KEY, VALID_ORCA_KEY, install_mocks


@pytest.fixture()
def integrations(settings: Settings, store: Store, mock_providers):
    client = httpx.Client()
    svc = IntegrationsService(store=store, settings=settings, http_client=client)
    svc.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=VALID_EL_KEY))
    yield svc
    client.close()


def _voice(voices, voice_id):
    return next(v for v in voices if v.voice_id == voice_id)


# --- 1. read-only voice listing -------------------------------------------


def test_listing_voices_never_grants_consent(integrations: IntegrationsService):
    voices = integrations.get_voices()

    clone = _voice(voices, CLONE_VOICE_ID)
    assert clone.consent_status == VoiceConsentStatus.REQUIRED
    assert clone.consent_source is None
    assert clone.attested_at is None
    assert clone.usable is False


def test_premade_voices_do_not_require_tenant_attestation(integrations: IntegrationsService):
    premade = _voice(integrations.get_voices(), PREMADE_VOICE_ID)

    assert premade.consent_status == VoiceConsentStatus.NOT_REQUIRED
    assert premade.usable is True


@pytest.mark.parametrize(
    "category",
    ["cloned", "professional", "generated", "brand-new-category", "", None],
)
def test_non_premade_categories_fail_closed_to_required(store: Store, category):
    """Category が cloned/custom/未知/欠落なら常に同意必須に倒す。"""
    payload = {"voice_id": "voice_x", "name": "X"}
    if category is not None:
        payload["category"] = category

    synced = VoiceConsentService(store=store).sync([payload], integration_id="int_1")

    assert synced[0].consent_status == VoiceConsentStatus.REQUIRED
    assert synced[0].usable is False


def test_relisting_voices_does_not_reset_or_grant_consent(integrations: IntegrationsService):
    sync_and_attest(integrations)

    reloaded = _voice(integrations.get_voices(), CLONE_VOICE_ID)

    assert reloaded.consent_status == VoiceConsentStatus.ATTESTED
    assert reloaded.attestation_version == VOICE_ATTESTATION_VERSION


# --- 2/3. explicit attestation --------------------------------------------


def test_attestation_records_tenant_timestamp_version_and_source(
    integrations: IntegrationsService,
):
    integrations.get_voices()

    ref = integrations.attest_voice_consent(
        CLONE_VOICE_ID,
        accepted=True,
        attestation_version=VOICE_ATTESTATION_VERSION,
        attested_by="default",
    )

    assert ref.consent_status == VoiceConsentStatus.ATTESTED
    assert ref.consent_source == VoiceConsentSource.OPERATOR_ATTESTATION
    assert ref.attestation_version == VOICE_ATTESTATION_VERSION
    assert ref.attested_by == "default"
    assert ref.attested_at is not None
    assert ref.tenant_id == "default"
    assert ref.is_usable() is True


def test_attestation_requires_accepted_true(integrations: IntegrationsService):
    integrations.get_voices()

    with pytest.raises(VoiceConsentError) as exc:
        integrations.attest_voice_consent(
            CLONE_VOICE_ID,
            accepted=False,
            attestation_version=VOICE_ATTESTATION_VERSION,
            attested_by="default",
        )
    assert exc.value.code == "consent_not_accepted"
    assert integrations.voice_consent.get(CLONE_VOICE_ID).is_usable() is False


def test_attestation_rejects_unknown_version(integrations: IntegrationsService):
    integrations.get_voices()

    with pytest.raises(VoiceConsentError) as exc:
        integrations.attest_voice_consent(
            CLONE_VOICE_ID,
            accepted=True,
            attestation_version="voice-consent-v0",
            attested_by="default",
        )
    assert exc.value.code == "unsupported_attestation_version"


def test_attestation_rejects_voice_outside_the_workspace(integrations: IntegrationsService):
    integrations.get_voices()

    with pytest.raises(VoiceConsentError) as exc:
        integrations.attest_voice_consent(
            "voice_not_mine",
            accepted=True,
            attestation_version=VOICE_ATTESTATION_VERSION,
            attested_by="default",
        )
    assert exc.value.status_code == 404


# --- 6. fail-closed migration of legacy rows ------------------------------


def test_legacy_auto_consent_flag_is_not_honoured(store: Store):
    """旧実装の ``consent_flag: True`` (一覧取得で自動生成) は同意として扱わない。"""
    store.voice_refs[CLONE_VOICE_ID] = {
        "tenant_id": "default",
        "integration_id": "int_legacy",
        "provider": "elevenlabs",
        "voice_id": CLONE_VOICE_ID,
        "active": True,
        "consent_flag": True,
    }
    service = VoiceConsentService(store=store)

    ref = service.get(CLONE_VOICE_ID)
    assert ref.consent_status == VoiceConsentStatus.REQUIRED
    assert ref.consent_source is None
    assert ref.is_usable() is False
    with pytest.raises(VoiceConsentError):
        service.assert_usable(CLONE_VOICE_ID)


def test_attested_without_source_is_not_honoured(store: Store):
    """``consent_source`` 無しの attested は改竄・部分書き込みとみなし降格する。"""
    store.voice_refs[CLONE_VOICE_ID] = {
        "tenant_id": "default",
        "integration_id": "int_legacy",
        "provider": "elevenlabs",
        "voice_id": CLONE_VOICE_ID,
        "category": "cloned",
        "active": True,
        "consent_status": "attested",
    }

    ref = VoiceConsentService(store=store).get(CLONE_VOICE_ID)
    assert ref.consent_status == VoiceConsentStatus.REQUIRED
    assert ref.is_usable() is False


def test_attested_with_stale_attestation_version_is_not_usable():
    ref = VoiceRef(
        voice_id=CLONE_VOICE_ID,
        category="cloned",
        consent_status=VoiceConsentStatus.ATTESTED,
        consent_source=VoiceConsentSource.OPERATOR_ATTESTATION,
        attestation_version="voice-consent-v0",
    )
    assert ref.is_usable() is False


# --- tenant isolation ------------------------------------------------------


def test_consent_is_scoped_to_the_attesting_tenant(store: Store):
    acme = VoiceConsentService(store=store, tenant_id="acme")
    globex = VoiceConsentService(store=store, tenant_id="globex")
    acme.sync(
        [{"voice_id": CLONE_VOICE_ID, "name": "Clone", "category": "cloned"}],
        integration_id="int_acme",
    )
    acme.attest(
        CLONE_VOICE_ID,
        accepted=True,
        attestation_version=VOICE_ATTESTATION_VERSION,
        attested_by="acme",
        active_integration_id="int_acme",
    )

    assert acme.assert_usable(CLONE_VOICE_ID).tenant_id == "acme"
    with pytest.raises(VoiceConsentError) as exc:
        globex.assert_usable(CLONE_VOICE_ID)
    assert exc.value.code == "voice_not_registered"
    assert globex.list_refs() == []


# --- 5. revocation and integration deletion -------------------------------


def test_revocation_makes_the_voice_unusable(integrations: IntegrationsService):
    sync_and_attest(integrations)

    revoked = integrations.revoke_voice_consent(CLONE_VOICE_ID)

    assert revoked.consent_status == VoiceConsentStatus.REQUIRED
    assert revoked.consent_source is None
    assert revoked.revoked_at is not None
    with pytest.raises(VoiceConsentError) as exc:
        integrations.assert_voice_usable(CLONE_VOICE_ID)
    assert exc.value.code == "voice_consent_required"


def test_deleting_the_integration_deactivates_its_voices(integrations: IntegrationsService):
    sync_and_attest(integrations)

    integrations.delete(Provider.ELEVENLABS)

    with pytest.raises(VoiceConsentError) as exc:
        integrations.assert_voice_usable(CLONE_VOICE_ID)
    assert exc.value.code == "voice_inactive"


def test_voice_removed_from_the_provider_becomes_inactive(store: Store):
    service = VoiceConsentService(store=store)
    service.sync(
        [{"voice_id": CLONE_VOICE_ID, "name": "Clone", "category": "cloned"}],
        integration_id="int_1",
    )
    service.attest(
        CLONE_VOICE_ID,
        accepted=True,
        attestation_version=VOICE_ATTESTATION_VERSION,
        attested_by="default",
        active_integration_id="int_1",
    )

    service.sync([], integration_id="int_1")

    with pytest.raises(VoiceConsentError) as exc:
        service.assert_usable(CLONE_VOICE_ID)
    assert exc.value.code == "voice_inactive"


def test_reregistering_the_integration_preserves_voice_consent(
    integrations: IntegrationsService,
):
    """同一tenant・同一voice_idの同意はAPIキーの差し替え後も有効。"""
    sync_and_attest(integrations)
    before = integrations.voice_consent.get(CLONE_VOICE_ID)
    assert before is not None
    old_integration_id = integrations.active_integration_id()

    integrations.register(
        Provider.ELEVENLABS,
        IntegrationRegisterRequest(api_key=VALID_EL_KEY),
    )
    new_integration_id = integrations.active_integration_id()
    resynced = _voice(integrations.get_voices(), CLONE_VOICE_ID)
    persisted = integrations.voice_consent.get(CLONE_VOICE_ID)
    assert persisted is not None

    assert new_integration_id != old_integration_id
    assert resynced.consent_status == VoiceConsentStatus.ATTESTED
    assert resynced.usable is True
    assert resynced.attested_at == before.attested_at
    assert persisted.integration_id == new_integration_id


# --- 4. generation paths are fail closed ----------------------------------


def test_webinar_creation_rejects_a_voice_without_consent(
    settings: Settings, store: Store, mock_providers
):
    client = httpx.Client()
    svc = IntegrationsService(store=store, settings=settings, http_client=client)
    svc.register(Provider.ORCAROUTER, IntegrationRegisterRequest(api_key=VALID_ORCA_KEY))
    svc.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=VALID_EL_KEY))
    svc.get_voices()
    orch = PipelineOrchestrator(store=store, settings=settings, http_client=client)

    with pytest.raises(VoiceConsentError) as exc:
        orch.create_webinar(
            WebinarCreateRequest(theme="no consent", voice_id=CLONE_VOICE_ID, auto_run=True)
        )
    assert exc.value.code == "voice_consent_required"
    assert store.webinars.values() == []
    client.close()


def test_webinar_creation_rejects_an_unconsented_clone_when_auto_run_is_false(
    settings: Settings, store: Store, integrations: IntegrationsService
):
    """Draft creation must not become a way around the consent gate."""
    integrations.get_voices()
    orch = PipelineOrchestrator(store=store, settings=settings)

    with pytest.raises(VoiceConsentError) as exc:
        orch.create_webinar(
            WebinarCreateRequest(theme="draft without consent", voice_id=CLONE_VOICE_ID, auto_run=False)
        )

    assert exc.value.code == "voice_consent_required"
    assert store.webinars.values() == []


def test_premade_voice_is_allowed_without_tenant_attestation(
    settings: Settings, store: Store, integrations: IntegrationsService
):
    integrations.get_voices()
    orch = PipelineOrchestrator(store=store, settings=settings)

    webinar = orch.create_webinar(
        WebinarCreateRequest(theme="premade draft", voice_id=PREMADE_VOICE_ID, auto_run=False)
    )

    assert webinar.voice_id == PREMADE_VOICE_ID


def test_default_voice_is_rejected_as_unregistered(settings: Settings, store: Store):
    service = IntegrationsService(store=store, settings=settings)

    with pytest.raises(VoiceConsentError) as exc:
        service.assert_voice_usable("default")

    assert exc.value.code == "voice_not_registered"


def test_webinar_creation_rejects_an_arbitrary_voice_id(
    settings: Settings, store: Store, mock_providers
):
    client = httpx.Client()
    svc = IntegrationsService(store=store, settings=settings, http_client=client)
    svc.register(Provider.ORCAROUTER, IntegrationRegisterRequest(api_key=VALID_ORCA_KEY))
    svc.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=VALID_EL_KEY))
    orch = PipelineOrchestrator(store=store, settings=settings, http_client=client)

    with pytest.raises(VoiceConsentError) as exc:
        orch.create_webinar(
            WebinarCreateRequest(theme="arbitrary", voice_id="voice_someone_else", auto_run=True)
        )
    assert exc.value.code == "voice_not_registered"
    client.close()


def test_tts_revalidates_consent_revoked_after_the_job_was_queued(
    settings: Settings, store: Store, mock_providers
):
    """非同期 job 待機中に同意が取り消されたら、外部 TTS を呼ばずに失敗する。"""
    client = httpx.Client()
    svc = IntegrationsService(store=store, settings=settings, http_client=client)
    svc.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=VALID_EL_KEY))
    sync_and_attest(svc)
    tts = TTSAdapter(store=store, settings=settings, integrations=svc, http_client=client)
    prepared = {
        "slides": [{"slide_index": 0, "sentences": ["こんにちは"], "title": "t"}],
        "total_credits": 5,
    }
    svc.revoke_voice_consent(CLONE_VOICE_ID)

    with respx.mock(assert_all_called=False) as router:
        tts_route = router.post(url__regex=r".*/text-to-speech/.*").respond(200, content=b"")
        with pytest.raises(VoiceConsentError) as exc:
            tts.synthesize_script("web_revoked", prepared, CLONE_VOICE_ID, "ja")

    assert exc.value.code == "voice_consent_required"
    assert tts_route.call_count == 0, "revoked consent must not reach the TTS provider"
    client.close()


def test_tts_revalidates_after_the_integration_was_deleted(
    settings: Settings, store: Store, mock_providers
):
    client = httpx.Client()
    svc = IntegrationsService(store=store, settings=settings, http_client=client)
    svc.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=VALID_EL_KEY))
    sync_and_attest(svc)
    tts = TTSAdapter(store=store, settings=settings, integrations=svc, http_client=client)
    prepared = {"slides": [{"slide_index": 0, "sentences": ["hi"], "title": "t"}], "total_credits": 2}
    svc.delete(Provider.ELEVENLABS)

    with respx.mock(assert_all_called=False) as router:
        tts_route = router.post(url__regex=r".*/text-to-speech/.*").respond(200, content=b"")
        with pytest.raises(VoiceConsentError) as exc:
            tts.synthesize_script("web_deleted", prepared, CLONE_VOICE_ID, "ja")

    assert exc.value.code == "voice_inactive"
    assert tts_route.call_count == 0
    client.close()


# --- API surface -----------------------------------------------------------


def test_voices_endpoint_is_read_only(client: TestClient, register_keys_only):
    register_keys_only()

    body = client.get("/api/v1/integrations/elevenlabs/voices").json()

    assert body["attestation_version"] == VOICE_ATTESTATION_VERSION
    clone = next(v for v in body["voices"] if v["voice_id"] == CLONE_VOICE_ID)
    assert clone["consent_status"] == "required"
    assert clone["usable"] is False
    # 再取得しても同意済みにはならない
    again = client.get("/api/v1/integrations/elevenlabs/voices").json()
    assert next(v for v in again["voices"] if v["voice_id"] == CLONE_VOICE_ID)["usable"] is False


def test_consent_endpoint_records_and_revokes(client: TestClient, register_keys_only):
    register_keys_only()
    client.get("/api/v1/integrations/elevenlabs/voices")

    granted = client.post(
        f"/api/v1/integrations/elevenlabs/voices/{CLONE_VOICE_ID}/consent",
        json={"accepted": True, "attestation_version": VOICE_ATTESTATION_VERSION},
    )
    assert granted.status_code == 200
    assert granted.json()["consent_status"] == "attested"
    assert granted.json()["consent_source"] == "operator_attestation"
    assert granted.json()["attested_by"] == "default"
    assert granted.json()["usable"] is True

    revoked = client.delete(
        f"/api/v1/integrations/elevenlabs/voices/{CLONE_VOICE_ID}/consent"
    )
    assert revoked.status_code == 200
    assert revoked.json()["consent_status"] == "required"
    assert revoked.json()["usable"] is False


def test_consent_endpoint_rejects_accepted_false(client: TestClient, register_keys_only):
    register_keys_only()
    client.get("/api/v1/integrations/elevenlabs/voices")

    denied = client.post(
        f"/api/v1/integrations/elevenlabs/voices/{CLONE_VOICE_ID}/consent",
        json={"accepted": False, "attestation_version": VOICE_ATTESTATION_VERSION},
    )
    assert denied.status_code == 400

    omitted = client.post(
        f"/api/v1/integrations/elevenlabs/voices/{CLONE_VOICE_ID}/consent",
        json={},
    )
    assert omitted.status_code == 400


def test_consent_endpoints_require_auth(client: TestClient):
    unauthorized = {"Authorization": "Bearer wrong"}
    assert client.post(
        f"/api/v1/integrations/elevenlabs/voices/{CLONE_VOICE_ID}/consent",
        json={"accepted": True, "attestation_version": VOICE_ATTESTATION_VERSION},
        headers=unauthorized,
    ).status_code == 401
    assert client.delete(
        f"/api/v1/integrations/elevenlabs/voices/{CLONE_VOICE_ID}/consent",
        headers=unauthorized,
    ).status_code == 401


def test_webinar_api_rejects_unconsented_voice(client: TestClient, register_keys_only):
    register_keys_only()
    client.get("/api/v1/integrations/elevenlabs/voices")

    response = client.post(
        "/api/v1/webinars",
        json={"theme": "no consent", "voice_id": CLONE_VOICE_ID, "auto_run": True},
    )

    assert response.status_code == 403
    assert CLONE_VOICE_ID in response.json()["detail"]


def test_webinar_api_rejects_unconsented_voice_when_auto_run_is_false(
    client: TestClient, register_keys_only
):
    register_keys_only()
    client.get("/api/v1/integrations/elevenlabs/voices")

    response = client.post(
        "/api/v1/webinars",
        json={"theme": "draft no consent", "voice_id": CLONE_VOICE_ID, "auto_run": False},
    )

    assert response.status_code == 403
    assert client.get("/api/v1/webinars").json() == []


def test_running_a_step_after_revocation_is_rejected(client: TestClient, register_keys):
    register_keys()
    created = client.post(
        "/api/v1/webinars",
        json={"theme": "revoke later", "voice_id": CLONE_VOICE_ID, "auto_run": False},
    ).json()
    client.delete(f"/api/v1/integrations/elevenlabs/voices/{CLONE_VOICE_ID}/consent")

    response = client.post(f"/api/v1/webinars/{created['id']}/steps/outline/run")

    assert response.status_code == 403
