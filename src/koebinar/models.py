"""Domain and API models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceType(str, Enum):
    PDF = "pdf"
    URL = "url"
    TEXT = "text"


class DocumentStatus(str, Enum):
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


class WebinarStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class PipelineStep(str, Enum):
    OUTLINE = "outline"
    SLIDES = "slides"
    SCRIPT = "script"
    TTS_SCRIPT = "tts_script"
    AUDIO = "audio"
    TIMELINE = "timeline"
    VIDEO = "video"


PIPELINE_ORDER: list[PipelineStep] = [
    PipelineStep.OUTLINE,
    PipelineStep.SLIDES,
    PipelineStep.SCRIPT,
    PipelineStep.TTS_SCRIPT,
    PipelineStep.AUDIO,
    PipelineStep.TIMELINE,
    PipelineStep.VIDEO,
]


class ArtifactType(str, Enum):
    OUTLINE = "outline"
    SLIDES = "slides"
    SCRIPT = "script"
    TTS_SCRIPT = "tts_script"
    AUDIO = "audio"
    TIMELINE = "timeline"
    VIDEO = "video"
    DURATIONS = "durations"


class Provider(str, Enum):
    ORCAROUTER = "orcarouter"
    ELEVENLABS = "elevenlabs"


class IntegrationStatus(str, Enum):
    ACTIVE = "active"
    INVALID = "invalid"
    DELETED = "deleted"


class Answerability(str, Enum):
    ANSWERABLE = "answerable"
    INSUFFICIENT = "insufficient"
    RESTRICTED = "restricted"


class QuestionStatus(str, Enum):
    PENDING = "pending"
    ANSWERED = "answered"
    HELD = "held"
    FAILED = "failed"


class Lang(str, Enum):
    JA = "ja"
    EN = "en"


class Template(str, Enum):
    TECH = "tech"
    CASUAL = "casual"
    FORMAL = "formal"


class Style(str, Enum):
    CASUAL = "casual"
    KEYNOTE = "keynote"
    FORMAL = "formal"
    HUMOROUS = "humorous"


# --- Request / Response schemas ---


class KnowledgeCreateRequest(BaseModel):
    title: str
    source_type: SourceType
    content: str = Field(..., description="Raw text, URL, or PDF text extraction payload")
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeDocument(BaseModel):
    id: str
    title: str
    source_type: SourceType
    storage_uri: str
    status: DocumentStatus
    chunk_count: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class Chunk(BaseModel):
    id: str
    document_id: str
    text: str
    section: str = ""
    embedding: list[float] = Field(default_factory=list)


class WebinarCreateRequest(BaseModel):
    theme: str
    audience: str = "general"
    duration_min: int = 5
    lang: Lang = Lang.JA
    template: Template = Template.TECH
    style: Style = Style.KEYNOTE
    voice_id: str = "default"
    document_ids: list[str] = Field(default_factory=list)
    auto_run: bool = True


class PipelineArtifact(BaseModel):
    id: str
    webinar_id: str
    step: PipelineStep
    type: ArtifactType
    storage_uri: str
    model_id: Optional[str] = None
    prompt_version: Optional[str] = None
    input_hash: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    meta: dict[str, Any] = Field(default_factory=dict)


class Webinar(BaseModel):
    id: str
    theme: str
    audience: str
    duration_min: int
    lang: Lang
    template: Template
    style: Style
    voice_id: str
    document_ids: list[str] = Field(default_factory=list)
    status: WebinarStatus = WebinarStatus.CREATED
    current_step: Optional[PipelineStep] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    artifacts: list[PipelineArtifact] = Field(default_factory=list)
    script: Optional[dict[str, Any]] = None


class ScriptPatchRequest(BaseModel):
    slides: list[dict[str, Any]]


class IntegrationRegisterRequest(BaseModel):
    api_key: str
    accept_free_tier: bool = False


class IntegrationView(BaseModel):
    id: str
    provider: Provider
    key_mask: str
    status: IntegrationStatus
    validated_at: Optional[datetime] = None
    meta: dict[str, Any] = Field(default_factory=dict)


class VoiceInfo(BaseModel):
    voice_id: str
    name: str
    category: str = "cloned"
    labels: dict[str, str] = Field(default_factory=dict)


class QuestionCreateRequest(BaseModel):
    webinar_id: str
    message: str


class Citation(BaseModel):
    document_id: str
    chunk_id: str
    score: float = 0.0


class Answer(BaseModel):
    id: str
    question_id: str
    text: str
    confidence: float
    answerability: Answerability
    citations: list[Citation] = Field(default_factory=list)
    model_id: Optional[str] = None
    prompt_version: Optional[str] = None
    intent: Optional[dict[str, Any]] = None


class Question(BaseModel):
    id: str
    webinar_id: str
    message: str
    status: QuestionStatus = QuestionStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    answer: Optional[Answer] = None


class GenerationLog(BaseModel):
    id: str
    request_id: str
    purpose: str
    model_id: str
    prompt_version: str
    cost_hint: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class IntentSignal(BaseModel):
    id: str
    question_id: str
    type: str
    value: str
    confidence: float


class ErrorBody(BaseModel):
    detail: str
    code: Optional[str] = None
