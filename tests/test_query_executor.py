"""Tests for SQL query validation, security, and execution."""

import pytest
import pandas as pd
from backend.database.query_executor import QueryExecutor, get_query_executor


@pytest.fixture
def executor():
    return get_query_executor()


def test_validate_valid_select(executor):
    is_valid, err = executor.validate_sql("SELECT COUNT(*) FROM orders;")
    assert is_valid is True
    assert err is None


def test_validate_valid_with_cte(executor):
    sql = "WITH delivered AS (SELECT * FROM orders WHERE order_status = 'delivered') SELECT COUNT(*) FROM delivered;"
    is_valid, err = executor.validate_sql(sql)
    assert is_valid is True
    assert err is None


def test_validate_reject_empty(executor):
    is_valid, err = executor.validate_sql("   ")
    assert is_valid is False
    assert "empty" in err.lower()


def test_validate_reject_multi_statement(executor):
    sql = "SELECT 1; SELECT 2;"
    is_valid, err = executor.validate_sql(sql)
    assert is_valid is False
    assert "multiple" in err.lower()


@pytest.mark.parametrize("bad_keyword", ["DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER"])
def test_validate_reject_mutation_keywords(executor, bad_keyword):
    sql = f"{bad_keyword} TABLE orders;"
    is_valid, err = executor.validate_sql(sql)
    assert is_valid is False
    assert "forbidden" in err.lower() or "only select" in err.lower()


def test_execute_valid_query(executor):
    result = executor.execute("SELECT 1 AS num, 'test' AS label;")
    assert result.success is True
    assert result.row_count == 1
    assert result.data is not None
    assert result.data.iloc[0]["num"] == 1
    assert result.data.iloc[0]["label"] == "test"
    assert result.execution_time_seconds > 0.0


def test_execute_syntax_error(executor):
    result = executor.execute("SELECT FROM WHERE;")
    assert result.success is False
    assert "error" in result.error_message.lower()
