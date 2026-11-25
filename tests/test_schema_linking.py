"""Tests for database introspection and schema linking."""

from unittest.mock import MagicMock

import pytest

import backend.services.schema_linking as schema_linking
from backend.services.schema_linking import (
    ColumnMetadata,
    DatabaseSchema,
    ForeignKeyMetadata,
    SchemaInspector,
    SchemaLinker,
    TableMetadata,
)


def _synthetic_schema():
    schema = DatabaseSchema()
    columns = {
        "customers": {
            "customer_id": ("integer", True),
            "customer_state": ("varchar", False),
        },
        "orders": {
            "order_id": ("integer", True),
            "customer_id": ("integer", False),
        },
        "order_items": {
            "order_item_id": ("integer", True),
            "order_id": ("integer", False),
            "price": ("numeric", False),
        },
        "order_payments": {
            "payment_id": ("integer", True),
            "order_id": ("integer", False),
            "payment_value": ("numeric", False),
        },
        "order_reviews": {
            "review_id": ("integer", True),
            "order_id": ("integer", False),
            "review_score": ("integer", False),
        },
    }

    for table_name, table_columns in columns.items():
        table = TableMetadata(name=table_name)
        for column_name, (type_name, is_primary_key) in table_columns.items():
            table.columns[column_name] = ColumnMetadata(
                name=column_name,
                type_name=type_name,
                nullable=not is_primary_key,
                is_primary_key=is_primary_key,
            )
            if is_primary_key:
                table.primary_keys.append(column_name)
        schema.tables[table_name] = table

    schema.foreign_keys = [
        ForeignKeyMetadata("orders", "customer_id", "customers", "customer_id"),
        ForeignKeyMetadata("order_items", "order_id", "orders", "order_id"),
        ForeignKeyMetadata("order_payments", "order_id", "orders", "order_id"),
        ForeignKeyMetadata("order_reviews", "order_id", "orders", "order_id"),
    ]
    for foreign_key in schema.foreign_keys:
        schema.tables[foreign_key.constrained_table].foreign_keys.append(foreign_key)
    return schema


@pytest.fixture
def synthetic_schema():
    return _synthetic_schema()


@pytest.fixture
def schema_linker(synthetic_schema):
    inspector = MagicMock()
    inspector.introspect.return_value = synthetic_schema
    return SchemaLinker(inspector=inspector)


def test_schema_introspection(monkeypatch):
    schema_data = _synthetic_schema()
    fake_inspector = MagicMock()
    fake_inspector.get_table_names.return_value = list(schema_data.tables)

    def get_primary_key(table_name):
        return {"constrained_columns": schema_data.tables[table_name].primary_keys}

    def get_columns(table_name):
        return [
            {
                "name": column.name,
                "type": column.type_name,
                "nullable": column.nullable,
            }
            for column in schema_data.tables[table_name].columns.values()
        ]

    def get_foreign_keys(table_name):
        return [
            {
                "constrained_columns": [foreign_key.constrained_column],
                "referred_table": foreign_key.referred_table,
                "referred_columns": [foreign_key.referred_column],
            }
            for foreign_key in schema_data.tables[table_name].foreign_keys
        ]

    fake_inspector.get_pk_constraint.side_effect = get_primary_key
    fake_inspector.get_columns.side_effect = get_columns
    fake_inspector.get_foreign_keys.side_effect = get_foreign_keys
    monkeypatch.setattr(schema_linking, "inspect", lambda engine: fake_inspector)

    inspector = SchemaInspector(engine=object())
    schema = inspector.introspect()

    expected = ["customers", "orders", "order_items", "order_payments", "order_reviews"]
    for table in expected:
        assert table in schema.tables
        assert len(schema.tables[table].columns) > 0
        assert len(schema.tables[table].primary_keys) > 0
    assert len(schema.foreign_keys) == 4
    assert schema.tables["orders"].columns["customer_id"].type_name == "integer"


def test_schema_linking_orders(schema_linker):
    res = schema_linker.link("How many orders were placed?")
    assert "orders" in res.relevant_tables
    assert "COUNT" in res.detected_operations


def test_schema_linking_join(schema_linker):
    res = schema_linker.link("What is the total revenue by customer state?")
    assert "customers" in res.relevant_tables
    assert "order_items" in res.relevant_tables
    assert "SUM" in res.detected_operations
    assert len(res.relevant_relationships) > 0


def test_schema_linking_reviews(schema_linker):
    res = schema_linker.link("Quelle est la note moyenne des avis clients ?")
    assert "order_reviews" in res.relevant_tables
    assert "AVG" in res.detected_operations
