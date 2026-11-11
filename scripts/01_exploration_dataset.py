
from pathlib import Path
import pandas as pd

# 1. Définition des chemins
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "olist"
REPORT_DIR = BASE_DIR / "reports"

REPORT_DIR.mkdir(parents=True, exist_ok=True)

# 2. Fichiers à explorer
FILES = [
    "olist_customers_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
]

# 3. Stockage des résultats du profilage
summary = []
missing_values = []

print("=" * 70)
print("             DATASENSE - EXPLORATION DU DATASET OLIST")
print("=" * 70)

# 4. Exploration de chaque fichier
for filename in FILES:

    file_path = DATA_DIR / filename

    print(f"\n\n{'=' * 70}")
    print(f"FICHIER : {filename}")
    print("=" * 70)

    if not file_path.exists():
        print("ERREUR : fichier introuvable.")
        continue

    try:
        # Chargement du fichier CSV
        df = pd.read_csv(file_path, encoding="utf-8", low_memory=False)

        # Informations générales
        rows, columns = df.shape

        print(f"\nNombre de lignes : {rows}")
        print(f"Nombre de colonnes : {columns}")
        print(f"Taille du fichier : {file_path.stat().st_size / (1024 * 1024):.2f} MB")

        # Noms et types des colonnes
        print("\n--- COLONNES ET TYPES ---")
        print(df.dtypes.to_string())

        # Valeurs manquantes
        print("\n--- VALEURS MANQUANTES ---")

        null_counts = df.isnull().sum()

        for column, count in null_counts.items():
            if count > 0:
                percentage = (count / rows) * 100

                print(f"{column}: {count} ({percentage:.2f} %)")

                missing_values.append({
                    "fichier": filename,
                    "colonne": column,
                    "valeurs_manquantes": count,
                    "pourcentage": round(percentage, 2)
                })

        if null_counts.sum() == 0:
            print("Aucune valeur manquante.")

        # Doublons
        duplicates = df.duplicated().sum()

        print(f"\nNombre de lignes dupliquées : {duplicates}")

        # Aperçu des premières lignes
        print("\n--- APERÇU DES 5 PREMIÈRES LIGNES ---")
        print(df.head().to_string(index=False))

        # Enregistrement du résumé
        summary.append({
            "fichier": filename,
            "nombre_lignes": rows,
            "nombre_colonnes": columns,
            "lignes_dupliquees": duplicates,
            "valeurs_manquantes_total": int(null_counts.sum())
        })

    except Exception as error:
        print(f"ERREUR pendant l'exploration : {error}")

# 5. Export des rapports
summary_df = pd.DataFrame(summary)
summary_df.to_csv(
    REPORT_DIR / "01_profiling_summary.csv",
    index=False,
    encoding="utf-8-sig"
)

missing_df = pd.DataFrame(missing_values)
missing_df.to_csv(
    REPORT_DIR / "01_missing_values.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\n\n" + "=" * 70)
print("EXPLORATION TERMINÉE")
print("=" * 70)

print("\nRésumé général :")
print(summary_df.to_string(index=False))

print("\nRapports enregistrés dans :", REPORT_DIR)
