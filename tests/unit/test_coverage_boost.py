"""Targeted unit tests to raise C0/C1 coverage on edge branches."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from koebinar.config import Settings, get_settings, reset_settings_cache
from koebinar.crypto import encrypt_secret
from koebinar.integrations.elevenlabs import ElevenLabsClient, ElevenLabsError
from koebinar.integrations.service import IntegrationError, IntegrationsService
from koebinar.knowledge.chunking import chunk_text, extract_text_from_pdf_payload
from koebinar.knowledge.search import cosine, embed_text, lexical_overlap
from koebinar.llm.client import LLMError, OrcaRouterClient, parse_chat_content
from koebinar.main import create_app
from koebinar.models import (
    IntegrationRegisterRequest,
    IntegrationStatus,
    KnowledgeCreateRequest,
    PipelineStep,
    Provider,
    QuestionCreateRequest,
    SourceType,
    WebinarCreateRequest,
    WebinarStatus,
)
from koebinar.pipeline.orchestrator import PipelineError, PipelineOrchestrator
from koebinar.pipeline.renderer import RenderError, VideoRenderer, remotion_available
from koebinar.pipeline.steps import GenerationSteps
from koebinar.pipeline.timeline import frames_to_seconds, validate_timeline
from koebinar.pipeline.tts import TTSAdapter, wav_duration_sec
from koebinar.qa.service import QAService
from koebinar.storage import IntegrationRecord, Store, get_store, reset_store, set_store
from tests.helpers import CLONE_VOICE_ID, attest_voice, sync_and_attest
from tests.mocks.providers import VALID_EL_KEY, VALID_ORCA_KEY, install_mocks


def test_pdf_noise_and_chunk_windows():
    noisy = "%PDF-1.4 \x00\x01 binary 漢字テキスト and more"
    assert "漢字" in extract_text_from_pdf_payload(noisy) or "テキスト" in extract_text_from_pdf_payload(noisy)
    # force window path with long single paragraph
    long = "x" * 1200
    chunks = chunk_text(long, max_chars=100, overlap=10)
    assert len(chunks) > 5


def test_cosine_and_lexical_edge():
    assert cosine([], [1.0]) == 0.0
    assert cosine([1.0], [1.0, 2.0]) == 0.0
    assert lexical_overlap("", "abc") == 0.0
    assert lexical_overlap("the a an", "foo bar") == 0.0
    assert embed_text("") == [0.0] * 64


def test_llm_client_errors_and_parse():
    with respx.mock:
        respx.get("https://api.orcarouter.ai/v1/models").mock(side_effect=httpx.ConnectError("down"))
        c = OrcaRouterClient("k")
        with pytest.raises(LLMError):
            c.list_models()
        c.close()

    with respx.mock:
        respx.get("https://api.orcarouter.ai/v1/models").mock(
            return_value=httpx.Response(500, text="private upstream body")
        )
        c = OrcaRouterClient("k")
        with pytest.raises(LLMError) as unstructured_error:
            c.list_models()
        c.close()
        assert "private upstream body" not in str(unstructured_error.value)

    api_key = "sk-sensitive-orca-key"
    with respx.mock:
        respx.post("https://api.orcarouter.ai/v1/chat/completions").mock(
            return_value=httpx.Response(
                401,
                json={
                    "error": {
                        "code": "invalid_model",
                        "message": f"API key {api_key} cannot use model adaptive",
                    }
                },
            )
        )
        c = OrcaRouterClient(api_key)
        with pytest.raises(LLMError) as structured_error:
            c.chat_completions([{"role": "user", "content": "hi"}], retries=0)
        c.close()
        assert structured_error.value.provider_code == "invalid_model"
        assert structured_error.value.provider_message == "API key [redacted] cannot use model adaptive"
        assert api_key not in str(structured_error.value)

    with respx.mock:
        respx.post("https://api.orcarouter.ai/v1/chat/completions").mock(
            side_effect=httpx.ConnectError("down")
        )
        c = OrcaRouterClient("k")
        with pytest.raises(LLMError):
            c.chat_completions([{"role": "user", "content": "hi"}], retries=0)
        c.close()

    with respx.mock:
        respx.post("https://api.orcarouter.ai/v1/chat/completions").mock(
            return_value=httpx.Response(500, text="boom")
        )
        c = OrcaRouterClient("k")
        with pytest.raises(LLMError):
            c.chat_completions([{"role": "user", "content": "hi"}], retries=0)
        c.close()

    with respx.mock:
        route = respx.post("https://api.orcarouter.ai/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": {"already": "dict"}}}
                    ]
                },
            )
        )
        c = OrcaRouterClient("k")
        assert c.chat_json([{"role": "user", "content": "x"}])["already"] == "dict"
        c.close()
        request_body = json.loads(route.calls[0].request.content)
        assert request_body["model"] == "orcarouter/auto"

    with pytest.raises(LLMError):
        parse_chat_content({})


def test_elevenlabs_client_errors():
    with respx.mock:
        respx.get("https://api.elevenlabs.io/v1/user/subscription").mock(
            side_effect=httpx.ConnectError("x")
        )
        c = ElevenLabsClient("k")
        with pytest.raises(ElevenLabsError):
            c.get_subscription()
        c.close()

    with respx.mock:
        respx.get("https://api.elevenlabs.io/v1/user/subscription").mock(
            return_value=httpx.Response(500, text="e")
        )
        c = ElevenLabsClient("k")
        with pytest.raises(ElevenLabsError):
            c.get_subscription()
        c.close()

    with respx.mock:
        respx.get("https://api.elevenlabs.io/v1/voices").mock(side_effect=httpx.ConnectError("x"))
        c = ElevenLabsClient("k")
        with pytest.raises(ElevenLabsError):
            c.list_voices()
        c.close()

    with respx.mock:
        respx.get("https://api.elevenlabs.io/v1/voices").mock(return_value=httpx.Response(500, text="e"))
        c = ElevenLabsClient("k")
        with pytest.raises(ElevenLabsError):
            c.list_voices()
        c.close()

    with respx.mock:
        respx.post("https://api.elevenlabs.io/v1/text-to-speech/v1").mock(
            side_effect=httpx.ConnectError("x")
        )
        c = ElevenLabsClient("k")
        with pytest.raises(ElevenLabsError):
            c.text_to_speech("v1", "hi", retries=0)
        c.close()

    with respx.mock:
        route = respx.post("https://api.elevenlabs.io/v1/text-to-speech/v1")
        route.side_effect = [
            httpx.Response(429, text="rate"),
            httpx.Response(200, content=b"RIFF...."),
        ]
        c = ElevenLabsClient("k")
        assert c.text_to_speech("v1", "hi", retries=1, voice_settings={"stability": 0.5}) == b"RIFF...."
        c.close()

    with respx.mock:
        respx.post("https://api.elevenlabs.io/v1/text-to-speech/v1").mock(
            return_value=httpx.Response(500, text="e")
        )
        c = ElevenLabsClient("k")
        with pytest.raises(ElevenLabsError):
            c.text_to_speech("v1", "hi", retries=0)
        c.close()


def test_elevenlabs_client_preserves_safe_structured_error_detail():
    api_key = "xi-sensitive-key"
    with respx.mock:
        respx.get("https://api.elevenlabs.io/v1/voices").mock(
            return_value=httpx.Response(
                403,
                json={
                    "detail": {
                        "status": "missing_permissions",
                        "message": f"API key {api_key} is missing voices_read",
                        "request_id": "req_debug_123",
                    }
                },
            )
        )
        client = ElevenLabsClient(api_key)
        with pytest.raises(ElevenLabsError) as error:
            client.list_voices()
        client.close()

    assert error.value.status_code == 403
    assert error.value.provider_code == "missing_permissions"
    assert error.value.provider_message == "API key [redacted] is missing voices_read"
    assert error.value.request_id == "req_debug_123"
    assert api_key not in str(error.value)
    assert "missing_permissions" in str(error.value)
    assert "voices_read" in str(error.value)

    with respx.mock:
        respx.post("https://api.elevenlabs.io/v1/text-to-speech/v1").mock(
            return_value=httpx.Response(
                403,
                json={
                    "detail": {
                        "code": "missing_permissions",
                        "message": "The API key is missing text_to_speech.",
                    }
                },
            )
        )
        client = ElevenLabsClient(api_key)
        with pytest.raises(ElevenLabsError) as tts_error:
            client.text_to_speech("v1", "hi", retries=0)
        client.close()

    assert tts_error.value.provider_code == "missing_permissions"
    assert "text_to_speech" in str(tts_error.value)


def test_integrations_resolve_system_fallback_and_decrypt_fail(settings: Settings, store: Store):
    settings.allow_system_llm_key = True
    settings.orcarouter_api_key = "sys-orca"
    settings.allow_system_tts_key = True
    settings.elevenlabs_api_key = "sys-el"
    svc = IntegrationsService(store=store, settings=settings)
    assert svc.resolve_api_key(Provider.ORCAROUTER) == "sys-orca"
    assert svc.resolve_api_key(Provider.ELEVENLABS) == "sys-el"

    store.integrations[Provider.ORCAROUTER] = IntegrationRecord(
        id="x",
        provider=Provider.ORCAROUTER,
        encrypted_api_key="not-valid-token",
        key_mask="sk...xxxx",
        status=IntegrationStatus.ACTIVE,
    )
    with pytest.raises(IntegrationError):
        svc.resolve_api_key(Provider.ORCAROUTER, require=True)
    assert store.integrations[Provider.ORCAROUTER].status == IntegrationStatus.INVALID

    svc.mark_invalid(Provider.ELEVENLABS)  # no-op when missing
    with pytest.raises(IntegrationError):
        svc.register(Provider.ORCAROUTER, IntegrationRegisterRequest(api_key=""))  # noqa — empty after strip? api_key="" 


def test_integrations_unsupported_and_voices_error(settings: Settings, store: Store):
    svc = IntegrationsService(store=store, settings=settings, http_client=httpx.Client())
    # Provider enum only has two; exercise code path via monkeypatch-like call
    with pytest.raises(IntegrationError):
        # empty key
        svc.register(Provider.ORCAROUTER, IntegrationRegisterRequest(api_key="   "))


def test_storage_reset_and_get_set(settings: Settings):
    st = Store(settings=settings)
    st.documents["a"] = MagicMock()
    st.reset()
    assert st.documents == {}
    set_store(st)
    assert get_store() is st
    reset_store()
    assert get_store() is not st


def test_orchestrator_errors(settings: Settings, store: Store):
    with install_mocks():
        client = httpx.Client()
        orch = PipelineOrchestrator(store=store, settings=settings, http_client=client)
        with pytest.raises(PipelineError):
            orch.get("missing")
        with pytest.raises(PipelineError):
            orch.run_from("missing", "outline")
        # create without auto, invalid step
        svc = IntegrationsService(store=store, settings=settings, http_client=client)
        svc.register(Provider.ORCAROUTER, IntegrationRegisterRequest(api_key=VALID_ORCA_KEY))
        svc.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=VALID_EL_KEY))
        sync_and_attest(svc)
        w = orch.create_webinar(
            WebinarCreateRequest(theme="t", auto_run=False, voice_id=CLONE_VOICE_ID)
        )
        with pytest.raises(PipelineError):
            orch.run_from(w.id, "bogus_step")
        with pytest.raises(PipelineError):
            orch.video_path(w.id)
        # force exception path in run_from
        with patch.object(orch, "_run_step", side_effect=RuntimeError("boom")):
            with pytest.raises(PipelineError) as ei:
                orch.run_from(w.id, PipelineStep.OUTLINE)
            assert ei.value.status_code == 500
        client.close()


def test_renderer_validate_and_remotion(settings: Settings, store: Store):
    r = VideoRenderer(store=store, settings=settings)
    with pytest.raises(RenderError):
        r.render("w", {"fps": 0, "total_frames": 0, "slides": []}, [])
    # With force_render_double in test settings, remotion is treated unavailable
    assert remotion_available(settings) is False
    # A Remotion failure must fail closed; production code never silently uses a double.
    settings.force_render_double = False
    with patch("koebinar.pipeline.renderer.remotion_available", return_value=True):
        with patch(
            "koebinar.pipeline.renderer.invoke_remotion_render",
            side_effect=RenderError("chromium missing"),
        ):
            with pytest.raises(RenderError, match="chromium missing"):
                r.render(
                    "w",
                    {
                        "fps": 30,
                        "total_frames": 30,
                        "slides": [{"start_frame": 0, "end_frame": 30, "title": "t", "duration_frames": 30}],
                    },
                    [{"title": "t"}],
                    force_double=False,
                )
            assert r.used_double is False


def test_timeline_validate_overlap_and_fps():
    with pytest.raises(ValueError):
        frames_to_seconds(1, 0)
    errs = validate_timeline(
        {
            "fps": 30,
            "total_frames": 10,
            "slides": [
                {"slide_index": 0, "start_frame": 0, "end_frame": 5},
                {"slide_index": 1, "start_frame": 3, "end_frame": 8},
            ],
        }
    )
    assert any("overlap" in e for e in errs)


def test_steps_fallback_paths(settings: Settings, store: Store):
    client = httpx.Client()
    from koebinar.models import Webinar, Lang, Template, Style

    w = Webinar(
        id="w1",
        theme="T",
        audience="a",
        duration_min=2,
        lang=Lang.EN,
        template=Template.CASUAL,
        style=Style.CASUAL,
        voice_id="v",
    )
    with respx.mock(assert_all_called=False) as router:
        router.get(url__regex=r".*/models/?$").respond(
            200, json={"data": [{"id": "orcarouter/auto"}]}
        )
        router.post(url__regex=r".*/chat/completions/?$").respond(
            200,
            json={"choices": [{"message": {"content": json.dumps({"ok": True})}}]},
        )
        # register needs models
        integ = IntegrationsService(store=store, settings=settings, http_client=client)
        store.integrations[Provider.ORCAROUTER] = IntegrationRecord(
            id="i1",
            provider=Provider.ORCAROUTER,
            encrypted_api_key=encrypt_secret(VALID_ORCA_KEY, settings.master_key),
            key_mask="sk...0001",
            status=IntegrationStatus.ACTIVE,
        )
        steps = GenerationSteps(store=store, settings=settings, integrations=integ, http_client=client)
        out = steps.generate_outline(w)
        assert "sections" in out
        slides = steps.generate_slides(w, out)
        assert "slides" in slides
        script = steps.generate_script(w, slides)
        assert "slides" in script
        empty = steps._fallback_slides(w, {"sections": []})
        assert empty["slides"]
        # auth failure
        router.post(url__regex=r".*/chat/completions/?$").respond(401, json={"error": "no"})
        with pytest.raises(LLMError):
            steps.generate_outline(w)
        assert store.integrations[Provider.ORCAROUTER].status == IntegrationStatus.ACTIVE

        router.get(url__regex=r".*/models/?$").respond(
            401, json={"error": {"code": "invalid_api_key", "message": "Invalid API key"}}
        )
        with pytest.raises(LLMError):
            steps.generate_outline(w)
        assert store.integrations[Provider.ORCAROUTER].status == IntegrationStatus.INVALID
    client.close()


def test_tts_auth_failure_marks_invalid(settings: Settings, store: Store):
    client = httpx.Client()
    store.integrations[Provider.ELEVENLABS] = IntegrationRecord(
        id="el1",
        provider=Provider.ELEVENLABS,
        encrypted_api_key=encrypt_secret(VALID_EL_KEY, settings.master_key),
        key_mask="xi...0001",
        status=IntegrationStatus.ACTIVE,
    )
    integ = IntegrationsService(store=store, settings=settings, http_client=client)
    with install_mocks():
        sync_and_attest(integ)
    tts = TTSAdapter(store=store, settings=settings, integrations=integ, http_client=client)
    prepared = {
        "slides": [{"slide_index": 0, "sentences": ["Hello world"], "title": "t"}],
        "total_credits": 11,
    }
    with respx.mock(assert_all_called=False) as router:
        router.post(url__regex=r".*/text-to-speech/.*").respond(401, json={"detail": "no"})
        with pytest.raises(Exception):
            tts.synthesize_script("web1", prepared, "voice_clone_ja_en_01", "en")
        assert store.integrations[Provider.ELEVENLABS].status == IntegrationStatus.INVALID
    client.close()


def test_qa_export_and_failure_paths(settings: Settings, store: Store):
    with install_mocks():
        client = httpx.Client()
        integ = IntegrationsService(store=store, settings=settings, http_client=client)
        integ.register(Provider.ORCAROUTER, IntegrationRegisterRequest(api_key=VALID_ORCA_KEY))
        from koebinar.knowledge.service import KnowledgeService
        from koebinar.models import Webinar, Lang, Template, Style, WebinarStatus

        ks = KnowledgeService(store=store)
        doc = ks.register(
            KnowledgeCreateRequest(
                title="t",
                source_type=SourceType.TEXT,
                content="Starter plan costs 100 USD per month with SSO security encryption.",
            )
        )
        store.webinars["w1"] = Webinar(
            id="w1",
            theme="t",
            audience="a",
            duration_min=3,
            lang=Lang.EN,
            template=Template.TECH,
            style=Style.KEYNOTE,
            voice_id="v",
            document_ids=[doc.id],
            status=WebinarStatus.COMPLETED,
        )
        qa = QAService(store=store, settings=settings, knowledge=ks, integrations=integ, http_client=client)
        q = qa.ask(QuestionCreateRequest(webinar_id="w1", message="What is starter plan pricing cost USD?"))
        assert q.answer is not None
        assert "question_id" in qa.export("csv")
        assert qa.get(q.id) is not None
        with pytest.raises(ValueError):
            qa.ask(QuestionCreateRequest(webinar_id="missing", message="x"))
        # LLM 401 during strong retrieval
        with respx.mock:
            respx.post("https://api.orcarouter.ai/v1/chat/completions").respond(401, json={"e": 1})
            q2 = qa.ask(QuestionCreateRequest(webinar_id="w1", message="starter plan pricing cost USD security"))
            assert q2.status.value in ("failed", "held", "answered")
        client.close()


def test_api_error_branches(settings: Settings, store: Store):
    with install_mocks():
        app = create_app(settings=settings, store=store, http_client=httpx.Client())
        from fastapi.testclient import TestClient

        with TestClient(app) as c:
            c.headers["Authorization"] = "Bearer mvp-token"
            # patch missing webinar
            r = c.patch("/api/v1/webinars/nope/script", json={"slides": []})
            assert r.status_code == 404
            # video file missing even if artifact points wrong — create completed without file
            # question integration error path hard; video missing file:
            from koebinar.models import Webinar, Lang, Template, Style, PipelineArtifact, ArtifactType, PipelineStep

            w = Webinar(
                id="wx",
                theme="t",
                audience="a",
                duration_min=1,
                lang=Lang.JA,
                template=Template.TECH,
                style=Style.KEYNOTE,
                voice_id="v",
            )
            w.artifacts.append(
                PipelineArtifact(
                    id="a",
                    webinar_id="wx",
                    step=PipelineStep.VIDEO,
                    type=ArtifactType.VIDEO,
                    storage_uri=str(settings.artifacts_dir / "missing.mp4"),
                )
            )
            store.webinars["wx"] = w
            r = c.get("/api/v1/webinars/wx/video")
            assert r.status_code == 404


def test_main_cli_and_lifespan(settings: Settings, store: Store):
    app = create_app(settings=settings, store=store, http_client=httpx.Client())
    assert app.title
    # root already covered
    with patch("uvicorn.run") as run:
        from koebinar.main import cli

        cli()
        run.assert_called()


def test_chunking_paragraph_merge_and_section():
    text = "short\n\n" + ("para " * 20) + "\n\nanother"
    chunks = chunk_text(text, max_chars=40, overlap=5)
    assert chunks
    from koebinar.knowledge.chunking import estimate_section

    assert estimate_section(1, 2) in ("body", "intro", "outro")


def test_tts_empty_audio_and_non_wav(settings: Settings, store: Store):
    with install_mocks():
        client = httpx.Client()
        integ = IntegrationsService(store=store, settings=settings, http_client=client)
        integ.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=VALID_EL_KEY))
        sync_and_attest(integ)
        tts = TTSAdapter(store=store, settings=settings, integrations=integ, http_client=client)
        prepared = {
            "slides": [{"slide_index": 0, "sentences": ["Hi"], "title": "t"}],
            "total_credits": 2,
        }
        with respx.mock:
            respx.post(url__regex=r".*/text-to-speech/.*").respond(200, content=b"")
            durs, meta = tts.synthesize_script("w2", prepared, CLONE_VOICE_ID, "ja")
            assert durs and durs[0]["duration_sec"] > 0
        with respx.mock:
            respx.post(url__regex=r".*/text-to-speech/.*").respond(200, content=b"NOTWAVDATA")
            durs2, _ = tts.synthesize_script("w3", prepared, CLONE_VOICE_ID, "en")
            assert durs2
        client.close()


def test_load_artifact_from_disk(settings: Settings, store: Store):
    with install_mocks():
        client = httpx.Client()
        integ = IntegrationsService(store=store, settings=settings, http_client=client)
        integ.register(Provider.ORCAROUTER, IntegrationRegisterRequest(api_key=VALID_ORCA_KEY))
        integ.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=VALID_EL_KEY))
        sync_and_attest(integ)
        orch = PipelineOrchestrator(store=store, settings=settings, http_client=client)
        w = orch.create_webinar(WebinarCreateRequest(theme="disk", auto_run=True, voice_id=CLONE_VOICE_ID))
        # strip artifact list but keep files on disk
        arts = list(w.artifacts)
        w.artifacts = []
        store.webinars[w.id] = w
        data = orch._load_artifact_json(w, arts[0].type)
        assert data is not None
        with pytest.raises(PipelineError):
            orch._load_artifact_json(w, PipelineStep.VIDEO)  # wrong type misuse
        # use proper missing type
        from koebinar.models import ArtifactType

        w2 = orch.create_webinar(WebinarCreateRequest(theme="x", auto_run=False))
        with pytest.raises(PipelineError):
            orch._load_artifact_json(w2, ArtifactType.OUTLINE)
        client.close()


def test_config_reset():
    reset_settings_cache()
    s1 = get_settings()
    reset_settings_cache()
    s2 = get_settings()
    assert s1 is not s2


def test_integrations_voices_http_error(settings: Settings, store: Store):
    client = httpx.Client()
    store.integrations[Provider.ELEVENLABS] = IntegrationRecord(
        id="el2",
        provider=Provider.ELEVENLABS,
        encrypted_api_key=encrypt_secret(VALID_EL_KEY, settings.master_key),
        key_mask="xi...0001",
        status=IntegrationStatus.ACTIVE,
    )
    svc = IntegrationsService(store=store, settings=settings, http_client=client)
    with respx.mock(assert_all_called=False) as router:
        router.get(url__regex=r".*/voices/?$").respond(403, json={"detail": "no"})
        with pytest.raises(IntegrationError):
            svc.get_voices()
    client.close()
