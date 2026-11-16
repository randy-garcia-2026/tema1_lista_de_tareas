"""API REST de gestión de tareas (Todo API).

Este módulo define la aplicación FastAPI y todos sus endpoints. Ofrece un CRUD
completo sobre el recurso ``todos`` almacenado en una base de datos SQLite:

====== ============================ ==========================================
Método Ruta                         Descripción
====== ============================ ==========================================
GET    ``/api/todos``               Lista tareas (filtro opcional por estado).
GET    ``/api/todos/{todo_id}``     Obtiene una tarea por su id.
POST   ``/api/todos``               Crea una tarea nueva (devuelve 201).
PATCH  ``/api/todos/{todo_id}``     Actualiza parcialmente una tarea.
DELETE ``/api/todos/{todo_id}``     Elimina una tarea (devuelve 204).
====== ============================ ==========================================

Arquitectura general
--------------------
* **Persistencia**: SQLite mediante el módulo estándar ``sqlite3``. La conexión
  se obtiene por petición con la dependencia ``get_db`` (definida en
  ``src.database``), que se inyecta con ``Depends``. Se asume que dicha
  dependencia gestiona el ciclo de vida de la conexión (commit/cierre).
* **Validación**: los modelos Pydantic de ``src.models`` validan la entrada
  (``TodoCreate``, ``TodoUpdate``) y serializan la salida (``Todo``).
* **Errores**: los errores de validación se devuelven con un formato JSON
  uniforme (ver ``validation_error_handler``) y los recursos inexistentes
  producen un 404 con un mensaje en español.

Ejecución en desarrollo::

    uvicorn src.main:app --reload

La documentación interactiva queda disponible en ``/docs`` (Swagger UI) y
``/redoc``.
"""

import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.database import get_db, init_db
from src.models import Status, Todo, TodoCreate, TodoUpdate


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestiona el ciclo de vida (arranque y apagado) de la aplicación.

    FastAPI ejecuta este gestor de contexto asíncrono una sola vez:

    * El código **anterior** al ``yield`` se ejecuta al arrancar el servidor,
      antes de atender la primera petición. Aquí se llama a ``init_db()`` para
      dejar la base de datos lista (p. ej. crear la tabla ``todos`` si no
      existe).
    * El código **posterior** al ``yield`` se ejecutaría al apagar el servidor.
      Actualmente no hay tareas de limpieza.

    Args:
        app: Instancia de la aplicación FastAPI (requerida por la firma que
            espera FastAPI, aunque aquí no se utiliza).
    """
    init_db()
    yield


# Instancia principal de la aplicación. El título aparece en la documentación
# automática (/docs) y `lifespan` enlaza el arranque con la inicialización de BD.
app = FastAPI(title="Todo API", lifespan=lifespan)


# --- Manejo centralizado de errores ---
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc: RequestValidationError):
    """Devuelve un formato uniforme para los errores de validación de entrada.

    Sustituye la respuesta 422 por defecto de FastAPI por una más simple y en
    español. Se dispara cuando el cuerpo, los parámetros de ruta o de consulta
    no cumplen el esquema declarado (p. ej. un ``todo_id`` no numérico o un
    ``status`` fuera del enum).

    Args:
        request: Petición que originó el error (no se utiliza).
        exc: Excepción con el detalle de todos los fallos de validación.

    Returns:
        ``JSONResponse`` con código 422 y un cuerpo del tipo::

            {
                "detail": "Datos de entrada inválidos",
                "errors": [{"loc": [...], "msg": "...", "type": "..."}]
            }
    """
    return JSONResponse(
        status_code=422,
        content={"detail": "Datos de entrada inválidos", "errors": jsonable(exc)},
    )


def jsonable(exc: RequestValidationError) -> list[dict]:
    """Convierte los errores de validación de Pydantic en estructuras JSON.

    Se conservan únicamente los campos útiles para el cliente. Se descartan
    otros datos que ``exc.errors()`` puede incluir (como ``input`` o ``ctx``),
    que podrían contener objetos no serializables o información sensible.

    Args:
        exc: Excepción de validación lanzada por FastAPI.

    Returns:
        Lista de diccionarios con las claves:

        * ``loc``: ubicación del error (p. ej. ``["body", "title"]``).
        * ``msg``: mensaje legible del fallo.
        * ``type``: identificador del tipo de error (p. ej. ``"missing"``).
    """
    return [
        {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
        for e in exc.errors()
    ]


# --- Utilidades ---
def todo_not_found(todo_id: int) -> HTTPException:
    """Construye la excepción HTTP 404 para una tarea inexistente.

    Solo **crea** la excepción; quien la invoca debe lanzarla con ``raise``.
    Centralizar el mensaje garantiza respuestas coherentes en todos los
    endpoints.

    Args:
        todo_id: Identificador de la tarea que no se encontró.

    Returns:
        ``HTTPException`` con estado 404 y el mensaje
        ``"Tarea con id {todo_id} no encontrada"``.
    """
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Tarea con id {todo_id} no encontrada",
    )


def get_todo_or_404(db: sqlite3.Connection, todo_id: int) -> sqlite3.Row:
    """Obtiene una tarea por id o lanza un 404 si no existe.

    Se usa tanto para las lecturas como para comprobar la existencia antes de
    modificar o borrar, y para releer la fila tras un INSERT/UPDATE.

    La consulta está parametrizada (``?``), por lo que es segura frente a
    inyección SQL.

    Args:
        db: Conexión SQLite activa (se espera ``row_factory = sqlite3.Row``
            para poder convertir la fila a diccionario con ``dict(row)``).
        todo_id: Identificador de la tarea buscada.

    Returns:
        La fila ``sqlite3.Row`` correspondiente a la tarea.

    Raises:
        HTTPException: 404 si no existe ninguna tarea con ese id.
    """
    row = db.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    if row is None:
        raise todo_not_found(todo_id)
    return row


# --- Endpoints ---
@app.get("/api/todos", response_model=list[Todo])
def list_todos(status: Status | None = None, db: sqlite3.Connection = Depends(get_db)):
    """Lista las tareas, con filtrado opcional por estado.

    Ejemplos::

        GET /api/todos                 -> todas las tareas
        GET /api/todos?status=<valor>  -> solo las tareas con ese estado

    Los resultados se devuelven ordenados por ``id`` ascendente.

    Nota:
        El parámetro ``status`` oculta, dentro de esta función, al módulo
        ``fastapi.status`` importado arriba. No supone un problema porque aquí
        no se usa dicho módulo, pero conviene recordarlo si se amplía la
        función.

    Args:
        status: Estado por el que filtrar (enum ``Status``). Si es ``None`` no
            se aplica ningún filtro.
        db: Conexión a la base de datos, inyectada por ``get_db``.

    Returns:
        Lista de tareas serializadas según el modelo ``Todo``.
    """
    if status is None:
        rows = db.execute("SELECT * FROM todos ORDER BY id").fetchall()
    else:
        # `status.value` es el valor de texto del enum almacenado en la BD.
        rows = db.execute(
            "SELECT * FROM todos WHERE status = ? ORDER BY id", (status.value,)
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/todos/{todo_id}", response_model=Todo)
def get_todo(todo_id: int, db: sqlite3.Connection = Depends(get_db)):
    """Devuelve una única tarea por su identificador.

    Args:
        todo_id: Id de la tarea (parámetro de ruta, validado como entero).
        db: Conexión a la base de datos, inyectada por ``get_db``.

    Returns:
        La tarea solicitada según el modelo ``Todo``.

    Raises:
        HTTPException: 404 si la tarea no existe.
    """
    return dict(get_todo_or_404(db, todo_id))


@app.post("/api/todos", response_model=Todo, status_code=201)
def create_todo(payload: TodoCreate, db: sqlite3.Connection = Depends(get_db)):
    """Crea una tarea nueva.

    Solo se insertan ``title`` y ``description``; el resto de columnas (``id``,
    ``status``, fechas, etc.) las rellena la base de datos con sus valores por
    defecto. Tras insertar se relee la fila para devolver la tarea completa,
    incluyendo esos valores generados.

    Args:
        payload: Cuerpo de la petición validado como ``TodoCreate``.
        db: Conexión a la base de datos, inyectada por ``get_db``.

    Returns:
        La tarea recién creada, con código HTTP 201.
    """
    cur = db.execute(
        "INSERT INTO todos (title, description) VALUES (?, ?)",
        (payload.title, payload.description),
    )
    # `lastrowid` es el id autogenerado por el INSERT anterior.
    return dict(get_todo_or_404(db, cur.lastrowid))


@app.patch("/api/todos/{todo_id}", response_model=Todo)
def update_todo(
    todo_id: int, payload: TodoUpdate, db: sqlite3.Connection = Depends(get_db)
):
    """Actualiza parcialmente una tarea (semántica PATCH).

    Solo se modifican los campos que el cliente envía explícitamente en el
    cuerpo. Esto se logra con ``model_dump(exclude_unset=True)``, que distingue
    entre un campo **ausente** (no se toca) y un campo enviado como ``null``.

    Reglas de negocio:

    * ``title`` no puede enviarse como ``null`` (columna obligatoria).
    * ``status`` no puede enviarse como ``null``.
    * Otros campos opcionales (p. ej. ``description``) sí pueden ponerse a
      ``null`` para vaciarlos.
    * Si el cuerpo está vacío (``{}``) no se ejecuta ningún UPDATE y se
      devuelve la tarea sin cambios.

    Args:
        todo_id: Id de la tarea a modificar.
        payload: Campos a actualizar, validados como ``TodoUpdate``.
        db: Conexión a la base de datos, inyectada por ``get_db``.

    Returns:
        La tarea tras aplicar los cambios.

    Raises:
        HTTPException: 404 si la tarea no existe; 422 si ``title`` o
            ``status`` se envían como ``null``.
    """
    # Comprueba la existencia antes de validar/modificar (lanza 404 si falta).
    current = get_todo_or_404(db, todo_id)
    # Solo los campos realmente enviados por el cliente.
    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes and changes["title"] is None:
        raise HTTPException(status_code=422, detail="El título no puede ser null")
    if "status" in changes:
        if changes["status"] is None:
            raise HTTPException(status_code=422, detail="El status no puede ser null")
        # Se guarda el valor de texto del enum, no el objeto enum.
        changes["status"] = changes["status"].value
    if changes:
        # Las claves provienen del modelo Pydantic, no del usuario.
        # Por eso es seguro interpolarlas en el SQL; los VALORES, en cambio,
        # siempre van como parámetros (?) para evitar inyección SQL.
        sets = ", ".join(f"{k} = ?" for k in changes)
        db.execute(
            f"UPDATE todos SET {sets} WHERE id = ?", (*changes.values(), todo_id)
        )
    # Se relee la fila para devolver el estado final actualizado.
    return dict(get_todo_or_404(db, todo_id))


@app.delete("/api/todos/{todo_id}", status_code=204)
def delete_todo(todo_id: int, db: sqlite3.Connection = Depends(get_db)):
    """Elimina una tarea por su identificador.

    Primero se verifica que exista (para responder 404 en lugar de un falso
    éxito) y después se borra. La respuesta no lleva cuerpo, como exige el
    código 204 (No Content).

    Args:
        todo_id: Id de la tarea a eliminar.
        db: Conexión a la base de datos, inyectada por ``get_db``.

    Returns:
        ``Response`` vacía con código 204.

    Raises:
        HTTPException: 404 si la tarea no existe.
    """
    get_todo_or_404(db, todo_id)
    db.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    return Response(status_code=204)
