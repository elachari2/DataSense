"""Unit and integration tests for NL2SQL service."""

from unittest.mock import MagicMock
import pytest
from backend.services.nl2sql_service import NL2SQLService, get_nl2sql_service
from backend.services.llm_service import LLMResponse


def test_nl2sql_clean_json_response():
    svc = get_nl2sql_service()
    
    # Test markdown fence stripping
    raw_markdown = '```json\n{"status": "success", "sql": "SELECT 1"}\n```'
    cleaned = svc._clean_json_response(raw_markdown)
    assert cleaned == '{"status": "success", "sql": "SELECT 1"}'


def test_nl2sql_empty_question():
    svc = get_nl2sql_service()
    res = svc.process_question("   ")
    assert res.status == "unsupported"
    assert res.sql is None


def test_nl2sql_mock_pipeline():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = LLMResponse(
        text='{"status": "success", "sql": "SELECT COUNT(*) FROM orders", "explanation": "Counts orders"}',
        model="gemini-mock",
        success=True,
        duration_seconds=0.1
    )
    
    svc = NL2SQLService(llm_service=mock_llm)
    res = svc.process_question("How many orders?", execute=True)
    
    assert res.status == "success"
    assert res.sql == "SELECT COUNT(*) FROM orders"
    assert res.is_valid_sql is True
    assert res.execution_result is not None
    assert res.execution_result.success is True
