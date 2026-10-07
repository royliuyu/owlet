"""Settings from YAML, then .env, then environment variables.

Paths are resolved from this file's repository root, never from the
process working directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "config").is_dir():
            return candidate
    return here.parents[2]


REPO_ROOT = _find_repo_root()
DEFAULT_YAML = REPO_ROOT / "config" / "default.yaml"
LOCAL_YAML = REPO_ROOT / "config" / "local.yaml"


class LLMSettings(BaseModel):
    """Ollama by default. Any OpenAI-compatible host works via base_url."""

    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3:4b"
    embedding_model: str = "qwen3-embedding:0.6b"
    embedding_dim: int = 1024
    timeout: float = 180.0
    num_ctx: int = 8192
    embed_batch: int = 16


class ChunkSettings(BaseModel):
    """Token budget per chunk.

    These are starting points to tune against retrieval quality, not
    fixed truths. Changing any of them changes `chunking_version`, which
    is what makes a re-index detectable.
    """

    target_tokens: int = 500
    max_tokens: int = 800
    min_tokens: int = 120
    overlap_tokens: int = 80

    @property
    def version(self) -> str:
        """Identifies the chunk layout these settings produce."""
        return (
            f"v2-structure-{self.target_tokens}-{self.max_tokens}"
            f"-{self.min_tokens}-{self.overlap_tokens}"
        )


class GoogleSettings(BaseModel):
    """OAuth client for Calendar, and later Mail on the same account.

    `redirect_origins` is a comma-separated list of extra origins that may
    finish sign-in, such as a later cloud host. Loopback on `port` is always
    allowed and is not listed here. The client secret may be empty when the
    Google client is public and PKCE is enough.
    """

    client_id: str = ""
    client_secret: str = ""
    redirect_origins: str = ""

    @property
    def origins(self) -> list[str]:
        return [
            part.strip().rstrip("/")
            for part in self.redirect_origins.split(",")
            if part.strip()
        ]


class RetrievalSettings(BaseModel):
    bm25_k: int = 50
    vector_k: int = 50
    rrf_k: int = 60
    top_k: int = 8
    # How many passages one document may take before another document gets a slot.
    # Leftover slots are filled from the overflow, so a library with one match
    # still returns a full page of that document.
    per_doc_k: int = 2


class Settings(BaseSettings):
    """Bootstrap values only.

    Which folders owlet reads is not here: that is user data, edited from
    the UI, and lives in the `sources` table of the metadata database.
    """

    data_dir: Path = Path("data")
    auth_token: str = ""
    host: str = "127.0.0.1"
    port: int = 8000
    llm: LLMSettings = Field(default_factory=LLMSettings)
    chunking: ChunkSettings = Field(default_factory=ChunkSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    google: GoogleSettings = Field(default_factory=GoogleSettings)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "metadata.db"

    model_config = SettingsConfigDict(
        env_prefix="OWLET_",
        env_nested_delimiter="__",
        env_file=REPO_ROOT / ".env",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del file_secret_settings
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlSettingsSource(settings_cls, LOCAL_YAML),
            YamlSettingsSource(settings_cls, DEFAULT_YAML),
        )

    @model_validator(mode="after")
    def _resolve_paths(self) -> Settings:
        self.data_dir = _resolve(self.data_dir)
        return self


class YamlSettingsSource(PydanticBaseSettingsSource):
    def __init__(self, settings_cls: type[BaseSettings], path: Path) -> None:
        super().__init__(settings_cls)
        self.path = path

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        del field
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        loaded = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{self.path} must contain a mapping")
        return loaded


def load_settings() -> Settings:
    return Settings()


def _resolve(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()
