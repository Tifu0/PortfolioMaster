import streamlit as st
import pandas as pd
import numpy as np
from ..core.models import Exchange, Quote, QuoteStatus, Instrument
from ..core.calculations import daily_variation, variation_since_analysis, decline_to_target
from ..db.repository import (
    upsert_quote,
    get_all_instruments,
    wipe_database,
    upsert_instrument,
    get_instrument_by_ticker,
    get_quote_by_instrument_id,
    delete_instrument,
)
from ..providers.yahoo_adapter import YahooAdapter
from ..refresh.batch_runner import BatchRunner
from ..ingest.normalizer import normalize
from ..core.config import get_yahoo_suffix
import logging
from decimal import Decimal
from datetime import datetime


def render_filters(df):
    search = st.sidebar.text_input("Buscar por ticker/nombre")

    unique_markets = [m for m in df['exchange'].dropna().unique() if m]
    unique_currencies = [c for c in df['currency'].dropna().unique() if c]

    market_filter = st.sidebar.multiselect("Mercado", options=unique_markets)
    currency_filter = st.sidebar.multiselect("Moneda", options=unique_currencies)

    filtered_df = df.copy()
    if search:
        search_mask = (
            filtered_df['user_ticker'].fillna('').astype(str).str.contains(search, case=False) |
            filtered_df['company_name'].fillna('').astype(str).str.contains(search, case=False)
        )
        filtered_df = filtered_df[search_mask]
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

    # 1. Asegurar tipos numéricos (float64) para todos los precios
    for col in ['latest_price', 'previous_close', 'analysis_reference_price', 'target_price']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # 2. Calcular variaciones conservando tipo float (np.nan para valores no disponibles).
    # Esto permite ordenación numérica real en lugar de ordenación léxica de strings ("N/A", "%").
    def _calc_to_float(calc_val):
        if calc_val is None:
            return np.nan
        try:
            return float(calc_val)
        except (TypeError, ValueError):
            return np.nan

    df['daily_variation'] = pd.to_numeric(
        df.apply(lambda r: _calc_to_float(daily_variation(r['latest_price'], r['previous_close']).daily_variation), axis=1),
        errors='coerce'
    )
    df['variation_since_analysis'] = pd.to_numeric(
        df.apply(lambda r: _calc_to_float(variation_since_analysis(r['latest_price'], r['analysis_reference_price']).variation_since_analysis), axis=1),
        errors='coerce'
    )
    df['decline_to_target'] = pd.to_numeric(
        df.apply(lambda r: _calc_to_float(decline_to_target(r['target_price'], r['latest_price']).decline_to_target), axis=1),
        errors='coerce'
    )

    # 3. Controles de ordenación interactiva
    col_sort1, col_sort2, col_sort3 = st.columns([2, 1.2, 1.2])
    with col_sort1:
        sort_options = {
            "Sin ordenar (orden original)": None,
            "Ticker": "user_ticker",
            "Empresa": "company_name",
            "Último Precio": "latest_price",
            "Var. Diaria (%)": "daily_variation",
            "Var. vs Análisis (%)": "variation_since_analysis",
            "Caída a Objetivo (%)": "decline_to_target",
            "Precio Objetivo": "target_price",
        }
        selected_sort = st.selectbox("Ordenar por:", options=list(sort_options.keys()), index=0)

    with col_sort2:
        sort_order = st.radio("Sentido:", options=["Ascendente", "Descendente"], horizontal=True, index=0)

    with col_sort3:
        st.write("")  # alineación con radio
        na_last = st.checkbox("Valores N/A al final", value=True)

    sort_col = sort_options[selected_sort]
    if sort_col:
        ascending = (sort_order == "Ascendente")
        na_position = "last" if na_last else "first"
        df = df.sort_values(by=sort_col, ascending=ascending, na_position=na_position)

    # 4. Columnas a visualizar y configuración de tipos en Streamlit
    display_columns = [
        'user_ticker', 'company_name', 'exchange', 'currency',
        'latest_price', 'daily_variation', 'variation_since_analysis',
        'decline_to_target', 'target_price'
    ]
    cols_to_show = [c for c in display_columns if c in df.columns]

    column_config = {
        "user_ticker": st.column_config.TextColumn("Ticker"),
        "company_name": st.column_config.TextColumn("Empresa"),
        "exchange": st.column_config.TextColumn("Mercado"),
        "currency": st.column_config.TextColumn("Divisa"),
        "latest_price": st.column_config.NumberColumn(
            "Último Precio",
            format="%.2f",
            help="Precio más reciente de cotización"
        ),
        "daily_variation": st.column_config.NumberColumn(
            "Var. Diaria",
            format="%.2f%%",
            help="Variación respecto al cierre de la sesión anterior"
        ),
        "variation_since_analysis": st.column_config.NumberColumn(
            "Var. vs Análisis",
            format="%.2f%%",
            help="Variación respecto al precio de referencia del análisis"
        ),
        "decline_to_target": st.column_config.NumberColumn(
            "Caída a Objetivo",
            format="%.2f%%",
            help="Distancia porcentual hasta el precio objetivo"
        ),
        "target_price": st.column_config.NumberColumn(
            "Precio Objetivo",
            format="%.2f",
            help="Precio objetivo establecido"
        ),
    }

    st.dataframe(
        df[cols_to_show],
        column_config=column_config,
        width="stretch",
        hide_index=True
    )


def render_manual_entry():
    """Formulario para añadir nuevos valores de forma manual o actualizar existentes."""
    st.header("Añadir / Gestionar Valores Manualmente")
    st.write(
        "Añade nuevos instrumentos que no estén en tu archivo de importación, "
        "o introduce/modifica cotizaciones y precios objetivo de forma manual."
    )

    tab_new, tab_edit = st.tabs(["➕ Añadir Nuevo Instrumento", "✏️ Modificar Instrumento Existente"])

    with tab_new:
        with st.form("manual_add_instrument_form", clear_on_submit=False):
            st.subheader("Datos del Instrumento")
            col1, col2 = st.columns(2)

            with col1:
                user_ticker = st.text_input(
                    "Ticker / Símbolo *",
                    placeholder="Ej: AAPL, BME:SAN, MSFT, LON:AZN, EPA:RMS",
                    help="Ticker del activo. Puedes incluir prefijo de bolsa (ej: BME: para España, EPA: para Francia)."
                )
                company_name = st.text_input(
                    "Nombre de la empresa",
                    placeholder="Ej: Apple Inc., Banco Santander",
                    help="Nombre o descripción legible de la empresa."
                )
                exchange_options = ["AUTO (Detectar por ticker/divisa)"] + [e.value for e in Exchange if e != Exchange.UNKNOWN]
                selected_exchange = st.selectbox(
                    "Mercado / Exchange",
                    options=exchange_options,
                    help="Mercado o país del valor. 'AUTO' intentará detectarlo a partir del ticker o la divisa."
                )
                currencies = ["EUR", "USD", "GBP", "CHF", "JPY", "AUD", "CAD", "Otra..."]
                currency_choice = st.selectbox("Divisa", options=currencies, index=0)
                custom_currency = ""
                if currency_choice == "Otra...":
                    custom_currency = st.text_input("Especifica la divisa:", value="USD")

            with col2:
                target_price = st.number_input(
                    "Precio Objetivo",
                    min_value=0.0,
                    step=0.01,
                    value=0.0,
                    format="%.2f",
                    help="Precio al que deseas entrar o vender."
                )
                analysis_reference_price = st.number_input(
                    "Precio de Referencia del Análisis",
                    min_value=0.0,
                    step=0.01,
                    value=0.0,
                    format="%.2f",
                    help="Precio de la acción en el momento que se realizó el análisis."
                )
                analysis_date = st.date_input(
                    "Fecha del Análisis",
                    value=datetime.today().date()
                )
                comment = st.text_area(
                    "Comentarios / Tesis",
                    placeholder="Notas personales, zona de soporte, PER, catalizador...",
                    help="Notas y observaciones de seguimiento."
                )

            st.markdown("---")
            st.subheader("Cotización y Precios")
            pc1, pc2, pc3 = st.columns(3)
            with pc1:
                fetch_yahoo = st.checkbox(
                    "Descargar cotización de Yahoo Finance",
                    value=True,
                    help="Consulta Yahoo Finance para obtener el último precio y cierre previo automáticamente."
                )
            with pc2:
                manual_price = st.number_input(
                    "Último precio manual",
                    min_value=0.0,
                    step=0.01,
                    value=0.0,
                    format="%.2f",
                    help="Rellena esto si el valor no cotiza en Yahoo Finance o prefieres fijar un precio manual."
                )
            with pc3:
                manual_prev = st.number_input(
                    "Cierre anterior manual",
                    min_value=0.0,
                    step=0.01,
                    value=0.0,
                    format="%.2f",
                    help="Opcional: necesario para calcular la variación diaria si se introduce precio manual."
                )

            submitted = st.form_submit_button("Guardar Nuevo Instrumento", type="primary")

            if submitted:
                if not user_ticker.strip():
                    st.error("El Ticker es un campo obligatorio.")
                else:
                    ticker_clean = user_ticker.strip()
                    curr = custom_currency.strip().upper() if currency_choice == "Otra..." else currency_choice.strip().upper()

                    norm_ticker, detected_exchange = normalize(ticker_clean, curr)
                    if selected_exchange.startswith("AUTO"):
                        exchange = detected_exchange
                    else:
                        try:
                            exchange = Exchange(selected_exchange)
                        except ValueError:
                            exchange = detected_exchange

                    suffix = get_yahoo_suffix(ticker_clean, exchange, curr)
                    if suffix and not norm_ticker.upper().endswith(suffix.upper()):
                        provider_symbol = f"{norm_ticker}{suffix}"
                    else:
                        provider_symbol = norm_ticker

                    ref_dec = Decimal(str(analysis_reference_price)) if analysis_reference_price > 0 else None
                    tgt_dec = Decimal(str(target_price)) if target_price > 0 else None

                    inst = Instrument(
                        user_ticker=ticker_clean,
                        provider_symbol=provider_symbol,
                        exchange=exchange,
                        currency=curr,
                        company_name=company_name.strip() or ticker_clean,
                        analysis_date=analysis_date,
                        analysis_reference_price=ref_dec,
                        target_price=tgt_dec,
                        comment=comment.strip(),
                        active=True,
                    )

                    try:
                        upsert_instrument(inst)
                        saved_inst = get_instrument_by_ticker(ticker_clean)
                        inst_id = saved_inst.id if saved_inst else None

                        if manual_price > 0 and inst_id:
                            q = Quote(
                                instrument_id=inst_id,
                                price=Decimal(str(manual_price)),
                                previous_close=Decimal(str(manual_prev)) if manual_prev > 0 else None,
                                quote_timestamp=datetime.now(),
                                fetched_at=datetime.now(),
                                provider="Manual",
                                status=QuoteStatus.FRESH,
                            )
                            upsert_quote(q)
                            st.success(f"Instrumento '{ticker_clean}' guardado con precio manual de {manual_price:.2f} {curr}.")
                        elif fetch_yahoo and provider_symbol and inst_id:
                            try:
                                adapter = YahooAdapter()
                                quotes = adapter.fetch([provider_symbol])
                                if provider_symbol in quotes and quotes[provider_symbol].is_valid():
                                    q = quotes[provider_symbol]
                                    q.instrument_id = inst_id
                                    upsert_quote(q)
                                    st.success(f"Instrumento '{ticker_clean}' guardado con cotización de Yahoo: {float(q.price):.2f} {curr}.")
                                else:
                                    st.success(f"Instrumento '{ticker_clean}' guardado. Yahoo Finance no devolvió precio para '{provider_symbol}' (puedes añadirlo manualmente en la pestaña de edición).")
                            except Exception as yerr:
                                st.warning(f"Instrumento '{ticker_clean}' guardado, pero ocurrió un aviso con Yahoo Finance: {yerr}")
                        else:
                            st.success(f"Instrumento '{ticker_clean}' guardado en la base de datos.")

                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al guardar el instrumento: {e}")

    with tab_edit:
        st.subheader("Editar o introducir precios para un instrumento existente")
        instruments = get_all_instruments()

        if not instruments:
            st.info("No hay instrumentos guardados en el Watchlist.")
            return

        inst_dict = {
            f"{i.user_ticker} - {i.company_name} ({i.exchange.value}, {i.currency})": i
            for i in instruments
        }
        selected_key = st.selectbox("Selecciona instrumento a editar:", options=list(inst_dict.keys()))
        inst_to_edit = inst_dict[selected_key]
        quote_to_edit = get_quote_by_instrument_id(inst_to_edit.id) if inst_to_edit.id else None

        with st.form("edit_instrument_values_form", clear_on_submit=False):
            e_col1, e_col2 = st.columns(2)
            with e_col1:
                cur_price = float(quote_to_edit.price) if quote_to_edit and quote_to_edit.price else 0.0
                new_price = st.number_input(
                    "Último Precio",
                    min_value=0.0,
                    step=0.01,
                    value=cur_price,
                    format="%.2f",
                    help="Introduce el precio actual si está en N/A o necesitas corregirlo."
                )
                cur_prev = float(quote_to_edit.previous_close) if quote_to_edit and quote_to_edit.previous_close else 0.0
                new_prev = st.number_input(
                    "Cierre Anterior",
                    min_value=0.0,
                    step=0.01,
                    value=cur_prev,
                    format="%.2f",
                    help="Cierre previo para calcular la variación diaria."
                )
                edit_company_name = st.text_input("Nombre de Empresa", value=inst_to_edit.company_name)

            with e_col2:
                cur_tgt = float(inst_to_edit.target_price) if inst_to_edit.target_price else 0.0
                new_target = st.number_input("Precio Objetivo", min_value=0.0, step=0.01, value=cur_tgt, format="%.2f")

                cur_ref = float(inst_to_edit.analysis_reference_price) if inst_to_edit.analysis_reference_price else 0.0
                new_ref = st.number_input("Precio Referencia Análisis", min_value=0.0, step=0.01, value=cur_ref, format="%.2f")

                edit_comment_val = st.text_area("Comentario / Tesis", value=inst_to_edit.comment)

            b1, b2 = st.columns([1, 1])
            with b1:
                btn_save_changes = st.form_submit_button("Guardar Cambios", type="primary")
            with b2:
                btn_refresh_single = st.form_submit_button("Consultar Yahoo Finance ahora")

            if btn_save_changes:
                inst_to_edit.company_name = edit_company_name.strip() or inst_to_edit.user_ticker
                inst_to_edit.target_price = Decimal(str(new_target)) if new_target > 0 else None
                inst_to_edit.analysis_reference_price = Decimal(str(new_ref)) if new_ref > 0 else None
                inst_to_edit.comment = edit_comment_val.strip()
                upsert_instrument(inst_to_edit)

                if new_price > 0 and inst_to_edit.id:
                    q = Quote(
                        instrument_id=inst_to_edit.id,
                        price=Decimal(str(new_price)),
                        previous_close=Decimal(str(new_prev)) if new_prev > 0 else None,
                        quote_timestamp=datetime.now(),
                        fetched_at=datetime.now(),
                        provider="Manual",
                        status=QuoteStatus.FRESH,
                    )
                    upsert_quote(q)

                st.success(f"Instrumento '{inst_to_edit.user_ticker}' actualizado.")
                st.rerun()

            if btn_refresh_single:
                if inst_to_edit.provider_symbol and inst_to_edit.id:
                    try:
                        adapter = YahooAdapter()
                        quotes = adapter.fetch([inst_to_edit.provider_symbol])
                        if inst_to_edit.provider_symbol in quotes and quotes[inst_to_edit.provider_symbol].is_valid():
                            q = quotes[inst_to_edit.provider_symbol]
                            q.instrument_id = inst_to_edit.id
                            upsert_quote(q)
                            st.success(f"Precio actualizado desde Yahoo: {float(q.price):.2f} {inst_to_edit.currency}")
                            st.rerun()
                        else:
                            st.warning(f"Yahoo Finance no devolvió precio para {inst_to_edit.provider_symbol}.")
                    except Exception as ex:
                        st.error(f"Error al consultar Yahoo Finance: {ex}")

        with st.expander("🗑️ Eliminar instrumento del Watchlist"):
            st.warning(f"¿Deseas eliminar '{inst_to_edit.user_ticker}' definitivamente de la base de datos?")
            if st.button(f"Eliminar {inst_to_edit.user_ticker}", type="secondary", key=f"del_{inst_to_edit.user_ticker}"):
                if delete_instrument(inst_to_edit.user_ticker):
                    st.success(f"Instrumento '{inst_to_edit.user_ticker}' eliminado.")
                    st.rerun()


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