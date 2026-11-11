
from pathlib import Path
import os
import pandas as pd

from dotenv import load_dotenv
from sqlalchemy import create_engine, URL, text

# =====================================================
# 1. CONFIGURATION
# =====================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "olist"

load_dotenv(BASE_DIR / ".env")

required_variables = [
    "DB_HOST", "DB_PORT", "DB_NAME",
    "DB_USER", "DB_PASSWORD"
]

missing = [v for v in required_variables if not os.getenv(v)]

if missing:
    raise ValueError(
        f"Variables manquantes dans .env : {missing}"
    )

database_url = URL.create(
    drivername="postgresql+psycopg",
    username=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT")),
    database=os.getenv("DB_NAME")
)

engine = create_engine(database_url)

# =====================================================
# 2. ORDRE D'IMPORTATION
# =====================================================

FILES = [
    ("olist_customers_dataset.csv", "customers"),
    ("olist_orders_dataset.csv", "orders"),
    ("olist_order_items_dataset.csv", "order_items"),
    ("olist_order_payments_dataset.csv", "order_payments"),
    ("olist_order_reviews_dataset.csv", "order_reviews"),
]

DATE_COLUMNS = {
    "orders": [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date"
    ],
    "order_items": ["shipping_limit_date"],
    "order_reviews": [
        "review_creation_date",
        "review_answer_timestamp"
    ]
}

INTEGER_COLUMNS = {
    "order_items": ["order_item_id"],
    "order_payments": [
        "payment_sequential",
        "payment_installments"
    ],
    "order_reviews": ["review_score"]
}

# =====================================================
# 3. VERIFICATION DES TABLES
# =====================================================

print("=" * 65)
print("DATASENSE - IMPORTATION VERS POSTGRESQL")
print("=" * 65)

with engine.connect() as connection:
    print("\nConnexion à PostgreSQL...")

    connection.execute(text("SELECT 1"))
    print("Connexion réussie.")

    existing_rows = {}

    for filename, table_name in FILES:
        count = connection.execute(
            text(f'SELECT COUNT(*) FROM "{table_name}"')
        ).scalar_one()

        existing_rows[table_name] = count

    if any(count > 0 for count in existing_rows.values()):
        raise RuntimeError(
            "Au moins une table contient déjà des données. "
            "Importation annulée pour éviter les doublons."
        )

# =====================================================
# 4. IMPORTATION PAR LOTS
# =====================================================

imported_counts = {}

try:
    with engine.begin() as connection:

        for filename, table_name in FILES:

            file_path = DATA_DIR / filename

            print(f"\n{'-' * 65}")
            print(f"Fichier : {filename}")
            print(f"Table cible : {table_name}")

            if not file_path.exists():
                raise FileNotFoundError(file_path)

            total_rows = 0

            # Lecture par lots de 5 000 lignes
            for chunk in pd.read_csv(
                file_path,
                chunksize=5000,
                encoding="utf-8",
                low_memory=False
            ):

                # Conversion des dates
                for column in DATE_COLUMNS.get(table_name, []):
                    chunk[column] = pd.to_datetime(
                        chunk[column],
                        errors="coerce"
                    )

                # Conversion des entiers avec gestion des NULL
                for column in INTEGER_COLUMNS.get(table_name, []):
                    values = pd.to_numeric(
                        chunk[column],
                        errors="coerce"
                    )

                    chunk[column] = values.map(
                        lambda value: (
                            int(value) if pd.notna(value) else None
                        )
                    )

                # Insertion dans PostgreSQL
                chunk.to_sql(
                    name=table_name,
                    con=connection,
                    if_exists="append",
                    index=False,
                    chunksize=1000
                )

                total_rows += len(chunk)

                print(f"Lignes importées : {total_rows}")

            imported_counts[table_name] = total_rows

            print(
                f"Importation terminée : {total_rows} lignes."
            )

    print("\nTransaction validée.")

except Exception:
    print("\nERREUR : importation interrompue.")
    print("La transaction a été annulée.")
    raise

# =====================================================
# 5. VERIFICATION DES VOLUMES
# =====================================================

print("\n" + "=" * 65)
print("VERIFICATION DES DONNEES DANS POSTGRESQL")
print("=" * 65)

with engine.connect() as connection:

    for filename, table_name in FILES:

        database_count = connection.execute(
            text(f'SELECT COUNT(*) FROM "{table_name}"')
        ).scalar_one()

        print(
            f"{table_name}: "
            f"{database_count} lignes en base"
        )

        if database_count != imported_counts[table_name]:
            print("ATTENTION : différence de volume détectée.")
        else:
            print("OK : volume conforme.")

print("\nIMPORTATION TERMINEE.")
engine.dispose()
