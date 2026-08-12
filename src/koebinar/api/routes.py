"""REST API routes for Koebinar MVP."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from koebinar.api.deps import AppState, get_app_state, require_auth
from koebinar.integrations.service import IntegrationError
from koebinar.models import (
    IntegrationRegisterRequest,
    KnowledgeCreateRequest,
    PublicationPatchRequest,
    Provider,
    QuestionCreateRequest,
    ScriptPatchRequest,
    ViewerQuestionCreateRequest,
    WebinarCreateRequest,
    WebinarStatus,
)
from koebinar.pipeline.orchestrator import PipelineError


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "koebinar"}

    # --- Knowledge ---
    @router.post("/knowledge/documents", dependencies=[Depends(require_auth)])
    def register_document(body: KnowledgeCreateRequest, request: Request) -> dict[str, Any]:
        state = get_app_state(request)
        if not body.title or not body.content:
            raise HTTPException(status_code=422, detail="title and content are required")
        doc = state.knowledge.register(body)
        return doc.model_dump(mode="json")

    @router.get("/knowledge/documents", dependencies=[Depends(require_auth)])
    def list_documents(request: Request) -> list[dict[str, Any]]:
        state = get_app_state(request)
        return [d.model_dump(mode="json") for d in state.knowledge.list_documents()]

    @router.get("/knowledge/documents/{document_id}", dependencies=[Depends(require_auth)])
    def get_document(document_id: str, request: Request) -> dict[str, Any]:
        state = get_app_state(request)
        doc = state.knowledge.get(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="document not found")
        return doc.model_dump(mode="json")

    # --- Webinars ---
    @router.post("/webinars", dependencies=[Depends(require_auth)])
    def create_webinar(body: WebinarCreateRequest, request: Request) -> dict[str, Any]:
        state = get_app_state(request)
        if not body.theme:
            raise HTTPException(status_code=422, detail="theme is required")
        try:
            w = state.pipeline.create_webinar(body)
        except (PipelineError, IntegrationError) as exc:
            code = getattr(exc, "status_code", 400)
            raise HTTPException(status_code=code, detail=str(exc)) from exc
        return w.model_dump(mode="json")

    @router.get("/webinars", dependencies=[Depends(require_auth)])
    def list_webinars(request: Request) -> list[dict[str, Any]]:
        state = get_app_state(request)
        return [w.model_dump(mode="json") for w in state.pipeline.list_webinars()]

    @router.get("/webinars/{webinar_id}", dependencies=[Depends(require_auth)])
    def get_webinar(webinar_id: str, request: Request) -> dict[str, Any]:
        state = get_app_state(request)
        try:
            w = state.pipeline.get(webinar_id)
        except PipelineError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return w.model_dump(mode="json")

    @router.patch("/webinars/{webinar_id}/publication", dependencies=[Depends(require_auth)])
    def patch_publication(
        webinar_id: str, body: PublicationPatchRequest, request: Request
    ) -> dict[str, Any]:
        state = get_app_state(request)
        try:
            w = state.pipeline.patch_publication(webinar_id, body)
        except PipelineError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return w.model_dump(mode="json")

    @router.patch("/webinars/{webinar_id}/script", dependencies=[Depends(require_auth)])
    def patch_script(webinar_id: str, body: ScriptPatchRequest, request: Request) -> dict[str, Any]:
        state = get_app_state(request)
        try:
            w = state.pipeline.patch_script(webinar_id, body)
        except PipelineError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return w.model_dump(mode="json")

    @router.post("/webinars/{webinar_id}/steps/{step}/run", dependencies=[Depends(require_auth)])
    def run_step(
        webinar_id: str,
        step: str,
        request: Request,
        sync: Optional[bool] = Query(default=None),
    ) -> dict[str, Any]:
        state = get_app_state(request)
        try:
            w = state.pipeline.run_step_async(webinar_id, step, sync=sync)
        except (PipelineError, IntegrationError) as exc:
            code = getattr(exc, "status_code", 400)
            raise HTTPException(status_code=code, detail=str(exc)) from exc
        return w.model_dump(mode="json")

    @router.get("/webinars/{webinar_id}/jobs", dependencies=[Depends(require_auth)])
    def list_jobs(webinar_id: str, request: Request) -> dict[str, Any]:
        state = get_app_state(request)
        try:
            state.pipeline.get(webinar_id)
        except PipelineError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        jobs = state.pipeline.jobs.list_for_webinar(webinar_id)
        return {"jobs": [j.model_dump(mode="json") for j in jobs]}

    @router.get("/jobs/{job_id}", dependencies=[Depends(require_auth)])
    def get_job(job_id: str, request: Request) -> dict[str, Any]:
        state = get_app_state(request)
        job = state.pipeline.jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job.model_dump(mode="json")

    @router.get("/health/stack")
    def health_stack(request: Request) -> dict[str, Any]:
        """B-stack readiness: API + durable store + job queue stats."""
        state = get_app_state(request)
        stats = state.pipeline.jobs.stats()
        return {
            "status": "ok",
            "service": "koebinar",
            "sync_pipeline": state.settings.sync_pipeline,
            "db_path": str(state.settings.db_path),
            "artifacts_dir": str(state.settings.artifacts_dir),
            "jobs": stats,
            "remotion_project": str(state.settings.remotion_project_dir),
        }

    @router.get("/webinars/{webinar_id}/video", dependencies=[Depends(require_auth)])
    def get_video(webinar_id: str, request: Request) -> Response:
        state = get_app_state(request)
        try:
            path = state.pipeline.video_path(webinar_id)
        except PipelineError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        p = Path(path)
        if not p.exists():
            raise HTTPException(status_code=404, detail="video file missing")
        return FileResponse(
            path,
            media_type="video/mp4",
            filename="webinar.mp4",
            headers={"Cache-Control": "private, no-store"},
        )

    # --- Public viewer ---
    def get_published_webinar(webinar_id: str, request: Request):
        state = get_app_state(request)
        try:
            webinar = state.pipeline.get(webinar_id)
        except PipelineError as exc:
            raise HTTPException(status_code=404, detail="webinar not found") from exc
        if webinar.status != WebinarStatus.COMPLETED or webinar.published_at is None:
            raise HTTPException(status_code=404, detail="webinar not found")
        return state, webinar

    def public_question_view(state: AppState, webinar, question) -> dict[str, Any]:
        answer = None
        if question.answer is not None and question.status.value != "failed":
            citations = []
            for item in question.answer.citations:
                if item.document_id not in webinar.document_ids:
                    continue
                citation = item.model_dump(mode="json")
                document = state.store.documents.get(item.document_id)
                citation["source_title"] = document.title if document else "参照資料"
                citations.append(citation)
            answer = {
                "text": question.answer.text,
                "confidence": question.answer.confidence,
                "answerability": question.answer.answerability.value,
                "citations": citations,
            }
        return {
            "id": question.id,
            "message": question.message,
            "status": question.status.value,
            "created_at": question.model_dump(mode="json")["created_at"],
            "answer": answer,
        }

    @router.get("/public/webinars/{webinar_id}")
    def get_public_webinar(webinar_id: str, request: Request) -> dict[str, Any]:
        _, webinar = get_published_webinar(webinar_id, request)
        return {
            "id": webinar.id,
            "theme": webinar.theme,
            "audience": webinar.audience,
            "duration_min": webinar.duration_min,
            "lang": webinar.lang.value,
            "template": webinar.template.value,
            "published_at": webinar.model_dump(mode="json")["published_at"],
        }

    @router.get("/public/webinars/{webinar_id}/video")
    def get_public_video(webinar_id: str, request: Request) -> Response:
        state, _ = get_published_webinar(webinar_id, request)
        try:
            path = state.pipeline.video_path(webinar_id)
        except PipelineError as exc:
            raise HTTPException(status_code=404, detail="video not found") from exc
        if not Path(path).exists():
            raise HTTPException(status_code=404, detail="video not found")
        return FileResponse(
            path,
            media_type="video/mp4",
            filename="webinar.mp4",
            headers={"Cache-Control": "private, no-store"},
        )

    @router.post("/public/webinars/{webinar_id}/questions")
    def create_public_question(
        webinar_id: str, body: ViewerQuestionCreateRequest, request: Request
    ) -> dict[str, Any]:
        state, webinar = get_published_webinar(webinar_id, request)
        if not body.message.strip():
            raise HTTPException(status_code=422, detail="message required")
        client_host = request.client.host if request.client else "unknown"
        if not state.public_qa_limiter.allow(
            f"{client_host}:{webinar_id}",
            limit=state.settings.public_qa_rate_limit,
            window_seconds=state.settings.public_qa_rate_window_sec,
        ):
            raise HTTPException(
                status_code=429,
                detail="too many questions; please wait and try again",
                headers={"Retry-After": str(state.settings.public_qa_rate_window_sec)},
            )
        try:
            question = state.qa.ask(
                QuestionCreateRequest(webinar_id=webinar_id, message=body.message.strip())
            )
        except IntegrationError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return public_question_view(state, webinar, question)

    @router.get("/public/webinars/{webinar_id}/questions/{question_id}")
    def get_public_question(
        webinar_id: str, question_id: str, request: Request
    ) -> dict[str, Any]:
        state, webinar = get_published_webinar(webinar_id, request)
        question = state.qa.get(question_id)
        if question is None or question.webinar_id != webinar_id:
            raise HTTPException(status_code=404, detail="question not found")
        return public_question_view(state, webinar, question)

    # --- Integrations ---
    @router.post("/integrations/{provider}", dependencies=[Depends(require_auth)])
    def register_integration(
        provider: str, body: IntegrationRegisterRequest, request: Request
    ) -> dict[str, Any]:
        state = get_app_state(request)
        try:
            prov = Provider(provider)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"unsupported provider: {provider}") from exc
        try:
            view = state.integrations.register(prov, body)
        except IntegrationError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        data = view.model_dump(mode="json")
        # never include full key
        assert "api_key" not in data
        return data

    @router.get("/integrations", dependencies=[Depends(require_auth)])
    def list_integrations(request: Request) -> list[dict[str, Any]]:
        state = get_app_state(request)
        return [v.model_dump(mode="json") for v in state.integrations.list_all()]

    @router.delete("/integrations/{provider}", dependencies=[Depends(require_auth)])
    def delete_integration(provider: str, request: Request) -> dict[str, str]:
        state = get_app_state(request)
        try:
            prov = Provider(provider)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"unsupported provider: {provider}") from exc
        try:
            state.integrations.delete(prov)
        except IntegrationError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return {"status": "deleted", "provider": provider}

    @router.get("/integrations/elevenlabs/voices", dependencies=[Depends(require_auth)])
    def list_voices(request: Request) -> dict[str, Any]:
        state = get_app_state(request)
        try:
            voices = state.integrations.get_voices()
        except IntegrationError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return {"voices": [v.model_dump(mode="json") for v in voices]}

    # --- Questions ---
    @router.post("/questions", dependencies=[Depends(require_auth)])
    def create_question(body: QuestionCreateRequest, request: Request) -> dict[str, Any]:
        state = get_app_state(request)
        if not body.message or not body.webinar_id:
            raise HTTPException(status_code=422, detail="webinar_id and message required")
        try:
            q = state.qa.ask(body)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except IntegrationError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return q.model_dump(mode="json")

    @router.get("/questions/{question_id}", dependencies=[Depends(require_auth)])
    def get_question(question_id: str, request: Request) -> dict[str, Any]:
        state = get_app_state(request)
        q = state.qa.get(question_id)
        if not q:
            raise HTTPException(status_code=404, detail="question not found")
        return q.model_dump(mode="json")

    @router.get("/analytics/questions", dependencies=[Depends(require_auth)])
    def analytics_questions(
        request: Request,
        format: str = Query(default="json", pattern="^(json|csv)$"),
    ) -> Response:
        state = get_app_state(request)
        if format == "csv":
            return PlainTextResponse(state.qa.export("csv"), media_type="text/csv")
        return JSONResponse(content=state.qa.list_for_analytics())

    return router
