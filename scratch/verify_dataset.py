
import json

with open("data/evaluation/questions.json") as f:
    qs = json.load(f)

print(f"Total questions: {len(qs)}")
ids = [q["id"] for q in qs]
print(f"ID range: {min(ids)} - {max(ids)}")
print(f"Duplicate IDs: {len(ids) - len(set(ids))}")

langs = {}
cats = {}
diffs = {}
for q in qs:
    langs[q["language"]] = langs.get(q["language"], 0) + 1
    cats[q["category"]] = cats.get(q["category"], 0) + 1
    diffs[q["difficulty"]] = diffs.get(q["difficulty"], 0) + 1

print(f"Languages: {langs}")
print(f"Categories: {cats}")
print(f"Difficulties: {diffs}")

# Validate required fields
required = ["id", "question", "language", "category", "difficulty", "reference_sql", "expected_tables"]
missing_fields = []
for q in qs:
    for field in required:
        if field not in q:
            qid = q.get("id", "?")
            missing_fields.append(f"Q{qid} missing {field}")
print(f"Missing fields: {missing_fields if missing_fields else 'NONE'}")

# Check reference SQL all start with SELECT
bad_sql = [q["id"] for q in qs if not q["reference_sql"].strip().upper().startswith("SELECT")]
print(f"Non-SELECT reference SQL: {bad_sql if bad_sql else 'NONE'}")

# Categories breakdown
print("\nCategory breakdown:")
for cat, cnt in sorted(cats.items()):
    print(f"  {cat}: {cnt}")
