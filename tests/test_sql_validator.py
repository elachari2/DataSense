"""Focused tests for PostgreSQL AST validation and result-limit enforcement."""

import pytest

from backend.security.sql_validator import SQLValidationCode, SQLValidator


@pytest.fixture
def validator():
    return SQLValidator(default_limit=100, max_limit=1000)


TABLES = {"customers", "orders", "order_items", "order_payments", "order_reviews"}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM orders",
        "SELECT * FROM orders WHERE order_status = 'delivered'",
        "SELECT * FROM orders ORDER BY order_purchase_timestamp DESC",
        "SELECT order_status, COUNT(*) FROM orders GROUP BY order_status",
        "SELECT order_status, COUNT(*) FROM orders GROUP BY order_status HAVING COUNT(*) > 1",
        "SELECT * FROM orders LIMIT 50",
        "SELECT * FROM orders LIMIT 0001",
        "SELECT * FROM orders OFFSET 10",
        "SELECT * FROM orders OFFSET 500",
        "SELECT * FROM orders o JOIN customers c ON c.customer_id = o.customer_id",
        "SELECT * FROM orders o JOIN customers c ON c.customer_id = o.customer_id "
        "JOIN order_items i ON i.order_id = o.order_id",
        "SELECT COUNT(*) FROM orders",
        "SELECT SUM(price) FROM order_items",
        "SELECT AVG(review_score) FROM order_reviews",
        "SELECT DISTINCT order_status FROM orders",
        "SELECT * FROM orders WHERE customer_id IN (SELECT customer_id FROM customers)",
        "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent",
        "WITH recent AS (SELECT * FROM orders), customers_cte AS "
        "(SELECT * FROM customers) SELECT * FROM recent JOIN customers_cte ON TRUE",
        "SELECT order_id FROM orders UNION SELECT order_id FROM order_items",
        "SELECT order_id FROM orders UNION ALL SELECT order_id FROM order_items",
        "SELECT /* safe comment */ * FROM orders -- trailing comment",
        "SELECT * FROM orders;",
        "SELECT DATE_TRUNC('month', order_purchase_timestamp) FROM orders",
        "SELECT COALESCE(order_status, 'unknown') FROM orders",
    ],
)
def test_allows_supported_read_queries(validator, sql):
    result = validator.validate(sql, allowed_tables=TABLES)

    assert result.valid
    assert result.statement_count == 1
    assert result.sql


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO orders (order_id) VALUES ('x')",
        "UPDATE orders SET order_status = 'paid'",
        "DELETE FROM orders",
        "MERGE INTO orders USING customers ON TRUE WHEN MATCHED THEN DELETE",
        "DROP TABLE orders",
        "ALTER TABLE orders ADD COLUMN unsafe TEXT",
        "CREATE TABLE unsafe (id INT)",
        "TRUNCATE orders",
        "GRANT SELECT ON orders TO PUBLIC",
        "REVOKE SELECT ON orders FROM PUBLIC",
        "CALL do_something()",
        "DO $$ BEGIN PERFORM 1; END $$",
        "EXECUTE 'SELECT 1'",
        "SET statement_timeout = 0",
        "RESET statement_timeout",
        "BEGIN",
        "COMMIT",
        "SELECT * INTO copied_orders FROM orders",
        "SELECT * FROM orders FOR UPDATE",
        "SELECT * FROM orders FOR SHARE",
        "SELECT 1; DELETE FROM orders",
        "SELECT 1; DROP TABLE orders",
        "WITH bad AS (DELETE FROM orders RETURNING *) SELECT * FROM bad",
        "SELECT * FROM missing_table",
        "SELECT * FROM pg_catalog.pg_tables",
        "SELECT * FROM information_schema.tables",
        "SELECT FROM WHERE",
        "",
        "   ",
        "-- only a comment",
        "SELECT * FROM orders LIMIT -1",
        "SELECT * FROM orders LIMIT 1.5",
        "SELECT * FROM orders LIMIT ALL",
        "SELECT * FROM orders LIMIT $1",
        "SELECT * FROM orders WHERE order_id = $1",
        "SELECT * FROM orders OFFSET -1",
        "SELECT * FROM orders OFFSET 1001",
        "SELECT * FROM orders OFFSET :offset",
        "SELECT pg_sleep(1)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_catalog.pg_read_file('/etc/passwd')",
        "SELECT (SELECT pg_sleep(1))",
        "SELECT order_id FROM orders UNION ALL SELECT pg_sleep(1)",
        "SELECT * FROM generate_series(1, 1000000000)",
        "SELECT set_config('statement_timeout', '0', false)",
        "SELECT nextval('orders_id_seq')",
        "SELECT public.custom_function(1)",
        "SELECT unknown_function(1)",
    ],
)
def test_rejects_unsafe_or_invalid_queries(validator, sql):
    result = validator.validate(sql, allowed_tables=TABLES)
    assert not result.valid
    assert result.error_code is not None


def test_reports_multiple_statements_even_with_comments(validator):
    result = validator.validate("SELECT 1 -- first query\n; /* separator */ DELETE FROM orders")

    assert not result.valid
    assert result.error_code is SQLValidationCode.MULTIPLE_STATEMENTS
    assert result.statement_count == 2


def test_trailing_semicolon_and_comment_are_a_single_statement(validator):
    result = validator.validate("SELECT 1; -- allowed trailing comment")

    assert result.valid
    assert result.statement_count == 1


def test_statement_count_and_error_code_for_parse_error(validator):
    result = validator.validate("SELECT FROM WHERE")

    assert not result.valid
    assert result.error_code is SQLValidationCode.SQL_PARSE_ERROR


def test_default_limit_is_added(validator):
    result = validator.validate("SELECT * FROM orders", allowed_tables=TABLES)

    assert result.valid
    assert result.limit_applied
    assert result.result_limit == 100
    assert result.sql.endswith("LIMIT 100")
    assert "FROM public.orders" in result.sql


def test_reasonable_limit_is_preserved(validator):
    result = validator.validate("SELECT * FROM orders LIMIT 50", allowed_tables=TABLES)

    assert result.valid
    assert not result.limit_applied
    assert result.result_limit == 50
    assert result.sql.endswith("LIMIT 50")


def test_leading_zero_limit_is_accepted(validator):
    result = validator.validate("SELECT * FROM orders LIMIT 0001", allowed_tables=TABLES)

    assert result.valid
    assert result.result_limit == 1


def test_excessive_limit_is_clamped(validator):
    result = validator.validate("SELECT * FROM orders LIMIT 50000", allowed_tables=TABLES)

    assert result.valid
    assert result.limit_applied
    assert result.result_limit == 1000
    assert result.sql.endswith("LIMIT 1000")


@pytest.mark.parametrize(
    ("sql", "expected_limit"),
    [
        ("SELECT * FROM orders OFFSET 20", 100),
        (
            "WITH recent AS (SELECT * FROM orders LIMIT 5) SELECT * FROM recent",
            100,
        ),
        (
            "SELECT order_id FROM orders UNION ALL SELECT order_id FROM order_items",
            100,
        ),
        (
            "SELECT * FROM (SELECT * FROM orders LIMIT 5) AS limited",
            100,
        ),
    ],
)
def test_complex_queries_receive_outer_limit_without_changing_inner_limit(
    validator, sql, expected_limit
):
    result = validator.validate(sql, allowed_tables=TABLES)

    assert result.valid
    assert result.result_limit == expected_limit
    assert result.limit_applied
    if "LIMIT 5" in sql:
        assert result.sql.count("LIMIT 5") == 1
        assert result.sql.endswith(f"LIMIT {expected_limit}")


def test_rejects_tables_outside_public_allowlist(validator):
    result = validator.validate("SELECT * FROM orders", allowed_tables={"customers"})

    assert not result.valid
    assert result.error_code is SQLValidationCode.FORBIDDEN_TABLE


def test_cte_name_is_not_treated_as_a_database_table(validator):
    result = validator.validate(
        "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent",
        allowed_tables=TABLES,
    )

    assert result.valid
    assert result.referenced_tables == ("orders",)


def test_nested_cte_name_does_not_hide_outer_catalog_table(validator):
    sql = (
        "SELECT rolname, rolpassword FROM pg_authid "
        "WHERE EXISTS (WITH pg_authid AS (SELECT 1) SELECT 1)"
    )
    result = validator.validate(sql, allowed_tables=TABLES)

    assert not result.valid
    assert result.error_code is SQLValidationCode.FORBIDDEN_TABLE
    assert "pg_authid" in result.referenced_tables


def test_nested_cte_shadow_does_not_hide_allowed_outer_table(validator):
    sql = (
        "SELECT * FROM orders "
        "WHERE EXISTS (WITH orders AS (SELECT 1) SELECT 1)"
    )
    result = validator.validate(sql, allowed_tables=TABLES)

    assert result.valid
    assert result.referenced_tables == ("orders",)
    assert "FROM public.orders" in result.sql


def test_database_tables_require_an_explicit_allowlist(validator):
    result = validator.validate("SELECT * FROM orders")

    assert not result.valid
    assert result.error_code is SQLValidationCode.FORBIDDEN_TABLE


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT o.order_id FROM orders o JOIN internal_secrets s ON TRUE",
        "WITH secret_rows AS (SELECT * FROM internal_secrets) SELECT * FROM secret_rows",
        "SELECT * FROM (SELECT * FROM internal_secrets) AS nested_rows",
        "SELECT order_id FROM orders UNION ALL SELECT secret_id FROM internal_secrets",
    ],
)
def test_unapproved_table_is_rejected_in_every_query_scope(validator, sql):
    result = validator.validate(sql, allowed_tables=TABLES)

    assert not result.valid
    assert result.error_code is SQLValidationCode.FORBIDDEN_TABLE
    assert "internal_secrets" in result.referenced_tables


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT order_id FROM orders INTERSECT SELECT order_id FROM order_items",
        "SELECT order_id FROM orders EXCEPT SELECT order_id FROM order_items",
    ],
)
def test_rejects_unapproved_set_operations(validator, sql):
    result = validator.validate(sql, allowed_tables=TABLES)

    assert not result.valid
    assert result.error_code is SQLValidationCode.NON_SELECT_QUERY


def test_named_parameters_survive_sql_normalization(validator):
    result = validator.validate(
        "SELECT * FROM orders WHERE order_id = :order_id",
        allowed_tables=TABLES,
    )

    assert result.valid
    assert ":order_id" in result.sql
    assert "FROM public.orders" in result.sql


def test_validator_rejects_invalid_limit_configuration():
    with pytest.raises(ValueError):
        SQLValidator(default_limit=100, max_limit=50)
