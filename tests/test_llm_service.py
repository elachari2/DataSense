"""Unit tests for GeminiLLMService with mocks and client tests."""

from unittest.mock import MagicMock, patch
import pytest
from backend.services.llm_service import GeminiLLMService, LLMResponse


def test_llm_service_initialization():
    service = GeminiLLMService()
    assert service.model is not None
    assert service.temperature == 0.0


def test_llm_service_missing_api_key():
    with patch("backend.services.llm_service.get_settings") as mock_settings:
        mock_settings.return_value.llm.api_key = None
        mock_settings.return_value.llm.model = "gemini-3.1-flash-lite"
        service = GeminiLLMService()
        service.api_key = None
        res = service.generate("Hello")
        assert res.success is False
        assert "not configured" in res.error.lower()


def test_llm_service_successful_mock_generate():
    service = GeminiLLMService()
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"status": "success", "sql": "SELECT 1"}'
    mock_client.models.generate_content.return_value = mock_response
    service._client = mock_client

    res = service.generate("Generate query")
    assert res.success is True
    assert "SELECT 1" in res.text
