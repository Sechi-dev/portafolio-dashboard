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
import re
from datetime import datetime
from time import sleep

st.set_page_config(layout="wide", page_title="Dashboard de Cartera - Editable (form)")

st.title("Dashboard de Cartera")

# -------------------------
# Helpers
# -------------------------
def load_portfolio(path="portfolio_raw.csv"):
    """
    Lectura directa del CSV local (sin cache) para evitar discrepancias con commits.
    Si el archivo no existe devuelve DF vacío con las columnas esperadas.
    """
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=['ticker', 'amount_ARS'])
    if 'ticker' not in df.columns or 'amount_ARS' not in df.columns:
        return pd.DataFrame(columns=['ticker', 'amount_ARS'])
    df = df[['ticker', 'amount_ARS']].copy()
    df['amount_ARS'] = pd.to_numeric(df['amount_ARS'], errors='coerce').fillna(0)
    df['ticker'] = df['ticker'].astype(str).str.strip().str.upper()
    return df

def df_to_csv_bytes(df):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode('utf-8')

def sanitize_ticker(t):
    """
    Formato básico de validación/sanitización: sólo letras, números, punto y guion.
    Retorna ticker upper o None si inválido.
    """
    if t is None:
        return None
    t = str(t).strip().upper()
    if t == "":
        return None
    # permitir letras, números, punto, guion, slash (por si)
    if not re.match(r'^[A-Z0-9\.\-\/]+$', t):
        return None
    return t

# -------------------------
# GitHub persistence helpers
# -------------------------
def get_github_headers():
    token = None
    try:
        token = st.secrets["GITHUB_PAT"]
    except Exception:
        token = os.getenv("GITHUB_PAT")
    if not token:
        return None
    # usar Bearer por compatibilidad moderna
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

def get_file_sha(repo, path):
    """Devuelve el SHA del archivo si existe, o None."""
    headers = get_github_headers()
    if not headers:
        return None
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json().get("sha")
    except Exception:
        return None
    return None

def commit_csv_to_github(df, repo=None, path=None, message=None, author_name=None, author_email=None, max_retries=2):
    """
    Crea o actualiza el archivo 'path' en el repo con el CSV generado desde df.
    Devuelve dict result {ok: bool, status_code: int, message: str}
    Reintenta un par de veces ante fallos transitorios.
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

    commit_message = message or f"Auto-update portfolio_raw.csv - {datetime.utcnow().isoformat()}Z"
    payload = {
        "message": commit_message,
        "content": content_b64,
    }
    # Optional author
    author = {}
    if st.secrets.get("GITHUB_COMMIT_NAME", None):
        author["name"] = st.secrets.get("GITHUB_COMMIT_NAME")
    if st.secrets.get("GITHUB_COMMIT_EMAIL", None):
        author["email"] = st.secrets.get("GITHUB_COMMIT_EMAIL")
    if author:
        payload["committer"] = author

    sha = get_file_sha(repo, path)
    if sha:
        payload["sha"] = sha

    url = f"https://api.github.com/repos/{repo}/contents/{path}"

    attempt = 0
    while attempt <= max_retries:
        try:
            r = requests.put(url, headers=headers, data=json.dumps(payload), timeout=20)
            if r.status_code in (200, 201):
                return {"ok": True, "message": "File committed", "status_code": r.status_code}
            else:
                # si es un error permanente, devolverlo sin reintentar en ciertas condiciones
                attempt += 1
                last_text = r.text
                last_status = r.status_code
                # reintentar en 5xx; en 4xx no tiene sentido
                if 500 <= r.status_code < 600 and attempt <= max_retries:
                    sleep(1)
                    continue
                return {"ok": False, "message": f"GitHub API error: {r.status_code} - {r.text}", "status_code": r.status_code}
        except Exception as e:
            attempt += 1
            last_text = str(e)
            last_status = None
            if attempt <= max_retries:
                sleep(1)
                continue
            return {"ok": False, "message": f"Exception: {e}", "status_code": None}
    # fallback
    return {"ok": False, "message": f"Failed after {max_retries} attempts: {last_text}", "status_code": last_status}

# -------------------------
# Inicializar session state y helpers de limpieza
# -------------------------
if 'df' not in st.session_state:
    st.session_state.df = load_portfolio()
if 'editor_key' not in st.session_state:
    st.session_state.editor_key = 0

# flags de UI
if 'show_delete_confirm' not in st.session_state:
    st.session_state.show_delete_confirm = False
if 'delete_candidate' not in st.session_state:
    st.session_state.delete_candidate = ""
if 'last_deleted' not in st.session_state:
    # last_deleted: dict with { 'row': {'ticker':..., 'amount_ARS':...}, 'timestamp': datetime }
    st.session_state.last_deleted = None
if 'last_commit_result' not in st.session_state:
    st.session_state.last_commit_result = None
# flags to request resets BEFORE widget creation (avoid setting session_state widget keys after instantiation)
if 'need_reset_select_delete' not in st.session_state:
    st.session_state.need_reset_select_delete = False
if 'need_reset_select_edit' not in st.session_state:
    st.session_state.need_reset_select_edit = False

def cleanup_session_keys(prefixes):
    """
    Borra de st.session_state las keys que comienzan con alguno de los 'prefixes'.
    Útil para evitar acumulación de keys dinámicas.
    """
    to_delete = [k for k in list(st.session_state.keys()) if any(k.startswith(p) for p in prefixes)]
    for k in to_delete:
        try:
            del st.session_state[k]
        except Exception:
            pass

def persist_and_local_write(df):
    """
    Intentar commit a GitHub (si está configurado) mostrando spinner y reintentos.
    También escribe el CSV localmente para sincronizar la sesión.
    Devuelve el resultado del commit (dict) o None si no se intentó.
    """
    # siempre escribir local para asegurar consistencia
    try:
        df.to_csv("portfolio_raw.csv", index=False)
    except Exception:
        pass

    # Si no hay token/repo configurado no intentamos el commit
    if not get_github_headers():
        return {"ok": False, "message": "GITHUB_PAT no configurado en secrets.", "status_code": None}

    with st.spinner("Persistiendo cambios en GitHub..."):
        res = commit_csv_to_github(df)
    # mostrar resultado
    if res.get("ok"):
        st.success("Cambios guardados en GitHub.")
    else:
        st.error(f"Error al guardar en GitHub: {res.get('message')}")
    # guardar para inspección
    st.session_state.last_commit_result = res
    return res

# Mensaje inicial si persistencia no configurada
if not get_github_headers():
    st.info("Persistencia a GitHub deshabilitada: configurá GITHUB_PAT en Secrets para activar commits automáticos.")

# -------------------------
# Layout: controles y tabla a la izquierda; KPIs/gráficos a la derecha
# -------------------------
left, right = st.columns([1.4, 2])

with left:
    # -------------------------
    # Agregar nuevo ticker
    # -------------------------
    st.subheader("Agregar nuevo ticker")
    new_ticker_raw = st.text_input("Ticker (sin sufijo)", value="", placeholder="Ej: ABCD", key="add_ticker_input")
    new_amount = st.number_input("Monto invertido (ARS)", min_value=0.0, value=0.0, step=1000.0, format="%.2f", key="add_amount_input")
    if st.button("Agregar ticker"):
        t = sanitize_ticker(new_ticker_raw)
        a = float(new_amount)
        if not t or a <= 0:
            st.warning("Ingresá ticker válido y un monto mayor a 0.")
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

                # limpiar keys obsoletas que puedan retener valores antiguos
                cleanup_session_keys(['select_edit_out_', 'edit_amount_input_', 'select_delete_'])

                # Forzar refresh lógico
                st.session_state.editor_key += 1

                # persistir local y en GitHub (si está configurado)
                res = persist_and_local_write(st.session_state.df)

                st.success(f"Ticker {t} agregado con {a:,.2f} ARS.")

    st.markdown("---")

    # -------------------------
    # Eliminar Ticker (solo 1) con confirmación explícita y undo
    # -------------------------
    st.subheader("Eliminar Tickers")

    # Si se solicitó reset del select desde iteraciones previas, hacerlo ANTES de crear el widget
    if st.session_state.get('need_reset_select_delete', False):
        # Resetear valor del widget en session_state antes de instanciar el selectbox
        st.session_state['select_delete'] = ""
        st.session_state['need_reset_select_delete'] = False

    if len(st.session_state.df) > 0:
        delete_options = st.session_state.df['ticker'].tolist()
        # key estable para evitar problemas; si se quiere forzar recreación se usa need_reset_select_delete
        ticker_to_delete = st.selectbox(
            "Seleccioná un ticker para eliminar (solo 1)",
            options=[""] + delete_options,
            index=0,
            key="select_delete"
        )

        if st.button("Eliminar seleccionado"):
            if ticker_to_delete == "":
                st.warning("Primero seleccioná un ticker válido.")
            else:
                st.session_state.delete_candidate = ticker_to_delete
                st.session_state.show_delete_confirm = True

        # Confirmación visible en la misma columna (no usamos st.modal por compatibilidad)
        if st.session_state.show_delete_confirm:
            candidate = st.session_state.delete_candidate
            st.warning(f"⚠️ Estás por eliminar el ticker **{candidate}**.")
            st.write("Esta acción eliminará la posición del portfolio. Tenés opción de Deshacer luego de confirmar.")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Confirmar eliminación"):
                    # guardar fila eliminada para posible undo
                    row = st.session_state.df.loc[st.session_state.df['ticker'] == candidate].iloc[0].to_dict()
                    st.session_state.last_deleted = {'row': row, 'timestamp': datetime.utcnow().isoformat()}

                    base = st.session_state.df.copy()
                    base = base[base['ticker'] != candidate].reset_index(drop=True)
                    st.session_state.df = base

                    # cleanup keys obsoletas
                    cleanup_session_keys(['select_edit_out_', 'edit_amount_input_', 'select_delete'])

                    # Forzar refresh lógico
                    st.session_state.editor_key += 1

                    # persistir local y en GitHub (si está configurado)
                    res = persist_and_local_write(st.session_state.df)

                    # Después de confirmar, pedimos que el select sea reseteado antes de la próxima renderización
                    st.session_state['need_reset_select_delete'] = True
                    st.session_state.show_delete_confirm = False
                    st.session_state.delete_candidate = ""

                    st.success(f"Ticker {candidate} eliminado correctamente. Podés deshacer esta acción abajo.")
            with c2:
                if st.button("Cancelar"):
                    st.session_state.show_delete_confirm = False
                    st.session_state.delete_candidate = ""
                    # pedir reset del select antes de la próxima renderización para que se vea vacío
                    st.session_state['need_reset_select_delete'] = True
                    st.info("Eliminación cancelada.")
    else:
        st.info("No hay tickers para eliminar.")

    # Mostrar opción para deshacer la última eliminación (undo)
    if st.session_state.get('last_deleted', None):
        st.markdown("---")
        st.info("Se eliminó recientemente un ticker. Podés restaurarlo si fue un error.")
        row = st.session_state.last_deleted['row']
        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("Deshacer última eliminación"):
                # Reinsertar la fila al inicio (o en el orden deseado)
                base = st.session_state.df.copy()
                to_insert = pd.DataFrame([row])
                base = pd.concat([to_insert, base], ignore_index=True)
                base['ticker'] = base['ticker'].astype(str).str.strip().str.upper()
                base['amount_ARS'] = pd.to_numeric(base['amount_ARS'], errors='coerce').fillna(0)
                st.session_state.df = base.reset_index(drop=True)

                # persistir local y en GitHub
                res = persist_and_local_write(st.session_state.df)

                # limpiar last_deleted
                st.session_state.last_deleted = None

                # limpiar keys y forzar refresh
                cleanup_session_keys(['select_edit_out_', 'edit_amount_input_', 'select_delete'])
                st.session_state.editor_key += 1

                st.success("Eliminación deshecha: ticker restaurado.")
        with c2:
            st.write(f"Ticker: **{row['ticker']}** — Monto: **{row['amount_ARS']:, .2f} ARS**")

    st.markdown("---")

    # -------------------------
    # SELECTBOX para editar
    # -------------------------
    st.subheader("Editar Ticker")

    # Si se solicitó reset del select edit, hacerlo ANTES de crear el widget
    if st.session_state.get('need_reset_select_edit', False):
        st.session_state['selected_edit_ticker'] = ""
        st.session_state['need_reset_select_edit'] = False

    tickers_options = st.session_state.df['ticker'].tolist() if len(st.session_state.df) > 0 else []
    options_for_select = [""] + tickers_options

    if 'selected_edit_ticker' not in st.session_state:
        st.session_state.selected_edit_ticker = ""

    # selectbox estable para edición
    st.session_state.selected_edit_ticker = st.selectbox(
        "Seleccioná ticker a editar",
        options=options_for_select,
        index=0,
        key="select_edit"
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

        # number_input key estable pero con editor_key para forzar reseteo si se necesita
        number_key = f"edit_amount_input_{ticker_to_edit if ticker_to_edit != '' else 'none'}"
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

            # cleanup keys obsoletas
            cleanup_session_keys(['edit_amount_input_', 'select_edit'])

            # Forzar refresh
            st.session_state.editor_key += 1

            # persistir
            res = persist_and_local_write(st.session_state.df)

            # pedir reset del select edit en próxima renderización para que venga vacío
            st.session_state['need_reset_select_edit'] = True
            st.session_state.selected_edit_ticker = ""
            st.success(f"Ticker {ticker_to_edit} actualizado a {new_amount_for_ticker:,.2f} ARS.")

    st.markdown("---")

    # -------------------------
    # Tabla de Posición (visual)
    # -------------------------
    st.subheader("Tabla de Posición")
    if len(st.session_state.df) == 0:
        st.info("No hay posiciones cargadas.")
    else:
        df_table = st.session_state.df.copy()
        df_table = df_table.sort_values('amount_ARS', ascending=False).reset_index(drop=True)
        df_table_display = df_table.copy()
        df_table_display['amount_ARS'] = df_table_display['amount_ARS'].map("{:,.2f}".format)
        st.dataframe(df_table_display, use_container_width=True)

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

    # -------------------------
    # Cálculo HHI (Herfindahl–Hirschman Index)
    # -------------------------
    if not df_weights.empty:
        df_weights['weight_frac'] = df_weights['weight_pct'] / 100.0
        hhi_fraction = (df_weights['weight_frac'] ** 2).sum()  # rango 0..1
        hhi_10000 = hhi_fraction * 10000.0  # escala 0..10000 (usada comúnmente)
    else:
        hhi_fraction = 0.0
        hhi_10000 = 0.0

    # Interpretación por umbrales
    if hhi_10000 < 1000:
        hhi_label = "Diversificada (baja concentración)"
    elif hhi_10000 < 1800:
        hhi_label = "Moderada concentración"
    else:
        hhi_label = "Alta concentración"

    # Mostrar HHI como KPI adicional (añadimos una fila de métricas compacta)
    try:
        colE, colF = st.columns([1, 1])
        colE.metric("HHI (0–1)", f"{hhi_fraction:.4f}")
        colF.metric("HHI (0–10000)", f"{hhi_10000:.0f}")
    except Exception:
        st.write(f"HHI: {hhi_fraction:.4f} (0–1) — {hhi_10000:.0f} (0–10000)")

    st.markdown(f"**Interpretación HHI:** {hhi_label}")
    st.markdown("---")

    # --- Visual: tabla de pesos (izquierda de la columna derecha) ---
    st.subheader("Distribución y top holdings")
    if not df_weights.empty:
        display_table = df_weights[['ticker', 'amount_ARS', 'weight_pct']].copy()
        display_table['amount_ARS'] = display_table['amount_ARS'].map("{:,.2f}".format)
        display_table['weight_pct'] = display_table['weight_pct'].map("{:.2f}%".format)
        st.dataframe(display_table.reset_index(drop=True), use_container_width=True)

        # Resumen top 5 como texto compacto
        top5_list = df_weights.head(5)[['ticker', 'weight_pct']].copy()
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
