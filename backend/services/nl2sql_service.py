"""
DataSense - NL2SQL Engine & Prompt Engineering Service.
Transforms natural language questions into accurate, executable PostgreSQL queries,
validates syntax, executes queries via QueryExecutor, and formats the response.
"""

import json
import re
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import pandas as pd

from backend.config.settings import get_settings, Settings
from backend.services.llm_service import GeminiLLMService, get_llm_service
from backend.services.schema_linking import SchemaLinker, SchemaLinkingResult, get_schema_linker
from backend.database.query_executor import QueryExecutor, QueryResult, get_query_executor

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior PostgreSQL database architect and expert SQL engineer specializing in the Olist e-commerce database.

YOUR GOAL:
Translate the user's natural language question (in English or French) into a single, highly accurate, executable PostgreSQL query.

DATABASE CONSTRAINTS:
1. STRICT ADHERENCE TO SCHEMA: Use ONLY the tables, columns, and relationships explicitly provided in the schema context below. NEVER invent table names, column names, or relationships.
2. DIALECT: Output standard, valid PostgreSQL SQL.
3. JOINS: Join tables using actual foreign-key relationships. Avoid unnecessary joins. Always use clean table aliases (e.g. 'o' for orders, 'c' for customers, 'oi' for order_items).
4. AGGREGATIONS & GROUPING:
   - When calculating counts, sums, or averages alongside dimension columns, always include every non-aggregated column in the GROUP BY clause.
   - For ranking ("top N", "highest", "lowest", "best"), use ORDER BY with LIMIT.
5. METRIC PRECISION:
   - "orders" / "commandes": COUNT(*) or COUNT(DISTINCT o.order_id) from orders.
   - "customers" / "clients": COUNT(DISTINCT c.customer_unique_id) or COUNT(c.customer_id) depending on whether unique people or orders are asked.
   - "revenue" / "chiffre d'affaires" / "sales" / "ventes": SUM(oi.price) or SUM(op.payment_value) from order_items or order_payments.
   - "average review score" / "note moyenne": ROUND(AVG(r.review_score), 2) from order_reviews.
   - "delivery delay" / "délai de livraison": EXTRACT(EPOCH FROM (o.order_delivered_customer_date - o.order_purchase_timestamp)) / 86400.
6. DATE & TIME OPERATIONS:
   - Use EXTRACT(YEAR FROM o.order_purchase_timestamp) or EXTRACT(YEAR FROM o.order_delivered_customer_date).
   - Use DATE_TRUNC('month', timestamp) for monthly aggregations.
   - Only consider orders delivered when specifically asked about deliveries: o.order_status = 'delivered'.
7. READ-ONLY SECURITY:
   - ONLY produce SELECT queries (or WITH queries followed by SELECT).
   - NEVER generate INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, or DDL.
   - NEVER generate multiple queries separated by semicolons.

OUTPUT FORMAT:
Respond with a single valid JSON object strictly matching this schema:
{
    "status": "success" | "clarification_required" | "unsupported",
    "sql": "SELECT ...",
    "explanation": "Brief explanation of how the query computes the answer."
}

If the question is ambiguous or impossible to answer with the given schema, set "status" to "clarification_required" or "unsupported", set "sql" to null, and explain why.

IMPORTANT: Do not wrap your response in markdown code blocks or triple backticks. Return ONLY the raw JSON string.
"""


@dataclass
class NL2SQLResponse:
    question: str
    status: str
    sql: Optional[str] = None
    explanation: str = ""
    is_valid_sql: bool = False
    execution_result: Optional[QueryResult] = None
    schema_linking: Optional[SchemaLinkingResult] = None
    llm_duration_seconds: float = 0.0
    total_duration_seconds: float = 0.0
    error_message: Optional[str] = None

    @property
    def has_data(self) -> bool:
        return (
            self.execution_result is not None
            and self.execution_result.success
            and self.execution_result.data is not None
            and not self.execution_result.data.empty
        )

    @property
    def data(self) -> Optional[pd.DataFrame]:
        return self.execution_result.data if self.execution_result else None


class NL2SQLService:
    """Orchestrates Schema Linking, Prompt Construction, Gemini Generation, Validation, and Execution."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        llm_service: Optional[GeminiLLMService] = None,
        schema_linker: Optional[SchemaLinker] = None,
        query_executor: Optional[QueryExecutor] = None,
    ):
        self.settings = settings or get_settings()
        self.llm = llm_service or get_llm_service()
        self.schema_linker = schema_linker or get_schema_linker()
        self.executor = query_executor or get_query_executor()

    def _clean_json_response(self, text: str) -> str:
        """Strips markdown fences or preamble text to isolate pure JSON."""
        cleaned = text.strip()
        # Remove ```json ... ``` fences
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    def process_question(self, question: str, execute: bool = True) -> NL2SQLResponse:
        """
        Executes the full NL2SQL pipeline:
        1. Validate user question.
        2. Perform Schema Linking.
        3. Build prompt with focused schema context.
        4. Call Gemini to generate SQL.
        5. Parse structured JSON response.
        6. Validate SQL for read-only security.
        7. Execute SQL against PostgreSQL.
        8. Return comprehensive NL2SQLResponse.
        """
        import time
        start_time = time.time()

        if not question or not question.strip():
            return NL2SQLResponse(
                question=question,
                status="unsupported",
                explanation="Please provide a non-empty question.",
                error_message="Empty question string."
            )

        # 1. Schema Linking
        linking_result = self.schema_linker.link(question)

        # 2. Build User Prompt
        relationships_text = ""
        if linking_result.relevant_relationships:
            relationships_text = "\nRELEVANT RELATIONSHIPS:\n" + "\n".join(
                f"- {rel}" for rel in linking_result.relevant_relationships
            )

        operations_text = ""
        if linking_result.detected_operations:
            operations_text = f"\nDETECTED OPERATIONS: {', '.join(linking_result.detected_operations)}"

        user_prompt = f"""USER QUESTION:
"{question}"

DATABASE SCHEMA CONTEXT:
{linking_result.context_schema_ddl}
{relationships_text}
{operations_text}

Generate the JSON response containing the exact PostgreSQL SQL query.
"""

        # 3. Call LLM
        llm_response = self.llm.generate(
            prompt=user_prompt,
            system_instruction=SYSTEM_PROMPT,
            temperature=0.0,
            response_mime_type="application/json"
        )

        if not llm_response.success:
            return NL2SQLResponse(
                question=question,
                status="error",
                explanation="Failed to generate SQL due to an LLM provider error.",
                schema_linking=linking_result,
                llm_duration_seconds=llm_response.duration_seconds,
                total_duration_seconds=time.time() - start_time,
                error_message=llm_response.error
            )

        # 4. Parse Structured JSON
        raw_text = self._clean_json_response(llm_response.text)
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            # Fallback regex if LLM included conversational prose
            sql_match = re.search(r"SELECT\s+.*?(?:;|\Z)", raw_text, re.IGNORECASE | re.DOTALL)
            if sql_match:
                parsed = {
                    "status": "success",
                    "sql": sql_match.group(0).strip().rstrip(";"),
                    "explanation": "Extracted SQL query from model response."
                }
            else:
                return NL2SQLResponse(
                    question=question,
                    status="error",
                    explanation="Failed to parse structured JSON from LLM response.",
                    schema_linking=linking_result,
                    llm_duration_seconds=llm_response.duration_seconds,
                    total_duration_seconds=time.time() - start_time,
                    error_message=f"Invalid JSON returned: {raw_text[:200]}"
                )

        status = parsed.get("status", "success")
        sql = parsed.get("sql")
        explanation = parsed.get("explanation", "")

        if not sql or status != "success":
            return NL2SQLResponse(
                question=question,
                status=status,
                sql=None,
                explanation=explanation or "The question could not be answered with the available database schema.",
                schema_linking=linking_result,
                llm_duration_seconds=llm_response.duration_seconds,
                total_duration_seconds=time.time() - start_time
            )

        # Clean trailing semicolon or formatting
        sql = sql.strip().rstrip(";")

        # 5. Validate SQL
        is_valid, val_err = self.executor.validate_sql(sql)
        if not is_valid:
            return NL2SQLResponse(
                question=question,
                status="security_rejected",
                sql=sql,
                explanation=explanation,
                is_valid_sql=False,
                schema_linking=linking_result,
                llm_duration_seconds=llm_response.duration_seconds,
                total_duration_seconds=time.time() - start_time,
                error_message=f"SQL Validation Failed: {val_err}"
            )

        # 6. Execute SQL
        exec_result: Optional[QueryResult] = None
        if execute:
            exec_result = self.executor.execute(sql)

        total_duration = time.time() - start_time

        return NL2SQLResponse(
            question=question,
            status="success" if (exec_result is None or exec_result.success) else "execution_error",
            sql=sql,
            explanation=explanation,
            is_valid_sql=True,
            execution_result=exec_result,
            schema_linking=linking_result,
            llm_duration_seconds=llm_response.duration_seconds,
            total_duration_seconds=total_duration,
            error_message=exec_result.error_message if exec_result and not exec_result.success else None
        )


_nl2sql_service_instance: Optional[NL2SQLService] = None


def get_nl2sql_service() -> NL2SQLService:
    """Returns singleton NL2SQLService instance."""
    global _nl2sql_service_instance
    if _nl2sql_service_instance is None:
        _nl2sql_service_instance = NL2SQLService()
    return _nl2sql_service_instance
