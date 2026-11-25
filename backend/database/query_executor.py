"""
DataSense - PostgreSQL Query Executor & Security Guard.
Validates read-only status, enforces timeouts, rejects multi-statement payloads,
and executes queries safely against the database.
"""

import time
import logging
import sys
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Collection
import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import (
    DBAPIError,
    OperationalError,
    SQLAlchemyError,
    TimeoutError as SQLAlchemyTimeoutError,
)

from src.db import get_engine
from backend.config.settings import get_settings, Settings
from backend.security.sql_validator import (
    SQLValidationCode,
    SQLValidationResult,
    SQLValidator,
)

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    sql: str
    success: bool
    data: Optional[pd.DataFrame] = None
    row_count: int = 0
    column_names: List[str] = field(default_factory=list)
    execution_time_seconds: float = 0.0
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sql": self.sql,
            "success": self.success,
            "row_count": self.row_count,
            "column_names": self.column_names,
            "execution_time_seconds": self.execution_time_seconds,
            "error_message": self.error_message,
            "error_code": self.error_code,
            "rows": self.data.to_dict(orient="records") if self.data is not None else []
        }


class QueryExecutor:
    """Safely executes read-only SQL queries against PostgreSQL."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        engine=None,
        allowed_tables: Optional[Collection[str]] = None,
        schema_inspector=None,
    ):
        self.settings = settings or get_settings()
        self.engine = engine or get_engine()
        self.timeout_ms = self.settings.db.statement_timeout_ms
        self.max_rows = self.settings.db.max_result_rows
        if self.timeout_ms <= 0:
            raise ValueError("The SQL statement timeout must be greater than zero.")
        if self.max_rows <= 0:
            raise ValueError("The maximum SQL result row count must be greater than zero.")
        self.allowed_tables = allowed_tables
        if schema_inspector is None:
            from backend.services.schema_linking import SchemaInspector

            schema_inspector = SchemaInspector(engine=self.engine)
        self.schema_inspector = schema_inspector
        self.sql_validator = SQLValidator(
            default_limit=self.settings.db.default_sql_limit,
            max_limit=min(self.settings.db.max_sql_limit, self.max_rows),
        )

    def validate_query(self, sql: str) -> SQLValidationResult:
        """Validate SQL and return its safe, normalized representation."""
        if self.allowed_tables is not None:
            return self._log_validation_result(
                self.sql_validator.validate(
                    sql,
                    allowed_tables=set(self.allowed_tables).intersection(
                        self.settings.db.allowed_query_tables
                    ),
                )
            )

        probe = self.sql_validator.validate(sql, allowed_tables=())
        if probe.valid or not probe.referenced_tables:
            return self._log_validation_result(probe)
        if probe.error_code is not SQLValidationCode.FORBIDDEN_TABLE:
            return self._log_validation_result(probe)

        try:
            database_tables = self.schema_inspector.introspect().tables.keys()
        except SQLAlchemyError as error:
            logger.error("Could not load PostgreSQL schema for SQL validation: %s", type(error).__name__)
            return self.sql_validator._reject(
                SQLValidationCode.SCHEMA_LOOKUP_ERROR,
                "The database schema could not be checked, so the query was not executed.",
                statement_count=probe.statement_count,
                referenced_tables=probe.referenced_tables,
            )

        configured_tables = set(self.settings.db.allowed_query_tables)
        allowed_tables = configured_tables.intersection(database_tables)
        result = self.sql_validator.validate(sql, allowed_tables=allowed_tables)
        return self._log_validation_result(result)

    @staticmethod
    def _log_validation_result(result: SQLValidationResult) -> SQLValidationResult:
        if result.valid and result.sql is None:
            return SQLValidationResult(
                valid=False,
                sql=None,
                statement_count=result.statement_count,
                result_limit=None,
                limit_applied=False,
                error_code=SQLValidationCode.UNSAFE_QUERY_STRUCTURE,
                error_message="SQL validation did not produce an executable query.",
                referenced_tables=result.referenced_tables,
            )
        if not result.valid and result.error_code is not None:
            logger.warning("Rejected SQL query: code=%s", result.error_code.value)
        return result

    def validate_sql(self, sql: str) -> tuple[bool, Optional[str]]:
        """Compatibility wrapper for callers using the original tuple result."""
        result = self.validate_query(sql)
        return result.valid, result.error_message

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> QueryResult:
        """
        Executes a validated read-only SQL query inside a read-only transaction.
        Enforces execution timeouts and limits maximum returned rows.
        """
        start_time = time.perf_counter()

        # 1. Validation check
        validation = self.validate_query(sql)
        if not validation.valid or validation.sql is None:
            return QueryResult(
                sql=sql.strip() if isinstance(sql, str) else "",
                success=False,
                error_message=validation.error_message,
                error_code=validation.error_code.value if validation.error_code else None,
                execution_time_seconds=round(time.perf_counter() - start_time, 6)
            )
        validated_sql = validation.sql

        # 2. Execution with timeout and read-only transaction
        try:
            with self.engine.connect() as conn:
                try:
                    conn.begin()
                    conn.execute(text("SET TRANSACTION READ ONLY;"))
                    conn.execute(text(f"SET LOCAL statement_timeout = {self.timeout_ms};"))
                    conn.execute(text("SET LOCAL search_path = pg_catalog;"))

                    query_conn = conn.execution_options(stream_results=True)
                    cursor = query_conn.execute(text(validated_sql), params or {})
                    columns = list(cursor.keys())
                    raw_rows = cursor.fetchmany(self.max_rows)
                    df = pd.DataFrame(raw_rows, columns=columns)
                    duration = round(time.perf_counter() - start_time, 6)

                    return QueryResult(
                        sql=validated_sql,
                        success=True,
                        data=df,
                        row_count=len(df),
                        column_names=columns,
                        execution_time_seconds=duration
                    )
                finally:
                    self._rollback_active_transaction(conn)

        except SQLAlchemyError as error:
            duration = round(time.perf_counter() - start_time, 6)
            error_code, error_message, sqlstate = self._classify_database_error(error)
            logger.warning(
                "SQL execution failed: category=%s exception=%s sqlstate=%s",
                error_code,
                type(error).__name__,
                sqlstate,
            )
            return QueryResult(
                sql=validated_sql,
                success=False,
                error_message=error_message,
                error_code=error_code,
                execution_time_seconds=duration
            )

    @staticmethod
    def _rollback_active_transaction(conn) -> None:
        if not conn.in_transaction():
            return

        active_error = sys.exc_info()[1]
        try:
            conn.rollback()
        except SQLAlchemyError as rollback_error:
            try:
                conn.invalidate()
            except SQLAlchemyError as invalidate_error:
                logger.error(
                    "Could not invalidate a connection after rollback failure (%s)",
                    type(invalidate_error).__name__,
                )
            if active_error is None:
                raise
            logger.error(
                "SQL rollback failed; connection invalidated (original=%s, rollback=%s)",
                type(active_error).__name__,
                type(rollback_error).__name__,
            )

    @staticmethod
    def _classify_database_error(error: SQLAlchemyError) -> tuple[str, str, Optional[str]]:
        if isinstance(error, SQLAlchemyTimeoutError):
            return (
                "CONNECTION_POOL_TIMEOUT",
                "The database is busy. Please retry shortly.",
                None,
            )

        original = error.orig if isinstance(error, DBAPIError) else None
        sqlstate = (
            getattr(original, "pgcode", None)
            or getattr(original, "sqlstate", None)
        )
        primary_message = getattr(
            getattr(original, "diag", None),
            "message_primary",
            None,
        )
        if not isinstance(primary_message, str):
            primary_message = ""
        primary_message = primary_message.lower()

        if sqlstate == "57014":
            if "statement timeout" in primary_message:
                return "QUERY_TIMEOUT", "The query exceeded the execution time limit.", sqlstate
            return "QUERY_CANCELLED", "The query was cancelled before it completed.", sqlstate
        if sqlstate == "42601":
            return "SQL_SYNTAX_ERROR", "The database rejected the query syntax.", sqlstate
        if sqlstate == "42P01":
            return "TABLE_NOT_FOUND", "A requested table was not found.", sqlstate
        if sqlstate == "42703":
            return "COLUMN_NOT_FOUND", "A requested column was not found.", sqlstate
        if sqlstate == "42501":
            return "PERMISSION_DENIED", "The database role is not permitted to run this query.", sqlstate
        if (
            (sqlstate and sqlstate.startswith("08"))
            or getattr(error, "connection_invalidated", False)
            or (isinstance(error, OperationalError) and sqlstate is None)
        ):
            return "CONNECTION_ERROR", "The database connection failed. Please retry.", sqlstate
        if sqlstate and sqlstate.startswith("25"):
            return "TRANSACTION_ERROR", "The database transaction could not be completed.", sqlstate
        return "DATABASE_ERROR", "The database could not execute the query.", sqlstate


_query_executor_instance: Optional[QueryExecutor] = None


def get_query_executor() -> QueryExecutor:
    """Returns singleton QueryExecutor instance."""
    global _query_executor_instance
    if _query_executor_instance is None:
        _query_executor_instance = QueryExecutor()
    return _query_executor_instance
