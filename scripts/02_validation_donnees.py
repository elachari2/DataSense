
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "olist"
REPORT_DIR = BASE_DIR / "reports"

# Chargement des cinq tables
customers = pd.read_csv(DATA_DIR / "olist_customers_dataset.csv")
orders = pd.read_csv(DATA_DIR / "olist_orders_dataset.csv")
items = pd.read_csv(DATA_DIR / "olist_order_items_dataset.csv")
payments = pd.read_csv(DATA_DIR / "olist_order_payments_dataset.csv")
reviews = pd.read_csv(DATA_DIR / "olist_order_reviews_dataset.csv")

results = []

def check_unique(df, columns, table_name):
    duplicates = df.duplicated(subset=columns).sum()

    results.append({
        "controle": f"Unicite {table_name} ({', '.join(columns)})",
        "problemes": int(duplicates)
    })

    print(f"{table_name} - doublons sur {columns} : {duplicates}")


def check_foreign_key(child_df, child_column,
                      parent_df, parent_column, relation_name):

    orphan_count = (
        ~child_df[child_column].isin(parent_df[parent_column])
    ).sum()

    results.append({
        "controle": relation_name,
        "problemes": int(orphan_count)
    })

    print(f"{relation_name} : {orphan_count} references orphelines")


print("=" * 65)
print("DATASENSE - VALIDATION DE L'INTEGRITE DES DONNEES")
print("=" * 65)

# 1. Vérification des identifiants uniques
print("\n1. VERIFICATION DES CLES")

check_unique(customers, ["customer_id"], "Customers")
check_unique(orders, ["order_id"], "Orders")
check_unique(items, ["order_id", "order_item_id"], "Order Items")
check_unique(payments, ["order_id", "payment_sequential"], "Payments")
check_unique(reviews, ["review_id"], "Reviews")

# 2. Vérification des relations entre les tables
print("\n2. VERIFICATION DES RELATIONS")

check_foreign_key(
    orders, "customer_id",
    customers, "customer_id",
    "Orders -> Customers"
)

check_foreign_key(
    items, "order_id",
    orders, "order_id",
    "Order Items -> Orders"
)

check_foreign_key(
    payments, "order_id",
    orders, "order_id",
    "Payments -> Orders"
)

check_foreign_key(
    reviews, "order_id",
    orders, "order_id",
    "Reviews -> Orders"
)

# 3. Vérification des notes des avis
print("\n3. VALIDATION DES NOTES")

invalid_scores = (
    ~reviews["review_score"].between(1, 5)
).sum()

print(f"Notes hors intervalle 1-5 : {invalid_scores}")

results.append({
    "controle": "Notes des avis entre 1 et 5",
    "problemes": int(invalid_scores)
})

# 4. Répartition des statuts de commandes
print("\n4. STATUTS DES COMMANDES")

print(orders["order_status"].value_counts().to_string())

# 5. Vérification des dates
print("\n5. VALIDATION DES DATES")

date_columns = [
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date"
]

for column in date_columns:
    parsed = pd.to_datetime(orders[column], errors="coerce")

    invalid_dates = (
        orders[column].notna() & parsed.isna()
    ).sum()

    print(f"{column} - dates invalides : {invalid_dates}")

    results.append({
        "controle": f"Dates invalides - {column}",
        "problemes": int(invalid_dates)
    })

# 6. Disponibilité des commentaires clients
print("\n6. COMMENTAIRES CLIENTS")

non_empty_comments = (
    reviews["review_comment_message"]
    .fillna("")
    .str.strip()
    .ne("")
    .sum()
)

print(f"Commentaires disponibles : {non_empty_comments}")
print(f"Total des avis : {len(reviews)}")

# 7. Export du rapport
REPORT_DIR.mkdir(parents=True, exist_ok=True)

report = pd.DataFrame(results)
report.to_csv(
    REPORT_DIR / "02_integrity_validation.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\n" + "=" * 65)
print("VALIDATION TERMINEE")
print("=" * 65)

print("\nRapport enregistré dans reports/02_integrity_validation.csv")
