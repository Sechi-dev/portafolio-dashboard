# streamlit_app.py
# Minimal Streamlit app to visualize portfolio_raw.csv (CEDEAR mapping workflow)
# Requerimientos: streamlit, pandas, plotly

import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(layout="wide", page_title="Dashboard de Cartera - BYMA")

st.title("Dashboard de Cartera — Snapshot (CEDEAR)")

# -------------------------
# Función para cargar CSV
# -------------------------
@st.cache_data
def load_portfolio(path="portfolio_raw.csv"):
    try:
        df = pd.read_csv(path)
    except Exception as e:
        st.error(f"Error al leer {path}: {e}")
        return pd.DataFrame(columns=['ticker','amount_ARS'])
    # Validación simple
    if 'ticker' not in df.columns or 'amount_ARS' not in df.columns:
        st.error("El CSV debe tener columnas: 'ticker' y 'amount_ARS'")
        return pd.DataFrame(columns=['ticker','amount_ARS'])
    # Asegurar tipos
    df = df[['ticker','amount_ARS']].copy()
    df['amount_ARS'] = pd.to_numeric(df['amount_ARS'], errors='coerce').fillna(0)
    return df

df = load_portfolio()

# -------------------------
# KPIs
# -------------------------
total_value = df['amount_ARS'].sum()
num_instruments = len(df)
col1, col2, col3 = st.columns(3)
col1.metric("Valor total (ARS)", f"{total_value:,.0f}")
col2.metric("Nº instrumentos", f"{num_instruments}")
col3.metric("Última actualización", "Snapshot")

st.markdown("---")

# -------------------------
# Visualizaciones básicas
# -------------------------
if num_instruments == 0:
    st.info("No hay datos en portfolio_raw.csv o el formato es incorrecto.")
else:
    st.subheader("Distribución por ticker")
    fig_pie = px.pie(df, names='ticker', values='amount_ARS', title='Peso por ticker')
    st.plotly_chart(fig_pie, use_container_width=True)

    st.subheader("Top holdings (monto ARS)")
    fig_bar = px.bar(df.sort_values('amount_ARS', ascending=False), x='ticker', y='amount_ARS', title='Top holdings')
    st.plotly_chart(fig_bar, use_container_width=True)

    st.subheader("Tabla de posiciones")
    st.dataframe(df.sort_values('amount_ARS', ascending=False).reset_index(drop=True))

st.markdown("""
**Nota:** Esta app es la base. Para tener precios CEDEAR en tiempo real hay que integrar la función de pricing (BYMA/InvertirOnline).  
Cuando quieras, te doy el snippet exacto para esa integración.
""")
