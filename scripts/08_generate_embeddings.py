from pathlib import Path
import sys
import time

import pandas as pd
from sentence_transformers import SentenceTransformer
from sqlalchemy import text
from pgvector.sqlalchemy import Vector

# Permet d'importer src.db depuis le dossier scripts
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.db import get_engine

# =====================================================
# CONFIGURATION
# =====================================================

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
BATCH_SIZE = 64

engine = get_engine()

# =====================================================
# 1. CHARGEMENT DU MODELE
# =====================================================

print("=" * 60)
print("DATASENSE - GENERATION DES EMBEDDINGS")
print("=" * 60)

print("\nChargement du modèle multilingue...")
model = SentenceTransformer(MODEL_NAME)

dimension = model.get_embedding_dimension()
print(f"Modèle chargé. Dimension : {dimension}")

if dimension != 384:
    raise ValueError(f"Dimension inattendue : {dimension}")

# =====================================================
# 2. RECUPERATION DES COMMENTAIRES NON TRAITES
# =====================================================

query = text("""
    SELECT r.review_id, r.order_id, r.review_comment_message
    FROM order_reviews r
    LEFT JOIN reviews_semantic s
        ON r.review_id = s.review_id
        AND r.order_id = s.order_id
    WHERE NULLIF(BTRIM(r.review_comment_message), '') IS NOT NULL
      AND s.review_id IS NULL
    ORDER BY r.review_id, r.order_id
""")

with engine.connect() as conn:
    df = pd.read_sql(query, conn)

total = len(df)

print(f"\nCommentaires restant à traiter : {total}")

if total == 0:
    print("Tous les commentaires possèdent déjà un embedding.")
    sys.exit(0)

# =====================================================
# 3. GENERATION ET INSERTION PAR LOTS
# =====================================================

insert_query = text("""
    INSERT INTO reviews_semantic
        (review_id, order_id, review_text, embedding)
    VALUES
        (:review_id, :order_id, :review_text, :embedding)
    ON CONFLICT (review_id, order_id) DO NOTHING
""").bindparams(
    # Le type explicite permet à SQLAlchemy de transmettre
    # correctement le vecteur à PostgreSQL.
    __import__("sqlalchemy").bindparam(
        "embedding", type_=Vector(384)
    )
)

start_time = time.time()
processed = 0

print("\nDébut de la génération...\n")

for start in range(0, total, BATCH_SIZE):
    batch = df.iloc[start:start + BATCH_SIZE]

    texts = batch["review_comment_message"].tolist()

    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=False,
        normalize_embeddings=True
    )

    records = []

    for (_, row), embedding in zip(batch.iterrows(), embeddings):
        records.append({
            "review_id": row["review_id"],
            "order_id": row["order_id"],
            "review_text": row["review_comment_message"],
            "embedding": embedding.tolist()
        })

    # Chaque lot est validé séparément : reprise possible
    # si le programme est interrompu.
    with engine.begin() as conn:
        conn.execute(insert_query, records)

    processed += len(records)

    elapsed = time.time() - start_time
    percentage = processed / total * 100

    print(
        f"Progression : {processed}/{total} "
        f"({percentage:.1f} %) | "
        f"Temps : {elapsed:.1f} s"
    )

# =====================================================
# 4. VERIFICATION FINALE
# =====================================================

with engine.connect() as conn:
    count = conn.execute(
        text("SELECT COUNT(*) FROM reviews_semantic")
    ).scalar()

print("\n" + "=" * 60)
print("GENERATION TERMINEE")
print("=" * 60)
print(f"Embeddings enregistrés au total : {count}")
print(f"Durée : {(time.time() - start_time) / 60:.2f} minutes")

engine.dispose()
