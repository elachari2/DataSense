"""
DataSense - Database Schema Introspection & Schema Linking Service.
Dynamically discovers PostgreSQL tables, columns, data types, keys, and foreign-key relationships.
Links natural language questions to the relevant sub-schema for focused LLM prompts.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from sqlalchemy import inspect

from src.db import get_engine

logger = logging.getLogger(__name__)


@dataclass
class ColumnMetadata:
    name: str
    type_name: str
    nullable: bool
    is_primary_key: bool


@dataclass
class ForeignKeyMetadata:
    constrained_table: str
    constrained_column: str
    referred_table: str
    referred_column: str

    def __str__(self) -> str:
        return f"{self.constrained_table}.{self.constrained_column} -> {self.referred_table}.{self.referred_column}"


@dataclass
class TableMetadata:
    name: str
    columns: Dict[str, ColumnMetadata] = field(default_factory=dict)
    primary_keys: List[str] = field(default_factory=list)
    foreign_keys: List[ForeignKeyMetadata] = field(default_factory=list)

    def to_ddl_summary(self) -> str:
        cols = []
        for col_name, col in self.columns.items():
            pk_mark = " [PK]" if col.is_primary_key else ""
            cols.append(f"  - {col_name}: {col.type_name}{pk_mark}")
        
        fks = []
        for fk in self.foreign_keys:
            fks.append(f"  * FK: {fk.constrained_column} REFERENCES {fk.referred_table}({fk.referred_column})")
        
        text = f"TABLE {self.name}:\n" + "\n".join(cols)
        if fks:
            text += "\n" + "\n".join(fks)
        return text


@dataclass
class DatabaseSchema:
    tables: Dict[str, TableMetadata] = field(default_factory=dict)
    foreign_keys: List[ForeignKeyMetadata] = field(default_factory=list)

    def get_full_schema_summary(self) -> str:
        return "\n\n".join(t.to_ddl_summary() for t in self.tables.values())

    def get_focused_schema_summary(self, table_names: List[str]) -> str:
        selected = [self.tables[t] for t in table_names if t in self.tables]
        if not selected:
            return self.get_full_schema_summary()
        return "\n\n".join(t.to_ddl_summary() for t in selected)


@dataclass
class SchemaLinkingResult:
    question: str
    relevant_tables: List[str]
    relevant_columns: Dict[str, List[str]]
    relevant_relationships: List[str]
    detected_operations: List[str]
    context_schema_ddl: str


class SchemaInspector:
    """Introspects the live PostgreSQL schema dynamically via SQLAlchemy."""

    def __init__(self, engine=None):
        self.engine = engine or get_engine()
        self._cached_schema: Optional[DatabaseSchema] = None

    def introspect(self, force_refresh: bool = False) -> DatabaseSchema:
        """Dynamically inspects PostgreSQL to extract tables, columns, PKs, and FKs."""
        if self._cached_schema is not None and not force_refresh:
            return self._cached_schema

        inspector = inspect(self.engine)
        table_names = inspector.get_table_names(schema="public")
        
        schema = DatabaseSchema()

        for table_name in table_names:
            table_meta = TableMetadata(name=table_name)
            pks = inspector.get_pk_constraint(table_name).get("constrained_columns", [])
            table_meta.primary_keys = pks

            for col in inspector.get_columns(table_name):
                c_name = col["name"]
                table_meta.columns[c_name] = ColumnMetadata(
                    name=c_name,
                    type_name=str(col["type"]),
                    nullable=bool(col.get("nullable", True)),
                    is_primary_key=c_name in pks
                )

            for fk in inspector.get_foreign_keys(table_name):
                for constrained_col, referred_col in zip(
                    fk["constrained_columns"], fk["referred_columns"]
                ):
                    fk_meta = ForeignKeyMetadata(
                        constrained_table=table_name,
                        constrained_column=constrained_col,
                        referred_table=fk["referred_table"],
                        referred_column=referred_col
                    )
                    table_meta.foreign_keys.append(fk_meta)
                    schema.foreign_keys.append(fk_meta)

            schema.tables[table_name] = table_meta

        self._cached_schema = schema
        return schema


class SchemaLinker:
    """
    Performs Schema Linking: maps user natural language questions to the relevant
    tables, columns, and relationships in the PostgreSQL database.
    """

    # Domain vocabulary mapping for Olist e-commerce
    KEYWORD_MAPPINGS = {
        "orders": [
            "order", "commande", "commandes", "orders", "purchase", "achat", "delivered",
            "livraison", "livré", "livree", "statut", "status", "shipped", "carrier",
            "date", "timestamp", "annee", "year", "2016", "2017", "2018", "delai", "delay"
        ],
        "customers": [
            "customer", "client", "clients", "customers", "city", "ville", "state", "etat",
            "zip", "region", "pays", "bresil", "brazil", "unique"
        ],
        "order_items": [
            "item", "items", "article", "articles", "product", "produit", "produits",
            "price", "prix", "freight", "frais", "port", "seller", "vendeur", "vendeurs",
            "sales", "vente", "ventes", "revenue", "chiffre d'affaires", "ca"
        ],
        "order_payments": [
            "payment", "paiement", "paiements", "payments", "installments", "versement",
            "type", "credit", "boleto", "voucher", "debit", "valeur", "value"
        ],
        "order_reviews": [
            "review", "reviews", "avis", "commentaire", "commentaires", "score", "note",
            "notes", "etoiles", "stars", "satisfaction", "message", "positif", "negatif",
            "evaluation", "moyenne"
        ]
    }

    OPERATION_PATTERNS = {
        "COUNT": [r"\bhow many\b", r"\bcombien\b", r"\bnombre\b", r"\bcount\b", r"\btotal number\b"],
        "SUM": [r"\btotal\b", r"\bsum\b", r"\brevenue\b", r"\bchiffre d'affaires\b", r"\bmontant\b"],
        "AVG": [r"\baverage\b", r"\bmoyenne\b", r"\bmoyen\b", r"\bmean\b"],
        "MAX": [r"\bhighest\b", r"\bmax\b", r"\bmaximum\b", r"\bplus grand\b", r"\bplus cher\b"],
        "MIN": [r"\blowest\b", r"\bmin\b", r"\bminimum\b", r"\bmoins cher\b"],
        "TOP_N": [r"\btop\s*\d+\b", r"\bles\s*\d+\b", r"\bpremier\b", r"\bpremiers\b", r"\branking\b"],
        "GROUP_BY": [r"\bby\b", r"\bpar\b", r"\bper\b", r"\brepartition\b", r"\bdistribution\b"]
    }

    def __init__(self, inspector: Optional[SchemaInspector] = None):
        self.inspector = inspector or SchemaInspector()

    def link(self, question: str) -> SchemaLinkingResult:
        """
        Analyzes the user question and maps it to the relevant PostgreSQL schema subset.
        Validates selected tables and columns against the live database metadata.
        """
        schema = self.inspector.introspect()
        all_tables = list(schema.tables.keys())

        normalized_q = question.lower()
        relevant_tables: List[str] = []

        # 1. Detect candidate tables from domain keywords
        for table_name, keywords in self.KEYWORD_MAPPINGS.items():
            if table_name in all_tables:
                for kw in keywords:
                    if re.search(r"\b" + re.escape(kw) + r"\b", normalized_q):
                        if table_name not in relevant_tables:
                            relevant_tables.append(table_name)
                        break

        # If question mentions metrics like revenue or price, order_items or order_payments is crucial
        if any(w in normalized_q for w in ["revenue", "chiffre d'affaires", "ca", "sales", "vente", "ventes", "prix", "price"]):
            if "order_items" in all_tables and "order_items" not in relevant_tables:
                relevant_tables.append("order_items")

        # If question mentions orders and items, ensure orders is included
        if "order_items" in relevant_tables or "order_payments" in relevant_tables or "order_reviews" in relevant_tables:
            if "orders" in all_tables and "orders" not in relevant_tables:
                relevant_tables.append("orders")

        # Default fallback: if no specific table matched, include all discovered tables
        if not relevant_tables:
            relevant_tables = all_tables

        # 2. Identify relevant relationships for joined tables
        relevant_relationships: List[str] = []
        for fk in schema.foreign_keys:
            if fk.constrained_table in relevant_tables and fk.referred_table in relevant_tables:
                rel_str = f"{fk.constrained_table}.{fk.constrained_column} = {fk.referred_table}.{fk.referred_column}"
                if rel_str not in relevant_relationships:
                    relevant_relationships.append(rel_str)

        # 3. Detect candidate columns per relevant table
        relevant_columns: Dict[str, List[str]] = {}
        for t_name in relevant_tables:
            table_meta = schema.tables.get(t_name)
            if not table_meta:
                continue
            cols = []
            for col_name in table_meta.columns.keys():
                col_clean = col_name.replace("_", " ")
                if col_name in normalized_q or col_clean in normalized_q:
                    cols.append(col_name)
            relevant_columns[t_name] = cols

        # 4. Detect aggregate operations
        detected_operations = []
        for op, patterns in self.OPERATION_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, normalized_q):
                    detected_operations.append(op)
                    break

        # 5. Build focused schema DDL text
        context_schema_ddl = schema.get_focused_schema_summary(relevant_tables)

        return SchemaLinkingResult(
            question=question,
            relevant_tables=relevant_tables,
            relevant_columns=relevant_columns,
            relevant_relationships=relevant_relationships,
            detected_operations=detected_operations,
            context_schema_ddl=context_schema_ddl
        )


_schema_linker_instance: Optional[SchemaLinker] = None


def get_schema_linker() -> SchemaLinker:
    """Returns singleton SchemaLinker instance."""
    global _schema_linker_instance
    if _schema_linker_instance is None:
        _schema_linker_instance = SchemaLinker()
    return _schema_linker_instance
