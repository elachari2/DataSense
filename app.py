import pandas as pd
import streamlit as st
from src.db import test_connection

st.set_page_config(page_title="DataSense", layout="wide")
st.title("DataSense")

with st.sidebar:
    st.header("État du système")
    try:
        version, has_vector = test_connection()
        st.success("PostgreSQL connecté")
        st.write("pgvector :", "activé" if has_vector else "absent")
    except Exception as e:
        st.error(f"Connexion impossible : {e}")

st.header("Import de fichier CSV")
file = st.file_uploader("Choisir un CSV", type=["csv"])

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
