
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "olist"
REPORT_DIR = BASE_DIR / "reports"

reviews = pd.read_csv(
    DATA_DIR / "olist_order_reviews_dataset.csv"
)

orders = pd.read_csv(
    DATA_DIR / "olist_orders_dataset.csv"
)

# Associer chaque avis à son client
data = reviews.merge(
    orders[["order_id", "customer_id"]],
    on="order_id",
    how="left"
)

# Identifier les review_id répétés
counts = data["review_id"].value_counts()
repeated_ids = counts[counts > 1].index

repeated = data[data["review_id"].isin(repeated_ids)].copy()

# Analyser chaque groupe de review_id
analysis = repeated.groupby("review_id").agg(
    nombre_lignes=("order_id", "size"),
    nombre_commandes=("order_id", "nunique"),
    nombre_clients=("customer_id", "nunique"),
    nombre_notes=("review_score", "nunique"),
    nombre_commentaires=(
        "review_comment_message",
        lambda x: x.nunique(dropna=False)
    )
).reset_index()

print("=" * 65)
print("DATASENSE - ANALYSE DETAILLEE DES AVIS REPETES")
print("=" * 65)

print("\n1. NOMBRE DE CLIENTS PAR review_id REPETE")
print(analysis["nombre_clients"].value_counts().sort_index())

print("\n2. NOMBRE DE NOTES DIFFERENTES")
print(analysis["nombre_notes"].value_counts().sort_index())

print("\n3. NOMBRE DE COMMENTAIRES DIFFERENTS")
print(analysis["nombre_commentaires"].value_counts().sort_index())

print("\n4. EXEMPLES DE GROUPES AVEC PLUSIEURS CLIENTS")

multiple_customers = analysis[
    analysis["nombre_clients"] > 1
]

print(multiple_customers.head(10).to_string(index=False))

# Export des résultats
REPORT_DIR.mkdir(parents=True, exist_ok=True)

analysis.to_csv(
    REPORT_DIR / "04_reviews_detail.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\nRapport enregistre : reports/04_reviews_detail.csv")
print("\nAnalyse terminee.")
