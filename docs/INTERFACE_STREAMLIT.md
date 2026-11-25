# Interface Streamlit

## Utilisation

Lancer l'application depuis la racine du repository :

```powershell
streamlit run app.py
```

Le navigateur ouvre l'assistant DataSense. Saisissez une question dans la zone de clavardage ou choisissez un exemple. Le backend existant détermine si elle nécessite le pipeline SQL, la recherche sémantique des avis ou les deux. L'interface ne génère ni n'exécute elle-même de SQL.

## Réponses et sources

- Les réponses texte sont affichées dans la conversation.
- Les résultats SQL sont présentés dans un tableau interactif, avec les lignes et la durée SQL lorsque ces informations sont disponibles.
- Les requêtes SQL validées sont consultables dans un volet repliable.
- Les commentaires retrouvés sont présentés comme des données, avec leur score de similarité et les identifiants disponibles.
- Les graphiques ne sont proposés que si les colonnes retournées s'y prêtent : barres pour une dimension de cardinalité limitée et une mesure, courbe pour une date et une mesure, ou nuage de points pour deux mesures. Les résultats d'une seule ligne et les dimensions à plus de 30 valeurs distinctes ne déclenchent pas de graphique.
- Les réponses partielles et les erreurs sont signalées sans afficher de trace d'exception ni de détail de connexion.

## Historique et données locales

Les questions et réponses sont conservées dans `st.session_state` pendant la session Streamlit. Elles ne sont pas écrites dans PostgreSQL et ne survivent pas à la session. Le bouton **Nouvelle conversation** efface l'historique courant.

Le profilage CSV reste local à l'interface : les fichiers importés sont lus avec pandas et ne sont pas transmis à Gemini ni au service de questions.

## Exemples

- « Combien de commandes ont été livrées en 2018 ? »
- « Que pensent les clients de la livraison ? »
- « Quel est le chiffre d'affaires et que disent les avis ? »

La disponibilité réelle des fonctions SQL et sémantiques dépend de la configuration du backend, de PostgreSQL, de Gemini et de la table `public.reviews_semantic`. Voir [RECHERCHE_SEMANTIQUE.md](./RECHERCHE_SEMANTIQUE.md) pour l'initialisation explicite de cette table.

## Tests

Les tests de l'interface utilisent `streamlit.testing.v1.AppTest` avec un orchestrateur simulé :

```powershell
python -m pytest tests/test_app.py -q
```

Ils n'appellent ni Gemini ni une base réelle. Pour la suite complète, voir la commande et les précautions de test dans le [README](../README.md#5-exécution-des-tests-automatisés).
