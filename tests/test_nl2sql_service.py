"""Unit and integration tests for NL2SQL service."""

from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from backend.services.nl2sql_service import NL2SQLService
from backend.services.llm_service import LLMResponse
from backend.security.sql_validator import SQLValidator


def _mock_schema_linker():
    linker = MagicMock()
    linker.link.return_value = SimpleNamespace(
        relevant_relationships=[],
        detected_operations=["COUNT"],
        context_schema_ddl="TABLE orders:\n  - order_id: integer [PK]",
    )
    return linker


def test_nl2sql_clean_json_response():
    svc = NL2SQLService(
        llm_service=MagicMock(),
        schema_linker=_mock_schema_linker(),
        query_executor=MagicMock(),
    )
    
    # Test markdown fence stripping
    raw_markdown = '```json\n{"status": "success", "sql": "SELECT 1"}\n```'
    cleaned = svc._clean_json_response(raw_markdown)
    assert cleaned == '{"status": "success", "sql": "SELECT 1"}'


def test_nl2sql_empty_question():
    svc = NL2SQLService(
        llm_service=MagicMock(),
        schema_linker=_mock_schema_linker(),
        query_executor=MagicMock(),
    )
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
    
    mock_executor = MagicMock()
    mock_executor.validate_query.return_value = SQLValidator().validate(
        "SELECT COUNT(*) FROM orders",
        allowed_tables={"orders"},
    )
    mock_executor.execute.return_value = SimpleNamespace(
        success=True,
        error_message=None,
        error_code=None,
    )
    svc = NL2SQLService(
        llm_service=mock_llm,
        schema_linker=_mock_schema_linker(),
        query_executor=mock_executor,
    )
    res = svc.process_question("How many orders?", execute=True)
    
    assert res.status == "success"
    assert res.sql == "SELECT COUNT(*) FROM public.orders LIMIT 100"
    assert res.is_valid_sql is True
    assert res.execution_result is not None
    assert res.execution_result.success is True


def test_nl2sql_rejected_sql_is_not_executed():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = LLMResponse(
        text='{"status": "success", "sql": "SELECT 1; DELETE FROM orders"}',
        model="gemini-mock",
        success=True,
        duration_seconds=0.1
    )
    mock_executor = MagicMock()
    mock_executor.validate_query.return_value = SQLValidator().validate(
        "SELECT 1; DELETE FROM orders"
    )

    svc = NL2SQLService(
        llm_service=mock_llm,
        schema_linker=_mock_schema_linker(),
        query_executor=mock_executor,
    )
    res = svc.process_question("How many orders?", execute=True)

    assert res.status == "security_rejected"
    assert res.error_code == "MULTIPLE_STATEMENTS"
    mock_executor.execute.assert_not_called()
