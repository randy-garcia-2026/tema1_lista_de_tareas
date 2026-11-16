"""Panel de control de tareas (interfaz web con Streamlit).

Esta aplicación es el cliente de la API REST definida en ``src/main.py``.
No accede a la base de datos directamente: todas las operaciones se hacen
mediante peticiones HTTP a ``/api/todos``.

Funcionalidades:
    - Contadores de tareas (total, pendientes y completadas).
    - Formulario para crear tareas nuevas.
    - Tabla coloreada según el estado de cada tarea.
    - Botones para completar o eliminar cada tarea.

Configuración:
    API_URL: variable de entorno con la URL base de la API
             (por defecto ``http://localhost:8000``).

Ejecución:
    streamlit run app_ui.py
"""

import os

import pandas as pd
import requests
import streamlit as st

# URL completa del recurso de tareas; la base puede cambiarse con la variable API_URL.
API_URL = os.environ.get("API_URL", "http://localhost:8000") + "/api/todos"
# Segundos máximos de espera por petición, para que la UI no se quede colgada.
TIMEOUT = 5

st.set_page_config(page_title="Panel de tareas", page_icon="✅", layout="wide")


def api(method: str, path: str = "", **kwargs):
    """Envía una petición HTTP a la API de tareas.

    Args:
        method: Verbo HTTP ("GET", "POST", "PATCH", "DELETE").
        path: Ruta relativa a ``API_URL``, por ejemplo ``"/3"``.
        **kwargs: Argumentos extra para ``requests.request`` (por ejemplo ``json=``).

    Returns:
        El objeto ``requests.Response`` si la petición fue exitosa. Si hay un
        error de conexión o la API responde con un código de error, muestra el
        mensaje en la interfaz con ``st.error`` y devuelve ``None``.
    """
    try:
        resp = requests.request(method, API_URL + path, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as e:
        st.error(f"No se pudo conectar con la API: {e}")
        return None
    if not resp.ok:
        # La API devuelve el motivo del error en el campo "detail"; si el cuerpo
        # no es JSON, se muestra el texto tal cual.
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        st.error(f"Error {resp.status_code}: {detail}")
        return None
    return resp


def color_row(row):
    """Devuelve los estilos CSS de una fila de la tabla según su estado.

    Verde para las tareas ``done`` y naranja para el resto. Se usa con
    ``DataFrame.style.apply(..., axis=1)``, por lo que debe devolver una lista
    con un estilo por cada celda de la fila.
    """
    color = "#c8f7c5" if row["Estado"] == "done" else "#ffe0b2"
    return [f"background-color: {color}; color: #222"] * len(row)


st.title("✅ Panel de control de tareas")

# Mensaje "flash": st.rerun() reinicia el script y borra lo mostrado, así que el
# aviso se guarda en session_state y se muestra (una sola vez) tras el rerun.
if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

# Se cargan todas las tareas en cada ejecución; si la API falla, la lista queda vacía.
resp = api("GET")
todos = resp.json() if resp is not None else []

# --- Contadores ---
done = sum(t["status"] == "done" for t in todos)
c1, c2, c3 = st.columns(3)
c1.metric("Total", len(todos))
c2.metric("Pendientes", len(todos) - done)
c3.metric("Completadas", done)

st.divider()

# --- Formulario de creación ---
# clear_on_submit vacía los campos al enviar. La validación del título se hace
# aquí para dar feedback rápido; la API la repite por su cuenta.
with st.form("nueva_tarea", clear_on_submit=True):
    st.subheader("Nueva tarea")
    title = st.text_input("Título")
    description = st.text_area("Descripción")
    if st.form_submit_button("Crear tarea"):
        if not title.strip():
            st.warning("El título es obligatorio.")
        elif api("POST", json={"title": title, "description": description or None}):
            st.session_state["flash"] = "Tarea creada."
            st.rerun()

st.divider()

# --- Tabla con colores ---
st.subheader("Tareas")
if not todos:
    st.info("No hay tareas todavía.")
else:
    # Se construye un DataFrame con nombres de columna en español para mostrarlo;
    # una descripción vacía (None) se muestra como cadena vacía.
    table = pd.DataFrame(
        {
            "ID": [t["id"] for t in todos],
            "Título": [t["title"] for t in todos],
            "Descripción": [t["description"] or "" for t in todos],
            "Estado": [t["status"] for t in todos],
        }
    )
    st.dataframe(
        table.style.apply(color_row, axis=1), hide_index=True, width="stretch"
    )

    # --- Acciones por tarea ---
    # Una fila por tarea con su resumen y los botones. Cada botón lleva una
    # "key" única (basada en el id) porque Streamlit exige claves distintas
    # entre widgets repetidos. Tras una acción exitosa se hace rerun para
    # refrescar contadores y tabla.
    st.subheader("Acciones")
    for t in todos:
        col_info, col_done, col_del = st.columns([6, 2, 2])
        icon = "🟢" if t["status"] == "done" else "🟠"
        col_info.markdown(f"{icon} **#{t['id']}** {t['title']}")
        if col_done.button(
            "Completar",
            key=f"done_{t['id']}",
            disabled=t["status"] == "done",
            width="stretch",
        ):
            if api("PATCH", f"/{t['id']}", json={"status": "done"}):
                st.rerun()
        if col_del.button("Eliminar", key=f"del_{t['id']}", width="stretch"):
            if api("DELETE", f"/{t['id']}"):
                st.rerun()
