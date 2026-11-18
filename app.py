import pandas as pd
import streamlit as st
import time

from src.db import test_connection
from backend.services.nl2sql_service import get_nl2sql_service
from backend.services.llm_service import get_llm_service
from backend.config.settings import get_settings

st.set_page_config(
    page_title="DataSense - Assistant NL2SQL & Analytics",
    page_icon="📊",
    layout="wide"
)

settings = get_settings()

st.title("DataSense — Intelligent Data Analytics")
st.caption("Interrogez la base de données e-commerce Olist en langage naturel grâce à l'IA (Gemini + PostgreSQL)")

# =====================================================
# SIDEBAR : ÉTAT DU SYSTÈME & MODÈLE
# =====================================================
with st.sidebar:
    st.header("État du système")
    try:
        version, has_vector = test_connection()
        st.success("PostgreSQL connecté")
        st.write("pgvector :", "activé" if has_vector else "absent")
        st.caption(f"Host: {settings.db.host}:{settings.db.port} ({settings.db.name})")
    except Exception as e:
        st.error(f"Connexion impossible : {e}")

    st.divider()
    st.header("Modèle LLM")
    st.write(f"Fournisseur : **{settings.llm.provider.upper()}**")
    st.write(f"Modèle : `{settings.llm.model}`")
    
    if st.button("Tester la connexion API Gemini"):
        with st.spinner("Test de connectivité..."):
            llm_service = get_llm_service()
            status = llm_service.test_connectivity()
            if status["success"]:
                st.success(f"API Gemini OK ({status['duration_seconds']}s)")
            else:
                st.error(f"Échec API : {status.get('error')}")

# =====================================================
# ONGLETS PRINCIPAUX : NL2SQL & PROFILAGE CSV
# =====================================================
tab_nl2sql, tab_csv = st.tabs(["💬 Assistant NL2SQL (Olist)", "📁 Import & Profilage CSV"])

with tab_nl2sql:
    st.header("Posez une question sur la base Olist")
    st.write("Exprimez votre besoin analytique en français ou en anglais :")

    if "nl2sql_question" not in st.session_state:
        st.session_state.nl2sql_question = ""

    # Exemples rapides
    col_ex1, col_ex2, col_ex3, col_ex4 = st.columns(4)
    if col_ex1.button("Delivered orders in 2018?"):
        st.session_state.nl2sql_question = "How many orders were delivered in 2018?"
        st.rerun()
    if col_ex2.button("Total revenue?"):
        st.session_state.nl2sql_question = "What is the total revenue?"
        st.rerun()
    if col_ex3.button("Average review score?"):
        st.session_state.nl2sql_question = "What is the average review score?"
        st.rerun()
    if col_ex4.button("Orders by status?"):
        st.session_state.nl2sql_question = "What is the distribution of orders by status?"
        st.rerun()

    # Champ de saisie
    user_query = st.text_input(
        "Votre question :",
        key="nl2sql_question",
        placeholder="Ex: Combien de commandes ont été livrées en 2018 ? ou What is the total revenue?"
    )

    col_btn, col_empty = st.columns([1, 5])
    submit_query = col_btn.button("Générer & Exécuter SQL", type="primary")

    if submit_query:
        if not user_query.strip():
            st.warning("Veuillez saisir une question ou cliquer sur un exemple.")
        else:
            nl2sql_svc = get_nl2sql_service()

            with st.spinner("Analyse du schéma et génération de la requête SQL..."):
                try:
                    response = nl2sql_svc.process_question(user_query, execute=True)
                except Exception as e:
                    st.error(f"Erreur inattendue du backend : {e}")
                    response = None

            if response is not None:
                if response.status == "success" and response.sql:
                    st.success("Requête générée et exécutée avec succès !")

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Lignes retournées", response.execution_result.row_count if response.execution_result else 0)
                    m2.metric("Temps LLM", f"{response.llm_duration_seconds:.2f}s")
                    m3.metric("Temps Exécution DB", f"{response.execution_result.execution_time_seconds:.3f}s" if response.execution_result else "0s")
                    m4.metric("Temps Total", f"{response.total_duration_seconds:.2f}s")

                    st.subheader("Requête SQL générée")
                    st.code(response.sql, language="sql")

                    if response.explanation:
                        st.info(f"**Explication :** {response.explanation}")

                    st.subheader("Résultats")
                    if response.has_data:
                        df_res = response.data
                        st.dataframe(df_res, use_container_width=True)

                        if len(df_res) > 1 and len(df_res.columns) == 2:
                            col1, col2 = df_res.columns
                            if pd.api.types.is_numeric_dtype(df_res[col2]) and not pd.api.types.is_numeric_dtype(df_res[col1]):
                                st.subheader("Visualisation")
                                st.bar_chart(df_res.set_index(col1))
                            elif pd.api.types.is_numeric_dtype(df_res[col1]) and not pd.api.types.is_numeric_dtype(df_res[col2]):
                                st.subheader("Visualisation")
                                st.bar_chart(df_res.set_index(col2))
                    else:
                        st.warning("La requête n'a retourné aucun enregistrement.")

                elif response.status == "clarification_required":
                    st.warning(f"Précision requise : {response.explanation}")
                elif response.status == "security_rejected":
                    st.error(f"Requête rejetée par le contrôle de sécurité : {response.error_message}")
                    if response.sql:
                        st.code(response.sql, language="sql")
                else:
                    st.error(f"Erreur : {response.error_message or response.explanation}")
                    if response.sql:
                        st.code(response.sql, language="sql")

# =====================================================
# ONGLET 2 : IMPORT DE FICHIER CSV (FONCTIONNALITÉ EXISTANTE PRÉSERVÉE)
# =====================================================
with tab_csv:
    st.header("Import et profilage de fichier CSV")
    file = st.file_uploader("Choisir un CSV", type=["csv"], key="csv_inspector")

    if file:
        df = pd.read_csv(file)
        c1, c2, c3 = st.columns(3)
        c1.metric("Lignes", f"{len(df):,}")
        c2.metric("Colonnes", df.shape[1])
        c3.metric("Doublons", int(df.duplicated().sum()))

        st.subheader("Aperçu")
        st.dataframe(df.head(50), use_container_width=True)

        st.subheader("Types et valeurs manquantes")
        info = pd.DataFrame({
            "type": df.dtypes.astype(str),
            "manquantes": df.isna().sum(),
            "% manquantes": (df.isna().mean() * 100).round(2),
        })
        st.dataframe(info, use_container_width=True)
