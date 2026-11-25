# DataSense — Assistant Intelligent d'Analyse de Données Olist

DataSense est une plateforme analytique avancée permettant d'interroger une base de données e-commerce relationnelle (**Olist**) en langage naturel grâce à l'intelligence artificielle (**Google Gemini API**) et **PostgreSQL**.

L'application route les questions posées en français ou en anglais vers le pipeline SQL sécurisé, la recherche sémantique des avis clients, ou les deux. Gemini synthétise uniquement les résultats fournis, restitués dans l'interface conversationnelle **Streamlit**.

---

## 1. Architecture du Projet (Sprint 3 — Baseline A)

```
DataSense/
├── app.py                              # Assistant SQL/sémantique et profilage CSV
├── docker-compose.yml                  # Conteneur PostgreSQL 16 avec extension pgvector (port 5544)
├── requirements.txt                    # Dépendances Python déclarées
├── .env.example                        # Modèle de variables d'environnement
├── backend/                            # Architecture Backend modulaire
│   ├── config/
│   │   └── settings.py                 # Configuration centralisée (DB, LLM Gemini, Timeouts)
│   ├── database/
│   │   └── query_executor.py           # Exécution SQL sécurisée, transactions READ ONLY, timeouts
│   └── services/
│       ├── llm_service.py              # Appels Gemini centralisés, fallback, reprise bornée et circuit breaker
│       ├── schema_linking.py           # Introspection dynamique SQLAlchemy & Schema Linking
│       ├── nl2sql_service.py           # Pipeline SQL (génération, validation, exécution)
│       ├── semantic_search_service.py   # Recherche pgvector des commentaires clients
│       └── question_orchestrator.py     # Routage Gemini SQL / sémantique / mixte
├── data/
│   ├── evaluation/
│   │   └── questions.json              # Benchmark de 30 questions de référence (FR & EN)
│   └── test_orders.csv                 # Données de test initiales
├── reports/
│   └── baseline_a_results.json         # Rapport automatisé de performance de la Baseline A
├── docs/
│   └── RECHERCHE_SEMANTIQUE.md         # Routage, schéma et préparation des avis vectoriels
├── scripts/
│   ├── evaluate_baseline_a.py          # Script d'évaluation automatisé (taux de succès, exactitude, temps)
│   ├── seed_demo_data.py               # Générateur de données réalistes d'évaluation
│   └── 01_ à 10_*.py                   # Scripts Data Engineering & Sémantique
├── sql/
│   ├── 01_analyses_metier.sql          # Requêtes SQL analytiques de référence
│   ├── 05_create_schema.sql            # Script DDL de création des 5 tables relationnelles
│   └── 06_create_reviews_semantic.sql  # Table et index pgvector pour les avis
├── src/
│   └── db.py                           # Connecteur SQLAlchemy initial et test de connectivité
└── tests/                              # Suite de tests automatisés pytest
    ├── test_settings.py
    ├── test_llm_service.py
    ├── test_schema_linking.py
    ├── test_query_executor.py
    ├── test_nl2sql_service.py
    ├── test_semantic_search_service.py
    ├── test_question_orchestrator.py
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
GEMINI_PRIMARY_MODEL=gemini-3.1-flash-lite
GEMINI_FALLBACK_MODELS=gemini-3.5-flash-lite,gemini-3.6-flash
GEMINI_FALLBACK_ENABLED=true
GEMINI_MAX_RETRIES_PER_MODEL=1
GEMINI_MODEL_COOLDOWN_SECONDS=60
GEMINI_DAILY_QUOTA_COOLDOWN_SECONDS=86400
GEMINI_MAX_RETRY_DELAY_SECONDS=2
LLM_TIMEOUT_SECONDS=30
LLM_TEMPERATURE=0.0
LLM_MAX_OUTPUT_TOKENS=1024
```

`LLM_MODEL` reste accepté comme nom historique si `GEMINI_PRIMARY_MODEL` n'est pas défini. Ne mettez jamais une clé API dans le dépôt.

### Étape 3 : Démarrer la base de données PostgreSQL

```powershell
# Lancer le conteneur Docker PostgreSQL 16 + pgvector
docker compose up -d

# Activer l'extension pgvector
docker exec -it datasense_db psql -U postgres -d datasense -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Vérifier la connexion
python -m src.db
```

Le port PostgreSQL `5544` est publié uniquement sur `127.0.0.1` pour le
développement local; ne l'exposez pas sur une interface réseau avec le compte
superutilisateur de démonstration.

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
python -m streamlit run app.py
```

L'application s'ouvre sur `http://localhost:8501` et propose :
1. **Assistant conversationnel :** Posez vos questions en français ou en anglais. Le backend existant route les demandes vers SQL, la recherche sémantique d'avis ou les deux. Les réponses, tableaux, commentaires sources et graphiques pertinents sont affichés dans la conversation.
2. **Historique de session :** Les échanges restent disponibles pendant la session Streamlit; « Nouvelle conversation » les efface. Ils ne sont pas persistés dans PostgreSQL.
3. **Import & Profilage CSV :** Outil de diagnostic local pour inspecter un CSV; le fichier n'est pas envoyé au pipeline de questions.

Le serveur Streamlit est configuré pour écouter uniquement sur `127.0.0.1`.
Ne remplacez pas cette adresse par une interface réseau avant d'avoir mis en
place une authentification et une autorisation adaptées aux données clients.

Pour les résultats tabulaires, le sélecteur de visualisation ne propose que les graphiques compatibles avec les colonnes retournées. Les erreurs destinées à l'utilisateur ne divulguent pas les détails de connexion ou les erreurs internes.

---

## 5. Exécution des Tests Automatisés

Lancer les tests unitaires et les tests d'interface Streamlit avec des services simulés :

```powershell
python -m pytest -q
```

Les tests d'interface se trouvent dans `tests/test_app.py`; ils utilisent `streamlit.testing.v1.AppTest` et des mocks, sans appeler Gemini ni modifier une base réelle. Le test PostgreSQL de timeout est opt-in et nécessite une base de test configurée avec `DATASENSE_TEST_DATABASE_URL`. Les tests qui utilisent la configuration locale de la base doivent être lancés uniquement avec une base de test.

Les tests du fallback Gemini sont simulés et ne vérifient ni la disponibilité live des modèles ni les quotas du projet :

```powershell
python -m pytest -q tests/test_llm_service.py tests/test_settings.py tests/test_nl2sql_service.py tests/test_question_orchestrator.py tests/test_app.py
```

Le fonctionnement, les limites de quota et le test live optionnel sont détaillés dans [`docs/GEMINI_MODEL_FALLBACK.md`](docs/GEMINI_MODEL_FALLBACK.md).

---

## 6. Sécurité des requêtes SQL

Les requêtes PostgreSQL générées sont analysées avec SQLGlot avant exécution. La politique de validation, les limites, les fonctions autorisées et les protections PostgreSQL sont décrites dans [`docs/SQL_SECURITY.md`](docs/SQL_SECURITY.md).

## 7. Banc d'Évaluation de la Baseline A (30 questions étalons)

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

## 8. Recherche sémantique des avis clients

L'orchestrateur classe les demandes en SQL, sémantique ou mixtes avec une réponse JSON Gemini validée. Les demandes SQL continuent d'utiliser `NL2SQLService`; les avis sont recherchés via le `SemanticSearchService` existant, avec au plus cinq commentaires transmis à Gemini. Le texte des avis est traité comme donnée non fiable, et non comme instruction. La Baseline A d'évaluation demeure un benchmark NL2SQL et ne mesure pas la qualité de la recherche d'avis.

Le service attend `public.reviews_semantic` avec des embeddings de 384 dimensions. Après avoir créé `order_reviews` et configuré l'accès PostgreSQL, initialiser le schéma (commande non destructive; nécessite les droits d'extension si `vector` n'est pas déjà activée) :

```powershell
Get-Content .\sql\06_create_reviews_semantic.sql | docker compose exec -T db psql -v ON_ERROR_STOP=1 -U postgres -d datasense
```

La génération d'embeddings est une opération d'écriture distincte qui insère les commentaires manquants; lancez-la explicitement seulement lorsque les données et la base cible ont été vérifiées :

```powershell
python scripts/08_generate_embeddings.py
```

Exemples : « Que pensent les clients de la livraison ? » ou « Quel produit est le plus vendu et que disent les avis associés ? ». Les tests du service sémantique utilisent des mocks. Le test PostgreSQL opt-in de l'exécuteur SQL vérifie le mode read-only et le timeout via `DATASENSE_TEST_DATABASE_URL`; il ne vérifie pas la qualité de la recherche sémantique. Les tests NL2SQL existants peuvent utiliser la base configurée par l'application : lancez toute la suite uniquement avec une base de test.

Les détails du routage, des erreurs, du schéma et des commandes sont dans [`docs/RECHERCHE_SEMANTIQUE.md`](docs/RECHERCHE_SEMANTIQUE.md).
