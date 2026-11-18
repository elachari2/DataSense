# DataSense — Assistant Intelligent d'Analyse de Données Olist

DataSense est une plateforme analytique avancée permettant d'interroger une base de données e-commerce relationnelle (**Olist**) en langage naturel grâce à l'intelligence artificielle (**Google Gemini API**) et **PostgreSQL**.

L'application transforme automatiquement les questions posées en français ou en anglais en requêtes SQL PostgreSQL valides, les sécurise, les exécute sur la base de données, et restitue les résultats sous forme tabulaire et graphique au sein d'une interface conversationnelle **Streamlit**.

---

## 1. Architecture du Projet (Sprint 3 — Baseline A)

```
DataSense/
├── app.py                              # Application interactive Streamlit (NL2SQL + Profilage CSV)
├── docker-compose.yml                  # Conteneur PostgreSQL 16 avec extension pgvector (port 5544)
├── requirements.txt                    # Dépendances Python déclarées
├── .env.example                        # Modèle de variables d'environnement
├── backend/                            # Architecture Backend modulaire
│   ├── config/
│   │   └── settings.py                 # Configuration centralisée (DB, LLM Gemini, Timeouts)
│   ├── database/
│   │   └── query_executor.py           # Exécution SQL sécurisée, transactions READ ONLY, timeouts
│   └── services/
│       ├── llm_service.py              # Intégration officielle SDK google-genai, backoff & gestion 429
│       ├── schema_linking.py           # Introspection dynamique SQLAlchemy & Schema Linking
│       └── nl2sql_service.py           # Pipeline complet NL2SQL (Prompts, Génération, Validation, Exécution)
├── data/
│   ├── evaluation/
│   │   └── questions.json              # Benchmark de 30 questions de référence (FR & EN)
│   └── test_orders.csv                 # Données de test initiales
├── reports/
│   └── baseline_a_results.json         # Rapport automatisé de performance de la Baseline A
├── scripts/
│   ├── evaluate_baseline_a.py          # Script d'évaluation automatisé (taux de succès, exactitude, temps)
│   ├── seed_demo_data.py               # Générateur de données réalistes d'évaluation
│   └── 01_ à 09_*.py                   # Scripts Data Engineering & Sémantique (Responsable A)
├── sql/
│   ├── 01_analyses_metier.sql          # Requêtes SQL analytiques de référence
│   └── 05_create_schema.sql            # Script DDL de création des 5 tables relationnelles
├── src/
│   └── db.py                           # Connecteur SQLAlchemy initial et test de connectivité
└── tests/                              # Suite de tests automatisés pytest
    ├── test_settings.py
    ├── test_llm_service.py
    ├── test_schema_linking.py
    ├── test_query_executor.py
    ├── test_nl2sql_service.py
    └── test_baseline_evaluation.py
```

---

## 2. Prérequis

- **Python :** 3.12 (recommandé)
- **Docker Desktop :** Actif pour le conteneur PostgreSQL + pgvector
- **Clé API Google Gemini :** Créée via [Google AI Studio](https://aistudio.google.com/app/api-keys)

---

## 3. Installation et Configuration

### Étape 1 : Cloner le dépôt et créer l'environnement virtuel

```powershell
# Cloner et se positionner dans le dossier
cd DataSense

# Créer et activer l'environnement virtuel Python 3.12
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

# Installer les dépendances
pip install -r requirements.txt
```

### Étape 2 : Configurer les variables d'environnement

Copiez `.env.example` vers `.env` et renseignez votre clé API Gemini :

```ini
DB_HOST=localhost
DB_PORT=5544
DB_NAME=datasense
DB_USER=postgres
DB_PASSWORD=postgres

# Configuration LLM Gemini
LLM_PROVIDER=gemini
LLM_API_KEY=VOTRE_CLE_API_GEMINI_ICI
LLM_MODEL=gemini-3.1-flash-lite
LLM_TEMPERATURE=0.0
LLM_MAX_OUTPUT_TOKENS=1024
```

### Étape 3 : Démarrer la base de données PostgreSQL

```powershell
# Lancer le conteneur Docker PostgreSQL 16 + pgvector
docker compose up -d

# Activer l'extension pgvector
docker exec -it datasense_db psql -U postgres -d datasense -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Vérifier la connexion
python -m src.db
```

### Étape 4 : Initialiser le schéma et les données de test

```powershell
# Créer les 5 tables relationnelles (customers, orders, order_items, order_payments, order_reviews)
python -c "from src.db import get_engine; from sqlalchemy import text; engine = get_engine(); sql = open('sql/05_create_schema.sql', encoding='utf-8').read(); [conn.execute(text(s)) for s in sql.split(';') if s.strip()]"

# Peupler la base avec des données réalistes pour l'évaluation
python scripts/seed_demo_data.py
```

---

## 4. Démarrage de l'Application Streamlit

```powershell
streamlit run app.py
```

L'application s'ouvre sur `http://localhost:8501` et propose :
1. **Assistant NL2SQL (Olist) :** Saisie libre de questions en français ou en anglais, exemples rapides pré-configurés, affichage du SQL généré, métriques de temps de réponse, tableau interactif et visualisation graphique automatique.
2. **Import & Profilage CSV :** Outil de diagnostic rapide pour inspecter n'importe quel fichier CSV local.

---

## 5. Exécution des Tests Automatisés

La suite de 30 tests unitaires et d'intégration couvre l'intégralité du pipeline backend :

```powershell
pytest -v
```

Tests inclus :
- `test_settings.py` : Validation de la configuration et des variables d'environnement.
- `test_query_executor.py` : Contrôle de sécurité (rejet des injections `DROP`, `DELETE`, `UPDATE`, `INSERT`, multi-requêtes).
- `test_schema_linking.py` : Introspection dynamique de PostgreSQL et détection des tables/colonnes/jointures.
- `test_llm_service.py` : Validation du client Gemini et gestion des erreurs/quotas.
- `test_nl2sql_service.py` : Pipeline complet de traduction langage naturel vers SQL.
- `test_baseline_evaluation.py` : Algorithme de comparaison d'équivalence de résultats.

---

## 6. Banc d'Évaluation de la Baseline A (30 questions étalons)

Pour mesurer objectivement les performances du moteur NL2SQL :

```powershell
# Évaluer les 30 questions de référence
python scripts/evaluate_baseline_a.py
```

Le script calcule :
- **Taux de génération SQL valide (%)**
- **Taux d'exécution sans erreur DB (%)**
- **Exactitude d'exécution (équivalence sémantique avec la vérité terrain) (%)**
- **Temps moyen de réponse de bout en bout (secondes)**

Les résultats détaillés par question sont consignés dans `reports/baseline_a_results.json`.

---

## 7. Limitations Connues & Feuille de Route Sprint 4

### Limitations actuelles (Baseline A) :
- Pas de recherche sémantique vectorielle sur les commentaires textuels libres (réservé à Baseline B / Sprint 4).
- Seuil de débit Free Tier fixé à 15 requêtes/minute (géré automatiquement avec temporisation).

### Travaux prévus pour le Sprint 4 :
- Intégration de la recherche sémantique vectorielle (`reviews_semantic` via `pgvector` et MiniLM).
- Validation AST avancée via `sqlglot`.
- Pipeline RAG hybride combinant NL2SQL et recherche d'avis similaires.
