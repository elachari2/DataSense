
import json

with open("reports/baseline_a_results.json") as f:
    data = json.load(f)

meta = data.get("metadata", {})
summary = data.get("summary", {})
results = data.get("results", [])

print("=== BASELINE A RESULTS VALIDATION ===")
print(f"Total questions evaluated: {len(results)}")
print(f"Metadata run_date: {meta.get('run_date', 'N/A')}")
print(f"Metadata model: {meta.get('model', 'N/A')}")
print(f"Metadata total_questions: {meta.get('total_questions', 'N/A')}")

print("\nSummary:")
for k, v in summary.items():
    print(f"  {k}: {v}")

# Count outcomes
gen_ok = sum(1 for r in results if r.get("sql_generated"))
exec_ok = sum(1 for r in results if r.get("execution_success"))
correct = sum(1 for r in results if r.get("result_match") == "EXACT_MATCH")
diff = sum(1 for r in results if r.get("result_match") == "EXEC_OK (DIFF)")
exec_error = sum(1 for r in results if r.get("result_match") == "EXEC_ERROR")
gen_fail = sum(1 for r in results if not r.get("sql_generated"))

print(f"\nComputed metrics:")
print(f"  SQL Generated:        {gen_ok}/30 ({gen_ok/30*100:.1f}%)")
print(f"  Execution Success:    {exec_ok}/30 ({exec_ok/30*100:.1f}%)")
print(f"  EXACT_MATCH:          {correct}/30 ({correct/30*100:.1f}%)")
print(f"  EXEC_OK (DIFF):       {diff}/30 ({diff/30*100:.1f}%)")
print(f"  EXEC_ERROR:           {exec_error}/30 ({exec_error/30*100:.1f}%)")
print(f"  Generation Failures:  {gen_fail}/30 ({gen_fail/30*100:.1f}%)")

print("\nDIFF cases (questions where result differs from reference):")
for r in results:
    if r.get("result_match") == "EXEC_OK (DIFF)":
        print(f"  Q{r['id']}: {r.get('question', '')[:60]}")
        print(f"    Generated SQL: {r.get('generated_sql', 'N/A')[:100]}")
        print(f"    Ref SQL: {r.get('reference_sql', 'N/A')[:100]}")

print("\nFailed cases:")
for r in results:
    if r.get("result_match") not in ("EXACT_MATCH", "EXEC_OK (DIFF)"):
        print(f"  Q{r['id']}: {r.get('question', '')[:60]}")
        print(f"    Result: {r.get('result_match')}, Error: {r.get('error_message', 'N/A')[:100]}")
