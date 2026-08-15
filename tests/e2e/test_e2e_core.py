"""Core E2E scenarios against real FastAPI entry with mock providers."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.helpers import CLONE_VOICE_ID, seed_attested_voice_ref
from tests.mocks.providers import INVALID_EL_KEY, INVALID_ORCA_KEY, VALID_EL_KEY, VALID_ORCA_KEY


def test_health_and_root(client: TestClient):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    r2 = client.get("/")
    assert r2.status_code == 200
    assert "api" in r2.json()


def test_auth_required(client: TestClient):
    r = client.post(
        "/api/v1/knowledge/documents",
        json={"title": "t", "source_type": "text", "content": "c"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401


def test_knowledge_register_list_get(client: TestClient):
    r = client.post(
        "/api/v1/knowledge/documents",
        json={
            "title": "Spec",
            "source_type": "text",
            "content": "Koebinar builds AI webinars using OrcaRouter LLM gateway and ElevenLabs TTS.",
        },
    )
    assert r.status_code == 200
    doc = r.json()
    assert doc["status"] == "indexed"
    assert doc["chunk_count"] >= 1
    listed = client.get("/api/v1/knowledge/documents").json()
    assert any(d["id"] == doc["id"] for d in listed)
    got = client.get(f"/api/v1/knowledge/documents/{doc['id']}").json()
    assert got["title"] == "Spec"


def test_webinar_list(client: TestClient, store):
    seed_attested_voice_ref(store, CLONE_VOICE_ID)
    r1 = client.post(
        "/api/v1/webinars",
        json={"theme": "Webinar A", "voice_id": CLONE_VOICE_ID, "auto_run": False},
    )
    assert r1.status_code == 200
    r2 = client.post(
        "/api/v1/webinars",
        json={"theme": "Webinar B", "voice_id": CLONE_VOICE_ID, "auto_run": False},
    )
    assert r2.status_code == 200
    w1, w2 = r1.json(), r2.json()

    listed = client.get("/api/v1/webinars")
    assert listed.status_code == 200
    ids = [w["id"] for w in listed.json()]
    assert w1["id"] in ids
    assert w2["id"] in ids
    # newest first
    assert ids.index(w2["id"]) < ids.index(w1["id"])


def test_webinar_list_requires_auth(client: TestClient):
    r = client.get("/api/v1/webinars", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_integrations_byok_flow_no_full_key_leak(client: TestClient, register_keys):
    orca, el = register_keys()
    assert VALID_ORCA_KEY not in str(orca)
    assert VALID_EL_KEY not in str(el)
    assert "..." in orca["key_mask"]
    listed = client.get("/api/v1/integrations").json()
    blob = str(listed)
    assert VALID_ORCA_KEY not in blob
    assert VALID_EL_KEY not in blob
    voices = client.get("/api/v1/integrations/elevenlabs/voices").json()
    assert len(voices["voices"]) >= 1
    d = client.delete("/api/v1/integrations/elevenlabs")
    assert d.status_code == 200
    # after delete, voices fail closed
    r = client.get("/api/v1/integrations/elevenlabs/voices")
    assert r.status_code in (401, 404, 400, 502)


def test_invalid_integration_keys(client: TestClient):
    r = client.post("/api/v1/integrations/orcarouter", json={"api_key": INVALID_ORCA_KEY})
    assert r.status_code == 422
    assert r.json()["detail"] == "OrcaRouter APIキーを検証できませんでした"
    assert INVALID_ORCA_KEY not in r.text
    r2 = client.post("/api/v1/integrations/elevenlabs", json={"api_key": INVALID_EL_KEY})
    assert r2.status_code == 422
    assert "無効・期限切れ" in r2.json()["detail"]
    assert "Voices Read権限" in r2.json()["detail"]
    assert INVALID_EL_KEY not in r2.text


def test_full_pipeline_ja_and_artifacts(client: TestClient, register_keys):
    register_keys()
    doc = client.post(
        "/api/v1/knowledge/documents",
        json={
            "title": "Product KB",
            "source_type": "text",
            "content": (
                "Koebinarは資料からウェビナー動画を自動生成します。"
                "OrcaRouter経由でLLMを呼び出し、ElevenLabsでナレーションします。"
                "RemotionでMP4を出力します。料金はスタータープランから。"
            ),
        },
    ).json()
    w = client.post(
        "/api/v1/webinars",
        json={
            "theme": "Koebinar製品紹介",
            "audience": "SaaS担当者",
            "duration_min": 3,
            "lang": "ja",
            "template": "tech",
            "style": "keynote",
            "voice_id": "voice_clone_ja_en_01",
            "document_ids": [doc["id"]],
            "auto_run": True,
        },
    )
    assert w.status_code == 200, w.text
    body = w.json()
    assert body["status"] == "completed"
    types = {a["type"] for a in body["artifacts"]}
    for t in ("outline", "slides", "script", "tts_script", "timeline", "video"):
        assert t in types
    assert "audio" in types or "durations" in types
    # verify files exist
    for a in body["artifacts"]:
        assert Path(a["storage_uri"]).exists(), a
    vid = client.get(f"/api/v1/webinars/{body['id']}/video")
    assert vid.status_code == 200
    assert len(vid.content) > 20
    assert vid.content[4:8] == b"ftyp"


def test_full_pipeline_en(client: TestClient, register_keys):
    register_keys()
    doc = client.post(
        "/api/v1/knowledge/documents",
        json={
            "title": "EN KB",
            "source_type": "text",
            "content": "Koebinar auto-generates webinar videos. It uses OrcaRouter and ElevenLabs with Remotion.",
        },
    ).json()
    w = client.post(
        "/api/v1/webinars",
        json={
            "theme": "Product Overview",
            "lang": "en",
            "duration_min": 3,
            "document_ids": [doc["id"]],
            "voice_id": "voice_clone_ja_en_01",
            "auto_run": True,
        },
    )
    assert w.status_code == 200, w.text
    assert w.json()["status"] == "completed"
    assert w.json()["lang"] == "en"


def test_script_patch_and_rerun_from_tts(client: TestClient, register_keys):
    register_keys()
    doc = client.post(
        "/api/v1/knowledge/documents",
        json={"title": "KB", "source_type": "text", "content": "API integration is simple with REST endpoints."},
    ).json()
    w = client.post(
        "/api/v1/webinars",
        json={
            "theme": "API",
            "lang": "ja",
            "document_ids": [doc["id"]],
            "voice_id": "voice_clone_ja_en_01",
            "auto_run": True,
        },
    ).json()
    patched_slides = [
        {
            "slide_index": 0,
            "title": "修正後",
            "narration": "これは手動で修正した台本です。OrcaRouterを使います。",
            "references": [doc["id"]],
        }
    ]
    p = client.patch(f"/api/v1/webinars/{w['id']}/script", json={"slides": patched_slides})
    assert p.status_code == 200
    assert p.json()["script"]["manually_edited"] is True
    rerun = client.post(f"/api/v1/webinars/{w['id']}/steps/tts_script/run")
    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["status"] == "completed"


def test_pipeline_fails_closed_without_keys(client: TestClient, store):
    seed_attested_voice_ref(store, CLONE_VOICE_ID)
    r = client.post(
        "/api/v1/webinars",
        json={"theme": "No keys", "voice_id": CLONE_VOICE_ID, "auto_run": True},
    )
    assert r.status_code in (401, 400, 403, 500)


def test_qa_answerable_and_hold(client: TestClient, register_keys):
    register_keys()
    doc = client.post(
        "/api/v1/knowledge/documents",
        json={
            "title": "Pricing",
            "source_type": "text",
            "content": "Starter plan costs 100 USD per month. Enterprise includes SSO and audit logs.",
        },
    ).json()
    w = client.post(
        "/api/v1/webinars",
        json={
            "theme": "Pricing",
            "lang": "en",
            "document_ids": [doc["id"]],
            "voice_id": "voice_clone_ja_en_01",
            "auto_run": True,
        },
    ).json()
    # in-KB
    q1 = client.post(
        "/api/v1/questions",
        json={"webinar_id": w["id"], "message": "How much is the starter plan pricing cost?"},
    )
    assert q1.status_code == 200, q1.text
    a1 = q1.json()["answer"]
    assert a1["answerability"] == "answerable"
    assert a1["citations"]
    # off-KB
    q2 = client.post(
        "/api/v1/questions",
        json={"webinar_id": w["id"], "message": "What is the capital of Mars colonization fleet xyzzy?"},
    )
    assert q2.status_code == 200
    a2 = q2.json()["answer"]
    assert a2["answerability"] == "insufficient"
    # poll get
    g = client.get(f"/api/v1/questions/{q1.json()['id']}")
    assert g.status_code == 200
    # analytics
    an = client.get("/api/v1/analytics/questions")
    assert an.status_code == 200
    assert isinstance(an.json(), list)
    csv = client.get("/api/v1/analytics/questions?format=csv")
    assert csv.status_code == 200
    assert "question_id" in csv.text


def test_delete_key_then_generation_fails(client: TestClient, register_keys):
    register_keys()
    client.delete("/api/v1/integrations/orcarouter")
    r = client.post(
        "/api/v1/webinars",
        json={"theme": "fail", "voice_id": CLONE_VOICE_ID, "auto_run": True},
    )
    assert r.status_code in (401, 400, 403, 500)
