
import json

with open("reports/baseline_a_results.json") as f:
    data = json.load(f)

print("=== BASELINE A RESULTS VALIDATION ===")
print(f"Evaluation Timestamp: {data.get('evaluation_timestamp')}")
print(f"Provider: {data.get('provider')}")
print(f"Model: {data.get('model')}")
print(f"Database: {data.get('database')}")
print(f"Total Questions: {data.get('total_questions')}")
print(f"Successful Generations: {data.get('successful_generations')}")
print(f"Successful Executions: {data.get('successful_executions')}")
print(f"Correct Results: {data.get('correct_results')}")
print(f"Failed Questions: {data.get('failed_questions')}")

metrics = data.get("metrics", {})
print("\nMetrics:")
for k, v in metrics.items():
    print(f"  {k}: {v}")

questions = data.get("questions", [])
print(f"\nTotal question records: {len(questions)}")

# Verify math
gen_rate = data["successful_generations"] / data["total_questions"] * 100
exec_rate = data["successful_executions"] / data["total_questions"] * 100
acc_rate = data["correct_results"] / data["total_questions"] * 100

print(f"\nMath verification:")
print(f"  Generation rate: {gen_rate:.2f}% (reported: {metrics.get('sql_generation_success_rate_percent')})")
print(f"  Execution rate:  {exec_rate:.2f}% (reported: {metrics.get('sql_execution_success_rate_percent')})")
print(f"  Accuracy:        {acc_rate:.2f}% (reported: {metrics.get('execution_accuracy_percent')})")

# Check divergent cases
print("\nAll question outcomes:")
correct_count = 0
exec_ok_count = 0
for q in questions:
    is_correct = q.get("correct")
    exec_ok = q.get("execution_success")
    if exec_ok:
        exec_ok_count += 1
    if is_correct:
        correct_count += 1
    else:
        print(f"  Q{q['id']} [{q['category']}]: correct={is_correct}, exec_ok={exec_ok}")
        print(f"    Q: {q['question'][:70]}")
        gen_sql = q.get("generated_sql", "N/A")
        ref_sql = q.get("reference_sql", "N/A")
        print(f"    Gen SQL: {gen_sql[:100]}")
        print(f"    Ref SQL: {ref_sql[:100]}")
        err = q.get("error")
        if err:
            print(f"    Error: {err}")

print(f"\nManual count - Correct: {correct_count}/30, Exec OK: {exec_ok_count}/30")
