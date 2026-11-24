
"""DataSense - Semantic search service using Sentence Transformers and pgvector."""

from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sentence_transformers import SentenceTransformer
from sqlalchemy import bindparam, text

from src.db import get_engine


MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIMENSION = 384


class SemanticSearchService:
    """Generates question embeddings and retrieves similar customer reviews."""

    def __init__(self, engine=None, model=None):
        # Dependencies can be injected to make automated tests independent
        # from the real database and embedding model.
        self.engine = engine
        self.model = model

    def _get_engine(self):
        """Create the database engine only when it is needed."""
        if self.engine is None:
            self.engine = get_engine()
        return self.engine

    def _get_model(self):
        """Load the multilingual model only once."""
        if self.model is None:
            self.model = SentenceTransformer(MODEL_NAME)
        return self.model

    def search(self, question: str, top_k: int = 5) -> list[dict[str, Any]]:
        """
        Search for the most relevant reviews.

        Args:
            question: User question, preferably in French.
            top_k: Maximum number of reviews to return.

        Returns:
            A list of dictionaries containing review_id, order_id,
            review_text and similarity.
        """
        if not isinstance(question, str) or not question.strip():
            raise ValueError("La question ne peut pas être vide.")

        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise ValueError("top_k doit être un entier supérieur ou égal à 1.")

        model = self._get_model()

        encoded = model.encode(
            question.strip(),
            normalize_embeddings=True
        )

        embedding = encoded.tolist() if hasattr(encoded, "tolist") else list(encoded)

        sql = text("""
            SELECT
                review_id,
                order_id,
                review_text,
                1 - (embedding <=> :embedding) AS similarity
            FROM reviews_semantic
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> :embedding
            LIMIT :top_k
        """).bindparams(
            bindparam("embedding", type_=Vector(EMBEDDING_DIMENSION)),
            bindparam("top_k")
        )

        engine = self._get_engine()

        with engine.connect() as conn:
            rows = conn.execute(
                sql,
                {
                    "embedding": embedding,
                    "top_k": top_k
                }
            ).fetchall()

        return [
            {
                "review_id": row.review_id,
                "order_id": row.order_id,
                "review_text": row.review_text,
                "similarity": float(row.similarity)
            }
            for row in rows
        ]


_semantic_search_instance: Optional[SemanticSearchService] = None


def get_semantic_search_service() -> SemanticSearchService:
    """Return the shared semantic search service instance."""
    global _semantic_search_instance

    if _semantic_search_instance is None:
        _semantic_search_instance = SemanticSearchService()

    return _semantic_search_instance
