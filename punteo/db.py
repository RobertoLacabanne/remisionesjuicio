"""Conexión y arranque de la base. SQLite en modo WAL, un archivo por caso."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config

# Se sube cuando cambia `esquema.sql`. Sirve para no reejecutar el script en cada
# conexión: el servidor es multihilo y dos conexiones corriendo el esquema a la vez
# chocan al recrear una vista, que es un DROP seguido de un CREATE y no es atómico.
ESQUEMA_VERSION = 2

_candado = threading.Lock()


def ahora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def conectar(ruta: Path | None = None) -> sqlite3.Connection:
    ruta = Path(ruta or config.BASE)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(ruta, timeout=30.0)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA journal_mode=WAL")
    cx.execute("PRAGMA foreign_keys=ON")
    cx.execute("PRAGMA synchronous=NORMAL")
    return cx


# Columnas agregadas a tablas que ya existían. `CREATE TABLE IF NOT EXISTS` no las
# suma a una base ya creada, así que hay que pedirlas una por una. Es la forma barata
# de migrar sin perder lo que hay adentro: un DROP TABLE acá borraría el trabajo de
# revisión, que es lo único del sistema que no se regenera.
COLUMNAS_AGREGADAS: tuple[tuple[str, str, str], ...] = (
    # Si el número de foja se leyó en la página o se dedujo del tramo (ver esquema.sql).
    # En una base vieja queda NULL, que es lo correcto: de esas páginas no se sabe.
    ("pagina", "foja_lectura", "TEXT"),
)


# Qué escribir en una columna recién agregada para las filas que ya estaban. Sin esto,
# una base vieja queda con NULL, y un NULL que la aplicación lee como «todo en orden» es
# peor que un dato que falta: acá una foja puesta por la máquina hace años pasaría por
# leída en el papel. `desconocida` dice lo que de verdad se sabe.
RELLENOS = {
    "pagina.foja_lectura":
        "UPDATE pagina SET foja_lectura='desconocida' "
        " WHERE foja_lectura IS NULL AND foja_origen IN ('detectada','confirmada')",
}


def _agregar_columnas_faltantes(cx: sqlite3.Connection) -> list[str]:
    agregadas = []
    for tabla, columna, tipo in COLUMNAS_AGREGADAS:
        # Sobre una tabla que no existe, `PRAGMA table_info` no da error: devuelve cero
        # filas. Sin este chequeo, en una base recién creada parecería que falta la
        # columna y el ALTER reventaría con «no such table».
        existentes = {r[1] for r in cx.execute(f"PRAGMA table_info({tabla})")}
        if not existentes:
            continue
        if columna not in existentes:
            cx.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
            relleno = RELLENOS.get(f"{tabla}.{columna}")
            if relleno:
                cx.execute(relleno)
            agregadas.append(f"{tabla}.{columna}")
    return agregadas


class BaseMasNueva(RuntimeError):
    """
    La base la escribió una versión posterior del programa.

    Se corta antes de tocar nada. Abrirla igual sería peor que no abrirla: el esquema
    viejo pisa las vistas nuevas, baja el número de versión y se lleva puestas las
    garantías que esa versión agregó —por ejemplo, exigir que las dos fojas de una cita
    estén confirmadas—. Y eso pasa en silencio, sobre el trabajo de revisión, que es lo
    único que no se regenera.
    """


def inicializar(cx: sqlite3.Connection, *, forzar: bool = False) -> bool:
    """Aplica el esquema si hace falta. Devuelve True si lo aplicó."""
    version = cx.execute("PRAGMA user_version").fetchone()[0]
    if version > ESQUEMA_VERSION:
        raise BaseMasNueva(
            f"esta base es de la versión {version} del esquema y este programa entiende "
            f"hasta la {ESQUEMA_VERSION}. Actualizá el programa: abrirla con esta versión "
            f"le sacaría los controles que la versión nueva agregó.")
    # Las columnas faltantes se chequean SIEMPRE, aunque la versión ya esté al día: una
    # base que quedó a mitad de camino —el número subió pero el ALTER no llegó a
    # correr— se quedaría rota para siempre y sin forma de arreglarse sola.
    with _candado:
        if _agregar_columnas_faltantes(cx):
            cx.commit()
    if not forzar and cx.execute("PRAGMA user_version").fetchone()[0] == ESQUEMA_VERSION:
        return False
    with _candado:
        if not forzar and cx.execute("PRAGMA user_version").fetchone()[0] == ESQUEMA_VERSION:
            return False
        cx.executescript(config.ESQUEMA.read_text(encoding="utf-8"))
        _agregar_columnas_faltantes(cx)
        cx.execute(f"PRAGMA user_version={ESQUEMA_VERSION}")
        cx.commit()
    return True


def abrir(ruta: Path | None = None) -> sqlite3.Connection:
    """Conexión con el esquema garantizado."""
    cx = conectar(ruta)
    inicializar(cx)
    return cx


def candado_de_escritura(cx: sqlite3.Connection) -> None:
    """
    Toma el candado de escritura ANTES de leer lo que se va a controlar.

    `BEGIN IMMEDIATE` y no el implícito de `sqlite3`, que abre la transacción recién en
    el primer INSERT: todo lo que se leyó antes quedó afuera, y otra conexión pudo
    cambiarlo en el medio. Dos detecciones proponían las mismas páginas; un punteo se
    escribía con una pieza que otra pestaña acababa de excluir. Con el inmediato, la
    otra conexión espera, y lo que se controla es lo que se escribe.
    """
    if cx.in_transaction:
        cx.commit()
    cx.execute("BEGIN IMMEDIATE")


def ajuste(cx: sqlite3.Connection, clave: str, valor=None):
    """Lee o escribe un ajuste. Sin `valor`, lee."""
    if valor is None:
        r = cx.execute("SELECT valor FROM ajuste WHERE clave=?", (clave,)).fetchone()
        return r["valor"] if r else None
    cx.execute("""INSERT INTO ajuste (clave, valor) VALUES (?,?)
                  ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor""",
               (clave, str(valor)))
    cx.commit()
    return str(valor)


def anotar_excepcion(cx: sqlite3.Connection, clase: str, detalle: str, *,
                     documento_id: int | None = None, pagina_id: int | None = None) -> None:
    """Deja constancia de algo que salió mal. Nunca se traga un error en silencio."""
    cx.execute("""INSERT INTO excepcion (clase, detalle, documento_id, pagina_id, creado_en)
                  VALUES (?,?,?,?,?)""", (clase, detalle, documento_id, pagina_id, ahora()))
