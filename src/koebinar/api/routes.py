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
    Provider,
    QuestionCreateRequest,
    ScriptPatchRequest,
    WebinarCreateRequest,
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

    @router.get("/webinars/{webinar_id}", dependencies=[Depends(require_auth)])
    def get_webinar(webinar_id: str, request: Request) -> dict[str, Any]:
        state = get_app_state(request)
        try:
            w = state.pipeline.get(webinar_id)
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
    def run_step(webinar_id: str, step: str, request: Request) -> dict[str, Any]:
        state = get_app_state(request)
        try:
            w = state.pipeline.run_from(webinar_id, step)
        except (PipelineError, IntegrationError) as exc:
            code = getattr(exc, "status_code", 400)
            raise HTTPException(status_code=code, detail=str(exc)) from exc
        return w.model_dump(mode="json")

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
        return FileResponse(path, media_type="video/mp4", filename="webinar.mp4")

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
    @router.post("/questions")
    def create_question(body: QuestionCreateRequest, request: Request) -> dict[str, Any]:
        # viewers may post without operator token in MVP widget path — still simple
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

    @router.get("/questions/{question_id}")
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
