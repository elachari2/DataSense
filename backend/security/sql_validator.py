"""AST-based validation for read-only PostgreSQL queries."""

from dataclasses import dataclass
from enum import Enum
from typing import Collection, Optional, Tuple

import sqlglot
from sqlglot import exp
from sqlglot.dialects.postgres import Postgres
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import Scope, traverse_scope


class SQLValidationCode(str, Enum):
    EMPTY_QUERY = "EMPTY_QUERY"
    INVALID_INPUT = "INVALID_INPUT"
    SQL_PARSE_ERROR = "SQL_PARSE_ERROR"
    MULTIPLE_STATEMENTS = "MULTIPLE_STATEMENTS"
    NON_SELECT_QUERY = "NON_SELECT_QUERY"
    FORBIDDEN_OPERATION = "FORBIDDEN_OPERATION"
    FORBIDDEN_FUNCTION = "FORBIDDEN_FUNCTION"
    FORBIDDEN_TABLE = "FORBIDDEN_TABLE"
    LIMIT_INVALID = "LIMIT_INVALID"
    QUERY_LIMIT_EXCEEDED = "QUERY_LIMIT_EXCEEDED"
    UNSAFE_QUERY_STRUCTURE = "UNSAFE_QUERY_STRUCTURE"
    SCHEMA_LOOKUP_ERROR = "SCHEMA_LOOKUP_ERROR"


@dataclass(frozen=True)
class SQLValidationResult:
    valid: bool
    sql: Optional[str]
    statement_count: int
    result_limit: Optional[int]
    limit_applied: bool
    error_code: Optional[SQLValidationCode] = None
    error_message: Optional[str] = None
    referenced_tables: Tuple[str, ...] = ()


class _SQLAlchemyPostgresGenerator(Postgres.Generator):
    """Render named PostgreSQL binds in the format expected by SQLAlchemy text()."""

    def placeholder_sql(self, expression: exp.Placeholder) -> str:
        if expression.args.get("jdbc"):
            return "?"
        return f":{expression.name}" if expression.this else "?"


class SQLValidator:
    """Parses PostgreSQL SQL and permits only bounded, read-only SELECT queries."""

    FORBIDDEN_FUNCTIONS = frozenset({
        "pg_sleep",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "set_config",
        "nextval",
        "setval",
        "lo_import",
        "lo_export",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "pg_rotate_logfile",
        "pg_log_backend_memory_contexts",
        "dblink",
        "dblink_exec",
        "query_to_xml",
        "inet_server_addr",
        "inet_server_port",
    })

    ALLOWED_FUNCTIONS = frozenset({
        "abs", "acos", "asin", "atan", "atan2", "avg", "bool_and", "bool_or",
        "ceil", "ceiling", "char_length", "coalesce", "concat", "concat_ws",
        "count", "date_part", "date_trunc", "exists", "exp", "floor", "greatest",
        "initcap", "length", "least", "ln", "log", "lower", "ltrim", "max",
        "min", "mod", "nullif", "power", "replace", "round", "rtrim", "sign",
        "sin", "sqrt", "string_agg", "substring", "sum", "tan", "to_char",
        "to_date", "to_number", "to_timestamp", "trim", "trunc", "upper",
        "variance", "var_pop", "var_samp", "stddev", "stddev_pop", "stddev_samp",
        "array_agg", "json_agg", "jsonb_agg", "json_build_object",
        "jsonb_build_object", "current_date", "current_time", "current_timestamp",
        "localtime", "localtimestamp",
    })

    _FORBIDDEN_EXPRESSIONS = (
        exp.DML,
        exp.DDL,
        exp.Command,
        exp.Transaction,
        exp.Grant,
        exp.Revoke,
        exp.Analyze,
        exp.Set,
        exp.SetItem,
        exp.Use,
        exp.Lock,
        exp.Into,
    )

    def __init__(self, default_limit: int = 100, max_limit: int = 500):
        if default_limit < 0:
            raise ValueError("The default SQL limit cannot be negative.")
        if max_limit < 1:
            raise ValueError("The maximum SQL limit must be positive.")
        if default_limit > max_limit:
            raise ValueError("The default SQL limit cannot exceed the maximum SQL limit.")
        self.default_limit = default_limit
        self.max_limit = max_limit

    def validate(
        self,
        sql: str,
        allowed_tables: Optional[Collection[str]] = None,
    ) -> SQLValidationResult:
        """Return a structured result and normalized SQL only when all checks pass."""
        if sql is None or (isinstance(sql, str) and not sql.strip()):
            return self._reject(
                SQLValidationCode.EMPTY_QUERY,
                "SQL query cannot be empty.",
            )
        if not isinstance(sql, str):
            return self._reject(
                SQLValidationCode.INVALID_INPUT,
                "SQL query must be provided as text.",
            )

        try:
            parsed = sqlglot.parse(sql, read="postgres")
        except SqlglotError:
            return self._reject(
                SQLValidationCode.SQL_PARSE_ERROR,
                "SQL parse error: the query could not be parsed as PostgreSQL.",
            )

        statements = [
            statement
            for statement in parsed
            if statement is not None and not isinstance(statement, exp.Semicolon)
        ]
        statement_count = len(statements)
        if statement_count == 0:
            return self._reject(
                SQLValidationCode.EMPTY_QUERY,
                "SQL query cannot be empty or contain only comments.",
            )
        if statement_count != 1:
            return self._reject(
                SQLValidationCode.MULTIPLE_STATEMENTS,
                "Multiple SQL statements are not permitted; provide exactly one statement.",
                statement_count=statement_count,
            )

        root = statements[0]
        if not isinstance(root, (exp.Select, exp.Union)):
            return self._reject(
                SQLValidationCode.NON_SELECT_QUERY,
                "Only SELECT queries, including SELECT-based CTEs and UNIONs, are permitted.",
                statement_count=statement_count,
            )

        if any(isinstance(node, self._FORBIDDEN_EXPRESSIONS) for node in root.walk()):
            return self._reject(
                SQLValidationCode.FORBIDDEN_OPERATION,
                "The query contains a forbidden data, schema, session, or transaction operation.",
                statement_count=statement_count,
            )

        table_error, referenced_tables = self._validate_tables(root, allowed_tables)
        if table_error is not None:
            return self._reject(
                SQLValidationCode.FORBIDDEN_TABLE,
                table_error,
                statement_count=statement_count,
                referenced_tables=referenced_tables,
            )

        function_error = self._validate_functions(root)
        if function_error is not None:
            return self._reject(
                SQLValidationCode.FORBIDDEN_FUNCTION,
                function_error,
                statement_count=statement_count,
                referenced_tables=referenced_tables,
            )

        if root.find(exp.Parameter):
            return self._reject(
                SQLValidationCode.UNSAFE_QUERY_STRUCTURE,
                "Positional PostgreSQL parameters are not supported; use named parameters.",
                statement_count=statement_count,
                referenced_tables=referenced_tables,
            )
        for placeholder in root.find_all(exp.Placeholder):
            name = placeholder.name
            if not isinstance(name, str) or not name.isidentifier():
                return self._reject(
                    SQLValidationCode.UNSAFE_QUERY_STRUCTURE,
                    "Only named SQLAlchemy bind parameters are supported.",
                    statement_count=statement_count,
                    referenced_tables=referenced_tables,
                )

        for offset in root.find_all(exp.Offset):
            offset_expression = offset.args.get("expression")
            if not isinstance(offset_expression, exp.Literal) or offset_expression.is_string:
                return self._reject(
                    SQLValidationCode.LIMIT_INVALID,
                    "OFFSET must be a non-negative integer literal.",
                    statement_count=statement_count,
                    referenced_tables=referenced_tables,
                )
            raw_offset = str(offset_expression.this)
            if not raw_offset.isascii() or not raw_offset.isdigit():
                return self._reject(
                    SQLValidationCode.LIMIT_INVALID,
                    "OFFSET must be a non-negative integer literal.",
                    statement_count=statement_count,
                    referenced_tables=referenced_tables,
                )
            if int(raw_offset) > self.max_limit:
                return self._reject(
                    SQLValidationCode.QUERY_LIMIT_EXCEEDED,
                    f"OFFSET cannot exceed {self.max_limit} rows.",
                    statement_count=statement_count,
                    referenced_tables=referenced_tables,
                )

        self._qualify_public_tables(root)
        query_limit = root.args.get("limit")
        limit_applied = False
        if query_limit is None:
            result_limit = self.default_limit
            root.set(
                "limit",
                exp.Limit(expression=exp.Literal.number(result_limit)),
            )
            limit_applied = True
        else:
            limit_expression = query_limit.args.get("expression")
            if not isinstance(limit_expression, exp.Literal) or limit_expression.is_string:
                return self._reject(
                    SQLValidationCode.LIMIT_INVALID,
                    "LIMIT must be a non-negative integer literal.",
                    statement_count=statement_count,
                    referenced_tables=referenced_tables,
                )
            try:
                raw_limit = str(limit_expression.this)
                if not raw_limit.isascii() or not raw_limit.isdigit():
                    raise ValueError("LIMIT must contain only decimal digits.")
                result_limit = int(raw_limit)
            except (TypeError, ValueError):
                return self._reject(
                    SQLValidationCode.LIMIT_INVALID,
                    "LIMIT must be a non-negative integer literal.",
                    statement_count=statement_count,
                    referenced_tables=referenced_tables,
                )
            if result_limit < 0:
                return self._reject(
                    SQLValidationCode.LIMIT_INVALID,
                    "LIMIT must be a non-negative integer literal.",
                    statement_count=statement_count,
                    referenced_tables=referenced_tables,
                )
            if result_limit > self.max_limit:
                result_limit = self.max_limit
                query_limit.set("expression", exp.Literal.number(result_limit))
                limit_applied = True

        normalized_sql = _SQLAlchemyPostgresGenerator().generate(root)
        return SQLValidationResult(
            valid=True,
            sql=normalized_sql,
            statement_count=statement_count,
            result_limit=result_limit,
            limit_applied=limit_applied,
            referenced_tables=referenced_tables,
        )

    def _validate_tables(
        self,
        root: exp.Expr,
        allowed_tables: Optional[Collection[str]],
    ) -> tuple[Optional[str], Tuple[str, ...]]:
        allowed = (
            {self._normalize_identifier(name) for name in allowed_tables}
            if allowed_tables is not None
            else None
        )
        referenced = set()

        for table in self._database_tables(root):
            if isinstance(table.this, exp.Func):
                continue
            table_name = self._identifier_value(table.this)
            referenced.add(table_name)

            schema = self._identifier_value(table.args.get("db"))
            catalog = self._identifier_value(table.args.get("catalog"))
            if catalog or (schema and schema != "public"):
                return (
                    "Only unqualified tables or tables in the public schema are permitted.",
                    tuple(sorted(referenced)),
                )
            if allowed is not None and self._normalize_identifier(table_name) not in allowed:
                return (
                    f"Table '{table_name}' is not present in the allowed public schema.",
                    tuple(sorted(referenced)),
                )

        if referenced and allowed is None:
            return (
                "A configured table allowlist is required for queries that read database tables.",
                tuple(sorted(referenced)),
            )
        return None, tuple(sorted(referenced))

    def _qualify_public_tables(self, root: exp.Expr) -> None:
        for table in self._database_tables(root):
            if not table.args.get("db"):
                table.set("db", exp.to_identifier("public"))

    @staticmethod
    def _database_tables(root: exp.Expr):
        for scope in traverse_scope(root):
            for table in scope.tables:
                source = scope.sources.get(table.alias_or_name)
                if isinstance(source, Scope):
                    continue
                yield table

    def _validate_functions(self, root: exp.Expr) -> Optional[str]:
        for function in root.find_all(exp.Func):
            if isinstance(function.parent, exp.Dot) and function.parent.expression is function:
                return "Schema-qualified SQL functions are not permitted."

            name = function.name if isinstance(function, exp.Anonymous) else function.sql_name()
            normalized_name = name.lower()
            if normalized_name == "timestamp_trunc":
                normalized_name = "date_trunc"
            if normalized_name in self.FORBIDDEN_FUNCTIONS:
                return f"Function '{name}' is forbidden."
            if normalized_name not in self.ALLOWED_FUNCTIONS:
                return f"Function '{name}' is not in the read-only function allowlist."

        return None

    @staticmethod
    def _identifier_value(expression: Optional[exp.Expr]) -> str:
        if expression is None:
            return ""
        if isinstance(expression, exp.TableAlias):
            expression = expression.this
        if isinstance(expression, exp.Identifier):
            value = str(expression.this)
            return value if expression.args.get("quoted") else value.lower()
        return str(expression)

    @staticmethod
    def _normalize_identifier(value: str) -> str:
        return value

    @staticmethod
    def _reject(
        code: SQLValidationCode,
        message: str,
        statement_count: int = 0,
        referenced_tables: Tuple[str, ...] = (),
    ) -> SQLValidationResult:
        return SQLValidationResult(
            valid=False,
            sql=None,
            statement_count=statement_count,
            result_limit=None,
            limit_applied=False,
            error_code=code,
            error_message=message,
            referenced_tables=referenced_tables,
        )
