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


@dataclass(frozen=True)
class DatabaseSettings:
    host: str = os.getenv("DB_HOST", "localhost")
    port: int = int(os.getenv("DB_PORT", "5544"))
    name: str = os.getenv("DB_NAME", "datasense")
    user: str = os.getenv("DB_USER", "postgres")
    password: str = os.getenv("DB_PASSWORD", "postgres")
    statement_timeout_ms: int = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "10000"))
    max_result_rows: int = int(os.getenv("DB_MAX_RESULT_ROWS", "500"))

    @property
    def url(self) -> str:
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


@dataclass(frozen=True)
class LLMSettings:
    provider: str = os.getenv("LLM_PROVIDER", "gemini")
    api_key: Optional[str] = os.getenv("LLM_API_KEY")
    model: str = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.0"))
    max_output_tokens: int = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "1024"))
    request_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
    max_retries: int = int(os.getenv("LLM_MAX_RETRIES", "3"))


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
