import streamlit as st
import pandas as pd
from ..core.models import Exchange, QuoteStatus
from ..core.calculations import daily_variation, variation_since_analysis, decline_to_target
from ..db.repository import upsert_quote, get_all_instruments, wipe_database, upsert_instrument
from ..providers.yahoo_adapter import YahooAdapter
from ..refresh.batch_runner import BatchRunner
from ..ingest.normalizer import normalize
from ..core.config import get_yahoo_suffix
import logging
from .style import status_badge
from decimal import Decimal
from datetime import datetime

def render_filters(df):
    st.sidebar.header("Filtros")
    search = st.sidebar.text_input("Buscar por ticker/nombre")

    market_filter = st.sidebar.multiselect("Mercado", options=df['exchange'].unique())
    currency_filter = st.sidebar.multiselect("Moneda", options=df['currency'].unique())

    filtered_df = df.copy()
    if search:
        filtered_df = filtered_df[filtered_df['user_ticker'].str.contains(search, case=False) | filtered_df['company_name'].str.contains(search, case=False)]
    if market_filter:
        filtered_df = filtered_df[filtered_df['exchange'].isin(market_filter)]
    if currency_filter:
        filtered_df = filtered_df[filtered_df['currency'].isin(currency_filter)]

    return filtered_df

def render_table(df):
    required = {'latest_price', 'previous_close',
                'analysis_reference_price', 'target_price'}
    missing = required - set(df.columns)
    if missing:
        st.error(f"Faltan columnas para renderizar la tabla: {missing}")
        st.write("Columnas disponibles:", df.columns.tolist())
        st.dataframe(df)
        return

    if df.empty:
        st.info("No hay resultados con los filtros actuales.")
        return

    df = df.copy()  # evita SettingWithCopyWarning

    # Calcular variaciones (las funciones devuelven CalculationResult)
    df['daily_variation'] = df.apply(
        lambda r: daily_variation(r['latest_price'], r['previous_close']).daily_variation, axis=1)
    df['variation_since_analysis'] = df.apply(
        lambda r: variation_since_analysis(r['latest_price'], r['analysis_reference_price']).variation_since_analysis, axis=1)
    df['decline_to_target'] = df.apply(
        lambda r: decline_to_target(r['target_price'], r['latest_price']).decline_to_target, axis=1)

    # Formatear para visualización (maneja Decimal o None)
    def fmt_pct(x):
        if x is None:
            return "N/A"
        try:
            return f"{float(x):.2f}%"
        except (TypeError, ValueError):
            return "N/A"

    df['daily_variation'] = df['daily_variation'].apply(fmt_pct)
    df['variation_since_analysis'] = df['variation_since_analysis'].apply(fmt_pct)
    df['decline_to_target'] = df['decline_to_target'].apply(fmt_pct)

    # Mostrar tabla
    st.dataframe(df[['user_ticker', 'company_name', 'latest_price', 
                     'daily_variation', 'variation_since_analysis', 
                     'decline_to_target', 'target_price']])


def render_refresh_control():
    if st.sidebar.button("Borrar Base de Datos", type="primary"):
        wipe_database()
        st.sidebar.warning("Base de datos borrada. Recarga la página.")
        return

    if st.sidebar.button("Forzar Refresh"):
        st.sidebar.info("Refresh en progreso...")
        try:
            instruments = get_all_instruments()

            # Asegurar que cada instrumento tenga provider_symbol y exchange correctamente normalizados
            for inst in instruments:
                norm_ticker, exchange = normalize(inst.user_ticker, inst.currency)
                suffix = get_yahoo_suffix(inst.user_ticker, exchange, inst.currency)
                expected_provider_symbol = (
                    f"{norm_ticker}{suffix}"
                    if suffix and not norm_ticker.upper().endswith(suffix.upper())
                    else norm_ticker
                )
                if inst.provider_symbol != expected_provider_symbol or inst.exchange != exchange:
                    inst.provider_symbol = expected_provider_symbol
                    inst.exchange = exchange
                    upsert_instrument(inst)

            symbols = [inst.provider_symbol for inst in instruments if inst.provider_symbol]
            provider = YahooAdapter()
            runner = BatchRunner(provider=provider)
            quotes = runner.run(symbols)
            instrument_map = {inst.provider_symbol: inst.id for inst in instruments}
            for symbol, quote in quotes.items():
                quote.instrument_id = instrument_map.get(symbol)
                if quote.instrument_id:
                    upsert_quote(quote)
            st.sidebar.success("Refresh de Yahoo Finance completado.")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"Error en el refresh: {e}")