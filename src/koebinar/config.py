"""Application configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KOEBINAR_", env_file=".env", extra="ignore")

    app_name: str = "Koebinar"
    api_prefix: str = "/api/v1"
    data_dir: Path = Path("storage")
    artifacts_dir: Path = Path("artifacts")
    pronunciation_dict_path: Path = Path("data/pronunciation_dict.tsv")

    # Durable metadata DB (SQLite). Empty string disables durability (memory-only).
    db_path: Path = Path("storage/koebinar.db")

    # Master key for encrypting BYOK secrets (32-byte hex or passphrase)
    master_key: str = "koebinar-dev-master-key-change-me"

    # System fallback keys (demo only; disabled by default)
    orcarouter_api_key: str = ""
    elevenlabs_api_key: str = ""
    allow_system_llm_key: bool = False
    allow_system_tts_key: bool = False

    orcarouter_base_url: str = "https://api.orcarouter.ai/v1"
    elevenlabs_base_url: str = "https://api.elevenlabs.io/v1"

    confidence_threshold: float = 0.7
    fps: int = 30
    # Required for operator APIs. No default: a public web bundle must not reveal it.
    default_auth_token: str = ""
    # JSON array of {id, name, access_token}. When set, takes precedence over
    # default_auth_token and enables tenant-aware operator authentication.
    tenants_json: str = ""

    # Anonymous viewer Q&A abuse guard (per client IP + webinar, per process).
    public_qa_rate_limit: int = 10
    public_qa_rate_window_sec: int = 60

    # LLM / TTS model defaults
    # OrcaRouter's account-provisioned adaptive router. The bare "adaptive"
    # alias is not part of the hosted API's public model-id contract.
    llm_model: str = "orcarouter/auto"
    # Hosted OrcaRouter does not publish a recommended timeout. Its documented
    # OpenAI-compatible path can serve long-running routed generations, so keep
    # connect/write bounds narrow while allowing a long response read window.
    orcarouter_connect_timeout_sec: float = 10.0
    orcarouter_models_read_timeout_sec: float = 30.0
    orcarouter_read_timeout_sec: float = 600.0
    # Public Q&A is interactive and polls asynchronously; fail one attempt in a
    # bounded window instead of inheriting the long-form generation timeout.
    orcarouter_qa_read_timeout_sec: float = 60.0
    orcarouter_write_timeout_sec: float = 30.0
    orcarouter_pool_timeout_sec: float = 10.0
    orcarouter_max_retries: int = 1
    orcarouter_retry_backoff_sec: float = 1.0
    orcarouter_retry_max_delay_sec: float = 60.0
    tts_model: str = "eleven_v3"
    # The requested provider format is only a hint. Persisted artifacts derive
    # their extension and MIME type from the returned bytes.
    tts_output_format: str = "mp3_44100_128"
    prompt_version: str = "v1.0"

    # Pipeline execution: True = run steps in API process (tests/dev).
    # False = enqueue jobs for the worker process (local B-stack default).
    sync_pipeline: bool = False

    # Remotion
    remotion_project_dir: Path = Path("remotion")
    # 1080p H.264 rendering is slower than real time on the 2-vCPU demo host.
    # Include bundling, Chromium startup, frame rendering, encoding, and muxing.
    remotion_timeout_sec: float = 900.0
    force_render_double: bool = False
    # Maximum accepted difference between the timeline and probed media.
    audio_duration_tolerance_sec: float = 0.5

    # Worker
    worker_poll_interval_sec: float = 0.25
    worker_idle_exit: bool = False  # if True, worker exits when queue empty (tests)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        if self.db_path and str(self.db_path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


def reset_settings_cache() -> None:
    get_settings.cache_clear()
