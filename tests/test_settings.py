"""Tests for centralized configuration and settings."""

import os
from backend.config.settings import (
    get_settings,
    DatabaseSettings,
    LLMSettings,
    _env_bool,
    parse_model_candidates,
)


def test_settings_singleton():
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_database_settings():
    db = DatabaseSettings()
    assert db.port == int(os.getenv("DB_PORT", "5544"))
    assert db.name == os.getenv("DB_NAME", "datasense")
    assert "postgresql+psycopg2://" in db.url


def test_llm_settings():
    llm = LLMSettings()
    assert llm.provider == "gemini"
    assert llm.model is not None
    assert llm.temperature == 0.0


def test_fallback_model_configuration_preserves_order_and_removes_duplicates():
    assert parse_model_candidates(
        " gemini-a,gemini-b,gemini-a, ,gemini-c "
    ) == ("gemini-a", "gemini-b", "gemini-c")


def test_fallback_model_configuration_can_be_empty():
    assert parse_model_candidates("") == ()


def test_fallback_enabled_configuration_is_parsed(monkeypatch):
    monkeypatch.setenv("GEMINI_FALLBACK_ENABLED", "false")
    assert _env_bool("GEMINI_FALLBACK_ENABLED", True) is False
