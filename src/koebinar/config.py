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
    default_auth_token: str = "mvp-token"

    # LLM / TTS model defaults
    llm_model: str = "adaptive"
    tts_model: str = "eleven_v3"
    prompt_version: str = "v1.0"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


def reset_settings_cache() -> None:
    get_settings.cache_clear()
