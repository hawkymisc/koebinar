from __future__ import annotations

from koebinar.models import VOICE_ATTESTATION_VERSION, Provider
from tests.mocks.providers import CREATED_VOICE_ID, VALID_EL_KEY


CLONE_PATH = "/api/v1/integrations/elevenlabs/voices/clone"


def _register_elevenlabs(client) -> None:
    response = client.post(
        "/api/v1/integrations/elevenlabs",
        json={"api_key": VALID_EL_KEY, "accept_free_tier": False},
    )
    assert response.status_code == 200, response.text


def _clone_form(**overrides):
    data = {
        "name": "Koebinar Speaker",
        "description": "Clear Japanese narration",
        "remove_background_noise": "false",
        "consent_confirmed": "true",
        "attestation_version": VOICE_ATTESTATION_VERSION,
    }
    data.update(overrides)
    return data


def _provider_clone_was_called(mock_providers) -> bool:
    return any(call.request.url.path.endswith("/voices/add") for call in mock_providers.calls)


def test_create_voice_clone_registers_and_attests_voice(client):
    _register_elevenlabs(client)

    response = client.post(
        CLONE_PATH,
        data=_clone_form(),
        files=[("files", ("sample.mp3", b"fake-audio", "audio/mpeg"))],
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["requires_verification"] is False
    assert payload["attestation_version"] == VOICE_ATTESTATION_VERSION
    assert payload["voice"] == {
        "voice_id": CREATED_VOICE_ID,
        "name": "Koebinar Speaker",
        "category": "cloned",
        "labels": {"source": "koebinar_ivc"},
        "active": True,
        "consent_status": "attested",
        "consent_source": "operator_attestation",
        "attested_at": payload["voice"]["attested_at"],
        "attested_by": "default",
        "attestation_version": VOICE_ATTESTATION_VERSION,
        "usable": True,
    }


def test_create_voice_clone_requires_tenant_byok(client):
    response = client.post(
        CLONE_PATH,
        data=_clone_form(),
        files=[("files", ("sample.wav", b"sample", "audio/wav"))],
    )

    assert response.status_code == 409
    assert "active tenant ElevenLabs integration" in response.json()["detail"]


def test_create_voice_clone_rejects_missing_consent_before_provider_call(client, mock_providers):
    _register_elevenlabs(client)
    response = client.post(
        CLONE_PATH,
        data=_clone_form(consent_confirmed="false"),
        files=[("files", ("sample.mp3", b"sample", "audio/mpeg"))],
    )

    assert response.status_code == 400
    assert "consent" in response.json()["detail"]
    assert not _provider_clone_was_called(mock_providers)


def test_create_voice_clone_rejects_invalid_or_empty_sample(client, mock_providers):
    _register_elevenlabs(client)
    invalid = client.post(
        CLONE_PATH,
        data=_clone_form(),
        files=[("files", ("sample.txt", b"not-audio", "text/plain"))],
    )
    empty = client.post(
        CLONE_PATH,
        data=_clone_form(),
        files=[("files", ("sample.mp3", b"", "audio/mpeg"))],
    )

    assert invalid.status_code == 422
    assert empty.status_code == 422
    assert not _provider_clone_was_called(mock_providers)


def test_create_voice_clone_rejects_oversized_sample(client, mock_providers):
    _register_elevenlabs(client)
    response = client.post(
        CLONE_PATH,
        data=_clone_form(),
        files=[("files", ("sample.mp3", b"x" * (10 * 1024 * 1024 + 1), "audio/mpeg"))],
    )

    assert response.status_code == 413
    assert not _provider_clone_was_called(mock_providers)


def test_create_voice_clone_rejects_oversized_declared_request_before_parsing(client):
    response = client.post(
        CLONE_PATH,
        headers={"Content-Length": str(27 * 1024 * 1024)},
        content=b"not-parsed",
    )

    assert response.status_code == 413
    assert "26 MiB" in response.json()["detail"]


def test_create_voice_clone_requires_valid_content_length_before_parsing(client):
    response = client.post(
        CLONE_PATH,
        headers={"Content-Length": "invalid"},
        content=b"not-parsed",
    )

    assert response.status_code == 411
    assert "Content-Length" in response.json()["detail"]


def test_create_voice_clone_rejects_too_many_or_oversized_total_samples(client, mock_providers):
    _register_elevenlabs(client)
    too_many = client.post(
        CLONE_PATH,
        data=_clone_form(),
        files=[("files", (f"sample-{index}.mp3", b"x", "audio/mpeg")) for index in range(6)],
    )
    oversized_total = client.post(
        CLONE_PATH,
        data=_clone_form(),
        files=[
            ("files", ("one.mp3", b"x" * (9 * 1024 * 1024), "audio/mpeg")),
            ("files", ("two.mp3", b"x" * (9 * 1024 * 1024), "audio/mpeg")),
            ("files", ("three.mp3", b"x" * (8 * 1024 * 1024), "audio/mpeg")),
        ],
    )

    assert too_many.status_code == 422
    assert oversized_total.status_code == 413
    assert not _provider_clone_was_called(mock_providers)


def test_create_voice_clone_rejects_stale_attestation_version(client, mock_providers):
    _register_elevenlabs(client)
    response = client.post(
        CLONE_PATH,
        data=_clone_form(attestation_version="voice-consent-stale"),
        files=[("files", ("sample.mp3", b"sample", "audio/mpeg"))],
    )

    assert response.status_code == 400
    assert not _provider_clone_was_called(mock_providers)


def test_provider_auth_and_permission_errors_do_not_become_operator_401(client):
    _register_elevenlabs(client)

    unauthorized = client.post(
        CLONE_PATH,
        data=_clone_form(name="provider-unauthorized"),
        files=[("files", ("sample.mp3", b"sample", "audio/mpeg"))],
    )

    assert unauthorized.status_code == 422
    assert "invalid_api_key" in unauthorized.json()["detail"]

    # Re-register after the simulated invalid-key response marked the record invalid.
    _register_elevenlabs(client)
    forbidden = client.post(
        CLONE_PATH,
        data=_clone_form(name="provider-forbidden"),
        files=[("files", ("sample.mp3", b"sample", "audio/mpeg"))],
    )
    assert forbidden.status_code == 422
    assert "missing_permissions" in forbidden.json()["detail"]


def test_byok_decryption_failure_does_not_become_operator_401(client, store, mock_providers):
    _register_elevenlabs(client)
    record = store.integrations[Provider.ELEVENLABS]
    record.encrypted_api_key = "not-valid-ciphertext"
    store.integrations[Provider.ELEVENLABS] = record

    response = client.post(
        CLONE_PATH,
        data=_clone_form(),
        files=[("files", ("sample.mp3", b"sample", "audio/mpeg"))],
    )

    assert response.status_code == 422
    assert not _provider_clone_was_called(mock_providers)


def test_provider_transient_and_invalid_json_errors_keep_safe_statuses(client):
    _register_elevenlabs(client)
    cases = [
        ("provider-rate-limited", 429, "rate_limit_exceeded"),
        ("provider-unavailable", 503, "service_unavailable"),
        ("provider-invalid-json", 502, "valid JSON"),
    ]

    for name, expected_status, expected_detail in cases:
        response = client.post(
            CLONE_PATH,
            data=_clone_form(name=name),
            files=[("files", ("sample.mp3", b"sample", "audio/mpeg"))],
        )
        assert response.status_code == expected_status
        assert expected_detail in response.json()["detail"]
