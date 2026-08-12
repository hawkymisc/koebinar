"""Tests for durable store, async jobs/worker, and Remotion adapter boundary."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from koebinar.config import Settings
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
from koebinar.pipeline.orchestrator import PipelineOrchestrator
from koebinar.pipeline.renderer import (
    RenderError,
    VideoRenderer,
    build_minimal_mp4,
    invoke_remotion_render,
    remotion_available,
    remotion_project_ready,
)
from koebinar.storage import Store, open_store, set_store
from koebinar.worker import process_one, run_worker
from tests.mocks.providers import VALID_EL_KEY, VALID_ORCA_KEY, install_mocks


def test_remotion_project_scaffolded():
    root = Path(__file__).resolve().parents[2] / "remotion"
    assert remotion_project_ready(root)
    assert (root / "render.mjs").exists()
    assert (root / "src" / "Webinar.tsx").exists()
    assert (root / "src" / "Root.tsx").exists()
    assert (root / "package.json").exists()


def test_durable_store_survives_reopen(tmp_path: Path):
    data = tmp_path / "d"
    art = tmp_path / "a"
    db = data / "k.db"
    data.mkdir()
    art.mkdir()
    dict_path = Path(__file__).resolve().parents[2] / "data" / "pronunciation_dict.tsv"
    s = Settings(
        data_dir=data,
        artifacts_dir=art,
        db_path=db,
        pronunciation_dict_path=dict_path,
        sync_pipeline=True,
        force_render_double=True,
        master_key="m",
    )
    s.ensure_dirs()
    st1 = open_store(s)
    from koebinar.knowledge.service import KnowledgeService

    ks = KnowledgeService(store=st1)
    doc = ks.register(
        KnowledgeCreateRequest(title="Durable", source_type=SourceType.TEXT, content="persisted content about API")
    )
    doc_id = doc.id
    st1.write_bytes("web_x", "note.bin", b"hello-artifact")
    st1.close()

    st2 = open_store(s)
    assert doc_id in st2.documents
    assert st2.documents[doc_id].title == "Durable"
    assert (art / "web_x" / "note.bin").read_bytes() == b"hello-artifact"
    st2.close()


def test_async_enqueue_and_worker_completes(tmp_path: Path):
    data = tmp_path / "d"
    art = tmp_path / "a"
    db = data / "k.db"
    data.mkdir()
    art.mkdir()
    dict_path = Path(__file__).resolve().parents[2] / "data" / "pronunciation_dict.tsv"
    s = Settings(
        data_dir=data,
        artifacts_dir=art,
        db_path=db,
        pronunciation_dict_path=dict_path,
        sync_pipeline=False,
        force_render_double=True,
        master_key="m",
        remotion_project_dir=Path(__file__).resolve().parents[2] / "remotion",
    )
    s.ensure_dirs()
    with install_mocks():
        client = httpx.Client()
        store = open_store(s)
        set_store(store)
        from koebinar.integrations.service import IntegrationsService
        from koebinar.knowledge.service import KnowledgeService

        integ = IntegrationsService(store=store, settings=s, http_client=client)
        integ.register(Provider.ORCAROUTER, IntegrationRegisterRequest(api_key=VALID_ORCA_KEY))
        integ.register(Provider.ELEVENLABS, IntegrationRegisterRequest(api_key=VALID_EL_KEY))
        doc = KnowledgeService(store=store).register(
            KnowledgeCreateRequest(title="KB", source_type=SourceType.TEXT, content="Product API pricing security")
        )
        orch = PipelineOrchestrator(store=store, settings=s, http_client=client)
        w = orch.create_webinar(
            WebinarCreateRequest(
                theme="Async",
                document_ids=[doc.id],
                voice_id="voice_clone_ja_en_01",
                auto_run=True,
                sync=False,
            )
        )
        assert w.status.value == "queued"
        assert w.job_id
        job = JobQueue(store).get(w.job_id)
        assert job and job.status == JobStatus.PENDING

        # HTTP request would return here; worker processes offline
        assert process_one(store, s, http_client=client) is True
        w2 = orch.get(w.id)
        assert w2.status.value == "completed"
        types = {a.type.value for a in w2.artifacts}
        assert "video" in types
        assert "timeline" in types
        assert Path(orch.video_path(w.id)).exists()
        job2 = JobQueue(store).get(w.job_id)
        assert job2 and job2.status == JobStatus.COMPLETED
        client.close()
        store.close()


def test_api_async_create_then_worker(tmp_path: Path):
    data = tmp_path / "d"
    art = tmp_path / "a"
    db = data / "async.db"
    data.mkdir()
    art.mkdir()
    dict_path = Path(__file__).resolve().parents[2] / "data" / "pronunciation_dict.tsv"
    s = Settings(
        data_dir=data,
        artifacts_dir=art,
        db_path=db,
        pronunciation_dict_path=dict_path,
        sync_pipeline=False,
        force_render_double=True,
        master_key="m",
        default_auth_token="mvp-token",
        remotion_project_dir=Path(__file__).resolve().parents[2] / "remotion",
    )
    s.ensure_dirs()
    with install_mocks():
        store = open_store(s)
        app = create_app(settings=s, store=store, http_client=httpx.Client())
        with TestClient(app) as c:
            c.headers["Authorization"] = "Bearer mvp-token"
            c.post("/api/v1/integrations/orcarouter", json={"api_key": VALID_ORCA_KEY})
            c.post("/api/v1/integrations/elevenlabs", json={"api_key": VALID_EL_KEY})
            doc = c.post(
                "/api/v1/knowledge/documents",
                json={"title": "T", "source_type": "text", "content": "starter plan costs 100 USD"},
            ).json()
            w = c.post(
                "/api/v1/webinars",
                json={
                    "theme": "async api",
                    "document_ids": [doc["id"]],
                    "voice_id": "voice_clone_ja_en_01",
                    "auto_run": True,
                },
            ).json()
            assert w["status"] == "queued"
            assert w["job_id"]
            # status poll before worker
            g1 = c.get(f"/api/v1/webinars/{w['id']}").json()
            assert g1["status"] == "queued"
            # worker
            process_one(store, s, http_client=httpx.Client())
            g2 = c.get(f"/api/v1/webinars/{w['id']}").json()
            assert g2["status"] == "completed"
            jobs = c.get(f"/api/v1/webinars/{w['id']}/jobs").json()
            assert jobs["jobs"]
            assert jobs["jobs"][0]["status"] == "completed"
            stack = c.get("/api/v1/health/stack").json()
            assert stack["sync_pipeline"] is False
            assert "jobs" in stack
        store.close()


def test_invoke_remotion_success_with_fake_runner(tmp_path: Path):
    project = Path(__file__).resolve().parents[2] / "remotion"
    out = tmp_path / "out.mp4"

    def fake_run(cmd, **kwargs):
        # Write a non-empty "mp4" with remotion marker
        out.write_bytes(b"\x00\x00\x00\x1cftypisom" + b"remotion-fake-render")
        return subprocess.CompletedProcess(cmd, 0, stdout='{"phase":"done"}', stderr="")

    meta = invoke_remotion_render(
        project_dir=project,
        props={"timeline": {"total_frames": 30, "fps": 30, "slides": []}, "slides": []},
        output_path=out,
        runner=fake_run,
    )
    assert meta["renderer"] == "remotion"
    assert out.exists() and out.stat().st_size > 10


def test_invoke_remotion_failure(tmp_path: Path):
    project = Path(__file__).resolve().parents[2] / "remotion"
    out = tmp_path / "out.mp4"

    def fail_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="chromium crash")

    with pytest.raises(RenderError) as ei:
        invoke_remotion_render(
            project_dir=project,
            props={"timeline": {"total_frames": 1}, "slides": []},
            output_path=out,
            runner=fail_run,
        )
    assert "chromium" in str(ei.value) or "exit 1" in str(ei.value)


def test_video_renderer_uses_remotion_when_available(tmp_path: Path, settings: Settings, store: Store):
    settings.force_render_double = False
    out_bytes = {}

    def fake_run(cmd, **kwargs):
        # last arg is output path
        path = Path(cmd[cmd.index("--output") + 1])
        path.write_bytes(b"\x00\x00\x00\x1cftypisomREEL")
        out_bytes["n"] = path.stat().st_size
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("koebinar.pipeline.renderer.remotion_available", lambda s=None: True)
        r = VideoRenderer(store=store, settings=settings, runner=fake_run)
        tl = {
            "fps": 30,
            "total_frames": 30,
            "slides": [{"slide_index": 0, "title": "T", "start_frame": 0, "end_frame": 30, "duration_frames": 30}],
        }
        uri, meta = r.render("web1", tl, [{"title": "T"}])
        assert meta["renderer"] == "remotion"
        assert r.used_double is False
        assert Path(uri).read_bytes().startswith(b"\x00\x00\x00\x1cftyp")


def test_run_worker_once(tmp_path: Path):
    data = tmp_path / "d"
    art = tmp_path / "a"
    data.mkdir()
    art.mkdir()
    s = Settings(
        data_dir=data,
        artifacts_dir=art,
        db_path=data / "w.db",
        pronunciation_dict_path=Path(__file__).resolve().parents[2] / "data" / "pronunciation_dict.tsv",
        sync_pipeline=False,
        force_render_double=True,
        master_key="m",
        worker_idle_exit=True,
        worker_poll_interval_sec=0.01,
    )
    s.ensure_dirs()
    store = open_store(s)
    set_store(store)
    # empty queue
    n = run_worker(s, max_jobs=0)
    assert n == 0
    store.close()


def test_stack_scripts_exist():
    root = Path(__file__).resolve().parents[2]
    assert (root / "scripts" / "start-api.sh").exists()
    assert (root / "scripts" / "start-worker.sh").exists()
    assert (root / "scripts" / "start-stack.sh").exists()
    assert (root / "docker-compose.yml").exists()
