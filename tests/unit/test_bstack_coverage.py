"""Raise C1 on B-stack modules: storage, jobs, worker, renderer, routes."""

from __future__ import annotations

import json
import signal
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from koebinar.config import Settings, get_settings, reset_settings_cache
from koebinar.jobs import JobQueue, JobStatus
from koebinar.main import create_app
from koebinar.models import (
    IntegrationRegisterRequest,
    KnowledgeCreateRequest,
    PipelineStep,
    Provider,
    SourceType,
    WebinarCreateRequest,
)
from koebinar.pipeline.orchestrator import PipelineError, PipelineOrchestrator
from koebinar.pipeline.renderer import (
    RenderError,
    VideoRenderer,
    invoke_remotion_render,
    remotion_available,
    remotion_project_ready,
)
from tests.helpers import seed_attested_voice_ref
from koebinar.storage import Store, get_store, open_store, reset_store, set_store
from koebinar.worker import _handle_signal, main as worker_main, process_one, run_worker
from tests.helpers import CLONE_VOICE_ID, attest_voice, sync_and_attest
from tests.mocks.providers import VALID_EL_KEY, VALID_ORCA_KEY, install_mocks


@pytest.fixture()
def durable(tmp_path: Path):
    data = tmp_path / "d"
    art = tmp_path / "a"
    data.mkdir()
    art.mkdir()
    s = Settings(
        data_dir=data,
        artifacts_dir=art,
        db_path=data / "x.db",
        pronunciation_dict_path=Path(__file__).resolve().parents[2] / "data" / "pronunciation_dict.tsv",
        master_key="k",
        sync_pipeline=False,
        force_render_double=True,
        worker_poll_interval_sec=0.01,
        worker_idle_exit=True,
        default_auth_token="mvp-token",
        remotion_project_dir=Path(__file__).resolve().parents[2] / "remotion",
    )
    s.ensure_dirs()
    st = open_store(s)
    set_store(st)
    yield s, st
    st.close()


def test_storage_dict_ops_and_reset(durable):
    s, st = durable
    from koebinar.models import KnowledgeDocument, DocumentStatus, SourceType
    from koebinar.models import utcnow

    doc = KnowledgeDocument(
        id="d1",
        title="t",
        source_type=SourceType.TEXT,
        storage_uri="u",
        status=DocumentStatus.INDEXED,
        chunk_count=0,
    )
    st.documents["d1"] = doc
    assert "d1" in st.documents
    assert len(st.documents) >= 1
    assert list(st.documents.keys())
    assert list(st.documents.items())
    del st.documents["d1"]
    with pytest.raises(KeyError):
        _ = st.documents["d1"]
    with pytest.raises(KeyError):
        del st.documents["missing"]
    st.documents.clear()
    st.voice_refs["v1"] = {"active": True}
    assert st.voice_refs.get("nope") is None
    st.generation_logs.clear()
    st.intent_signals.clear()
    st.reset()
    assert len(st.documents) == 0


def test_jobs_fail_and_stats(durable):
    s, st = durable
    q = JobQueue(st)
    job = q.enqueue("w1", PipelineStep.OUTLINE)
    assert q.pending_count() == 1
    claimed = q.claim_next()
    assert claimed and claimed.id == job.id
    # second claim while running → none
    assert q.claim_next() is None
    q.fail(job.id, "boom")
    got = q.get(job.id)
    assert got and got.status == JobStatus.FAILED and "boom" in (got.error or "")
    assert q.stats().get("failed") == 1
    assert q.list_for_webinar("w1")
    assert q.get("nope") is None
    # claim race: pending then update fails path — enqueue another
    j2 = q.enqueue("w2", "slides")
    c2 = q.claim_next()
    assert c2
    q.complete(c2.id)
    assert q.get(c2.id).status == JobStatus.COMPLETED


def test_worker_process_failure_path(durable):
    s, st = durable
    q = JobQueue(st)
    # webinar missing → orchestrator fails
    job = q.enqueue("missing_web", PipelineStep.OUTLINE)
    with install_mocks():
        ok = process_one(st, s, http_client=httpx.Client())
    assert ok is True
    assert q.get(job.id).status == JobStatus.FAILED


def test_worker_main_once(durable, monkeypatch):
    s, st = durable
    monkeypatch.setenv("KOEBINAR_DB_PATH", str(s.db_path))
    monkeypatch.setenv("KOEBINAR_DATA_DIR", str(s.data_dir))
    monkeypatch.setenv("KOEBINAR_ARTIFACTS_DIR", str(s.artifacts_dir))
    monkeypatch.setenv("KOEBINAR_SYNC_PIPELINE", "false")
    reset_settings_cache()
    # empty queue, once
    code = worker_main(["--once", "--idle-exit"])
    assert code == 0


def test_worker_signal_handler():
    import koebinar.worker as w

    w._STOP = False
    w._handle_signal(signal.SIGINT, None)
    assert w._STOP is True
    w._STOP = False


def test_renderer_missing_entry_and_timeout(tmp_path: Path, durable):
    s, st = durable
    # missing render.mjs
    bad = tmp_path / "empty_proj"
    bad.mkdir()
    with pytest.raises(RenderError):
        invoke_remotion_render(
            project_dir=bad,
            props={},
            output_path=tmp_path / "o.mp4",
        )
    # timeout
    def slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd="node", timeout=1)

    proj = Path(__file__).resolve().parents[2] / "remotion"
    with pytest.raises(RenderError):
        invoke_remotion_render(
            project_dir=proj,
            props={"timeline": {}, "slides": []},
            output_path=tmp_path / "t.mp4",
            runner=slow,
        )
    # FileNotFoundError
    def no_node(*a, **k):
        raise FileNotFoundError("node")

    with pytest.raises(RenderError):
        invoke_remotion_render(
            project_dir=proj,
            props={"timeline": {}, "slides": []},
            output_path=tmp_path / "t2.mp4",
            runner=no_node,
        )
    # generic exception
    def boom(*a, **k):
        raise RuntimeError("x")

    with pytest.raises(RenderError):
        invoke_remotion_render(
            project_dir=proj,
            props={"timeline": {}, "slides": []},
            output_path=tmp_path / "t3.mp4",
            runner=boom,
        )
    # empty output
    def empty_ok(cmd, **kwargs):
        path = Path(cmd[cmd.index("--output") + 1])
        path.write_bytes(b"")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    with pytest.raises(RenderError):
        invoke_remotion_render(
            project_dir=proj,
            props={"timeline": {}, "slides": []},
            output_path=tmp_path / "t4.mp4",
            runner=empty_ok,
        )


def test_remotion_available_branches(tmp_path: Path, durable):
    s, st = durable
    s.force_render_double = True
    assert remotion_available(s) is False
    s.force_render_double = False
    s.remotion_project_dir = tmp_path / "nope"
    assert remotion_available(s) is False
    assert remotion_project_ready(tmp_path / "nope") is False
    # incomplete project
    p = tmp_path / "partial"
    p.mkdir()
    (p / "package.json").write_text("{}")
    assert remotion_project_ready(p) is False


def test_orchestrator_enqueue_invalid_step(durable):
    s, st = durable
    with install_mocks():
        orch = PipelineOrchestrator(store=st, settings=s, http_client=httpx.Client())
        seed_attested_voice_ref(st, "voice-queue")
        w = orch.create_webinar(
            WebinarCreateRequest(theme="x", voice_id="voice-queue", auto_run=False)
        )
        with pytest.raises(PipelineError):
            orch.enqueue_from(w.id, "not_a_step")


def test_routes_jobs_and_missing(durable):
    s, st = durable
    with install_mocks():
        app = create_app(settings=s, store=st, http_client=httpx.Client())
        with TestClient(app) as c:
            c.headers["Authorization"] = "Bearer mvp-token"
            assert c.get("/api/v1/jobs/nope").status_code == 404
            assert c.get("/api/v1/webinars/nope/jobs").status_code == 404
            c.post("/api/v1/integrations/orcarouter", json={"api_key": VALID_ORCA_KEY})
            c.post("/api/v1/integrations/elevenlabs", json={"api_key": VALID_EL_KEY})
            attest_voice(c, CLONE_VOICE_ID)
            doc = c.post(
                "/api/v1/knowledge/documents",
                json={"title": "t", "source_type": "text", "content": "body"},
            ).json()
            w = c.post(
                "/api/v1/webinars",
                json={
                    "theme": "q",
                    "document_ids": [doc["id"]],
                    "voice_id": CLONE_VOICE_ID,
                    "auto_run": True,
                    "sync": False,
                },
            ).json()
            jobs = c.get(f"/api/v1/webinars/{w['id']}/jobs").json()
            assert jobs["jobs"]
            jid = jobs["jobs"][0]["id"]
            assert c.get(f"/api/v1/jobs/{jid}").status_code == 200
            # force step run with sync query
            process_one(st, s, http_client=httpx.Client())
            r = c.post(f"/api/v1/webinars/{w['id']}/steps/timeline/run?sync=true")
            assert r.status_code == 200


def test_main_open_store_path(tmp_path: Path):
    reset_settings_cache()
    data = tmp_path / "d"
    art = tmp_path / "a"
    data.mkdir()
    art.mkdir()
    s = Settings(
        data_dir=data,
        artifacts_dir=art,
        db_path=data / "m.db",
        pronunciation_dict_path=Path(__file__).resolve().parents[2] / "data" / "pronunciation_dict.tsv",
        master_key="k",
        sync_pipeline=True,
        force_render_double=True,
        default_auth_token="mvp-token",
    )
    s.ensure_dirs()
    app = create_app(settings=s, store=None, http_client=httpx.Client())
    with TestClient(app) as c:
        assert c.get("/api/v1/health").status_code == 200


def test_provider_map_iteration(durable):
    s, st = durable
    from koebinar.storage import IntegrationRecord
    from koebinar.models import IntegrationStatus

    st.integrations[Provider.ORCAROUTER] = IntegrationRecord(
        id="i",
        provider=Provider.ORCAROUTER,
        encrypted_api_key="x",
        key_mask="m",
        status=IntegrationStatus.ACTIVE,
    )
    assert Provider.ORCAROUTER in list(st.integrations.keys())
    assert list(st.integrations.items())
    st.integrations.clear()


def test_run_worker_max_jobs(durable):
    s, st = durable
    with install_mocks():
        client = httpx.Client()
        from koebinar.integrations.service import IntegrationsService
        from koebinar.knowledge.service import KnowledgeService

        IntegrationsService(store=st, settings=s, http_client=client).register(
            Provider.ORCAROUTER, IntegrationRegisterRequest(api_key=VALID_ORCA_KEY)
        )
        integrations = IntegrationsService(store=st, settings=s, http_client=client)
        integrations.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=VALID_EL_KEY))
        sync_and_attest(integrations)
        doc = KnowledgeService(store=st).register(
            KnowledgeCreateRequest(title="t", source_type=SourceType.TEXT, content="c")
        )
        orch = PipelineOrchestrator(store=st, settings=s, http_client=client)
        orch.create_webinar(
            WebinarCreateRequest(theme="w", document_ids=[doc.id], auto_run=True, sync=False, voice_id="voice_clone_ja_en_01")
        )
        s.worker_idle_exit = False
        n = run_worker(s, max_jobs=1, http_client=client)
        assert n == 1
        client.close()
