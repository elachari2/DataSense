
"""
NL2SQL End-to-End verification: 10 live questions through the full pipeline.
"""
import sys
import time

sys.path.insert(0, ".")

from backend.services.nl2sql_service import get_nl2sql_service

svc = get_nl2sql_service()

questions = [
    # EN simple aggregation
    "How many orders were placed?",
    # FR simple aggregation
    "Combien de commandes au total ont été passées ?",
    # EN aggregation with join
    "What is the total revenue from product sales?",
    # EN filter
    "How many orders have been delivered?",
    # FR filter
    "Combien de commandes ont été annulées ?",
    # EN temporal
    "How many orders were delivered in 2018?",
    # EN GROUP BY
    "What is the distribution of orders by status?",
    # EN ranking / TOP N
    "Which Brazilian states have the highest number of customers?",
    # FR ranking with revenue
    "Quels sont les 5 vendeurs ayant généré le plus de chiffre d'affaires ?",
    # EN multi-table join
    "What is the average review score for delivered orders?",
]

print("=== NL2SQL END-TO-END PIPELINE VERIFICATION ===\n")
pass_count = 0
for i, q in enumerate(questions, 1):
    print(f"Q{i}: {q}")
    r = svc.process_question(q, execute=True)
    generated_sql = r.sql or "NONE"
    exec_ok = r.execution_result.success if r.execution_result else False
    row_count = r.execution_result.row_count if r.execution_result else 0
    duration = r.total_duration_seconds
    
    print(f"  Status  : {r.status}")
    print(f"  SQL     : {generated_sql[:100]}")
    print(f"  Exec OK : {exec_ok} | Rows: {row_count} | Time: {duration:.2f}s")
    if r.error_message:
        print(f"  ERROR   : {r.error_message}")
    if r.schema_linking:
        print(f"  Tables  : {r.schema_linking.relevant_tables}")
        print(f"  Ops     : {r.schema_linking.detected_operations}")
    print()
    
    if r.status in ("success",) and exec_ok:
        pass_count += 1
    
    time.sleep(4)  # Rate limit: 15 RPM free tier

print(f"=== RESULT: {pass_count}/{len(questions)} pipeline runs PASSED (status=success + exec_ok) ===")
