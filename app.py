import streamlit as st
import pandas as pd
import os
from portfoliomaster.db.connection import get_connection, init_db
from portfoliomaster.ui.components import (
    render_filters,
    render_table,
    render_refresh_control,
    render_manual_entry,
)
from portfoliomaster.ingest.import_session import import_spreadsheet
from portfoliomaster.db.repository import upsert_instrument

st.set_page_config(page_title="PortfolioMaster", layout="wide")

st.title("PortfolioMaster - Watchlist")

# Inicializamos la base de datos antes de intentar leer nada
init_db()


def load_data():
    conn = get_connection()
    try:
        df = pd.read_sql_query("""
            SELECT
                i.*,
                q.price          AS latest_price,
                q.previous_close AS previous_close
            FROM instruments i
            LEFT JOIN quotes q
                ON q.instrument_id = i.id
        """, conn)
    except pd.io.sql.DatabaseError as e:
        st.error(f"Error cargando datos: {e}")
        df = pd.DataFrame()
    finally:
        conn.close()
    return df


# Tabs
tab1, tab2, tab3 = st.tabs(["📊 Watchlist", "➕ Añadir Valor Manual", "📥 Importar"])

with tab1:
    df = load_data()
    # Sidebar
    st.sidebar.header("Filtros y Acciones")
    render_refresh_control()
    if not df.empty:
        filtered_df = render_filters(df)
        # Main table
        render_table(filtered_df)
    else:
        st.info("No hay instrumentos en el watchlist. Añade un valor manualmente en la pestaña '➕ Añadir Valor Manual' o importa un archivo CSV/Excel en '📥 Importar'.")

with tab2:
    render_manual_entry()

with tab3:
    st.header("Importar Watchlist")
    uploaded_file = st.file_uploader("Elige tu archivo CSV o Excel", type=["csv", "xlsx"])
    if uploaded_file:
        temp_path = f"temp_{uploaded_file.name}"
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        instruments, errors, unresolved, warnings = import_spreadsheet(
            temp_path, uploaded_file.name
        )
        os.remove(temp_path)

        if errors:
            st.error("Errores durante la importación:")
            for e in errors:
                st.write(e)

        if warnings:
            st.warning("Avisos durante la importación:")
            for warning in warnings:
                st.write(warning)

        if instruments:
            st.success(f"Se han validado {len(instruments)} instrumentos.")
            if st.button("Confirmar Importación"):
                for inst in instruments:
                    upsert_instrument(inst)
                st.success("Importación completada.")
                st.rerun()

        if unresolved:
            st.warning("Símbolos no resueltos:")
            st.write(unresolved)
