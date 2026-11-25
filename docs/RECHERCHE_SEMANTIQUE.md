# Recherche sémantique des commentaires clients

## Architecture

`QuestionOrchestrator` classe chaque demande avec Gemini en une réponse JSON validée :

- `sql` : délègue sans changement à `NL2SQLService`, qui conserve la validation SQL et l'exécution sécurisée existantes.
- `semantic` : appelle `SemanticSearchService.search(question, top_k=5)`.
- `mixed` : exécute le sous-problème SQL et la recherche d'avis, puis fournit les deux résultats à Gemini.

Le service existant utilise `paraphrase-multilingual-MiniLM-L12-v2`, encode en vecteurs normalisés de dimension 384 et trie les avis par distance cosinus pgvector (`<=>`). Il renvoie `review_id`, `order_id`, `review_text` et `similarity`. Les modèles, la base de données et Gemini sont injectables pour les tests.

Gemini reçoit au plus cinq avis, chacun limité à 2 000 caractères, ainsi que les scores et identifiants. Les avis et les valeurs SQL sont inclus comme données non fiables; les instructions contenues dans ces valeurs doivent être ignorées. La réponse est aussi validée comme JSON avant d'être renvoyée. Les réponses mixtes sont marquées partielles si une seule source est disponible.

## Préparer PostgreSQL

Le repository ne contenait pas de DDL pour `reviews_semantic`. Le script [`../sql/06_create_reviews_semantic.sql`](../sql/06_create_reviews_semantic.sql) crée, sans supprimer d'objet existant :

- l'extension `vector` si elle n'est pas déjà activée;
- `public.reviews_semantic`, avec clé primaire composite `(review_id, order_id)` correspondant à `order_reviews`;
- `review_text` et `embedding vector(384)`;
- un index HNSW utilisant `vector_cosine_ops`.

Pré-requis : PostgreSQL avec pgvector, la table `public.order_reviews` créée, et un rôle autorisé à créer l'extension si nécessaire. Le rôle d'exécution doit avoir `SELECT` sur `reviews_semantic`; le rôle de préparation des embeddings a besoin de lire `order_reviews` et d'insérer dans `reviews_semantic`. Cette tâche ne modifie aucun privilège.

Si `reviews_semantic` existe déjà, vérifiez son schéma avant d'appliquer le script : `CREATE TABLE IF NOT EXISTS` ne migre pas une table existante et ne valide pas ses colonnes ou contraintes.

Avec le service `db` de Docker Compose :

```powershell
Get-Content .\sql\06_create_reviews_semantic.sql | docker compose exec -T db psql -v ON_ERROR_STOP=1 -U postgres -d datasense
```

Cette étape crée le schéma, mais ne modifie ni n'insère de commentaires. La génération est distincte :

```powershell
python scripts/08_generate_embeddings.py
```

Le script d'embeddings lit `order_reviews` et insère les commentaires non encore vectorisés dans `reviews_semantic`; cette commande écrit dans la base et doit être exécutée explicitement sur la base cible vérifiée. Sans cette étape, la recherche renvoie une liste vide. Le script autonome `scripts/10_test_service_recherche_semantique.py` permet ensuite une recherche interactive. `scripts/07_test_recherche_semantique.py` reste un ancien prototype qui attend une vue `reviews_semantic_source` absente du repository; il n'est pas utilisé par l'orchestrateur.

La sidebar Streamlit ne marque désormais la recherche comme prête que si la table existe, que sa colonne est `vector(384)` et qu'au moins un embedding est présent. Le script `10` teste le retrieval indépendamment de Gemini. Le pipeline conversationnel nécessite aussi Gemini pour classer la question et synthétiser les avis; une panne Gemini n'empêche pas le test local du service, mais bloque la réponse conversationnelle.

## Tests et limites

Les erreurs Gemini sont journalisées par catégorie et statut HTTP, sans le texte brut de l'exception ni la clé API. La réponse de l'interface distingue les pannes fournisseur, d'authentification, de quota et de disponibilité du modèle sans révéler de secret.

Les tests unitaires du service et de l'orchestrateur utilisent des modèles, services et connexions simulés. Le test PostgreSQL opt-in de l'exécuteur SQL est ignoré par défaut; il ne s'exécute que si `DATASENSE_TEST_DATABASE_URL` désigne explicitement une base de test. Il vérifie le mode read-only et le timeout de l'exécuteur, pas la recherche sémantique. Aucun test de cette intégration n'effectue de génération d'embeddings ou d'écriture de données. Les tests NL2SQL existants peuvent utiliser la configuration DB de l'application; exécutez l'ensemble de la suite uniquement sur une base de test.

Lors de la vérification live du 25 novembre 2026, `public.reviews_semantic` contenait 89 vecteurs de dimension 384; une recherche réelle a retourné cinq résultats. Aucun commentaire n'a été transmis à Gemini pendant ce test. Gemini renvoyait une erreur HTTP 503; la disponibilité ultérieure peut différer. Les tests simulés ne démontrent pas la qualité métier de tous les résultats de recherche.
