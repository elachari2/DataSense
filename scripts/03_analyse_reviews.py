
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "olist"
REPORT_DIR = BASE_DIR / "reports"

reviews = pd.read_csv(
    DATA_DIR / "olist_order_reviews_dataset.csv"
)

print("=" * 65)
print("DATASENSE - ANALYSE DES REPETITIONS DANS REVIEWS")
print("=" * 65)

# 1. Identifier les review_id répétés
counts = reviews["review_id"].value_counts()
repeated_ids = counts[counts > 1]

print("\n1. REPETITION DES IDENTIFIANTS")
print(f"Nombre total d'avis : {len(reviews)}")
print(f"Nombre de review_id uniques : {reviews['review_id'].nunique()}")
print(f"Nombre de review_id répétés : {len(repeated_ids)}")
print(f"Nombre de lignes supplémentaires : {repeated_ids.sum() - len(repeated_ids)}")

# 2. Vérifier les lignes entièrement identiques
exact_duplicates = reviews.duplicated().sum()

print("\n2. DOUBLONS COMPLETS")
print(f"Nombre de lignes entièrement identiques : {exact_duplicates}")

# 3. Vérifier si un review_id est associé à plusieurs commandes
orders_per_review = reviews.groupby("review_id")["order_id"].nunique()

multiple_orders = orders_per_review[orders_per_review > 1]

print("\n3. ASSOCIATION AUX COMMANDES")
print(f"review_id associés à plusieurs commandes : {len(multiple_orders)}")

# 4. Vérifier l'unicité de la combinaison review_id + order_id
duplicate_pairs = reviews.duplicated(
    subset=["review_id", "order_id"]
).sum()

print("\n4. UNICITE DE LA COMBINAISON")
print(f"Répétitions de (review_id, order_id) : {duplicate_pairs}")

# 5. Afficher quelques exemples
print("\n5. EXEMPLES DE review_id REPETES")

if not repeated_ids.empty:
    sample_ids = repeated_ids.head(5).index

    sample = reviews[
        reviews["review_id"].isin(sample_ids)
    ].sort_values(["review_id", "order_id"])

    columns = [
        "review_id",
        "order_id",
        "review_score",
        "review_comment_title",
        "review_comment_message",
        "review_creation_date",
        "review_answer_timestamp"
    ]

    print(sample[columns].to_string(index=False))
else:
    print("Aucune répétition.")

# 6. Exporter les résultats détaillés
REPORT_DIR.mkdir(parents=True, exist_ok=True)

if not repeated_ids.empty:
    repeated_rows = reviews[
        reviews["review_id"].isin(repeated_ids.index)
    ]

    repeated_rows.to_csv(
        REPORT_DIR / "03_repeated_reviews.csv",
        index=False,
        encoding="utf-8-sig"
    )

print("\nAnalyse terminée.")
print("Rapport enregistré dans reports/03_repeated_reviews.csv")
