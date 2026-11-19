
"""
DataSense - Baseline A Evaluation V2
Re-evaluates stored SQL queries without calling the LLM.
Keeps the original evaluation report unchanged.
"""

import json
import logging
import re
import sys
from pathlib import Path
from decimal import Decimal

import pandas as pd

# Ensure project root is importable
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.database.query_executor import get_query_executor

REPORT_PATH = BASE_DIR / "reports" / "baseline_a_results.json"
OUTPUT_PATH = BASE_DIR / "reports" / "baseline_a_v2_results.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def normalize_value(value):
    """Normalize scalar values for comparison."""
    if pd.isna(value):
        return None

    if hasattr(value, "item"):
        value = value.item()

    if isinstance(value, (int, float, Decimal)):
        return round(float(value), 2)

    return str(value).strip().lower()


def normalize_dataframe(df):
    """Normalize a dataframe while preserving its columns."""
    if df is None:
        return None

    result = df.copy()
    result.columns = [str(c).strip().lower() for c in result.columns]

    for col in result.columns:
        result[col] = result[col].map(normalize_value)

    return result


def rows_as_sorted_tuples(df):
    """Convert dataframe rows to sortable normalized tuples."""
    if df is None:
        return None

    rows = [tuple(row) for row in df.itertuples(index=False, name=None)]
    return sorted(rows, key=lambda row: repr(row))


def compare_results(reference_df, generated_df):
    """
    Compare outputs without requiring identical column names or column count.
    Each reference column must match one distinct generated column.
    Extra generated columns are allowed.
    Row order is ignored.
    """
    if reference_df is None or generated_df is None:
        return False, "Missing result dataframe"

    if len(reference_df) != len(generated_df):
        return False, (
            f"Different row counts: reference={len(reference_df)}, "
            f"generated={len(generated_df)}"
        )

    if len(reference_df.columns) > len(generated_df.columns):
        return False, "Generated result has fewer columns than reference"

    ref = normalize_dataframe(reference_df)
    gen = normalize_dataframe(generated_df)

    # For each reference column, find one unused generated column
    # with identical values, ignoring row order.
    available = set(range(len(gen.columns)))

    for ref_col in ref.columns:
        ref_values = sorted(
            ref[ref_col].tolist(), key=repr
        )
        match = None

        for gen_index in available:
            gen_col = gen.columns[gen_index]
            gen_values = sorted(
                gen[gen_col].tolist(), key=repr
            )
            if ref_values == gen_values:
                match = gen_index
                break

        if match is None:
            return False, f"No matching generated column for '{ref_col}'"

        available.remove(match)

    return True, "All reference columns matched; extra columns allowed"


def classify_sql_issue(question_id, generated_sql):
    """
    Flag known logical risks identified during manual audit.
    This is a review flag, not an automatic SQL semantic proof.
    """
    sql = re.sub(r"\s+", " ", generated_sql or "").lower()

    known_issues = {
        3: (
            "Check COUNT(*) versus COUNT(DISTINCT customer_unique_id): "
            "the benchmark asks for customer rows."
        ),
        16: (
            "Check COUNT(DISTINCT customer_unique_id) versus COUNT(*): "
            "the reference counts customer records by state."
        ),
        17: (
            "Check the COUNT expression and missing LIMIT 5."
        ),
        19: (
            "Manual review: ordering individual item prices may match this "
            "dataset's top five, but does not implement MAX(price) per product."
        ),
    }

    if question_id == 3 and "distinct" in sql:
        return known_issues[3]
    if question_id == 16 and "distinct" in sql:
        return known_issues[16]
    if question_id == 17 and "limit 5" not in sql:
        return known_issues[17]
    if question_id == 19:
        if "group by" not in sql or "max(" not in sql:
            return known_issues[19]

    return None


def main():
    if not REPORT_PATH.exists():
        raise FileNotFoundError(f"Report not found: {REPORT_PATH}")

    with REPORT_PATH.open("r", encoding="utf-8") as file:
        original_report = json.load(file)

    questions = original_report.get("questions", [])
    if not questions:
        raise ValueError("No evaluation questions found in original report")

    executor = get_query_executor()

    results = []
    successful_executions = 0
    correct = 0
    failed_executions = 0

    print("=" * 70)
    print("DATASENSE - BASELINE A EVALUATION V2")
    print("=" * 70)
    print(f"Questions: {len(questions)}")
    print("LLM calls: 0")
    print("Original report will not be modified.")
    print()

    for item in questions:
        qid = item.get("id")
        question = item.get("question", "")
        reference_sql = item.get("reference_sql")
        generated_sql = item.get("generated_sql")

        print(f"[Q{qid}] {question}")

        reference_result = executor.execute(reference_sql) if reference_sql else None
        generated_result = executor.execute(generated_sql) if generated_sql else None

        reference_ok = bool(reference_result and reference_result.success)
        generated_ok = bool(generated_result and generated_result.success)

        is_correct = False
        comparison_message = "Execution failed"

        if reference_ok and generated_ok:
            successful_executions += 1
            is_correct, comparison_message = compare_results(
                reference_result.data,
                generated_result.data
            )
            if is_correct:
                correct += 1
        else:
            successful_executions += 1
            if not reference_ok:
                comparison_message = (
                    "Reference SQL error: "
                    + str(reference_result.error_message if reference_result else "Missing SQL")
                )
            else:
                comparison_message = (
                    "Generated SQL error: "
                    + str(generated_result.error_message if generated_result else "Missing SQL")
                )

        logic_review = classify_sql_issue(qid, generated_sql)

        print(f"  Reference execution: {'OK' if reference_ok else 'FAILED'}")
        print(f"  Generated execution: {'OK' if generated_ok else 'FAILED'}")
        print(f"  Result comparison: {'PASS' if is_correct else 'FAIL'}")
        print(f"  Details: {comparison_message}")
        if logic_review:
            print(f"  LOGIC REVIEW: {logic_review}")
        print()

        results.append({
            "id": qid,
            "question": question,
            "reference_sql": reference_sql,
            "generated_sql": generated_sql,
            "reference_execution_success": reference_ok,
            "generated_execution_success": generated_ok,
            "result_accuracy": is_correct,
            "comparison_message": comparison_message,
            "logic_review": logic_review,
        })

    total = len(questions)
    report = {
        "evaluation_version": "2.0",
        "evaluation_method": (
            "Re-execution of stored SQL queries; no LLM calls. "
            "Reference columns are matched by values; extra generated columns allowed."
        ),
        "original_report": str(REPORT_PATH.relative_to(BASE_DIR)),
        "total_questions": total,
        "successful_executions": successful_executions,
        "failed_executions": failed_executions,
	"successful_comparisons": correct,
	"incorrect_comparisons": total - correct,
	"correct_results": correct,
        "result_accuracy_percent": round(correct / total * 100, 2) if total else 0,
        "questions": results,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    print("=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(f"Total questions       : {total}")
    print(f"Successful executions : {successful_executions}")
    print(f"Successful comparisons: {correct}")
    print(f"Failed executions     : {failed_executions}")
    print(f"Correct results       : {correct}/{total}")
    print(f"Result accuracy       : {report['result_accuracy_percent']}%")
    print(f"Report saved to       : {OUTPUT_PATH}")
    print()
    print("IMPORTANT: Result accuracy is dataset-specific.")
    print("Logic review flags require human verification.")


if __name__ == "__main__":
    main()
