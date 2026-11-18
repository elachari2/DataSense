from pathlib import Path
import sys

from sentence_transformers import SentenceTransformer
from sqlalchemy import text
from pgvector.sqlalchemy import Vector

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.db import get_engine

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

QUESTION = input("\nSaisissez votre question en français : ").strip()

if not QUESTION:
    raise ValueError("La question ne peut pas être vide.")
print("=" * 65)
print("DATASENSE - TEST DE RECHERCHE SEMANTIQUE AVEC PGVECTOR")
print("=" * 65)

print("\nChargement du modèle...")
model = SentenceTransformer(MODEL_NAME)

print("\nQuestion :", QUESTION)

query_embedding = model.encode(
    QUESTION,
    normalize_embeddings=True
).tolist()

engine = get_engine()

sql = text("""
    SELECT
        review_id,
        order_id,
        review_text,
        1 - (embedding <=> :embedding) AS similarity
    FROM reviews_semantic
    WHERE embedding IS NOT NULL
    ORDER BY embedding <=> :embedding
    LIMIT 5
""").bindparams(
    __import__("sqlalchemy").bindparam(
        "embedding",
        type_=Vector(384)
    )
)

with engine.connect() as conn:
    results = conn.execute(
        sql,
        {"embedding": query_embedding}
    ).fetchall()

print("\nTOP 5 COMMENTAIRES LES PLUS PERTINENTS")
print("-" * 65)

for i, row in enumerate(results, 1):
    print(f"\n{i}. Similarité : {row.similarity:.4f}")
    print(f"Commentaire : {row.review_text}")
    print(f"Review ID : {row.review_id}")

engine.dispose()

print("\nRecherche terminée.")
