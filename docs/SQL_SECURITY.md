# Validation et exécution sécurisée du SQL

## Objectif et emplacement

Les requêtes Gemini ne sont pas fiables par défaut. `backend/security/sql_validator.py` utilise SQLGlot pour analyser l'AST en dialecte PostgreSQL et n'accepte qu'une requête de lecture unique et bornée. Cette couche ne dépend pas du fournisseur LLM et peut être réutilisée par les services backend.

Le parcours actuel est :

1. `NL2SQLService` demande une requête à Gemini.
2. `QueryExecutor.validate_query` fait analyser et valider la requête.
3. La requête normalisée et bornée est transmise à l'exécuteur, qui la valide à nouveau avant toute connexion/exécution.
4. PostgreSQL exécute la requête dans une transaction en lecture seule et avec un timeout.

Le pipeline Gemini/NL2SQL existant est raccordé à cette couche. Aucun service alternatif n'est créé.

## Requêtes acceptées et refusées

Les racines `SELECT` et `UNION` sont acceptées, y compris les CTE en lecture, sous-requêtes, jointures, agrégations et clauses de filtrage/tri. Toutes les branches d'un `UNION`, les sous-requêtes et les CTE sont inspectées.

Les opérations de modification, DDL, permissions, session et transaction sont refusées. Sont aussi refusés `SELECT INTO`, les verrous `FOR UPDATE`/`FOR SHARE`, toute expression SQLGlot contenant un nœud DML/DDL et les requêtes dont la racine n'est pas un `SELECT` ou un `UNION`.

SQLGlot compte les expressions produites par le parseur, pas les mots-clés ni les points-virgules. Un point-virgule final et un commentaire terminal sont tolérés; plusieurs statements non vides sont rejetés.

## Fonctions PostgreSQL

Une allowlist centralisée autorise les agrégations et fonctions usuelles de calcul, chaînes, dates et heures définies par `SQLValidator.ALLOWED_FUNCTIONS`. Les fonctions sensibles connues sont explicitement nommées dans `FORBIDDEN_FUNCTIONS` (par exemple `pg_sleep`, `pg_read_file`, `set_config`, `nextval`, `setval`, `lo_import` et `lo_export`). Toute fonction qui n'est pas dans l'allowlist, ainsi que toute fonction qualifiée par un schéma, est rejetée. Pour autoriser une fonction supplémentaire, vérifier au préalable sa sémantique et ses effets de bord, puis l'ajouter explicitement à la liste.

## Tables et schémas

L'exécuteur utilise l'introspection SQLAlchemy déjà présente dans `SchemaInspector`, mais une table n'est autorisée que si son nom appartient à `DB_ALLOWED_QUERY_TABLES` **et** si l'introspection la trouve dans `public`. La valeur par défaut liste explicitement les cinq tables analytiques Olist; toute extension doit être configurée intentionnellement. Les noms de tables des JOIN, CTE, sous-requêtes et branches d'union sont résolus par portée SQLGlot et vérifiés. Les références aux catalogues et aux schémas autres que `public` sont rejetées. Les références de tables non qualifiées sont normalisées vers `public.<table>`; les CTE sont reconnues comme des noms locaux et ne sont pas modifiées. L'absence de liste autorisée dans un usage direct du validateur est un refus, non une autorisation implicite.

La whitelist n'autorise aucun objet système, même si le compte PostgreSQL peut le lire. Une requête utilisant une table publique supplémentaire, telle qu'une table interne ou sensible, reste rejetée tant qu'elle n'est pas ajoutée explicitement à la configuration.

Les requêtes sans table, telles que `SELECT 1`, ne nécessitent pas d'introspection. Si l'introspection est requise mais indisponible, la validation échoue en mode fermé et aucune requête n'est exécutée.

## Limites de résultats

Les paramètres sont centralisés dans `DatabaseSettings` :

- `DB_DEFAULT_SQL_LIMIT` : limite ajoutée si le SELECT racine ne contient pas de LIMIT (défaut : `100`).
- `DB_MAX_SQL_LIMIT` : plafond d'un LIMIT existant (défaut : valeur de `DB_MAX_RESULT_ROWS`, soit `500`).
- `DB_MAX_RESULT_ROWS` : nombre maximal de lignes récupérées par l'exécuteur (défaut : `500`).
- `DB_ALLOWED_QUERY_TABLES` : noms de tables applicatives autorisées, séparés par des virgules (défaut : `customers,orders,order_items,order_payments,order_reviews`).

Un LIMIT positif ou nul écrit comme entier littéral est accepté; une limite invalide ou paramétrée est rejetée. Une limite supérieure au plafond est réduite. La limite est appliquée au SELECT racine ou au résultat final d'un UNION, sans modifier les limites des sous-requêtes et des CTE. Le plafond effectif est `min(DB_MAX_SQL_LIMIT, DB_MAX_RESULT_ROWS)`. La configuration doit respecter `0 <= DB_DEFAULT_SQL_LIMIT <= min(DB_MAX_SQL_LIMIT, DB_MAX_RESULT_ROWS)`; une configuration incohérente échoue explicitement à l'initialisation du validateur. Les paramètres nommés compatibles SQLAlchemy (`:nom`) sont acceptés dans les autres clauses; les paramètres PostgreSQL positionnels (`$1`) sont rejetés.

Les `OFFSET` sont contrôlés dans tous les sous-arbres : ils doivent être des entiers littéraux non négatifs et ne peuvent pas dépasser le plafond effectif des résultats. Les offsets paramétrés, négatifs ou excessifs sont rejetés. Cela limite les scans dus à une pagination par décalage; pour les grands jeux de données, préférer une pagination par curseur (keyset pagination).

## Exécution PostgreSQL (Task 2)

La validation SQL (Task 1) et les protections du moteur d'exécution sont deux contrôles distincts. `QueryExecutor.execute` revalide le SQL puis transmet uniquement la représentation normalisée validée à PostgreSQL. Une requête refusée ne demande aucune connexion d'exécution.

Chaque exécution utilise l'engine SQLAlchemy partagé par l'application (`pool_pre_ping=True`), ouvre une transaction, applique `SET TRANSACTION READ ONLY` avant le SQL utilisateur, puis définit `statement_timeout` et `search_path` avec `SET LOCAL`. Le `search_path` est limité à `pg_catalog`; les tables autorisées sont explicitement qualifiées par le validateur. Le timeout vient de `DB_STATEMENT_TIMEOUT_MS` (défaut : `10000` ms) et une valeur non positive empêche l'initialisation de l'exécuteur.

Les résultats sont lus avec `stream_results=True` et `fetchmany(DB_MAX_RESULT_ROWS)`. Que la lecture réussisse ou échoue, l'exécuteur annule explicitement la transaction avant de rendre la connexion au pool. Cela réinitialise également les paramètres transactionnels locaux. Si l'annulation échoue, la connexion est invalidée; cette erreur de nettoyage ne masque pas une erreur d'exécution déjà survenue. Le pool vérifie les connexions avec `pool_pre_ping`.

Les erreurs SQLSTATE usuelles (syntaxe, table/colonne absente, permissions, timeout, annulation, connexion et état de transaction) sont converties en codes et messages contrôlés. Les détails bruts du pilote et le SQL ne sont pas retournés à l'interface. Les délais d'attente du pool sont également signalés séparément. La limite SQL du résultat final et la borne de récupération restent les mécanismes de limitation des lignes; l'annulation de transaction ne change pas la logique des sous-requêtes.

Les tests unitaires d'exécution utilisent des mocks pour vérifier l'ordre des commandes, le rollback, le nettoyage et le classement d'erreurs sans écrire de données. Un test d'intégration PostgreSQL opt-in vérifie `transaction_read_only` et l'expiration réelle de `statement_timeout` avec des lectures seulement; il est ignoré sauf si `DATASENSE_TEST_DATABASE_URL` désigne explicitement une base de test. Les tests existants qui se connectent à PostgreSQL nécessitent une base de test configurée; aucun test de production n'est requis.

## Erreurs et protections PostgreSQL

`SQLValidationResult` expose le statut, le SQL normalisé, le nombre de statements, les informations de limite et un code d'erreur (`EMPTY_QUERY`, `SQL_PARSE_ERROR`, `MULTIPLE_STATEMENTS`, `NON_SELECT_QUERY`, `FORBIDDEN_OPERATION`, `FORBIDDEN_FUNCTION`, `FORBIDDEN_TABLE`, `LIMIT_INVALID`, `SCHEMA_LOOKUP_ERROR`, etc.). `NL2SQLResponse` expose également `error_code`. Les erreurs PostgreSQL renvoyées à l'interface restent génériques; les journaux n'incluent pas le SQL ni le message brut de la base.

L'exécution applique `SET TRANSACTION READ ONLY`, `statement_timeout` et un `search_path` limité à `pg_catalog`. Les tables applicatives étant explicitement qualifiées par `public`, ce chemin exclut également la résolution accidentelle de fonctions et d'opérateurs utilisateur. Les identifiants PostgreSQL ne sont pas modifiés et aucune permission ni donnée n'est changée par cette tâche. Les privilèges du rôle déployé n'ont pas été vérifiés; pour la défense en profondeur, le déploiement doit utiliser un rôle applicatif dédié disposant uniquement de `SELECT` sur les tables nécessaires. Le rôle `postgres` ne convient pas à une production. Cette vérification et toute modification de permissions doivent être faites séparément par l'administrateur de la base.

## Installation et tests

SQLGlot figure déjà dans `requirements.txt`; installation (depuis la racine) :

```powershell
pip install -r requirements.txt
python -m pytest tests/test_sql_validator.py tests/test_query_executor.py tests/test_nl2sql_service.py -q
python -m pytest -q
```

Le validateur unitaire reçoit une whitelist explicite pour tester les cas sans base externe. Les tests existants d'intégration PostgreSQL requièrent une base de test configurée et accessible.

## Limites

- L'allowlist de fonctions est volontairement restrictive; une fonction PostgreSQL légitime mais absente doit être revue avant ajout.
- La validation AST n'est pas une frontière de sécurité suffisante à elle seule. Les privilèges du rôle, les extensions installées, les opérateurs personnalisés et le coût de certaines requêtes restent des sujets de configuration PostgreSQL.
- L'introspection du schéma dépend de la connexion et du rôle applicatif. Une erreur entraîne un refus, non un contournement.
- Ce changement ne crée ni rôle PostgreSQL, ni endpoint, ni autre pipeline LLM.

## Fichiers concernés

- `backend/security/sql_validator.py` et `backend/security/__init__.py` : parsing, politique AST, limites et erreurs structurées.
- `backend/config/settings.py` : configuration centralisée des limites SQL.
- `backend/database/query_executor.py` : validation obligatoire, whitelist, transaction read-only, timeout et messages d'erreur contrôlés.
- `backend/services/nl2sql_service.py` : transmission exclusive du SQL validé à l'exécuteur.
- `tests/test_sql_validator.py`, `tests/test_query_executor.py` et `tests/test_nl2sql_service.py` : tests de politique et de non-exécution.
