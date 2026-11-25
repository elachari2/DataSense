"""
DataSense - Centralized Application Settings & Environment Configuration.
Manages database, LLM provider (Google Gemini), execution parameters, and timeouts.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")


def parse_model_candidates(value: str) -> tuple[str, ...]:
    """Parse an ordered, comma-separated model list without duplicates."""
    return tuple(
        dict.fromkeys(model.strip() for model in value.split(",") if model.strip())
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


@dataclass(frozen=True)
class DatabaseSettings:
    host: str = os.getenv("DB_HOST", "localhost")
    port: int = int(os.getenv("DB_PORT", "5544"))
    name: str = os.getenv("DB_NAME", "datasense")
    user: str = os.getenv("DB_USER", "postgres")
    password: str = os.getenv("DB_PASSWORD", "postgres")
    statement_timeout_ms: int = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "10000"))
    max_result_rows: int = int(os.getenv("DB_MAX_RESULT_ROWS", "500"))
    default_sql_limit: int = int(os.getenv("DB_DEFAULT_SQL_LIMIT", "100"))
    max_sql_limit: int = int(os.getenv("DB_MAX_SQL_LIMIT", os.getenv("DB_MAX_RESULT_ROWS", "500")))
    allowed_query_tables: tuple[str, ...] = tuple(
        table.strip()
        for table in os.getenv(
            "DB_ALLOWED_QUERY_TABLES",
            "customers,orders,order_items,order_payments,order_reviews",
        ).split(",")
        if table.strip()
    )

    @property
    def url(self) -> str:
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


@dataclass(frozen=True)
class LLMSettings:
    provider: str = os.getenv("LLM_PROVIDER", "gemini")
    api_key: Optional[str] = os.getenv("LLM_API_KEY")
    model: str = (
        os.getenv("GEMINI_PRIMARY_MODEL")
        or os.getenv("LLM_MODEL")
        or "gemini-3.1-flash-lite"
    )
    fallback_models: tuple[str, ...] = parse_model_candidates(
        os.getenv(
            "GEMINI_FALLBACK_MODELS",
            "gemini-3.5-flash-lite,gemini-3.6-flash",
        )
    )
    fallback_enabled: bool = _env_bool("GEMINI_FALLBACK_ENABLED", True)
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.0"))
    max_output_tokens: int = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "1024"))
    request_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
    max_retries_per_model: int = int(
        os.getenv("GEMINI_MAX_RETRIES_PER_MODEL", os.getenv("LLM_MAX_RETRIES", "1"))
    )
    model_cooldown_seconds: int = int(
        os.getenv("GEMINI_MODEL_COOLDOWN_SECONDS", "60")
    )
    daily_quota_cooldown_seconds: int = int(
        os.getenv("GEMINI_DAILY_QUOTA_COOLDOWN_SECONDS", "86400")
    )
    max_retry_delay_seconds: float = float(
        os.getenv("GEMINI_MAX_RETRY_DELAY_SECONDS", "2")
    )

    def __post_init__(self) -> None:
        if not 0 <= self.max_retries_per_model <= 3:
            raise ValueError("GEMINI_MAX_RETRIES_PER_MODEL must be between 0 and 3.")
        if self.model_cooldown_seconds < 1:
            raise ValueError("GEMINI_MODEL_COOLDOWN_SECONDS must be at least 1.")
        if self.daily_quota_cooldown_seconds < 1:
            raise ValueError(
                "GEMINI_DAILY_QUOTA_COOLDOWN_SECONDS must be at least 1."
            )
        if not 0 <= self.max_retry_delay_seconds <= 30:
            raise ValueError(
                "GEMINI_MAX_RETRY_DELAY_SECONDS must be between 0 and 30."
            )


@dataclass(frozen=True)
class Settings:
    base_dir: Path = BASE_DIR
    db: DatabaseSettings = DatabaseSettings()
    llm: LLMSettings = LLMSettings()


_settings_instance: Optional[Settings] = None


def get_settings() -> Settings:
    """Returns the singleton Settings instance."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance
