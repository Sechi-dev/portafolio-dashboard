# streamlit_app.py
# App Streamlit: controles alineados a la izquierda y tabla de posición (no editable)
import streamlit as st
import pandas as pd
import plotly.express as px
import io

st.set_page_config(layout="wide", page_title="Dashboard de Cartera - Editable (form)")

st.title("Dashboard de Cartera")

# -------------------------
# Helpers
# -------------------------
@st.cache_data
def load_portfolio(path="portfolio_raw.csv"):
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=['ticker','amount_ARS'])
    if 'ticker' not in df.columns or 'amount_ARS' not in df.columns:
        return pd.DataFrame(columns=['ticker','amount_ARS'])
    df = df[['ticker','amount_ARS']].copy()
    df['amount_ARS'] = pd.to_numeric(df['amount_ARS'], errors='coerce').fillna(0)
    df['ticker'] = df['ticker'].astype(str).str.strip().str.upper()
    return df

def df_to_csv_bytes(df):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode('utf-8')

# -------------------------
# Inicializar session state
# -------------------------
if 'df' not in st.session_state:
    st.session_state.df = load_portfolio()
if 'editor_key' not in st.session_state:
    st.session_state.editor_key = 0

# -------------------------
# Layout: controles y tabla a la izquierda; KPIs/gráficos a la derecha
# -------------------------
left, right = st.columns([1.4, 2])

with left:
    # ---------------------------
    # Editar Monto por ticker - selectbox FUERA del form, number_input DENTRO del form
    # ---------------------------
    st.subheader("Editar Monto por ticker")

    # Opciones actuales
    tickers_options = st.session_state.df['ticker'].tolist() if len(st.session_state.df) > 0 else []
    options_for_select = [""] + tickers_options

    # SELECTBOX fuera del form: se reconstruye con editor_key y actualiza inmediatamente al agregar/eliminar
    # Guardamos la selección en session_state.selected_edit_ticker para que el form la vea
    if 'selected_edit_ticker' not in st.session_state:
        st.session_state.selected_edit_ticker = ""
    st.session_state.selected_edit_ticker = st.selectbox(
        "Seleccioná ticker a editar",
        options=options_for_select,
        index=0,
        key=f"select_edit_out_{st.session_state.editor_key}"
    )

    # Ahora usamos un form para la edición (atomicidad)
    form_key = f"edit_form_{st.session_state.editor_key}"
    with st.form(key=form_key):
        ticker_to_edit = st.session_state.selected_edit_ticker  # leemos la selección actual

        # Si hay ticker válido, obtener su monto actual para default; si no, default 0
        if ticker_to_edit != "" and ticker_to_edit in st.session_state.df['ticker'].values:
            default_amount = float(st.session_state.df.loc[st.session_state.df['ticker'] == ticker_to_edit, 'amount_ARS'].iloc[0])
        else:
            default_amount = 0.0

        number_key = f"edit_amount_input_{ticker_to_edit if ticker_to_edit != '' else 'none'}_{st.session_state.editor_key}"
        new_amount_for_ticker = st.number_input(
            "Nuevo monto (ARS)",
            min_value=0.0,
            value=default_amount,
            step=1000.0,
            format="%.2f",
            key=number_key
        )

        submit_edit = st.form_submit_button(label="Actualizar monto seleccionado")

    # Procesar submit fuera del with
    if submit_edit:
        if ticker_to_edit == "" or ticker_to_edit not in st.session_state.df['ticker'].values:
            st.warning("Primero seleccioná un ticker válido.")
        else:
            base = st.session_state.df.copy()
            base.loc[base['ticker'] == ticker_to_edit, 'amount_ARS'] = float(new_amount_for_ticker)
            base['ticker'] = base['ticker'].astype(str).str.strip().str.upper()
            base['amount_ARS'] = pd.to_numeric(base['amount_ARS'], errors='coerce').fillna(0)
            st.session_state.df = base.reset_index(drop=True)
            # Forzar refresh de widgets dependientes
            st.session_state.editor_key += 1
            # al actualizar, limpiar la selección para que el selectbox quede en blanco (si querés)
            st.session_state.selected_edit_ticker = ""
            st.success(f"Ticker {ticker_to_edit} actualizado a {new_amount_for_ticker:,.2f} ARS.")

    st.markdown("---")
    st.subheader("Agregar nuevo ticker")
    new_ticker = st.text_input("Ticker (sin sufijo)", value="", placeholder="Ej: ABCD", key="add_ticker_input")
    new_amount = st.number_input("Monto invertido (ARS)", min_value=0.0, value=0.0, step=1000.0, format="%.2f", key="add_amount_input")
    if st.button("Agregar ticker"):
        t = str(new_ticker).strip().upper()
        a = float(new_amount)
        if t == "" or a <= 0:
            st.warning("Ingresá ticker y un monto mayor a 0.")
        else:
            base = st.session_state.df.copy()
            if t in base['ticker'].values:
                st.warning("El ticker ya existe. Para modificar su monto usá 'Editar Monto por ticker'.")
            else:
                new_row = {'ticker': t, 'amount_ARS': a}
                base = pd.concat([base, pd.DataFrame([new_row])], ignore_index=True)
                base['ticker'] = base['ticker'].astype(str).str.strip().str.upper()
                base['amount_ARS'] = pd.to_numeric(base['amount_ARS'], errors='coerce').fillna(0)
                st.session_state.df = base.reset_index(drop=True)
                # forzar refresh de widgets dependientes
                st.session_state.editor_key += 1
                st.success(f"Ticker {t} agregado con {a:,.2f} ARS.")

    st.markdown("---")
    st.subheader("Eliminar Tickers")
    if len(st.session_state.df) > 0:
        options = st.session_state.df['ticker'].tolist()
        to_delete = st.multiselect(
            "Seleccioná tickers a eliminar",
            options=options,
            key=f"multidel_{st.session_state.editor_key}"
        )
        if st.button("Eliminar seleccionados"):
            if not to_delete:
                st.warning("No seleccionaste tickers para eliminar.")
            else:
                base = st.session_state.df.copy()
                base = base[~base['ticker'].isin(to_delete)].reset_index(drop=True)
                st.session_state.df = base
                # forzar refresh de widgets dependientes
                st.session_state.editor_key += 1
                st.success(f"Eliminados: {', '.join(to_delete)}")
    else:
        st.info("No hay tickers para eliminar.")

    st.markdown("---")
    st.subheader("Tabla de Posición")
    # Tabla de posición: solo visual (ordenable en la UI)
    if len(st.session_state.df) == 0:
        st.info("No hay posiciones cargadas.")
    else:
        st.dataframe(st.session_state.df.sort_values('amount_ARS', ascending=False).reset_index(drop=True), use_container_width=True)

    st.markdown("---")
    # Exportar CSV actualizado
    csv_bytes = df_to_csv_bytes(st.session_state.df)
    st.download_button("Descargar portfolio (CSV actualizado)", csv_bytes, file_name="portfolio_raw_updated.csv", mime="text/csv")

with right:
    # KPIs y gráficos (se actualizan leyendo st.session_state.df)
    st.subheader("KPIs y visualizaciones")
    df_display = st.session_state.df.copy()
    total_value = df_display['amount_ARS'].sum()
    num_instruments = len(df_display)
    colA, colB, colC, colD = st.columns(4)
    colA.metric("Valor total (ARS)", f"{total_value:,.0f}")
    colB.metric("Nº instrumentos", f"{num_instruments}")
    if num_instruments > 0 and total_value > 0:
        top3_pct = df_display.sort_values('amount_ARS', ascending=False).head(3)['amount_ARS'].sum() / total_value * 100
        colC.metric("Concentración Top 3 (%)", f"{top3_pct:.2f}%")
    else:
        colC.metric("Concentración Top 3 (%)", "N/A")
    colD.metric("Última actualización", "Snapshot")

    st.markdown("---")
    if num_instruments == 0:
        st.info("No hay instrumentos para graficar.")
    else:
        st.subheader("Distribución por ticker")
        fig_pie = px.pie(df_display, names='ticker', values='amount_ARS', title='Peso por ticker')
        st.plotly_chart(fig_pie, use_container_width=True)

        st.subheader("Top holdings (monto ARS)")
        fig_bar = px.bar(df_display.sort_values('amount_ARS', ascending=False), x='ticker', y='amount_ARS', title='Top holdings')
        st.plotly_chart(fig_bar, use_container_width=True)
