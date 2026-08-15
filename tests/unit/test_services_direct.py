"""Direct service unit tests (real shipped functions, mocked HTTP via respx)."""

import httpx
import pytest
from unittest.mock import Mock

from koebinar.config import Settings
from koebinar.integrations.service import IntegrationError, IntegrationsService
from koebinar.knowledge.service import KnowledgeService
from koebinar.models import (
    Answerability,
    Chunk,
    IntegrationRegisterRequest,
    IntegrationStatus,
    KnowledgeCreateRequest,
    Provider,
    Question,
    SourceType,
    Webinar,
    WebinarCreateRequest,
)
from koebinar.pipeline.orchestrator import PipelineOrchestrator
from koebinar.qa.service import QAService
from koebinar.storage import Store
from tests.helpers import CLONE_VOICE_ID, seed_attested_voice_ref, sync_and_attest
from tests.mocks.providers import (
    FREE_EL_KEY,
    INVALID_EL_KEY,
    INVALID_ORCA_KEY,
    VALID_EL_KEY,
    VALID_ORCA_KEY,
    install_mocks,
)


@pytest.fixture()
def svc_env(settings: Settings, store: Store):
    with install_mocks():
        client = httpx.Client()
        yield settings, store, client
        client.close()


def test_knowledge_register_text_and_search(svc_env):
    settings, store, _ = svc_env
    ks = KnowledgeService(store=store)
    doc = ks.register(
        KnowledgeCreateRequest(
            title="Product",
            source_type=SourceType.TEXT,
            content="Koebinar generates webinar videos with OrcaRouter and ElevenLabs.",
        )
    )
    assert doc.chunk_count >= 1
    hits = ks.search("OrcaRouter webinar")
    assert hits
    assert hits[0][0].document_id == doc.id


def test_knowledge_pdf_and_url(svc_env):
    _, store, _ = svc_env
    ks = KnowledgeService(store=store)
    pdf = ks.register(
        KnowledgeCreateRequest(
            title="PDF",
            source_type=SourceType.PDF,
            content="%PDF-1.4 BT Security features include encryption. ET",
        )
    )
    url = ks.register(
        KnowledgeCreateRequest(
            title="URL",
            source_type=SourceType.URL,
            content="https://example.com/page",
        )
    )
    assert pdf.status.value == "indexed"
    assert url.chunk_count >= 1


def test_integrations_register_list_delete_mask(svc_env):
    settings, store, client = svc_env
    svc = IntegrationsService(store=store, settings=settings, http_client=client)
    view = svc.register(Provider.ORCAROUTER, IntegrationRegisterRequest(api_key=VALID_ORCA_KEY))
    assert view.key_mask.endswith("0001")
    assert VALID_ORCA_KEY not in view.key_mask
    listed = svc.list_all()
    assert any(i.provider == Provider.ORCAROUTER for i in listed)
    raw = store.integrations[Provider.ORCAROUTER].encrypted_api_key
    assert VALID_ORCA_KEY not in raw
    svc.delete(Provider.ORCAROUTER)
    with pytest.raises(IntegrationError):
        svc.resolve_api_key(Provider.ORCAROUTER, require=True)


def test_integrations_invalid_keys(svc_env):
    settings, store, client = svc_env
    svc = IntegrationsService(store=store, settings=settings, http_client=client)
    with pytest.raises(IntegrationError) as orca_error:
        svc.register(Provider.ORCAROUTER, IntegrationRegisterRequest(api_key=INVALID_ORCA_KEY))
    assert orca_error.value.code == "provider_validation_failed"
    assert orca_error.value.status_code == 422

    with pytest.raises(IntegrationError) as elevenlabs_error:
        svc.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=INVALID_EL_KEY))
    assert elevenlabs_error.value.code == "provider_validation_failed"
    assert elevenlabs_error.value.status_code == 422
    assert store.integrations == {}


def test_failed_validation_does_not_replace_an_existing_integration(svc_env):
    settings, store, client = svc_env
    svc = IntegrationsService(store=store, settings=settings, http_client=client)
    original = svc.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=VALID_EL_KEY))

    with pytest.raises(IntegrationError):
        svc.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=INVALID_EL_KEY))

    persisted = store.integrations[Provider.ELEVENLABS]
    assert persisted.id == original.id
    assert persisted.status == IntegrationStatus.ACTIVE
    assert INVALID_EL_KEY not in persisted.encrypted_api_key


@pytest.mark.parametrize("provider_status", [403, 429, 500])
def test_elevenlabs_provider_errors_use_non_authentication_status(
    settings: Settings, store: Store, provider_status: int
):
    def reject(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(provider_status, json={"detail": "provider rejected the key"})

    with httpx.Client(transport=httpx.MockTransport(reject)) as client:
        svc = IntegrationsService(store=store, settings=settings, http_client=client)
        with pytest.raises(IntegrationError) as error:
            svc.register(
                Provider.ELEVENLABS,
                IntegrationRegisterRequest(api_key="xi-el-sensitive-value"),
            )

    assert error.value.code == "provider_validation_failed"
    assert error.value.status_code == 422
    assert "xi-el-sensitive-value" not in str(error.value)
    assert store.integrations == {}


def test_elevenlabs_registration_allows_missing_subscription_scope(
    settings: Settings, store: Store
):
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/voices"):
            return httpx.Response(200, json={"voices": []})
        if request.url.path.endswith("/user/subscription"):
            return httpx.Response(403, json={"detail": "missing user subscription read"})
        raise AssertionError(f"unexpected request: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        svc = IntegrationsService(store=store, settings=settings, http_client=client)
        view = svc.register(
            Provider.ELEVENLABS,
            IntegrationRegisterRequest(api_key="xi-tts-and-voices-read"),
        )

    assert view.status == IntegrationStatus.ACTIVE
    assert view.meta["subscription_access"] is False
    assert "tier" not in view.meta
    assert any("User Read" in warning for warning in view.meta["warnings"])


@pytest.mark.parametrize(
    ("provider_status", "expected"),
    [
        (401, "無効・期限切れ"),
        (403, "Voices Read権限とIP allowlist"),
        (429, "レート制限"),
        (500, "一時的な障害"),
    ],
)
def test_elevenlabs_voice_validation_explains_safe_failure_reason(
    settings: Settings,
    store: Store,
    provider_status: int,
    expected: str,
):
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/voices")
        return httpx.Response(provider_status, json={"detail": "sensitive provider response"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        svc = IntegrationsService(store=store, settings=settings, http_client=client)
        with pytest.raises(IntegrationError) as error:
            svc.register(
                Provider.ELEVENLABS,
                IntegrationRegisterRequest(api_key="xi-sensitive-key"),
            )

    assert error.value.status_code == 422
    assert expected in str(error.value)
    assert "sensitive provider response" not in str(error.value)
    assert "xi-sensitive-key" not in str(error.value)


def test_elevenlabs_voice_validation_explains_connection_failure(
    settings: Settings, store: Store
):
    def disconnect(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("provider network detail", request=request)

    with httpx.Client(transport=httpx.MockTransport(disconnect)) as client:
        svc = IntegrationsService(store=store, settings=settings, http_client=client)
        with pytest.raises(IntegrationError) as error:
            svc.register(
                Provider.ELEVENLABS,
                IntegrationRegisterRequest(api_key="xi-sensitive-key"),
            )

    assert error.value.status_code == 422
    assert "ElevenLabsに接続できない" in str(error.value)
    assert "provider network detail" not in str(error.value)


def test_elevenlabs_voice_validation_surfaces_structured_provider_reason(
    settings: Settings, store: Store
):
    def reject(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/voices")
        return httpx.Response(
            403,
            json={
                "detail": {
                    "status": "ip_not_allowed",
                    "message": "This API key cannot be used from the current IP address.",
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(reject)) as client:
        svc = IntegrationsService(store=store, settings=settings, http_client=client)
        with pytest.raises(IntegrationError) as error:
            svc.register(
                Provider.ELEVENLABS,
                IntegrationRegisterRequest(api_key="xi-sensitive-key"),
            )

    message = str(error.value)
    assert "ip_not_allowed" in message
    assert "current IP address" in message
    assert "xi-sensitive-key" not in message


def test_elevenlabs_free_tier_requires_accept(svc_env):
    settings, store, client = svc_env
    svc = IntegrationsService(store=store, settings=settings, http_client=client)
    with pytest.raises(IntegrationError) as ei:
        svc.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=FREE_EL_KEY, accept_free_tier=False))
    assert ei.value.code == "free_tier_confirm"
    view = svc.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=FREE_EL_KEY, accept_free_tier=True))
    assert view.meta.get("tier") == "free"
    assert view.meta.get("warnings")


def test_voices_list(svc_env):
    settings, store, client = svc_env
    svc = IntegrationsService(store=store, settings=settings, http_client=client)
    svc.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=VALID_EL_KEY))
    voices = svc.get_voices()
    assert any(v.voice_id == "voice_clone_ja_en_01" for v in voices)


def test_pipeline_full_ja(svc_env):
    settings, store, client = svc_env
    integ = IntegrationsService(store=store, settings=settings, http_client=client)
    integ.register(Provider.ORCAROUTER, IntegrationRegisterRequest(api_key=VALID_ORCA_KEY))
    integ.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=VALID_EL_KEY))
    sync_and_attest(integ)
    ks = KnowledgeService(store=store)
    doc = ks.register(
        KnowledgeCreateRequest(
            title="KB",
            source_type=SourceType.TEXT,
            content="当社のAPIはRESTとWebhookを提供します。セキュリティはSOC2準拠です。",
        )
    )
    orch = PipelineOrchestrator(store=store, settings=settings, http_client=client)
    w = orch.create_webinar(
        WebinarCreateRequest(
            theme="API紹介",
            audience="エンジニア",
            duration_min=3,
            lang="ja",
            document_ids=[doc.id],
            voice_id="voice_clone_ja_en_01",
            auto_run=True,
        )
    )
    assert w.status.value == "completed"
    types = {a.type.value for a in w.artifacts}
    for needed in ("outline", "slides", "script", "tts_script", "audio", "timeline", "video"):
        assert needed in types or (needed == "audio" and "durations" in types)
    from pathlib import Path

    assert Path(orch.video_path(w.id)).exists()


def test_pipeline_fails_without_keys(svc_env):
    settings, store, client = svc_env
    orch = PipelineOrchestrator(store=store, settings=settings, http_client=client)
    seed_attested_voice_ref(store, CLONE_VOICE_ID)
    with pytest.raises(Exception):
        orch.create_webinar(
            WebinarCreateRequest(theme="x", voice_id=CLONE_VOICE_ID, auto_run=True)
        )


def test_qa_rejects_citations_not_present_in_retrieval(svc_env):
    settings, store, client = svc_env
    knowledge = Mock()
    knowledge.search.return_value = [
        (Chunk(id="chunk_allowed", document_id="doc_allowed", text="Grounded evidence"), 0.95)
    ]
    qa = QAService(store=store, settings=settings, knowledge=knowledge, http_client=client)
    qa._llm_answer = Mock(
        return_value={
            "answer_text": "Unverified claim",
            "confidence": 0.99,
            "citations": [
                {"document_id": "doc_foreign", "chunk_id": "chunk_foreign", "score": 1.0}
            ],
        }
    )
    webinar = Webinar(
        id="web_grounded",
        theme="Grounding",
        audience="general",
        duration_min=5,
        lang="en",
        template="tech",
        style="keynote",
        voice_id="default",
        document_ids=["doc_allowed"],
    )
    answer = qa._answer(
        Question(id="q_grounded", webinar_id=webinar.id, message="What is supported?"),
        webinar,
    )

    assert answer.answerability == Answerability.INSUFFICIENT
    assert answer.citations == []


def test_qa_normalizes_string_intent_from_orcarouter(svc_env):
    settings, store, client = svc_env
    knowledge = Mock()
    knowledge.search.return_value = [
        (Chunk(id="chunk_allowed", document_id="doc_allowed", text="Grounded evidence"), 0.95)
    ]
    qa = QAService(store=store, settings=settings, knowledge=knowledge, http_client=client)
    qa._llm_answer = Mock(
        return_value={
            "answer_text": "Supported answer",
            "confidence": 0.95,
            "citations": [
                {"document_id": "doc_allowed", "chunk_id": "chunk_allowed", "score": 0.95}
            ],
            "intent": "explanation",
        }
    )
    webinar = Webinar(
        id="web_string_intent",
        theme="Grounding",
        audience="general",
        duration_min=5,
        lang="en",
        template="tech",
        style="keynote",
        voice_id="default",
        document_ids=["doc_allowed"],
    )

    answer = qa._answer(
        Question(id="q_string_intent", webinar_id=webinar.id, message="Explain the evidence"),
        webinar,
    )

    assert answer.answerability == Answerability.ANSWERABLE
    assert answer.intent == {
        "type": "explanation",
        "value": "explanation",
        "confidence": 0.4,
    }


def test_qa_falls_back_when_model_confidence_is_not_numeric(svc_env):
    settings, store, client = svc_env
    knowledge = Mock()
    knowledge.search.return_value = [
        (Chunk(id="chunk_allowed", document_id="doc_allowed", text="Grounded evidence"), 0.95)
    ]
    qa = QAService(store=store, settings=settings, knowledge=knowledge, http_client=client)
    qa._llm_answer = Mock(
        return_value={
            "answer_text": "Supported answer",
            "confidence": "high",
            "citations": [
                {"document_id": "doc_allowed", "chunk_id": "chunk_allowed", "score": 0.95}
            ],
        }
    )
    webinar = Webinar(
        id="web_bad_confidence",
        theme="Grounding",
        audience="general",
        duration_min=5,
        lang="en",
        template="tech",
        style="keynote",
        voice_id="default",
        document_ids=["doc_allowed"],
    )

    answer = qa._answer(
        Question(id="q_bad_confidence", webinar_id=webinar.id, message="Explain the evidence"),
        webinar,
    )

    assert answer.answerability == Answerability.ANSWERABLE
    assert answer.confidence == pytest.approx(0.95)
