import logging

import pandas as pd
import streamlit as st

from backend.config.settings import get_settings
from backend.services.llm_service import (
    gemini_error_message,
    get_llm_service,
)
from backend.services.question_orchestrator import get_question_orchestrator
from backend.services.semantic_search_service import get_semantic_search_service
from src.db import test_connection


logger = logging.getLogger(__name__)
settings = get_settings()


st.set_page_config(
    page_title="DataSense - Assistant Olist",
    page_icon="📊",
    layout="wide",
)


@st.cache_data(ttl=60, show_spinner=False)
def _database_status():
    try:
        _, has_vector = test_connection()
    except Exception as error:
        logger.warning(
            "Database health check failed: exception=%s",
            type(error).__name__,
        )
        return False, False, None

    if not has_vector:
        return True, False, None

    try:
        readiness = get_semantic_search_service().readiness()
    except Exception as error:
        logger.warning(
            "Semantic readiness check failed: exception=%s",
            type(error).__name__,
        )
        return True, True, None
    return True, True, readiness


def _render_chart(data: pd.DataFrame, message_index: int) -> None:
    if len(data) < 2:
        return

    numeric_columns = [
        column
        for column in data.columns
        if pd.api.types.is_numeric_dtype(data[column])
        and not pd.api.types.is_bool_dtype(data[column])
    ]
    date_columns = [
        column
        for column in data.columns
        if pd.api.types.is_datetime64_any_dtype(data[column])
    ]
    category_columns = [
        column
        for column in data.columns
        if column not in numeric_columns and column not in date_columns
        and data[column].nunique(dropna=True) <= 30
    ]

    chart_types = []
    if category_columns and numeric_columns:
        chart_types.append("Barres")
    if date_columns and numeric_columns:
        chart_types.append("Courbe")
    if len(numeric_columns) >= 2:
        chart_types.append("Nuage de points")
    if not chart_types:
        return

    st.subheader("Visualisation")
    chart_type = st.selectbox(
        "Type de graphique",
        ["Aucun"] + chart_types,
        key=f"chart_type_{message_index}",
    )
    if chart_type == "Aucun":
        return

    if chart_type == "Barres":
        x_column = st.selectbox(
            "Dimension",
            category_columns,
            key=f"chart_x_{message_index}",
        )
        y_column = st.selectbox(
            "Mesure",
            numeric_columns,
            key=f"chart_y_{message_index}",
        )
        st.bar_chart(data, x=x_column, y=y_column)
    elif chart_type == "Courbe":
        x_column = st.selectbox(
            "Axe temporel",
            date_columns,
            key=f"chart_x_{message_index}",
        )
        y_column = st.selectbox(
            "Mesure",
            numeric_columns,
            key=f"chart_y_{message_index}",
        )
        st.line_chart(data.sort_values(x_column), x=x_column, y=y_column)
    else:
        x_column = st.selectbox(
            "Axe X",
            numeric_columns,
            key=f"chart_x_{message_index}",
        )
        y_choices = [column for column in numeric_columns if column != x_column]
        y_column = st.selectbox(
            "Axe Y",
            y_choices,
            key=f"chart_y_{message_index}",
        )
        st.scatter_chart(data, x=x_column, y=y_column)


def _render_semantic_evidence(results) -> None:
    if not results:
        return

    with st.expander("Commentaires clients retrouvés"):
        for review in results:
            metadata = [
                f"Similarité : {review['similarity']:.3f}",
                f"Avis : {review['review_id']}",
                f"Commande : {review['order_id']}",
            ]
            st.caption(" · ".join(metadata))
            st.text(review["review_text"])


def _render_response(response, message_index: int) -> None:
    intent_labels = {
        "sql": "SQL",
        "semantic": "Recherche sémantique",
        "mixed": "SQL + recherche sémantique",
    }
    st.caption(
        f"Traitement : {intent_labels.get(response.intent, 'Analyse')} · "
        f"Statut : {response.status}"
    )

    if response.status == "clarification_required":
        st.warning(response.explanation or "Merci de préciser votre question.")
        return
    if response.status == "security_rejected":
        st.error("La requête a été refusée par le contrôle de sécurité SQL.")
        return
    if response.status == "unsupported":
        st.info(response.explanation or "Cette question ne peut pas être traitée.")
        return
    if response.status == "error" and not response.answer:
        if response.error_code and response.error_code.startswith("GEMINI_"):
            st.error(
                gemini_error_message(
                    response.error_code,
                    response.provider_status,
                )
            )
        elif response.error_code == "INTENT_CLASSIFICATION_ERROR":
            st.error(
                "Gemini n'a pas fourni un classement de question valide. "
                "Réessayez avec une question plus précise."
            )
        elif response.error_code == "SEMANTIC_TABLE_MISSING":
            st.error(
                "La table public.reviews_semantic n'est pas initialisée."
            )
        elif response.error_code == "PGVECTOR_UNAVAILABLE":
            st.error("L'extension ou l'opérateur pgvector est indisponible.")
        elif response.error_code == "SEMANTIC_DATABASE_UNAVAILABLE":
            st.error("La base PostgreSQL de recherche est indisponible.")
        elif response.error_code == "SEMANTIC_RESPONSE_INVALID":
            st.error("Le service de recherche a retourné un résultat invalide.")
        elif response.error_code == "SEMANTIC_SEARCH_ERROR":
            st.error("La recherche dans les commentaires a échoué.")
        elif response.error_code == "ANSWER_GENERATION_ERROR":
            st.error(
                "La recherche est terminée, mais Gemini n'a pas pu synthétiser "
                "les résultats."
            )
        else:
            st.error(
                response.explanation
                or "Le traitement a échoué. Vérifiez les logs du backend."
            )
        return
    if response.status == "execution_error" and not response.answer:
        st.error("La requête SQL n'a pas pu être exécutée.")

    if response.status == "partial":
        st.warning("Certains résultats ne sont pas disponibles.")

    if response.answer:
        st.markdown(response.answer)
    elif response.explanation:
        st.markdown(response.explanation)

    execution = response.execution_result
    if execution is not None:
        metric_columns = st.columns(3)
        metric_columns[0].metric("Lignes retournées", execution.row_count)
        metric_columns[1].metric(
            "Temps SQL",
            f"{execution.execution_time_seconds:.3f} s",
        )
        metric_columns[2].metric(
            "Temps total",
            f"{response.total_duration_seconds:.2f} s",
        )

        if not execution.success:
            st.warning("Les résultats SQL ne sont pas disponibles.")
        elif execution.data is not None and not execution.data.empty:
            st.dataframe(
                execution.data,
                width="stretch",
                hide_index=True,
            )
            _render_chart(execution.data, message_index)
        else:
            st.info("La requête n'a retourné aucun enregistrement.")

    if response.sql and response.is_valid_sql:
        with st.expander("Consulter la requête SQL"):
            st.code(response.sql, language="sql")

    _render_semantic_evidence(response.semantic_results or [])


def _append_question(question: str) -> None:
    messages = st.session_state.conversation
    messages.append({"role": "user", "content": question})
    st.session_state.message_counter += 1
    message_id = st.session_state.message_counter

    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Analyse de votre question..."):
                response = get_question_orchestrator().process_question(
                    question,
                    execute=True,
                )
            _render_response(response, message_id)
            messages.append(
                {
                    "role": "assistant",
                    "response": response,
                    "chart_id": message_id,
                }
            )
        except Exception as error:
            logger.error(
                "Question orchestration failed: exception=%s",
                type(error).__name__,
            )
            message = (
                "Le service d'analyse est temporairement indisponible. "
                "Veuillez réessayer."
            )
            st.error(message)
            messages.append({"role": "assistant", "content": message})


st.title("DataSense — Assistant d'analyse Olist")
st.caption(
    "Posez vos questions en français ou en anglais sur les données de commandes "
    "et les commentaires clients."
)

with st.sidebar:
    st.title("DATASENSE")
    st.caption("Analysez vos données en langage naturel.")
    st.divider()

    st.subheader("État du service")
    database_available, vector_available, semantic_readiness = _database_status()
    if database_available:
        st.success("Base de données disponible")
        if not vector_available:
            st.warning("Extension de recherche vectorielle non détectée")
        elif semantic_readiness is None:
            st.warning("État de la recherche sémantique non vérifié")
        elif not semantic_readiness.table_exists:
            st.warning("Table public.reviews_semantic absente")
        elif not semantic_readiness.has_embeddings:
            st.warning("Table sémantique présente, embeddings absents")
        elif semantic_readiness.embedding_dimension != 384:
            st.warning(
                "Dimension des embeddings incorrecte : "
                f"{semantic_readiness.embedding_dimension or 'inconnue'}"
            )
        else:
            st.success("Recherche sémantique prête (embeddings 384D)")
    else:
        st.warning("Base de données momentanément indisponible")

    st.caption(f"Modèle principal configuré : {settings.llm.model}")
    if st.button("Tester Gemini", use_container_width=True):
        try:
            with st.spinner("Vérification de Gemini..."):
                status = get_llm_service().test_connectivity()
            if status["success"]:
                st.success(f"Gemini est disponible via {status['model']}.")
            else:
                st.warning(
                    gemini_error_message(
                        status.get("error_code"),
                        status.get("provider_status"),
                    )
                )
        except Exception as error:
            logger.warning(
                "Gemini connectivity check failed: exception=%s",
                type(error).__name__,
            )
            st.warning("Gemini est momentanément indisponible.")

    st.divider()
    if st.button(
        "Nouvelle conversation",
        key="new_conversation",
        type="primary",
        width="stretch",
    ):
        st.session_state.conversation = []
        st.rerun()

    st.subheader("Questions récentes")
    user_messages = [
        message["content"]
        for message in st.session_state.get("conversation", [])
        if message["role"] == "user"
    ]
    if user_messages:
        for question in reversed(user_messages[-8:]):
            st.caption(f"• {question}")
    else:
        st.caption("Votre historique apparaîtra ici.")

if "conversation" not in st.session_state:
    st.session_state.conversation = []
if "message_counter" not in st.session_state:
    st.session_state.message_counter = 0

for index, message in enumerate(st.session_state.conversation):
    with st.chat_message(message["role"]):
        if message["role"] == "user":
            st.markdown(message["content"])
        elif "response" in message:
            _render_response(
                message["response"],
                message.get("chart_id", index),
            )
        else:
            st.markdown(message["content"])

if not st.session_state.conversation:
    st.info("Exemples de questions")
    examples = [
        "Combien de commandes ont été livrées en 2018 ?",
        "Que pensent les clients de la livraison ?",
        "Quel est le chiffre d'affaires et que disent les avis ?",
    ]
    example_columns = st.columns(len(examples))
    selected_question = None
    for index, example in enumerate(examples):
        if example_columns[index].button(
            example,
            key=f"example_{index}",
            width="stretch",
        ):
            selected_question = example
            break
else:
    selected_question = None

chat_question = st.chat_input("Posez votre question à DataSense...")
if chat_question:
    selected_question = chat_question

if selected_question:
    _append_question(selected_question.strip())


with st.expander("Import et profilage CSV"):
    st.write("Inspectez un fichier local sans l'envoyer au pipeline de questions.")
    file = st.file_uploader("Choisir un fichier CSV", type=["csv"], key="csv_inspector")

    if file:
        try:
            data = pd.read_csv(file)
        except (UnicodeDecodeError, pd.errors.ParserError, ValueError):
            st.error("Le fichier CSV n'a pas pu être lu. Vérifiez son format.")
        else:
            metric_columns = st.columns(3)
            metric_columns[0].metric("Lignes", f"{len(data):,}")
            metric_columns[1].metric("Colonnes", data.shape[1])
            metric_columns[2].metric("Doublons", int(data.duplicated().sum()))

            st.subheader("Aperçu")
            st.dataframe(data.head(50), width="stretch")

            st.subheader("Types et valeurs manquantes")
            info = pd.DataFrame(
                {
                    "type": data.dtypes.astype(str),
                    "manquantes": data.isna().sum(),
                    "% manquantes": (data.isna().mean() * 100).round(2),
                }
            )
            st.dataframe(info, width="stretch")
