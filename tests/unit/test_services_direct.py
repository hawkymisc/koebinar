"""Direct service unit tests (real shipped functions, mocked HTTP via respx)."""

import httpx
import pytest

from koebinar.config import Settings
from koebinar.integrations.service import IntegrationError, IntegrationsService
from koebinar.knowledge.service import KnowledgeService
from koebinar.models import (
    IntegrationRegisterRequest,
    KnowledgeCreateRequest,
    Provider,
    SourceType,
    WebinarCreateRequest,
)
from koebinar.pipeline.orchestrator import PipelineOrchestrator
from koebinar.storage import Store
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
    with pytest.raises(IntegrationError):
        svc.register(Provider.ORCAROUTER, IntegrationRegisterRequest(api_key=INVALID_ORCA_KEY))
    with pytest.raises(IntegrationError):
        svc.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=INVALID_EL_KEY))


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
    with pytest.raises(Exception):
        orch.create_webinar(WebinarCreateRequest(theme="x", auto_run=True))
