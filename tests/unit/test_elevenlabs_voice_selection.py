"""Regression coverage for provider voice selection and TTS retries."""

from __future__ import annotations

import httpx
import pytest

from koebinar.integrations.elevenlabs import ElevenLabsClient, ElevenLabsError
from koebinar.integrations.service import IntegrationsService
from koebinar.integrations.voice_consent import VoiceConsentError
from koebinar.models import (
    WebinarCreateRequest,
    WebinarStatus,
    WebinarVoicePatchRequest,
)
from koebinar.pipeline.orchestrator import PipelineError, PipelineOrchestrator
from tests.helpers import seed_attested_voice_ref


def test_reserved_default_is_not_treated_as_a_provider_voice(settings, store) -> None:
    service = IntegrationsService(store=store, settings=settings)

    with pytest.raises(VoiceConsentError) as caught:
        service.assert_voice_usable("default")

    assert caught.value.code == "voice_not_registered"


def test_failed_webinar_can_switch_to_an_attested_voice(settings, store) -> None:
    seed_attested_voice_ref(store, "voice-old")
    seed_attested_voice_ref(store, "voice-new")
    pipeline = PipelineOrchestrator(store=store, settings=settings)
    webinar = pipeline.create_webinar(
        WebinarCreateRequest(theme="voice repair", voice_id="voice-old", auto_run=False)
    )
    webinar.status = WebinarStatus.FAILED
    webinar.error = "old voice failed"
    store.webinars[webinar.id] = webinar

    updated = pipeline.patch_voice(
        webinar.id,
        WebinarVoicePatchRequest(voice_id="voice-new"),
    )

    assert updated.voice_id == "voice-new"
    assert updated.error is None
    assert store.webinars[webinar.id].voice_id == "voice-new"


def test_webinar_api_requires_and_can_patch_a_provider_voice(client, store) -> None:
    seed_attested_voice_ref(store, "voice-old")
    seed_attested_voice_ref(store, "voice-new")

    missing = client.post(
        "/api/v1/webinars",
        json={"theme": "missing voice", "auto_run": False},
    )
    assert missing.status_code == 422

    created = client.post(
        "/api/v1/webinars",
        json={"theme": "voice patch", "voice_id": "voice-old", "auto_run": False},
    )
    assert created.status_code == 200, created.text

    updated = client.patch(
        f"/api/v1/webinars/{created.json()['id']}/voice",
        json={"voice_id": "voice-new"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["voice_id"] == "voice-new"


@pytest.mark.parametrize(
    "status",
    [WebinarStatus.QUEUED, WebinarStatus.RUNNING, WebinarStatus.COMPLETED],
)
def test_in_flight_or_completed_webinar_cannot_switch_voice(settings, store, status) -> None:
    seed_attested_voice_ref(store, "voice-old")
    seed_attested_voice_ref(store, "voice-new")
    pipeline = PipelineOrchestrator(store=store, settings=settings)
    webinar = pipeline.create_webinar(
        WebinarCreateRequest(theme="voice race", voice_id="voice-old", auto_run=False)
    )
    webinar.status = status
    store.webinars[webinar.id] = webinar

    with pytest.raises(PipelineError) as caught:
        pipeline.patch_voice(
            webinar.id,
            WebinarVoicePatchRequest(voice_id="voice-new"),
        )

    assert caught.value.status_code == 409
    assert caught.value.code == "voice_change_not_allowed"
    assert store.webinars[webinar.id].voice_id == "voice-old"


def test_voice_not_found_is_not_retried() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            404,
            json={
                "detail": {
                    "status": "voice_not_found",
                    "message": "The selected voice does not exist.",
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as shared:
        client = ElevenLabsClient("sk_test", client=shared)
        with pytest.raises(ElevenLabsError) as caught:
            client.text_to_speech("missing", "hello", retries=2)

    assert calls == 1
    assert caught.value.status_code == 404
    assert caught.value.provider_code == "voice_not_found"


def test_transient_server_error_can_recover() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"detail": {"status": "system_busy"}})
        return httpx.Response(200, content=b"audio")

    with httpx.Client(transport=httpx.MockTransport(handler)) as shared:
        client = ElevenLabsClient("sk_test", client=shared)
        result = client.text_to_speech("voice", "hello", retries=2)

    assert result == b"audio"
    assert calls == 2
