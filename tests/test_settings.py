"""Tests for centralized configuration and settings."""

import os
from backend.config.settings import Settings, get_settings, DatabaseSettings, LLMSettings


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
