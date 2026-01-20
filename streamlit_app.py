# streamlit_app.py
# App Streamlit mejorada: tabla editable (añadir / eliminar), gráficos reactivos y descarga CSV
import streamlit as st
import pandas as pd
import plotly.express as px
import io

st.set_page_config(layout="wide", page_title="Dashboard de Cartera - Editable")

st.title("Dashboard de Cartera — Editor interactivo")

# ---------- Helpers ----------
@st.cache_data
def load_portfolio(path="portfolio_raw.csv"):
    try:
        df = pd.read_csv(path)
    except Exception:
        # Si no existe, devolver df vacío con columnas esperadas
        return pd.DataFrame(columns=['ticker','amount_ARS'])
    # Asegurar columnas y tipos
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

# ---------- Cargar / inicializar df en session_state ----------
if 'df' not in st.session_state:
    st.session_state.df = load_portfolio()

# Work with a local copy for display / editing
df = st.session_state.df.copy()

# ---------- Left column: editor / inputs ----------
left, right = st.columns([1,2])

# ---------------------------
# Editor con clave dinámica
# ---------------------------
# Inicializar key del editor para forzar re-render cuando actualizamos el df
if 'editor_key' not in st.session_state:
    st.session_state.editor_key = 0

# Mostrar editor con key que depende del contador
try:
    edited = st.data_editor(st.session_state.df.copy(), num_rows="dynamic", use_container_width=True, key=f"editor_{st.session_state.editor_key}")
except Exception:
    edited = st.experimental_data_editor(st.session_state.df.copy(), num_rows="dynamic", use_container_width=True, key=f"editor_{st.session_state.editor_key}")

st.markdown("**Agregar nuevo ticker**")
new_ticker = st.text_input("Ticker (sin sufijo)", value="", placeholder="Ej: ABCD")
new_amount = st.number_input("Monto invertido (ARS)", min_value=0.0, value=0.0, step=1000.0, format="%.2f")

add_col1, add_col2 = st.columns([1,1])
with add_col1:
    if st.button("Agregar ticker"):
        t = str(new_ticker).strip().upper()
        a = float(new_amount)
        if t == "" or a <= 0:
            st.warning("Ingresá ticker y un monto mayor a 0.")
        else:
            base = st.session_state.df.copy()
            if t in base['ticker'].values:
                st.warning("El ticker ya existe. Puedes editar su monto en la tabla.")
            else:
                new_row = {'ticker': t, 'amount_ARS': a}
                base = pd.concat([base, pd.DataFrame([new_row])], ignore_index=True)
                base['ticker'] = base['ticker'].astype(str).str.strip().str.upper()
                base['amount_ARS'] = pd.to_numeric(base['amount_ARS'], errors='coerce').fillna(0)
                st.session_state.df = base
                # Incrementar editor_key para forzar re-render del widget
                st.session_state.editor_key += 1
                st.success(f"Ticker {t} agregado con {a:,.2f} ARS.")

with add_col2:
    st.markdown("**Eliminar tickers**")
    options = st.session_state.df['ticker'].tolist()
    to_delete = st.multiselect("Seleccioná tickers a eliminar", options=options)
    if st.button("Eliminar seleccionados"):
        if not to_delete:
            st.warning("No seleccionaste tickers para eliminar.")
        else:
            base = st.session_state.df.copy()
            base = base[~base['ticker'].isin(to_delete)].reset_index(drop=True)
            st.session_state.df = base
            # Incrementar editor_key para forzar re-render del widget
            st.session_state.editor_key += 1
            st.success(f"Eliminados: {', '.join(to_delete)}")

# Guardar cambios desde data_editor (botón)
if st.button("Aplicar cambios de la tabla"):
    try:
        cleaned = edited[['ticker','amount_ARS']].copy()
        cleaned['ticker'] = cleaned['ticker'].astype(str).str.strip().str.upper()
        cleaned['amount_ARS'] = pd.to_numeric(cleaned['amount_ARS'], errors='coerce').fillna(0)
        st.session_state.df = cleaned
        # Increment key to force data_editor widget refresh so further edits work reliably
        st.session_state.editor_key += 1
        st.success("Cambios aplicados.")
    except Exception as e:
        st.error(f"Error al aplicar cambios: {e}")

st.markdown("---")
st.markdown("**Exportar / Guardar**")
csv_bytes = df_to_csv_bytes(st.session_state.df)
st.download_button("Descargar portfolio (CSV actualizado)", csv_bytes, file_name="portfolio_raw_updated.csv", mime="text/csv")
st.markdown("Si querés persistir los cambios en GitHub, descargá este CSV y subilo al repo sustituyendo `portfolio_raw.csv`.")

# ---------- Right column: KPIs y gráficos (se actualizan según st.session_state.df) ----------
with right:
    st.subheader("KPIs y visualizaciones")
    df_display = st.session_state.df.copy()
    total_value = df_display['amount_ARS'].sum()
    num_instruments = len(df_display)
    colA, colB, colC, colD = st.columns(4)
    colA.metric("Valor total (ARS)", f"{total_value:,.0f}")
    colB.metric("Nº instrumentos", f"{num_instruments}")
    # Top3 concentration
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

        st.subheader("Tabla de posiciones (ordenable)")
        st.dataframe(df_display.sort_values('amount_ARS', ascending=False).reset_index(drop=True))
