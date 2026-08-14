"""E2E: durable store restart + async worker path under mocks."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from koebinar.config import Settings, reset_settings_cache
from koebinar.main import create_app
from koebinar.storage import open_store, set_store
from koebinar.worker import process_one
from tests.helpers import CLONE_VOICE_ID, attest_voice
from tests.mocks.providers import VALID_EL_KEY, VALID_ORCA_KEY, install_mocks


@pytest.fixture()
def async_env(tmp_path: Path):
    reset_settings_cache()
    data = tmp_path / "data"
    art = tmp_path / "artifacts"
    data.mkdir()
    art.mkdir()
    s = Settings(
        data_dir=data,
        artifacts_dir=art,
        db_path=data / "async.db",
        pronunciation_dict_path=Path(__file__).resolve().parents[2] / "data" / "pronunciation_dict.tsv",
        master_key="async-test-key",
        sync_pipeline=False,
        force_render_double=True,
        default_auth_token="mvp-token",
        remotion_project_dir=Path(__file__).resolve().parents[2] / "remotion",
    )
    s.ensure_dirs()
    with install_mocks():
        store = open_store(s)
        set_store(store)
        app = create_app(settings=s, store=store, http_client=httpx.Client())
        with TestClient(app) as c:
            c.headers["Authorization"] = "Bearer mvp-token"
            yield s, store, c
        store.close()


def test_e2e_durability_across_api_reopen(tmp_path: Path):
    reset_settings_cache()
    data = tmp_path / "data"
    art = tmp_path / "artifacts"
    data.mkdir()
    art.mkdir()
    s = Settings(
        data_dir=data,
        artifacts_dir=art,
        db_path=data / "dur.db",
        pronunciation_dict_path=Path(__file__).resolve().parents[2] / "data" / "pronunciation_dict.tsv",
        master_key="dur-key",
        sync_pipeline=True,
        force_render_double=True,
        default_auth_token="mvp-token",
    )
    s.ensure_dirs()
    with install_mocks():
        store1 = open_store(s)
        app1 = create_app(settings=s, store=store1, http_client=httpx.Client())
        with TestClient(app1) as c1:
            c1.headers["Authorization"] = "Bearer mvp-token"
            doc = c1.post(
                "/api/v1/knowledge/documents",
                json={"title": "KeepMe", "source_type": "text", "content": "durable kb body"},
            ).json()
            doc_id = doc["id"]
            c1.post("/api/v1/integrations/orcarouter", json={"api_key": VALID_ORCA_KEY})
        store1.close()

        # New API process / store handle, same db path
        store2 = open_store(s)
        app2 = create_app(settings=s, store=store2, http_client=httpx.Client())
        with TestClient(app2) as c2:
            c2.headers["Authorization"] = "Bearer mvp-token"
            got = c2.get(f"/api/v1/knowledge/documents/{doc_id}")
            assert got.status_code == 200
            assert got.json()["title"] == "KeepMe"
            integ = c2.get("/api/v1/integrations").json()
            assert any(i["provider"] == "orcarouter" for i in integ)
            assert VALID_ORCA_KEY not in str(integ)
        store2.close()


def test_e2e_async_pipeline_poll(async_env):
    s, store, c = async_env
    c.post("/api/v1/integrations/orcarouter", json={"api_key": VALID_ORCA_KEY})
    c.post("/api/v1/integrations/elevenlabs", json={"api_key": VALID_EL_KEY})
    attest_voice(c, CLONE_VOICE_ID)
    doc = c.post(
        "/api/v1/knowledge/documents",
        json={
            "title": "AsyncKB",
            "source_type": "text",
            "content": "Koebinar async pipeline with OrcaRouter ElevenLabs Remotion.",
        },
    ).json()
    created = c.post(
        "/api/v1/webinars",
        json={
            "theme": "Async webinar",
            "lang": "ja",
            "document_ids": [doc["id"]],
            "voice_id": "voice_clone_ja_en_01",
            "auto_run": True,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "queued"
    # Request finished without video; worker runs separately
    assert process_one(store, s, http_client=httpx.Client()) is True
    final = c.get(f"/api/v1/webinars/{body['id']}").json()
    assert final["status"] == "completed"
    types = {a["type"] for a in final["artifacts"]}
    for t in ("outline", "slides", "script", "timeline", "video"):
        assert t in types
    vid = c.get(f"/api/v1/webinars/{body['id']}/video")
    assert vid.status_code == 200
    assert len(vid.content) > 20


def test_e2e_async_step_rerun(async_env):
    s, store, c = async_env
    c.post("/api/v1/integrations/orcarouter", json={"api_key": VALID_ORCA_KEY})
    c.post("/api/v1/integrations/elevenlabs", json={"api_key": VALID_EL_KEY})
    attest_voice(c, CLONE_VOICE_ID)
    doc = c.post(
        "/api/v1/knowledge/documents",
        json={"title": "R", "source_type": "text", "content": "rerun knowledge content"},
    ).json()
    # create completed via sync override
    w = c.post(
        "/api/v1/webinars",
        json={
            "theme": "rerun",
            "document_ids": [doc["id"]],
            "voice_id": "voice_clone_ja_en_01",
            "auto_run": True,
            "sync": True,
        },
    ).json()
    assert w["status"] == "completed"
    # enqueue video step async
    r = c.post(f"/api/v1/webinars/{w['id']}/steps/video/run")
    assert r.status_code == 200
    assert r.json()["status"] == "queued"
    process_one(store, s, http_client=httpx.Client())
    assert c.get(f"/api/v1/webinars/{w['id']}").json()["status"] == "completed"


def test_e2e_health_stack(async_env):
    _, _, c = async_env
    r = c.get("/api/v1/health/stack")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["sync_pipeline"] is False
