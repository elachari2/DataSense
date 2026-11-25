"""Tests for SQL query validation, security, and execution."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest
from sqlalchemy.exc import (
    OperationalError,
    SQLAlchemyError,
    TimeoutError as SQLAlchemyTimeoutError,
)

from backend.database.query_executor import QueryExecutor
from backend.config.settings import DatabaseSettings, Settings


def _mock_executor(statement_timeout_ms=1234):
    connection = MagicMock()
    connection.in_transaction.return_value = True
    connection.execution_options.return_value = connection

    cursor = MagicMock()
    cursor.keys.return_value = ["num"]
    cursor.fetchmany.return_value = [(1,)]
    connection.execute.return_value = cursor

    connection_context = MagicMock()
    connection_context.__enter__.return_value = connection
    engine = MagicMock()
    engine.connect.return_value = connection_context

    settings = Settings(
        db=DatabaseSettings(
            statement_timeout_ms=statement_timeout_ms,
            allowed_query_tables=(
                "customers", "orders", "order_items", "order_payments", "order_reviews"
            ),
        )
    )
    executor = QueryExecutor(
        settings=settings,
        engine=engine,
        allowed_tables=settings.db.allowed_query_tables,
    )
    return executor, engine, connection, connection_context


def _postgres_error(sqlstate, primary_message):
    original = Exception("private driver detail")
    original.pgcode = sqlstate
    original.diag = SimpleNamespace(message_primary=primary_message)
    return OperationalError("SELECT 1", {}, original)


@pytest.fixture
def executor():
    executor, _, _, _ = _mock_executor()
    return executor


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
    connection = executor.engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.keys.return_value = ["num", "label"]
    connection.execute.return_value.fetchmany.return_value = [(1, "test")]
    result = executor.execute("SELECT 1 AS num, 'test' AS label;")
    assert result.success is True
    assert result.row_count == 1
    assert result.data is not None
    assert result.data.iloc[0]["num"] == 1
    assert result.data.iloc[0]["label"] == "test"
    assert result.execution_time_seconds > 0.0


def test_execute_preserves_named_parameters(executor):
    connection = executor.engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.fetchmany.return_value = [(7,)]
    result = executor.execute("SELECT :value AS num", {"value": 7})

    assert result.success is True
    assert result.data.iloc[0]["num"] == 7
    assert connection.execute.call_args_list[-1].args[1] == {"value": 7}


def test_execute_syntax_error(executor):
    result = executor.execute("SELECT FROM WHERE;")
    assert result.success is False
    assert "error" in result.error_message.lower()


def test_rejected_query_is_not_sent_to_database():
    from unittest.mock import MagicMock

    engine = MagicMock()
    executor = QueryExecutor(engine=engine, allowed_tables={"orders"})
    result = executor.execute("SELECT 1; DELETE FROM orders")

    assert result.success is False
    assert result.error_code == "MULTIPLE_STATEMENTS"
    engine.connect.assert_not_called()


def test_table_query_is_rejected_if_schema_introspection_fails():
    from unittest.mock import MagicMock

    engine = MagicMock()
    schema_inspector = MagicMock()
    schema_inspector.introspect.side_effect = SQLAlchemyError("private connection detail")
    executor = QueryExecutor(engine=engine, schema_inspector=schema_inspector)
    result = executor.execute("SELECT * FROM orders")

    assert result.success is False
    assert result.error_code == "SCHEMA_LOOKUP_ERROR"
    assert "private connection detail" not in result.error_message
    engine.connect.assert_not_called()


def test_nested_cte_catalog_table_bypass_never_reaches_database():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from backend.config.settings import DatabaseSettings, Settings

    engine = MagicMock()
    schema_inspector = MagicMock()
    schema_inspector.introspect.return_value = SimpleNamespace(
        tables={table: object() for table in (
            "customers", "orders", "order_items", "order_payments", "order_reviews"
        )}
    )
    settings = Settings(
        db=DatabaseSettings(
            allowed_query_tables=(
                "customers", "orders", "order_items", "order_payments", "order_reviews"
            )
        )
    )
    executor = QueryExecutor(
        settings=settings,
        engine=engine,
        schema_inspector=schema_inspector,
    )
    sql = (
        "SELECT rolname, rolpassword FROM pg_authid "
        "WHERE EXISTS (WITH pg_authid AS (SELECT 1) SELECT 1)"
    )

    result = executor.execute(sql)

    assert result.success is False
    assert result.error_code == "FORBIDDEN_TABLE"
    engine.connect.assert_not_called()


def test_public_table_outside_configured_allowlist_is_rejected():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from backend.config.settings import DatabaseSettings, Settings

    engine = MagicMock()
    schema_inspector = MagicMock()
    schema_inspector.introspect.return_value = SimpleNamespace(
        tables={"orders": object(), "internal_secrets": object()}
    )
    settings = Settings(
        db=DatabaseSettings(allowed_query_tables=("orders",))
    )
    executor = QueryExecutor(
        settings=settings,
        engine=engine,
        schema_inspector=schema_inspector,
    )

    result = executor.execute("SELECT * FROM internal_secrets")

    assert result.success is False
    assert result.error_code == "FORBIDDEN_TABLE"
    engine.connect.assert_not_called()


def test_injected_table_set_cannot_expand_configured_allowlist():
    from unittest.mock import MagicMock

    from backend.config.settings import DatabaseSettings, Settings

    engine = MagicMock()
    settings = Settings(
        db=DatabaseSettings(allowed_query_tables=("orders",))
    )
    executor = QueryExecutor(
        settings=settings,
        engine=engine,
        allowed_tables={"internal_secrets"},
    )

    result = executor.execute("SELECT * FROM internal_secrets")

    assert result.success is False
    assert result.error_code == "FORBIDDEN_TABLE"
    engine.connect.assert_not_called()


def test_execution_uses_read_only_transaction_local_timeout_and_streaming():
    executor, engine, connection, connection_context = _mock_executor()

    result = executor.execute("SELECT 1 AS num;")

    assert result.success is True
    assert connection.begin.call_count == 1
    statements = [call.args[0].text for call in connection.execute.call_args_list]
    assert statements == [
        "SET TRANSACTION READ ONLY;",
        "SET LOCAL statement_timeout = 1234;",
        "SET LOCAL search_path = pg_catalog;",
        result.sql,
    ]
    assert result.sql == "SELECT 1 AS num LIMIT 100"
    connection.execution_options.assert_called_once_with(stream_results=True)
    connection.execute.return_value.fetchmany.assert_called_once_with(500)
    connection.rollback.assert_called_once()
    connection_context.__exit__.assert_called_once()
    engine.connect.assert_called_once()


def test_each_execution_rolls_back_local_state_and_releases_connection():
    executor, engine, connection, connection_context = _mock_executor()

    first = executor.execute("SELECT 1")
    second = executor.execute("SELECT 2")

    assert first.success and second.success
    assert connection.begin.call_count == 2
    assert connection.rollback.call_count == 2
    assert connection_context.__exit__.call_count == 2
    statements = [call.args[0].text for call in connection.execute.call_args_list]
    assert statements.count("SET TRANSACTION READ ONLY;") == 2
    assert statements.count("SET LOCAL statement_timeout = 1234;") == 2
    assert statements.count("SET LOCAL search_path = pg_catalog;") == 2
    assert engine.connect.call_count == 2


def test_get_engine_reuses_one_pool_without_connecting_to_a_database(monkeypatch):
    import src.db as db_module

    for key, value in {
        "DB_USER": "test-user",
        "DB_PASSWORD": "test-password",
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "DB_NAME": "test-database",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(db_module, "_engine", None)
    engine = MagicMock()
    create_engine = MagicMock(return_value=engine)
    monkeypatch.setattr(db_module, "create_engine", create_engine)

    first = db_module.get_engine()
    second = db_module.get_engine()

    assert first is second is engine
    create_engine.assert_called_once()
    assert create_engine.call_args.kwargs == {"pool_pre_ping": True}


@pytest.mark.parametrize(
    ("sqlstate", "primary_message", "expected_code"),
    [
        ("42601", "syntax error", "SQL_SYNTAX_ERROR"),
        ("42P01", "relation does not exist", "TABLE_NOT_FOUND"),
        ("42703", "column does not exist", "COLUMN_NOT_FOUND"),
        ("42501", "permission denied", "PERMISSION_DENIED"),
        ("57014", "canceling statement due to statement timeout", "QUERY_TIMEOUT"),
        ("57014", "canceling statement due to user request", "QUERY_CANCELLED"),
        ("08006", "connection failure", "CONNECTION_ERROR"),
        ("25006", "read only transaction", "TRANSACTION_ERROR"),
    ],
)
def test_execution_errors_are_classified_and_rolled_back(
    sqlstate, primary_message, expected_code
):
    executor, _, connection, connection_context = _mock_executor()
    error = _postgres_error(sqlstate, primary_message)
    connection.execute.side_effect = [None, None, None, error]

    result = executor.execute("SELECT 1")

    assert result.success is False
    assert result.data is None
    assert result.error_code == expected_code
    assert "private driver detail" not in result.error_message
    connection.rollback.assert_called_once()
    connection_context.__exit__.assert_called_once()


def test_failed_rollback_invalidates_connection_without_masking_query_timeout():
    executor, _, connection, _ = _mock_executor()
    connection.execute.side_effect = [
        None,
        None,
        None,
        _postgres_error("57014", "canceling statement due to statement timeout"),
    ]
    connection.rollback.side_effect = SQLAlchemyError("private rollback detail")

    result = executor.execute("SELECT 1")

    assert result.success is False
    assert result.error_code == "QUERY_TIMEOUT"
    connection.invalidate.assert_called_once()


def test_streaming_fetch_failure_returns_no_partial_results_and_rolls_back():
    executor, _, connection, connection_context = _mock_executor()
    connection.execute.return_value.fetchmany.side_effect = _postgres_error(
        "57014", "canceling statement due to statement timeout"
    )

    result = executor.execute("SELECT 1")

    assert result.success is False
    assert result.data is None
    assert result.error_code == "QUERY_TIMEOUT"
    connection.rollback.assert_called_once()
    connection_context.__exit__.assert_called_once()


def test_read_only_setup_failure_does_not_execute_user_sql():
    executor, _, connection, connection_context = _mock_executor()
    connection.execute.side_effect = [
        _postgres_error("25006", "read only transaction"),
    ]

    result = executor.execute("SELECT 1")

    assert result.success is False
    assert result.error_code == "TRANSACTION_ERROR"
    assert connection.execute.call_count == 1
    connection.rollback.assert_called_once()
    connection_context.__exit__.assert_called_once()


def test_connection_pool_timeout_is_returned_as_a_controlled_error():
    executor, engine, _, _ = _mock_executor()
    engine.connect.side_effect = SQLAlchemyTimeoutError("private pool detail")

    result = executor.execute("SELECT 1")

    assert result.success is False
    assert result.error_code == "CONNECTION_POOL_TIMEOUT"
    assert "private pool detail" not in result.error_message


def test_postgresql_read_only_transaction_and_statement_timeout():
    import os

    from sqlalchemy import create_engine

    database_url = os.environ.get("DATASENSE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set DATASENSE_TEST_DATABASE_URL to run the PostgreSQL integration test.")

    engine = create_engine(database_url, pool_pre_ping=True)
    settings = Settings(
        db=DatabaseSettings(
            statement_timeout_ms=1000,
            allowed_query_tables=(),
        )
    )
    executor = QueryExecutor(settings=settings, engine=engine, allowed_tables=())
    queries = {
        "read-only probe": "SELECT current_setting('transaction_read_only')",
        "timeout probe": "SELECT pg_sleep(1.5)",
    }

    # Isolate PostgreSQL transaction behavior from SQLGlot's deliberate pg_sleep ban.
    executor.validate_query = lambda sql: SimpleNamespace(
        valid=True,
        sql=queries[sql],
        error_code=None,
    )
    try:
        read_only_result = executor.execute("read-only probe")
        timeout_result = executor.execute("timeout probe")
    finally:
        engine.dispose()

    assert read_only_result.success is True
    assert read_only_result.data.iloc[0, 0] == "on"
    assert timeout_result.success is False
    assert timeout_result.error_code == "QUERY_TIMEOUT"


def test_nonpositive_statement_timeout_is_rejected():
    engine = MagicMock()
    settings = Settings(
        db=DatabaseSettings(statement_timeout_ms=0)
    )

    with pytest.raises(ValueError, match="timeout"):
        QueryExecutor(settings=settings, engine=engine)
