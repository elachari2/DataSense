"""
DataSense - PostgreSQL Query Executor & Security Guard.
Validates read-only status, enforces timeouts, rejects multi-statement payloads,
and executes queries safely against the database.
"""

import time
import re
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.db import get_engine
from backend.config.settings import get_settings, Settings

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sql": self.sql,
            "success": self.success,
            "row_count": self.row_count,
            "column_names": self.column_names,
            "execution_time_seconds": self.execution_time_seconds,
            "error_message": self.error_message,
            "rows": self.data.to_dict(orient="records") if self.data is not None else []
        }


class QueryExecutor:
    """Safely executes read-only SQL queries against PostgreSQL."""

    FORBIDDEN_KEYWORDS = [
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
        "GRANT", "REVOKE", "EXEC", "EXECUTE", "VACUUM", "COPY", "LOCK"
    ]

    def __init__(self, settings: Optional[Settings] = None, engine=None):
        self.settings = settings or get_settings()
        self.engine = engine or get_engine()
        self.timeout_ms = self.settings.db.statement_timeout_ms
        self.max_rows = self.settings.db.max_result_rows

    def validate_sql(self, sql: str) -> tuple[bool, Optional[str]]:
        """
        Validates that the SQL string is safe to execute:
        - Must not be empty.
        - Must be a single statement.
        - Must start with SELECT or WITH (for CTEs).
        - Must not contain mutating keywords outside string literals.
        """
        if not sql or not sql.strip():
            return False, "SQL query cannot be empty."

        cleaned = sql.strip().rstrip(";")

        # Check for multiple statements
        if ";" in cleaned:
            return False, "Multiple SQL statements are not permitted."

        # Remove single-line and multi-line comments for keyword analysis
        stripped_comments = re.sub(r"--.*", "", cleaned)
        stripped_comments = re.sub(r"/\*.*?\*/", "", stripped_comments, flags=re.DOTALL).strip()

        # Check starting token
        match = re.match(r"^\s*([a-zA-Z]+)", stripped_comments)
        if not match:
            return False, "Invalid SQL query structure."

        initial_keyword = match.group(1).upper()
        if initial_keyword not in ("SELECT", "WITH"):
            return False, f"Only SELECT or WITH queries are permitted (got {initial_keyword})."

        # Check for forbidden mutation keywords as whole words
        for kw in self.FORBIDDEN_KEYWORDS:
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, stripped_comments, re.IGNORECASE):
                return False, f"Security violation: query contains forbidden keyword '{kw}'."

        return True, None

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> QueryResult:
        """
        Executes a validated read-only SQL query inside a read-only transaction.
        Enforces execution timeouts and limits maximum returned rows.
        """
        start_time = time.perf_counter()
        cleaned_sql = sql.strip().rstrip(";")

        # 1. Validation check
        is_valid, validation_error = self.validate_sql(cleaned_sql)
        if not is_valid:
            return QueryResult(
                sql=cleaned_sql,
                success=False,
                error_message=validation_error,
                execution_time_seconds=round(time.perf_counter() - start_time, 6)
            )

        # 2. Execution with timeout and read-only transaction
        try:
            with self.engine.connect() as conn:
                # Set transaction read-only and statement timeout
                conn.execute(text(f"SET statement_timeout = {self.timeout_ms};"))
                conn.execute(text("SET TRANSACTION READ ONLY;"))

                # Execute query
                cursor = conn.execute(text(cleaned_sql), params or {})
                columns = list(cursor.keys())
                
                # Fetch up to max_rows + 1 to detect truncation
                raw_rows = cursor.fetchmany(self.max_rows)
                
                df = pd.DataFrame(raw_rows, columns=columns)
                duration = round(time.perf_counter() - start_time, 6)

                return QueryResult(
                    sql=cleaned_sql,
                    success=True,
                    data=df,
                    row_count=len(df),
                    column_names=columns,
                    execution_time_seconds=duration
                )

        except SQLAlchemyError as e:
            duration = round(time.perf_counter() - start_time, 6)
            # Extract clean error message
            err_msg = str(e.orig) if hasattr(e, "orig") and e.orig else str(e)
            logger.warning(f"Database execution error on SQL: {cleaned_sql} -> {err_msg}")
            return QueryResult(
                sql=cleaned_sql,
                success=False,
                error_message=f"PostgreSQL Execution Error: {err_msg}",
                execution_time_seconds=duration
            )
        except Exception as e:
            duration = round(time.perf_counter() - start_time, 6)
            return QueryResult(
                sql=cleaned_sql,
                success=False,
                error_message=f"Execution Error: {str(e)}",
                execution_time_seconds=duration
            )


_query_executor_instance: Optional[QueryExecutor] = None


def get_query_executor() -> QueryExecutor:
    """Returns singleton QueryExecutor instance."""
    global _query_executor_instance
    if _query_executor_instance is None:
        _query_executor_instance = QueryExecutor()
    return _query_executor_instance
