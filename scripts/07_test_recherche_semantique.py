
from pathlib import Path
import os
import pandas as pd

from dotenv import load_dotenv
from sqlalchemy import create_engine, URL, text
from sentence_transformers import SentenceTransformer, util

# --------------------------------------------------
# 1. CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

required_variables = [
    "DB_HOST", "DB_PORT", "DB_NAME",
    "DB_USER", "DB_PASSWORD"
]

missing = [v for v in required_variables if not os.getenv(v)]

if missing:
    raise ValueError(f"Variables manquantes dans .env : {missing}")

database_url = URL.create(
    drivername="postgresql+psycopg",
    username=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT")),
    database=os.getenv("DB_NAME")
)

engine = create_engine(database_url)

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
SAMPLE_SIZE = 5000

print("=" * 65)
print("DATASENSE - RECHERCHE SEMANTIQUE SUR LES AVIS OLIST")
print("=" * 65)

# --------------------------------------------------
# 2. RECUPERATION DES COMMENTAIRES
# --------------------------------------------------

print("\nConnexion à PostgreSQL...")

with engine.connect() as connection:
    connection.execute(text("SELECT setseed(0.42)"))

    reviews = pd.read_sql_query(
        text("""
            SELECT
                review_id,
                order_id,
                review_score,
                review_text
            FROM reviews_semantic_source
            ORDER BY RANDOM()
            LIMIT :sample_size
        """),
        connection,
        params={"sample_size": SAMPLE_SIZE}
    )

print(f"Commentaires récupérés : {len(reviews)}")

if reviews.empty:
    raise RuntimeError("Aucun commentaire récupéré.")

# --------------------------------------------------
# 3. CHARGEMENT DU MODELE
# --------------------------------------------------

print("\nChargement du modèle...")

model = SentenceTransformer(
    MODEL_NAME,
    device="cpu"
)

print("Modèle chargé.")

# --------------------------------------------------
# 4. GENERATION DES EMBEDDINGS
# --------------------------------------------------

texts = reviews["review_text"].astype(str).tolist()

print("\nGénération des embeddings des commentaires...")

review_embeddings = model.encode(
    texts,
    batch_size=32,
    show_progress_bar=True,
    convert_to_tensor=True,
    normalize_embeddings=True
)

print("Embeddings des commentaires générés.")
print("Dimensions :", review_embeddings.shape)

# --------------------------------------------------
# 5. QUESTIONS EN FRANCAIS
# --------------------------------------------------

questions = [
    "Quels clients se plaignent d'un retard de livraison ?",
    "Quels clients ont reçu un produit cassé ou endommagé ?",
    "Quels clients sont satisfaits de la qualité du produit ?"
]

# --------------------------------------------------
# 6. RECHERCHE SEMANTIQUE
# --------------------------------------------------

for question in questions:

    print("\n" + "=" * 65)
    print("QUESTION :", question)
    print("=" * 65)

    query_embedding = model.encode(
        [question],
        convert_to_tensor=True,
        normalize_embeddings=True
    )

    similarities = util.cos_sim(
        query_embedding,
        review_embeddings
    )[0]

    top_results = similarities.topk(
        k=min(5, len(reviews))
    )

    for rank, (index, score) in enumerate(
        zip(top_results.indices.tolist(),
            top_results.values.tolist()),
        start=1
    ):
        review = reviews.iloc[index]

        print(f"\nRésultat {rank}")
        print("Similarité :", round(float(score), 4))
        print("Review ID :", review["review_id"])
        print("Order ID :", review["order_id"])
        print("Note :", review["review_score"])
        print("Commentaire :", review["review_text"])

print("\n" + "=" * 65)
print("TEST DE RECHERCHE SEMANTIQUE TERMINE.")
print("=" * 65)

engine.dispose()
