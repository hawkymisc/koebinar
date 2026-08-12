"""Pipeline orchestrator: step state, artifacts, re-run."""

from __future__ import annotations

from typing import Any, Optional

from koebinar.config import Settings, get_settings
from koebinar.crypto import generate_id
from koebinar.integrations.service import IntegrationError, IntegrationsService
from koebinar.jobs import JobQueue
from koebinar.knowledge.service import KnowledgeService
from koebinar.models import (
    ArtifactType,
    PIPELINE_ORDER,
    PipelineArtifact,
    PipelineStep,
    PublicationPatchRequest,
    ScriptPatchRequest,
    Webinar,
    WebinarCreateRequest,
    WebinarStatus,
    utcnow,
)
from koebinar.pipeline.renderer import VideoRenderer
from koebinar.pipeline.steps import GenerationSteps
from koebinar.pipeline.timeline import build_timeline
from koebinar.pipeline.tts import TTSAdapter
from koebinar.storage import Store, get_store


class PipelineError(Exception):
    def __init__(self, message: str, code: str | None = None, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class PipelineOrchestrator:
    def __init__(
        self,
        store: Optional[Store] = None,
        settings: Optional[Settings] = None,
        http_client=None,
    ) -> None:
        self.store = store or get_store()
        self.settings = settings or get_settings()
        self.http_client = http_client
        self.integrations = IntegrationsService(store=self.store, settings=self.settings, http_client=http_client)
        self.knowledge = KnowledgeService(store=self.store)
        self.steps = GenerationSteps(
            store=self.store,
            settings=self.settings,
            integrations=self.integrations,
            knowledge=self.knowledge,
            http_client=http_client,
        )
        self.tts = TTSAdapter(
            store=self.store,
            settings=self.settings,
            integrations=self.integrations,
            http_client=http_client,
        )
        self.renderer = VideoRenderer(store=self.store, settings=self.settings)
        self.jobs = JobQueue(self.store)

    def _use_sync(self, req_sync: bool | None = None) -> bool:
        if req_sync is not None:
            return bool(req_sync)
        return bool(self.settings.sync_pipeline)

    def create_webinar(self, req: WebinarCreateRequest) -> Webinar:
        wid = generate_id("web_")
        webinar = Webinar(
            id=wid,
            theme=req.theme,
            audience=req.audience,
            duration_min=req.duration_min,
            lang=req.lang,
            template=req.template,
            style=req.style,
            voice_id=req.voice_id,
            instructions=req.instructions,
            document_ids=list(req.document_ids),
            status=WebinarStatus.CREATED,
        )
        self.store.webinars[wid] = webinar
        if req.auto_run:
            if self._use_sync(req.sync):
                self.run_from(wid, PipelineStep.OUTLINE)
            else:
                self.enqueue_from(wid, PipelineStep.OUTLINE)
        return self.store.webinars[wid]

    def enqueue_from(self, webinar_id: str, step: PipelineStep | str) -> Webinar:
        """Enqueue pipeline run for the worker (does not execute steps here)."""
        if isinstance(step, str):
            try:
                step = PipelineStep(step)
            except ValueError as exc:
                raise PipelineError(f"unknown step: {step}", code="invalid_step") from exc
        w = self.get(webinar_id)
        job = self.jobs.enqueue(webinar_id, step)
        w.published_at = None
        w.status = WebinarStatus.QUEUED
        w.job_id = job.id
        w.error = None
        self.store.webinars[webinar_id] = w
        return w

    def get(self, webinar_id: str) -> Webinar:
        w = self.store.webinars.get(webinar_id)
        if not w:
            raise PipelineError("webinar not found", code="not_found", status_code=404)
        return w

    def list_webinars(self) -> list[Webinar]:
        items = list(self.store.webinars.values())
        items.sort(key=lambda w: w.created_at, reverse=True)
        return items

    def patch_publication(self, webinar_id: str, req: PublicationPatchRequest) -> Webinar:
        w = self.get(webinar_id)
        if req.published and w.status != WebinarStatus.COMPLETED:
            raise PipelineError(
                "completed webinar required",
                code="not_completed",
                status_code=409,
            )
        w.published_at = utcnow() if req.published else None
        self.store.webinars[webinar_id] = w
        return w

    def patch_script(self, webinar_id: str, req: ScriptPatchRequest) -> Webinar:
        w = self.get(webinar_id)
        script = w.script or {"slides": []}
        script = {**script, "slides": req.slides, "manually_edited": True}
        w.script = script
        w.published_at = None
        # persist script artifact
        uri = self.store.write_json(webinar_id, "script.json", script)
        self._upsert_artifact(
            w,
            step=PipelineStep.SCRIPT,
            atype=ArtifactType.SCRIPT,
            uri=uri,
            model_id=script.get("model_id"),
            prompt_version=script.get("prompt_version"),
        )
        self.store.webinars[webinar_id] = w
        return w

    def run_from(self, webinar_id: str, step: PipelineStep | str) -> Webinar:
        if isinstance(step, str):
            try:
                step = PipelineStep(step)
            except ValueError as exc:
                raise PipelineError(f"unknown step: {step}", code="invalid_step") from exc
        if step not in PIPELINE_ORDER:
            raise PipelineError(f"unknown step: {step}", code="invalid_step")

        w = self.get(webinar_id)
        w.published_at = None
        # Re-fetch and persist after each step so API polling sees progress
        w.status = WebinarStatus.RUNNING
        self.store.webinars[webinar_id] = w
        start_idx = PIPELINE_ORDER.index(step)
        try:
            for s in PIPELINE_ORDER[start_idx:]:
                w = self.get(webinar_id)
                w.current_step = s
                w.status = WebinarStatus.RUNNING
                self.store.webinars[webinar_id] = w
                self._run_step(w, s)
                self.store.webinars[webinar_id] = w
            w = self.get(webinar_id)
            w.status = WebinarStatus.COMPLETED
            w.error = None
        except (PipelineError, IntegrationError) as exc:
            w = self.get(webinar_id)
            w.status = WebinarStatus.FAILED
            w.error = str(exc)
            self.store.webinars[webinar_id] = w
            raise
        except Exception as exc:
            w = self.get(webinar_id)
            w.status = WebinarStatus.FAILED
            w.error = str(exc)
            self.store.webinars[webinar_id] = w
            raise PipelineError(str(exc), code="pipeline_failed", status_code=500) from exc
        self.store.webinars[webinar_id] = w
        return w

    def run_step_async(self, webinar_id: str, step: PipelineStep | str, *, sync: bool | None = None) -> Webinar:
        """Enqueue or run a step based on sync mode."""
        if self._use_sync(sync):
            return self.run_from(webinar_id, step)
        return self.enqueue_from(webinar_id, step)

    def video_path(self, webinar_id: str) -> str:
        w = self.get(webinar_id)
        for a in w.artifacts:
            if a.type == ArtifactType.VIDEO:
                return a.storage_uri
        raise PipelineError("video not ready", code="not_ready", status_code=404)

    def _run_step(self, w: Webinar, step: PipelineStep) -> None:
        if step == PipelineStep.OUTLINE:
            data = self.steps.generate_outline(w)
            uri = self.store.write_json(w.id, "outline.json", data)
            self._upsert_artifact(w, step, ArtifactType.OUTLINE, uri, data.get("model_id"), data.get("prompt_version"), data.get("input_hash"))
        elif step == PipelineStep.SLIDES:
            outline = self._load_artifact_json(w, ArtifactType.OUTLINE)
            data = self.steps.generate_slides(w, outline)
            uri = self.store.write_json(w.id, "slides.json", data)
            self._upsert_artifact(w, step, ArtifactType.SLIDES, uri, data.get("model_id"), data.get("prompt_version"), data.get("input_hash"))
        elif step == PipelineStep.SCRIPT:
            slides = self._load_artifact_json(w, ArtifactType.SLIDES)
            data = self.steps.generate_script(w, slides)
            w.script = data
            uri = self.store.write_json(w.id, "script.json", data)
            self._upsert_artifact(w, step, ArtifactType.SCRIPT, uri, data.get("model_id"), data.get("prompt_version"), data.get("input_hash"))
        elif step == PipelineStep.TTS_SCRIPT:
            script = w.script or self._load_artifact_json(w, ArtifactType.SCRIPT)
            data = self.tts.prepare_tts_script(script, w.lang.value)
            uri = self.store.write_json(w.id, "tts_script.json", data)
            self._upsert_artifact(w, step, ArtifactType.TTS_SCRIPT, uri, self.settings.tts_model, self.settings.prompt_version)
        elif step == PipelineStep.AUDIO:
            tts_script = self._load_artifact_json(w, ArtifactType.TTS_SCRIPT)
            durations, meta = self.tts.synthesize_script(w.id, tts_script, w.voice_id, w.lang.value)
            dur_uri = self.store.write_json(w.id, "durations.json", {"items": durations, **meta})
            self._upsert_artifact(w, step, ArtifactType.DURATIONS, dur_uri, meta.get("model_id"), self.settings.prompt_version)
            self._upsert_artifact(w, step, ArtifactType.AUDIO, dur_uri, meta.get("model_id"), self.settings.prompt_version, meta={"count": len(durations)})
        elif step == PipelineStep.TIMELINE:
            slides = self._load_artifact_json(w, ArtifactType.SLIDES)
            durations_doc = self._load_artifact_json(w, ArtifactType.DURATIONS)
            items = durations_doc.get("items") or durations_doc.get("durations") or []
            timeline = build_timeline(slides.get("slides") or [], items, fps=self.settings.fps)
            uri = self.store.write_json(w.id, "timeline.json", timeline)
            self._upsert_artifact(w, step, ArtifactType.TIMELINE, uri, None, self.settings.prompt_version)
        elif step == PipelineStep.VIDEO:
            slides = self._load_artifact_json(w, ArtifactType.SLIDES)
            timeline = self._load_artifact_json(w, ArtifactType.TIMELINE)
            uri, meta = self.renderer.render(w.id, timeline, slides.get("slides") or [])
            self._upsert_artifact(w, step, ArtifactType.VIDEO, uri, None, self.settings.prompt_version, meta=meta)
        else:
            raise PipelineError(f"unhandled step {step}", code="invalid_step")

    def _load_artifact_json(self, w: Webinar, atype: ArtifactType) -> dict[str, Any]:
        for a in reversed(w.artifacts):
            if a.type == atype:
                return self.store.read_json(a.storage_uri)
        # try conventional path
        name_map = {
            ArtifactType.OUTLINE: "outline.json",
            ArtifactType.SLIDES: "slides.json",
            ArtifactType.SCRIPT: "script.json",
            ArtifactType.TTS_SCRIPT: "tts_script.json",
            ArtifactType.DURATIONS: "durations.json",
            ArtifactType.TIMELINE: "timeline.json",
        }
        name = name_map.get(atype)
        if name:
            path = self.store.artifact_path(w.id, name)
            if path.exists():
                return self.store.read_json(str(path))
        raise PipelineError(f"missing artifact {atype.value}", code="missing_artifact", status_code=409)

    def _upsert_artifact(
        self,
        w: Webinar,
        step: PipelineStep,
        atype: ArtifactType,
        uri: str,
        model_id: str | None = None,
        prompt_version: str | None = None,
        input_hash: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> PipelineArtifact:
        art = PipelineArtifact(
            id=generate_id("art_"),
            webinar_id=w.id,
            step=step,
            type=atype,
            storage_uri=uri,
            model_id=model_id,
            prompt_version=prompt_version,
            input_hash=input_hash,
            meta=meta or {},
        )
        # replace previous of same type
        w.artifacts = [a for a in w.artifacts if a.type != atype]
        w.artifacts.append(art)
        return art
