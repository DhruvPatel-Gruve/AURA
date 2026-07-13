import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT_ADMIN_PASSWORD = "changeme123"

# ENV_FILE lets a second, fully independent AURA instance (its own SQLite DB,
# Qdrant collections, JWT secret, ITSM provider) run from the same codebase
# by pointing at a different dotenv file — e.g. `ENV_FILE=.env.zendesk
# uvicorn app.main:app --port 8001` — without touching the primary `.env`.
_AURA_ROOT = Path(__file__).resolve().parents[2]
_env_file_override = os.environ.get("ENV_FILE")
_ENV_FILE = (
    str(_AURA_ROOT / _env_file_override)
    if _env_file_override and not Path(_env_file_override).is_absolute()
    else _env_file_override or str(_AURA_ROOT / ".env")
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    app_env: str = Field("development", pattern="^(development|production)$")
    app_secret_key: str = Field(..., min_length=32)

    # ── ITSM provider ─────────────────────────────────────────────────────────
    # Every tenant's provider choice AND credentials are entirely DB-backed
    # (platform_config, encrypted at rest — see app/core/crypto.py) and set
    # via that tenant's own Setup Wizard, not read from process env vars.
    # There is deliberately no ITSM_PROVIDER/JSM_*/ZEN_* Settings field here —
    # a fresh boot needs zero ITSM configuration; only individual tenants do,
    # later, through their own wizard.
    #
    # Jira issue *type* (Task/Bug/Story/...) used when end users submit
    # tickets — distinct from AURA's own "category" concept (Network,
    # Hardware, etc, assigned later by triage_node), which is not a valid
    # Jira issuetype name and must never be sent as one. Global for now since
    # it's a low-stakes operational default, not a credential.
    jsm_default_issue_type: str = Field("Task", min_length=1)

    # ── Gemini ────────────────────────────────────────────────────────────────
    gemini_api_key: str = Field(...)
    gemini_embedding_model: str = "models/gemini-embedding-2"
    gemini_embedding_batch_size: int = Field(100, ge=1, le=100)

    # ── Qdrant ────────────────────────────────────────────────────────────────
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_vector_size: int = 768

    # ── SQLite ────────────────────────────────────────────────────────────────
    sqlite_db_path: str = "./aura.db"

    # ── Logging ───────────────────────────────────────────────────────────────
    log_dir: str = "./logs"
    log_max_bytes: int = Field(5_000_000, ge=100_000)
    log_backup_count: int = Field(5, ge=1, le=50)

    # ── Scheduler ─────────────────────────────────────────────────────────────
    ingestion_sync_interval_hours: int = Field(6, ge=1, le=168)
    ingestion_lookback_days: int = Field(90, ge=1, le=365)
    polling_interval_minutes: int = Field(5, ge=1, le=60)
    collision_timeout_minutes: int = Field(30, ge=1)

    # ── Agent defaults (seed values written to platform_config on first run) ──
    confidence_threshold: float = Field(0.90, ge=0.0, le=1.0)
    abstention_threshold: float = Field(0.60, ge=0.0, le=1.0)

    # ── CORS / Cookie ─────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    # ── Default Admin (seeded on first DB initialisation) ─────────────────────
    default_admin_email: str = "admin@aura.local"
    default_admin_password: str = Field(_INSECURE_DEFAULT_ADMIN_PASSWORD, min_length=8)

    # ── JWT ───────────────────────────────────────────────────────────────────
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = Field(30, ge=5)
    jwt_refresh_token_expire_days: int = Field(7, ge=1)

    # ── LLM (Phase 1) ─────────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3:8b"
    ollama_timeout_seconds: float = Field(45.0, ge=1.0)

    # ── Upload limits ─────────────────────────────────────────────────────────
    max_upload_size_mb: int = Field(20, ge=1, le=200)

    # ── Rate limiting ─────────────────────────────────────────────────────────
    rate_limit_login: str = "10/minute"
    rate_limit_refresh: str = "30/minute"
    rate_limit_chat: str = "20/minute"
    rate_limit_ticket_submit: str = "20/minute"
    rate_limit_upload: str = "10/minute"
    rate_limit_frontend_logs: str = "60/minute"

    # ── Derived helpers ───────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _guard_production_footguns(self) -> "Settings":
        """Fail closed at startup rather than silently running an insecure
        production deployment. These are deliberately fatal — a misconfigured
        prod environment should refuse to boot, not limp along vulnerable."""
        if not self.is_production:
            return self

        if self.default_admin_password == _INSECURE_DEFAULT_ADMIN_PASSWORD:
            raise ValueError(
                "APP_ENV=production but DEFAULT_ADMIN_PASSWORD is still the "
                "insecure built-in default. Set a strong DEFAULT_ADMIN_PASSWORD "
                "in the environment before starting in production."
            )
        if "*" in self.cors_origins_list:
            raise ValueError(
                "APP_ENV=production but CORS_ORIGINS includes '*' while "
                "credentials are allowed — this permits any origin to make "
                "authenticated cross-site requests. Set an explicit allowlist."
            )
        if not self.cookie_secure:
            raise ValueError(
                "APP_ENV=production but COOKIE_SECURE is not enabled — the "
                "refresh-token cookie would be sent over plaintext HTTP."
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlite_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.sqlite_db_path}"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
