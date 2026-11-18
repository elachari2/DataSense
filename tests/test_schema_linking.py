"""Tests for database introspection and schema linking."""

import pytest
from backend.services.schema_linking import (
    SchemaInspector,
    SchemaLinker,
    get_schema_linker
)


def test_schema_introspection():
    inspector = SchemaInspector()
    schema = inspector.introspect()
    
    # Verify expected tables exist
    expected = ["customers", "orders", "order_items", "order_payments", "order_reviews"]
    for table in expected:
        assert table in schema.tables
        assert len(schema.tables[table].columns) > 0
        assert len(schema.tables[table].primary_keys) > 0


def test_schema_linking_orders():
    linker = get_schema_linker()
    res = linker.link("How many orders were placed?")
    assert "orders" in res.relevant_tables
    assert "COUNT" in res.detected_operations


def test_schema_linking_join():
    linker = get_schema_linker()
    res = linker.link("What is the total revenue by customer state?")
    assert "customers" in res.relevant_tables
    assert "order_items" in res.relevant_tables
    assert "SUM" in res.detected_operations
    assert len(res.relevant_relationships) > 0


def test_schema_linking_reviews():
    linker = get_schema_linker()
    res = linker.link("Quelle est la note moyenne des avis clients ?")
    assert "order_reviews" in res.relevant_tables
    assert "AVG" in res.detected_operations
