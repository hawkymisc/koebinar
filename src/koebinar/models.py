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
    QUEUED = "queued"
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


# Reserved pseudo-voice used by the existing system-key/demo fallback path. It
# is not a provider Voice and therefore has no tenant consent record to collect.
SYSTEM_FALLBACK_VOICE_ID = "default"


class IntegrationStatus(str, Enum):
    ACTIVE = "active"
    INVALID = "invalid"
    DELETED = "deleted"


class VoiceConsentStatus(str, Enum):
    """Consent state of a provider voice for the owning tenant.

    ``required`` は「同意が必要だが未取得」を意味する fail-closed 初期値。
    """

    REQUIRED = "required"
    ATTESTED = "attested"
    NOT_REQUIRED = "not_required"


class VoiceConsentSource(str, Enum):
    """How an ``attested`` state was produced. Absent source is never trusted."""

    OPERATOR_ATTESTATION = "operator_attestation"


# 同意文面のバージョン。文面を変えたら必ず上げ、旧versionの同意は再取得させる。
VOICE_ATTESTATION_VERSION = "voice-consent-v1"
SUPPORTED_ATTESTATION_VERSIONS = frozenset({VOICE_ATTESTATION_VERSION})

# ElevenLabs が提供する共有ライブラリ音声。話者本人の同意はプロバイダ側で
# 取得済みのため、テナントによる attestation を要求しない。
# ここに載らない category (cloned / professional / 空文字 / 未知) は全て
# 同意必須として fail closed に倒す。
CONSENT_EXEMPT_VOICE_CATEGORIES = frozenset({"premade"})


def consent_status_for_category(category: str) -> VoiceConsentStatus:
    normalized = (category or "").strip().lower()
    if normalized in CONSENT_EXEMPT_VOICE_CATEGORIES:
        return VoiceConsentStatus.NOT_REQUIRED
    return VoiceConsentStatus.REQUIRED


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
    tenant_id: str = "default"
    title: str
    source_type: SourceType
    storage_uri: str
    status: DocumentStatus
    chunk_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class Chunk(BaseModel):
    id: str
    tenant_id: str = "default"
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
    instructions: str = ""
    document_ids: list[str] = Field(default_factory=list)
    auto_run: bool = True
    # When True, force in-process run even if settings.sync_pipeline is False.
    sync: Optional[bool] = None


class PipelineArtifact(BaseModel):
    id: str
    tenant_id: str = "default"
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
    tenant_id: str = "default"
    theme: str
    audience: str
    duration_min: int
    lang: Lang
    template: Template
    style: Style
    voice_id: str
    instructions: str = ""
    document_ids: list[str] = Field(default_factory=list)
    status: WebinarStatus = WebinarStatus.CREATED
    current_step: Optional[PipelineStep] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    artifacts: list[PipelineArtifact] = Field(default_factory=list)
    script: Optional[dict[str, Any]] = None
    job_id: Optional[str] = None
    published_at: Optional[datetime] = None


class ScriptPatchRequest(BaseModel):
    slides: list[dict[str, Any]]


class PublicationPatchRequest(BaseModel):
    published: bool


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


class LoginRequest(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=64)
    access_token: str = Field(min_length=1, max_length=512)


class TenantView(BaseModel):
    id: str
    name: str


class LoginResponse(BaseModel):
    tenant: TenantView
    token: str


class SessionResponse(BaseModel):
    tenant: TenantView


class VoiceInfo(BaseModel):
    """Provider metadata plus the tenant-scoped consent state of a voice."""

    voice_id: str
    name: str
    category: str = "cloned"
    labels: dict[str, str] = Field(default_factory=dict)
    active: bool = True
    consent_status: VoiceConsentStatus = VoiceConsentStatus.REQUIRED
    consent_source: Optional[VoiceConsentSource] = None
    attested_at: Optional[datetime] = None
    attested_by: Optional[str] = None
    attestation_version: Optional[str] = None
    usable: bool = False


class VoiceRef(BaseModel):
    """Tenant-scoped consent record for one provider voice.

    Persisted in ``store.voice_refs``. ``consent_status=attested`` is only
    honoured together with an explicit ``consent_source``; legacy rows written
    by the old auto-``consent_flag`` code path therefore migrate to
    ``required`` (fail closed) — see :meth:`from_stored`.
    """

    tenant_id: str = "default"
    integration_id: str = ""
    provider: Provider = Provider.ELEVENLABS
    voice_id: str
    name: str = ""
    category: str = "unknown"
    labels: dict[str, str] = Field(default_factory=dict)
    active: bool = True
    consent_status: VoiceConsentStatus = VoiceConsentStatus.REQUIRED
    consent_source: Optional[VoiceConsentSource] = None
    attested_at: Optional[datetime] = None
    attested_by: Optional[str] = None
    attestation_version: Optional[str] = None
    revoked_at: Optional[datetime] = None
    synced_at: datetime = Field(default_factory=utcnow)

    @classmethod
    def from_stored(cls, data: dict[str, Any]) -> "VoiceRef":
        """Load a persisted row, downgrading anything not provably attested.

        Rows written before A-005 carry ``consent_flag: true`` derived purely
        from a voice-list fetch. They are migrated to ``required`` so no
        presumed consent survives into the typed state. No dedicated database
        migration is needed: ``voice_refs`` is a JSON KV record, and this
        lazy normalization is safe for existing rows and future restarts.
        """
        payload = dict(data)
        payload.pop("consent_flag", None)
        status = payload.get("consent_status")
        source = payload.get("consent_source")
        category = payload.get("category") or ""
        if status not in {s.value for s in VoiceConsentStatus}:
            # Legacy / unknown row: recompute from category, never from a boolean.
            payload["consent_status"] = consent_status_for_category(category)
            payload["consent_source"] = None
        elif (
            status == VoiceConsentStatus.NOT_REQUIRED.value
            and consent_status_for_category(category) != VoiceConsentStatus.NOT_REQUIRED
        ):
            # ``not_required`` is only valid for a known exempt provider
            # category. Unknown or changed metadata must fail closed.
            payload["consent_status"] = VoiceConsentStatus.REQUIRED
            payload["consent_source"] = None
        elif status == VoiceConsentStatus.ATTESTED.value and source != VoiceConsentSource.OPERATOR_ATTESTATION.value:
            payload["consent_status"] = VoiceConsentStatus.REQUIRED
            payload["consent_source"] = None
        return cls.model_validate(payload)

    def is_usable(self) -> bool:
        if not self.active:
            return False
        if self.consent_status == VoiceConsentStatus.NOT_REQUIRED:
            return True
        return (
            self.consent_status == VoiceConsentStatus.ATTESTED
            and self.consent_source == VoiceConsentSource.OPERATOR_ATTESTATION
            and self.attestation_version in SUPPORTED_ATTESTATION_VERSIONS
            and self.attested_at is not None
            and bool(self.attested_by)
            and self.revoked_at is None
        )

    def to_voice_info(self) -> VoiceInfo:
        return VoiceInfo(
            voice_id=self.voice_id,
            name=self.name or "unnamed",
            category=self.category,
            labels=dict(self.labels),
            active=self.active,
            consent_status=self.consent_status,
            consent_source=self.consent_source,
            attested_at=self.attested_at,
            attested_by=self.attested_by,
            attestation_version=self.attestation_version,
            usable=self.is_usable(),
        )


class VoiceConsentRequest(BaseModel):
    """Explicit operator attestation for one cloned/custom voice."""

    accepted: bool = False
    attestation_version: str = VOICE_ATTESTATION_VERSION


class QuestionCreateRequest(BaseModel):
    webinar_id: str
    message: str


class ViewerQuestionCreateRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class Citation(BaseModel):
    document_id: str
    chunk_id: str
    score: float = 0.0


class Answer(BaseModel):
    id: str
    tenant_id: str = "default"
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
    tenant_id: str = "default"
    webinar_id: str
    message: str
    status: QuestionStatus = QuestionStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    answer: Optional[Answer] = None


class GenerationLog(BaseModel):
    id: str
    tenant_id: str = "default"
    request_id: str
    purpose: str
    model_id: str
    prompt_version: str
    cost_hint: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class IntentSignal(BaseModel):
    id: str
    tenant_id: str = "default"
    question_id: str
    type: str
    value: str
    confidence: float


class ErrorBody(BaseModel):
    detail: str
    code: Optional[str] = None
