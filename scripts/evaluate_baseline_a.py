"""
DataSense - Baseline A Automated Evaluation Script.
Evaluates the NL2SQL pipeline against the 30 reference questions benchmark:
Generates SQL via Gemini, executes both generated and reference SQL against PostgreSQL,
compares results, measures response times, and outputs reports/baseline_a_results.json.
"""

import sys
import json
import time
from datetime import datetime
from pathlib import Path
from decimal import Decimal
from typing import Optional, List, Dict, Any
import pandas as pd
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.config.settings import get_settings
from backend.services.nl2sql_service import get_nl2sql_service
from backend.database.query_executor import get_query_executor


def are_results_equivalent(df_gen: Optional[pd.DataFrame], df_ref: Optional[pd.DataFrame]) -> bool:
    """
    Compares two DataFrames for semantic/numerical equivalence:
    - Handles scalar single-value answers (e.g. COUNT, SUM, AVG) regardless of column name aliases.
    - Handles multiple rows and columns with tolerance for float rounding and ordering.
    """
    if df_gen is None or df_ref is None:
        return False
    if df_gen.empty and df_ref.empty:
        return True
    if df_gen.empty != df_ref.empty:
        return False

    # 1. Single scalar value comparison (most common for aggregation)
    if df_gen.shape == (1, 1) and df_ref.shape == (1, 1):
        v_gen = df_gen.iloc[0, 0]
        v_ref = df_ref.iloc[0, 0]
        if v_gen is None and v_ref is None:
            return True
        try:
            f_gen = float(v_gen)
            f_ref = float(v_ref)
            return abs(f_gen - f_ref) < 0.05
        except (ValueError, TypeError):
            return str(v_gen).strip().lower() == str(v_ref).strip().lower()

    # 2. Same number of rows and columns
    if df_gen.shape != df_ref.shape:
        return False

    # 3. Value-based comparison across rows
    # Convert Decimals to float
    def normalize_val(val):
        if isinstance(val, (Decimal, np.floating)):
            return round(float(val), 2)
        if isinstance(val, (int, np.integer)):
            return int(val)
        return str(val).strip().lower()

    # Compare set of rows or sorted rows
    try:
        norm_gen = [tuple(normalize_val(x) for x in row) for row in df_gen.values]
        norm_ref = [tuple(normalize_val(x) for x in row) for row in df_ref.values]
        return sorted(norm_gen, key=str) == sorted(norm_ref, key=str)
    except Exception:
        return False


def run_evaluation(limit: Optional[int] = None, delay_between_requests: float = 4.0):
    settings = get_settings()
    nl2sql_service = get_nl2sql_service()
    query_executor = get_query_executor()

    questions_path = BASE_DIR / "data" / "evaluation" / "questions.json"
    if not questions_path.exists():
        raise FileNotFoundError(f"Reference questions not found at {questions_path}")

    with open(questions_path, "r", encoding="utf-8") as f:
        questions = json.load(f)

    if limit:
        questions = questions[:limit]

    total_questions = len(questions)
    print("=" * 75)
    print("DATASENSE — BASELINE A AUTOMATED EVALUATION")
    print(f"Provider: {settings.llm.provider.upper()} | Model: {settings.llm.model}")
    print(f"Evaluating {total_questions} reference benchmark questions against PostgreSQL...")
    print(f"Rate limiting delay: {delay_between_requests}s per question (to stay under Free Tier 15 RPM)")
    print("=" * 75)

    results = []
    successful_generations = 0
    successful_executions = 0
    correct_results = 0
    total_time = 0.0

    for idx, item in enumerate(questions, 1):
        q_id = item["id"]
        q_text = item["question"]
        ref_sql = item["reference_sql"]
        cat = item.get("category", "general")
        diff = item.get("difficulty", "medium")

        print(f"\n[{idx}/{total_questions}] (ID {q_id}) {q_text}")

        # 1. Execute ground truth reference query
        ref_exec = query_executor.execute(ref_sql)
        df_ref = ref_exec.data if ref_exec.success else None

        # 2. Generate and execute SQL via NL2SQL service
        q_start = time.time()
        nl_resp = nl2sql_service.process_question(q_text, execute=True)
        q_duration = time.time() - q_start
        total_time += q_duration

        gen_sql = nl_resp.sql
        is_gen_ok = nl_resp.status == "success" and gen_sql is not None
        is_exec_ok = is_gen_ok and nl_resp.execution_result is not None and nl_resp.execution_result.success
        df_gen = nl_resp.data if is_exec_ok else None

        # 3. Check result equivalence
        is_accurate = False
        if is_exec_ok and df_ref is not None:
            is_accurate = are_results_equivalent(df_gen, df_ref)

        if is_gen_ok:
            successful_generations += 1
        if is_exec_ok:
            successful_executions += 1
        if is_accurate:
            correct_results += 1

        status_flag = "CORRECT" if is_accurate else ("EXEC_OK (DIFF)" if is_exec_ok else ("GEN_OK (EXEC_FAIL)" if is_gen_ok else "FAIL"))
        print(f"   Status: {status_flag} | Time: {q_duration:.2f}s")
        if gen_sql:
            print(f"   Generated SQL: {gen_sql}")
        if not is_exec_ok and nl_resp.error_message:
            print(f"   Error: {nl_resp.error_message}")

        results.append({
            "id": q_id,
            "question": q_text,
            "category": cat,
            "difficulty": diff,
            "language": item.get("language", "en"),
            "reference_sql": ref_sql,
            "generated_sql": gen_sql,
            "generation_success": is_gen_ok,
            "execution_success": is_exec_ok,
            "execution_accuracy": is_accurate,
            "duration_seconds": round(q_duration, 3),
            "llm_duration_seconds": round(nl_resp.llm_duration_seconds, 3),
            "explanation": nl_resp.explanation,
            "error_message": nl_resp.error_message
        })

        if delay_between_requests > 0 and idx < total_questions:
            time.sleep(delay_between_requests)

    # Metrics calculation
    gen_rate = (successful_generations / total_questions) * 100 if total_questions > 0 else 0.0
    exec_rate = (successful_executions / successful_generations) * 100 if successful_generations > 0 else 0.0
    accuracy_rate = (correct_results / total_questions) * 100 if total_questions > 0 else 0.0
    error_rate = ((total_questions - correct_results) / total_questions) * 100 if total_questions > 0 else 0.0
    avg_response_time = (total_time / total_questions) if total_questions > 0 else 0.0

    report = {
        "evaluation_timestamp": datetime.now().isoformat(),
        "provider": settings.llm.provider,
        "model": settings.llm.model,
        "database": settings.db.name,
        "total_questions": total_questions,
        "successful_generations": successful_generations,
        "successful_executions": successful_executions,
        "correct_results": correct_results,
        "failed_questions": total_questions - correct_results,
        "metrics": {
            "sql_generation_success_rate_percent": round(gen_rate, 2),
            "sql_execution_success_rate_percent": round(exec_rate, 2),
            "execution_accuracy_percent": round(accuracy_rate, 2),
            "error_rate_percent": round(error_rate, 2),
            "average_response_time_seconds": round(avg_response_time, 3)
        },
        "questions": results
    }

    report_dir = BASE_DIR / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "baseline_a_results.json"

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 75)
    print("EVALUATION SUMMARY")
    print("=" * 75)
    print(f"Total Questions Evaluated       : {total_questions}")
    print(f"SQL Generation Success Rate    : {gen_rate:.1f}% ({successful_generations}/{total_questions})")
    print(f"SQL Execution Success Rate     : {exec_rate:.1f}% ({successful_executions}/{successful_generations})")
    print(f"Execution Accuracy (Equivalence): {accuracy_rate:.1f}% ({correct_results}/{total_questions})")
    print(f"Error Rate                     : {error_rate:.1f}%")
    print(f"Average Response Time          : {avg_response_time:.2f}s")
    print(f"Report saved to                : {report_path}")
    print("=" * 75)

    return report


if __name__ == "__main__":
    limit_arg = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run_evaluation(limit=limit_arg)
