# streamlit_app.py
# App Streamlit: controles alineados a la izquierda y tabla de posición (no editable)
import streamlit as st
import pandas as pd
import plotly.express as px
import io
import base64
import requests
import os
import json
from datetime import datetime

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
# GitHub persistence helpers
# -------------------------
def get_github_headers():
    token = None
    # Preferir st.secrets (configurá en Streamlit Cloud)
    try:
        token = st.secrets["GITHUB_PAT"]
    except Exception:
        # Intentar desde variable de entorno (si prefieres esa opción)
        token = os.getenv("GITHUB_PAT")
    if not token:
        return None
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}

def get_file_sha(repo, path):
    """Devuelve el SHA del archivo si existe, o None."""
    headers = get_github_headers()
    if not headers:
        return None
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    r = requests.get(url, headers=headers, timeout=20)
    if r.status_code == 200:
        return r.json().get("sha")
    return None

def commit_csv_to_github(df, repo=None, path=None, message=None, author_name=None, author_email=None):
    """
    Crea o actualiza el archivo 'path' en el repo con el CSV generado desde df.
    Devuelve dict result {ok: bool, status_code: int, message: str}
    """
    headers = get_github_headers()
    if not headers:
        return {"ok": False, "message": "GITHUB_PAT no configurado en secrets.", "status_code": None}

    repo = repo or st.secrets.get("GITHUB_REPO", None)
    path = path or st.secrets.get("GITHUB_FILEPATH", "portfolio_raw.csv")
    if not repo or not path:
        return {"ok": False, "message": "GITHUB_REPO o GITHUB_FILEPATH no configurados.", "status_code": None}

    csv_bytes = df_to_csv_bytes(df)
    content_b64 = base64.b64encode(csv_bytes).decode("utf-8")
    sha = get_file_sha(repo, path)

    commit_message = message or f"Auto-update portfolio_raw.csv - {datetime.utcnow().isoformat()}Z"
    payload = {
        "message": commit_message,
        "content": content_b64,
    }
    # Optional author
    author = {}
    if author_name := st.secrets.get("GITHUB_COMMIT_NAME", None):
        author["name"] = author_name
    if author_email := st.secrets.get("GITHUB_COMMIT_EMAIL", None):
        author["email"] = author_email
    if author:
        payload["committer"] = author

    if sha:
        payload["sha"] = sha  # update existing file

    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    try:
        r = requests.put(url, headers=headers, data=json.dumps(payload), timeout=20)
        if r.status_code in (200, 201):
            return {"ok": True, "message": "File committed", "status_code": r.status_code}
        else:
            return {"ok": False, "message": f"GitHub API error: {r.status_code} - {r.text}", "status_code": r.status_code}
    except Exception as e:
        return {"ok": False, "message": f"Exception: {e}", "status_code": None}

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
    # -------------------------
    # Agregar nuevo ticker
    # -------------------------
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
                # Forzar refresh de widgets dependientes
                st.session_state.editor_key += 1
                # Persistir en GitHub (intentar, pero no romper la app si falla)
                try:
                    res = commit_csv_to_github(st.session_state.df)
                    # opcional: guardar resultado en session state para debug
                    st.session_state.last_commit_result = res
                except Exception as e:
                    st.session_state.last_commit_result = {"ok": False, "message": str(e)}
                st.success(f"Ticker {t} agregado con {a:,.2f} ARS.")

    st.markdown("---")
    # -------------------------
    # Eliminar Tickers
    # -------------------------
    st.subheader("Eliminar Tickers")
    if len(st.session_state.df) > 0:
        options = st.session_state.df['ticker'].tolist()
        to_delete = st.multiselect("Seleccioná tickers a eliminar", options=options, key=f"multidel_{st.session_state.editor_key}")
        if st.button("Eliminar seleccionados"):
            if not to_delete:
                st.warning("No seleccionaste tickers para eliminar.")
            else:
                base = st.session_state.df.copy()
                base = base[~base['ticker'].isin(to_delete)].reset_index(drop=True)
                st.session_state.df = base
                st.session_state.editor_key += 1
                try:
                    res = commit_csv_to_github(st.session_state.df)
                    st.session_state.last_commit_result = res
                except Exception as e:
                    st.session_state.last_commit_result = {"ok": False, "message": str(e)}
                st.success(f"Eliminados: {', '.join(to_delete)}")
    else:
        st.info("No hay tickers para eliminar.")

    st.markdown("---")
    # -------------------------
    # SELECTBOX para editar
    # -------------------------
    st.subheader("Editar Ticker")
    # Construir opciones en cada render para reflejar cambios inmediatos
    tickers_options = st.session_state.df['ticker'].tolist() if len(st.session_state.df) > 0 else []
    options_for_select = [""] + tickers_options

    if 'selected_edit_ticker' not in st.session_state:
        st.session_state.selected_edit_ticker = ""

    st.session_state.selected_edit_ticker = st.selectbox(
        "Seleccioná ticker a editar",
        options=options_for_select,
        index=0,
        key=f"select_edit_out_{st.session_state.editor_key}"
    )

    # -------------------------
    # Form para editar (usa la selección del selectbox)
    # -------------------------
    form_key = f"edit_form_{st.session_state.editor_key}"
    with st.form(key=form_key):
        ticker_to_edit = st.session_state.selected_edit_ticker

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

    if submit_edit:
        if ticker_to_edit == "" or ticker_to_edit not in st.session_state.df['ticker'].values:
            st.warning("Primero seleccioná un ticker válido.")
        else:
            base = st.session_state.df.copy()
            base.loc[base['ticker'] == ticker_to_edit, 'amount_ARS'] = float(new_amount_for_ticker)
            base['ticker'] = base['ticker'].astype(str).str.strip().str.upper()
            base['amount_ARS'] = pd.to_numeric(base['amount_ARS'], errors='coerce').fillna(0)
            st.session_state.df = base.reset_index(drop=True)
            st.session_state.editor_key += 1
            try:
                res = commit_csv_to_github(st.session_state.df)
                st.session_state.last_commit_result = res
            except Exception as e:
                st.session_state.last_commit_result = {"ok": False, "message": str(e)}
            st.session_state.selected_edit_ticker = ""
            st.success(f"Ticker {ticker_to_edit} actualizado a {new_amount_for_ticker:,.2f} ARS.")

    st.markdown("---")
    # Exportar CSV actualizado
    csv_bytes = df_to_csv_bytes(st.session_state.df)
    st.download_button("Descargar portfolio (CSV actualizado)", csv_bytes, file_name="portfolio_raw_updated.csv", mime="text/csv")

with right:
    # ---------- Right column: KPIs, métricas de porcentaje y visualizaciones ----------
    st.subheader("KPIs y visualizaciones")

    # Tomar DF actual
    df_display = st.session_state.df.copy()
    # Asegurar columnas
    if df_display.empty:
        total_value = 0.0
        num_instruments = 0
    else:
        df_display['amount_ARS'] = pd.to_numeric(df_display['amount_ARS'], errors='coerce').fillna(0)
        total_value = df_display['amount_ARS'].sum()
        num_instruments = len(df_display)

    # KPI básicos
    colA, colB, colC, colD = st.columns(4)
    colA.metric("Valor total (ARS)", f"{total_value:,.0f}")
    colB.metric("Nº instrumentos", f"{num_instruments}")

    # --- Cálculo de pesos porcentuales ---
    if total_value > 0 and num_instruments > 0:
        df_weights = df_display.copy()
        df_weights['weight_pct'] = (df_weights['amount_ARS'] / total_value) * 100
        df_weights = df_weights.sort_values('weight_pct', ascending=False).reset_index(drop=True)

        # Top N metrics
        top1_pct = df_weights['weight_pct'].iloc[0] if len(df_weights) >= 1 else 0.0
        top3_pct = df_weights['weight_pct'].iloc[:3].sum() if len(df_weights) >= 3 else df_weights['weight_pct'].sum()
        top5_pct = df_weights['weight_pct'].iloc[:5].sum() if len(df_weights) >= 5 else df_weights['weight_pct'].sum()

        colC.metric("Concentración Top 3 (%)", f"{top3_pct:.2f}%")
        colD.metric("Activo dominante (Top 1 %)", f"{top1_pct:.2f}%")
    else:
        # vacíos
        df_weights = pd.DataFrame(columns=['ticker', 'amount_ARS', 'weight_pct'])
        colC.metric("Concentración Top 3 (%)", "N/A")
        colD.metric("Activo dominante (Top 1 %)", "N/A")

    st.markdown("---")

    # --- Visual: tabla de pesos (izquierda de la columna derecha) ---
    st.subheader("Distribución y top holdings")
    if not df_weights.empty:
        # Mostrar tabla con formato
        display_table = df_weights[['Ticker', 'Monto ($)', '% de composicón']].copy()
        display_table['amount_ARS'] = display_table['amount_ARS'].map("{:,.2f}".format)
        display_table['weight_pct'] = display_table['weight_pct'].map("{:.2f}%".format)
        st.dataframe(display_table.reset_index(drop=True), use_container_width=True)

        # Resumen top 5 como texto compacto
        top5_list = df_weights.head(5)[['ticker','weight_pct']].copy()
        top5_text = ", ".join([f"{row.ticker} ({row.weight_pct:.2f}%)" for row in top5_list.itertuples()])
        st.markdown(f"**Top 5 (por peso):** {top5_text}")
    else:
        st.info("No hay instrumentos para mostrar porcentaje.")

    st.markdown("---")

    # --- Mantener gráficos (pie + bar) actualizados según df_display ---
    if num_instruments == 0:
        st.info("No hay instrumentos para graficar.")
    else:
        st.subheader("Distribución por ticker (gráfico)")
        fig_pie = px.pie(df_weights, names='ticker', values='amount_ARS', title='Peso por ticker')
        st.plotly_chart(fig_pie, use_container_width=True)

        st.subheader("Top holdings (monto ARS)")
        fig_bar = px.bar(df_weights.sort_values('amount_ARS', ascending=False), x='ticker', y='amount_ARS', title='Top holdings')
        st.plotly_chart(fig_bar, use_container_width=True)
