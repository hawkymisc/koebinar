"""OrcaRouter timeout, retry, and error-classification regression tests."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from koebinar.config import Settings
from koebinar.crypto import encrypt_secret
from koebinar.llm.client import LLMError, OrcaRouterClient
from koebinar.models import IntegrationStatus, Lang, Provider, Style, Template, Webinar
from koebinar.pipeline.steps import GenerationSteps
from koebinar.storage import IntegrationRecord, Store


def _chat_response(content: str = '{"ok": true}') -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": content}}]},
    )


def test_official_auto_router_is_the_default_model() -> None:
    assert Settings().llm_model == "orcarouter/auto"


def test_orcarouter_request_overrides_shared_client_timeout() -> None:
    seen: list[dict[str, float]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"])
        return _chat_response()

    settings = Settings(
        orcarouter_connect_timeout_sec=7,
        orcarouter_read_timeout_sec=601,
        orcarouter_write_timeout_sec=31,
        orcarouter_pool_timeout_sec=11,
    )
    shared = httpx.Client(transport=httpx.MockTransport(handler), timeout=0.01)
    client = OrcaRouterClient("key", settings=settings, client=shared)

    assert client.chat_json([{"role": "user", "content": "hello"}]) == {"ok": True}
    assert seen == [{"connect": 7.0, "read": 601.0, "write": 31.0, "pool": 11.0}]
    shared.close()


def test_models_validation_keeps_a_short_read_timeout() -> None:
    seen: list[dict[str, float]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, json={"object": "list", "data": []})

    settings = Settings(
        orcarouter_connect_timeout_sec=7,
        orcarouter_models_read_timeout_sec=29,
        orcarouter_read_timeout_sec=601,
        orcarouter_write_timeout_sec=31,
        orcarouter_pool_timeout_sec=11,
    )
    shared = httpx.Client(transport=httpx.MockTransport(handler), timeout=0.01)
    client = OrcaRouterClient("key", settings=settings, client=shared)

    assert client.list_models()["data"] == []
    assert seen == [{"connect": 7.0, "read": 29.0, "write": 31.0, "pool": 11.0}]
    shared.close()


def test_read_timeout_retries_once_with_backoff_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("slow response", request=request)
        return _chat_response()

    settings = Settings(orcarouter_retry_backoff_sec=0.25, orcarouter_max_retries=1)
    shared = httpx.Client(transport=httpx.MockTransport(handler))
    client = OrcaRouterClient("key", settings=settings, client=shared)

    with patch("koebinar.llm.client.time.sleep") as sleep:
        assert client.chat_json([{"role": "user", "content": "hello"}]) == {"ok": True}

    assert calls == 2
    sleep.assert_called_once_with(0.25)
    shared.close()


@pytest.mark.parametrize("status", [400, 404, 425])
def test_permanent_client_errors_are_not_retried(status: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status,
            json={"error": {"type": "orcarouter_api_error", "code": "bad_request_body"}},
        )

    shared = httpx.Client(transport=httpx.MockTransport(handler))
    client = OrcaRouterClient("key", client=shared)

    with pytest.raises(LLMError) as caught:
        client.chat_completions([{"role": "user", "content": "hello"}])

    assert caught.value.status_code == status
    assert calls == 1
    shared.close()


@pytest.mark.parametrize("code", ["model_not_found", "byok:key_unavailable"])
def test_terminal_503_codes_are_not_retried(code: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            503,
            json={"error": {"type": "orcarouter_api_error", "code": code}},
        )

    shared = httpx.Client(transport=httpx.MockTransport(handler))
    client = OrcaRouterClient("key", client=shared)

    with pytest.raises(LLMError) as caught:
        client.chat_completions([{"role": "user", "content": "hello"}])

    assert caught.value.error_code == code
    assert calls == 1
    shared.close()


def test_transient_503_retries_then_succeeds() -> None:
    responses = iter(
        [
            httpx.Response(503, json={"error": {"type": "upstream_error", "code": ""}}),
            _chat_response(),
        ]
    )
    shared = httpx.Client(transport=httpx.MockTransport(lambda request: next(responses)))
    client = OrcaRouterClient("key", client=shared)

    with patch("koebinar.llm.client.time.sleep") as sleep:
        assert client.chat_json([{"role": "user", "content": "hello"}]) == {"ok": True}

    sleep.assert_called_once_with(client.settings.orcarouter_retry_backoff_sec)
    shared.close()


def test_429_honors_retry_after_seconds() -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "3"}),
            _chat_response(),
        ]
    )
    shared = httpx.Client(transport=httpx.MockTransport(lambda request: next(responses)))
    client = OrcaRouterClient("key", client=shared)

    with patch("koebinar.llm.client.time.sleep") as sleep:
        assert client.chat_json([{"role": "user", "content": "hello"}]) == {"ok": True}

    sleep.assert_called_once_with(3.0)
    shared.close()


@pytest.mark.parametrize("retry_after", [None, "not-a-number", "120"])
def test_429_without_safe_retry_window_is_not_retried(retry_after: str | None) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        headers = {"Retry-After": retry_after} if retry_after is not None else None
        return httpx.Response(429, headers=headers)

    settings = Settings(orcarouter_retry_max_delay_sec=60)
    shared = httpx.Client(transport=httpx.MockTransport(handler))
    client = OrcaRouterClient("key", settings=settings, client=shared)

    with pytest.raises(LLMError):
        client.chat_completions([{"role": "user", "content": "hello"}])

    assert calls == 1
    shared.close()


def test_403_is_forbidden_without_invalidating_the_key_classification() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "error": {
                    "message": "workspace balance exhausted",
                    "type": "orcarouter_api_error",
                    "code": "insufficient_user_quota",
                }
            },
        )

    shared = httpx.Client(transport=httpx.MockTransport(handler))
    client = OrcaRouterClient("key", client=shared)

    with pytest.raises(LLMError) as caught:
        client.chat_completions([{"role": "user", "content": "hello"}])

    assert caught.value.status_code == 403
    assert caught.value.error_code == "insufficient_user_quota"
    assert "invalid or unauthorized" not in str(caught.value)
    shared.close()


def test_json_mode_falls_back_only_when_upstream_does_not_implement_it() -> None:
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.content)
        payloads.append(payload)
        if "response_format" in payload:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "type": "orcarouter_api_error",
                        "code": "api_not_implemented",
                    }
                },
            )
        return _chat_response()

    shared = httpx.Client(transport=httpx.MockTransport(handler))
    client = OrcaRouterClient("key", client=shared)

    assert client.chat_json([{"role": "user", "content": "JSON only"}]) == {"ok": True}
    assert len(payloads) == 2
    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in payloads[1]
    shared.close()


def test_json_mode_can_disable_transport_retries_for_interactive_qa() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("slow routed model", request=request)

    settings = Settings(orcarouter_max_retries=2)
    shared = httpx.Client(transport=httpx.MockTransport(handler))
    client = OrcaRouterClient("key", settings=settings, client=shared)

    with pytest.raises(LLMError):
        client.chat_json([{"role": "user", "content": "JSON only"}], retries=0)

    assert attempts == 1
    shared.close()


def test_generation_403_does_not_mark_registered_key_invalid(
    settings: Settings,
    store: Store,
) -> None:
    store.integrations[Provider.ORCAROUTER] = IntegrationRecord(
        id="orca",
        provider=Provider.ORCAROUTER,
        encrypted_api_key=encrypt_secret("key", settings.master_key),
        key_mask="***key",
        status=IntegrationStatus.ACTIVE,
    )
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": []})
        return httpx.Response(
            403,
            json={
                "error": {
                    "message": "workspace balance exhausted",
                    "type": "orcarouter_api_error",
                    "code": "insufficient_user_quota",
                }
            },
        )

    transport = httpx.MockTransport(handler)
    shared = httpx.Client(transport=transport)
    steps = GenerationSteps(store=store, settings=settings, http_client=shared)
    webinar = Webinar(
        id="webinar",
        theme="timeout regression",
        audience="developers",
        duration_min=3,
        lang=Lang.JA,
        template=Template.TECH,
        style=Style.KEYNOTE,
        voice_id="voice",
    )

    with pytest.raises(LLMError):
        steps.generate_outline(webinar)

    assert store.integrations[Provider.ORCAROUTER].status == IntegrationStatus.ACTIVE
    shared.close()
