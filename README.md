# DataSense

Assistant d'analyse de données Olist : NL2SQL et recherche sémantique (PostgreSQL, pgvector, Streamlit).

## Prérequis

- Python 3.12 (3.14 non recommandé pour les embeddings)
- Docker Desktop

## Installation

1. `py -3.12 -m venv .venv` puis `.venv\Scripts\Activate.ps1`
2. `pip install -r requirements.txt`
3. Copier `.env.example` en `.env`
4. `docker compose up -d`
5. `docker exec -it datasense_db psql -U postgres -d datasense -c "CREATE EXTENSION IF NOT EXISTS vector;"`
6. `python -m src.db` (doit afficher la version PostgreSQL et True)
7. `streamlit run app.py`

## Structure

- `app.py` : interface Streamlit (import et aperçu CSV, état de la base)
- `src/db.py` : connexion Python/PostgreSQL
- `docker-compose.yml` : PostgreSQL 16 + pgvector (port 5544)
- `data/raw/` : fichiers Olist (non suivis par Git)

## Choix technologiques (présélection)

- LLM : API gratuite Groq (Llama 3.3 70B), Gemini en alternative
- Embeddings : paraphrase-multilingual-MiniLM-L12-v2 (384 dimensions)
