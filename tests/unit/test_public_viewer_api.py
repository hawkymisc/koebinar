"""Public viewer API contract tests."""

from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient

from koebinar.models import (
    Answer,
    Answerability,
    ArtifactType,
    Citation,
    DocumentStatus,
    KnowledgeDocument,
    PipelineArtifact,
    PipelineStep,
    Question,
    QuestionStatus,
    SourceType,
    Webinar,
    WebinarStatus,
)
from koebinar.storage import Store


def _completed_webinar(store: Store, video_path: Path, webinar_id: str = "web_public") -> Webinar:
    video_path.write_bytes(b"public-video")
    webinar = Webinar(
        id=webinar_id,
        theme="公開ウェビナー",
        audience="プロダクト担当者",
        duration_min=5,
        lang="ja",
        template="tech",
        style="keynote",
        voice_id="secret-voice",
        instructions="外部には出さない運用指示",
        document_ids=["doc_public"],
        status=WebinarStatus.COMPLETED,
        current_step=PipelineStep.VIDEO,
        artifacts=[
            PipelineArtifact(
                id="artifact_video",
                webinar_id=webinar_id,
                step=PipelineStep.VIDEO,
                type=ArtifactType.VIDEO,
                storage_uri=str(video_path),
            )
        ],
        script={"slides": [{"title": "非公開台本", "narration": "秘密"}]},
    )
    store.webinars[webinar.id] = webinar
    return webinar


def test_public_view_requires_explicit_publication(
    client: TestClient, store: Store, settings
):
    webinar = _completed_webinar(store, settings.artifacts_dir / "viewer.mp4")

    hidden = client.get(
        f"/api/v1/public/webinars/{webinar.id}",
        headers={"Authorization": "Bearer wrong"},
    )
    assert hidden.status_code == 404

    published = client.patch(
        f"/api/v1/webinars/{webinar.id}/publication",
        json={"published": True},
    )
    assert published.status_code == 200
    assert published.json()["published_at"] is not None

    public = client.get(
        f"/api/v1/public/webinars/{webinar.id}",
        headers={"Authorization": "Bearer wrong"},
    )
    assert public.status_code == 200
    assert public.json() == {
        "id": webinar.id,
        "theme": "公開ウェビナー",
        "audience": "プロダクト担当者",
        "duration_min": 5,
        "lang": "ja",
        "template": "tech",
        "published_at": published.json()["published_at"],
    }
    assert "voice_id" not in public.text
    assert "instructions" not in public.text
    assert "document_ids" not in public.text
    assert "script" not in public.text

    video = client.get(
        f"/api/v1/public/webinars/{webinar.id}/video",
        headers={"Authorization": "Bearer wrong"},
    )
    assert video.status_code == 200
    assert video.content == b"public-video"
    assert video.headers["content-type"].startswith("video/mp4")

    unpublished = client.patch(
        f"/api/v1/webinars/{webinar.id}/publication",
        json={"published": False},
    )
    assert unpublished.status_code == 200
    assert unpublished.json()["published_at"] is None
    assert client.get(f"/api/v1/public/webinars/{webinar.id}").status_code == 404
    assert client.get(f"/api/v1/public/webinars/{webinar.id}/video").status_code == 404


def test_only_completed_webinar_can_be_published(client: TestClient, store: Store):
    webinar = Webinar(
        id="web_draft",
        theme="未完成",
        audience="general",
        duration_min=5,
        lang="ja",
        template="tech",
        style="keynote",
        voice_id="default",
        status=WebinarStatus.RUNNING,
    )
    store.webinars[webinar.id] = webinar

    response = client.patch(
        f"/api/v1/webinars/{webinar.id}/publication",
        json={"published": True},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "completed webinar required"


def test_public_question_response_includes_source_titles(
    client: TestClient, store: Store, settings
):
    webinar = _completed_webinar(
        store,
        settings.artifacts_dir / "question-viewer.mp4",
        webinar_id="web_question",
    )
    webinar.published_at = webinar.created_at
    store.webinars[webinar.id] = webinar
    store.documents["doc_public"] = KnowledgeDocument(
        id="doc_public",
        title="製品仕様書",
        source_type=SourceType.TEXT,
        storage_uri="memory://doc_public",
        status=DocumentStatus.INDEXED,
        chunk_count=1,
    )
    store.documents["doc_foreign"] = KnowledgeDocument(
        id="doc_foreign",
        title="別ウェビナーの秘密資料",
        source_type=SourceType.TEXT,
        storage_uri="memory://doc_foreign",
        status=DocumentStatus.INDEXED,
        chunk_count=1,
    )
    question = Question(
        id="q_public",
        webinar_id=webinar.id,
        message="対応環境は？",
        status=QuestionStatus.ANSWERED,
        answer=Answer(
            id="ans_public",
            question_id="q_public",
            text="ブラウザで利用できます。",
            confidence=0.91,
            answerability=Answerability.ANSWERABLE,
            citations=[
                Citation(document_id="doc_public", chunk_id="chunk_1", score=0.8),
                Citation(document_id="doc_foreign", chunk_id="chunk_2", score=0.9),
            ],
        ),
    )
    store.questions[question.id] = question

    response = client.get(
        f"/api/v1/public/webinars/{webinar.id}/questions/{question.id}",
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 200
    citation = response.json()["answer"]["citations"][0]
    assert citation == {
        "document_id": "doc_public",
        "chunk_id": "chunk_1",
        "score": 0.8,
        "source_title": "製品仕様書",
    }
    assert "model_id" not in response.text
    assert "prompt_version" not in response.text
    assert "intent" not in response.text
    assert "question_id" not in response.text
    assert "別ウェビナーの秘密資料" not in response.text

    other = client.get("/api/v1/public/webinars/web_other/questions/q_public")
    assert other.status_code == 404


def test_legacy_question_endpoints_are_operator_only(client: TestClient):
    headers = {"Authorization": "Bearer wrong"}
    created = client.post(
        "/api/v1/questions",
        json={"webinar_id": "web_any", "message": "hello"},
        headers=headers,
    )
    assert created.status_code == 401
    assert client.get("/api/v1/questions/q_any", headers=headers).status_code == 401


def test_operator_api_fails_closed_without_configured_token(client: TestClient):
    client.app.state.koebinar.settings.default_auth_token = ""
    response = client.get("/api/v1/webinars")
    assert response.status_code == 503
    assert response.json()["detail"] == "operator authentication is not configured"


def test_public_questions_are_rate_limited(client: TestClient, store: Store, settings):
    webinar = _completed_webinar(
        store,
        settings.artifacts_dir / "limited-viewer.mp4",
        webinar_id="web_limited",
    )
    webinar.published_at = webinar.created_at
    store.webinars[webinar.id] = webinar
    app_state = client.app.state.koebinar
    app_state.settings.public_qa_rate_limit = 2
    app_state.qa.ask = Mock(
        side_effect=lambda req: Question(
            id=f"q_{req.message}",
            webinar_id=req.webinar_id,
            message=req.message,
            status=QuestionStatus.HELD,
        )
    )

    endpoint = f"/api/v1/public/webinars/{webinar.id}/questions"
    assert client.post(endpoint, json={"message": "one"}).status_code == 200
    assert client.post(endpoint, json={"message": "two"}).status_code == 200
    limited = client.post(endpoint, json={"message": "three"})
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == str(settings.public_qa_rate_window_sec)
    assert app_state.qa.ask.call_count == 2


def test_editing_or_regenerating_requires_republication(
    client: TestClient, store: Store, settings
):
    webinar = _completed_webinar(
        store,
        settings.artifacts_dir / "republish-viewer.mp4",
        webinar_id="web_republish",
    )
    webinar.published_at = webinar.created_at
    store.webinars[webinar.id] = webinar

    edited = client.patch(
        f"/api/v1/webinars/{webinar.id}/script",
        json={"slides": [{"title": "更新", "narration": "レビュー前"}]},
    )
    assert edited.status_code == 200
    assert edited.json()["published_at"] is None

    webinar = store.webinars[webinar.id]
    webinar.published_at = webinar.created_at
    store.webinars[webinar.id] = webinar
    queued = client.app.state.koebinar.pipeline.enqueue_from(webinar.id, PipelineStep.VIDEO)
    assert queued.published_at is None
