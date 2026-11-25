CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.reviews_semantic (
    review_id VARCHAR(50) NOT NULL,
    order_id VARCHAR(50) NOT NULL,
    review_text TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    PRIMARY KEY (review_id, order_id),
    CONSTRAINT fk_reviews_semantic_order_review
        FOREIGN KEY (review_id, order_id)
        REFERENCES public.order_reviews (review_id, order_id)
);

CREATE INDEX IF NOT EXISTS reviews_semantic_embedding_cosine_idx
    ON public.reviews_semantic
    USING hnsw (embedding vector_cosine_ops);
