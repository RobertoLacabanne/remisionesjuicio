"""
Sectores de evidencia.

Un grupo es un bloque del punteo: «Nuevo Banco de Entre Ríos», «Gabinete Informático
Forense», «Declaraciones testimoniales». Los nombres los pone el usuario y no hay una
lista fija, porque cada legajo se ordena distinto y una taxonomía impuesta se abandona
en la segunda causa.

Grupo y etiqueta no son lo mismo y por eso son dos cosas: el grupo arma bloque en la
salida y una pieza está en uno solo; la etiqueta es transversal —`WhatsApp`,
`Teléfono`— y no aparece en el escrito.

Agrupar es organizar. No cambia la naturaleza ni la procedencia de la prueba, y por eso
mover una pieza de grupo no toca ninguno de sus datos documentales.
"""
from __future__ import annotations

import sqlite3

from . import db


class GrupoInvalido(ValueError):
    pass


def listar(cx: sqlite3.Connection) -> list[dict]:
    """Los grupos con sus contadores, más el bloque de las que no tienen grupo."""
    grupos = [dict(r) for r in cx.execute("""
        SELECT g.*,
               COALESCE(SUM(e.activa), 0)                                  AS total,
               COALESCE(SUM(e.activa AND e.estado='incluida'), 0)          AS incluidas,
               COALESCE(SUM(e.activa AND e.estado='excluida'), 0)          AS excluidas,
               COALESCE(SUM(e.activa AND e.estado='pendiente'), 0)         AS pendientes
          FROM grupo_evidencia g
          LEFT JOIN evidencia e ON e.grupo_id = g.id
         GROUP BY g.id ORDER BY g.orden, g.nombre""")]
    sueltas = cx.execute("""
        SELECT COUNT(*) AS total,
               COALESCE(SUM(estado='incluida'), 0)  AS incluidas,
               COALESCE(SUM(estado='excluida'), 0)  AS excluidas,
               COALESCE(SUM(estado='pendiente'), 0) AS pendientes
          FROM evidencia WHERE activa=1 AND grupo_id IS NULL""").fetchone()
    if sueltas["total"]:
        # El bloque de las sueltas se devuelve con la lista y no aparte: si no, «sin
        # grupo» se convierte en un lugar donde las piezas se pierden de vista.
        grupos.append({"id": None, "nombre": "Sin agrupar", "descripcion": None,
                       "orden": 9999, "color": None, "encabezado": None,
                       "tipo": "sistema", "creado_en": None, **dict(sueltas)})
    return grupos


def crear(cx: sqlite3.Connection, nombre: str, *, descripcion: str | None = None,
          color: str | None = None, encabezado: str | None = None,
          tipo: str = "personalizado") -> dict:
    nombre = (nombre or "").strip()
    if not nombre:
        raise GrupoInvalido("el grupo necesita un nombre")
    orden = cx.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM grupo_evidencia").fetchone()[0]
    gid = cx.execute("""INSERT INTO grupo_evidencia (nombre, descripcion, orden, color,
                                                     encabezado, tipo, creado_en)
                        VALUES (?,?,?,?,?,?,?)""",
                     (nombre, descripcion, orden, color, encabezado, tipo,
                      db.ahora())).lastrowid
    cx.commit()
    return dict(cx.execute("SELECT * FROM grupo_evidencia WHERE id=?", (gid,)).fetchone())


def actualizar(cx: sqlite3.Connection, grupo_id: int, **campos) -> dict:
    permitidos = {"nombre", "descripcion", "color", "encabezado", "tipo"}
    cambios = {k: (v.strip() if isinstance(v, str) else v)
               for k, v in campos.items() if k in permitidos}
    if "nombre" in cambios and not cambios["nombre"]:
        raise GrupoInvalido("el grupo necesita un nombre")
    if cambios:
        sets = ", ".join(f"{k}=?" for k in cambios)
        cx.execute(f"UPDATE grupo_evidencia SET {sets} WHERE id=?",
                   (*cambios.values(), grupo_id))
        cx.commit()
    fila = cx.execute("SELECT * FROM grupo_evidencia WHERE id=?", (grupo_id,)).fetchone()
    if not fila:
        raise KeyError(grupo_id)
    return dict(fila)


def borrar(cx: sqlite3.Connection, grupo_id: int) -> dict:
    """
    Borra el grupo. Las piezas que tenía quedan sin grupo, NO se borran.

    Es `ON DELETE SET NULL` en el esquema, y está dicho acá también porque es la clase
    de cosa que alguien puede cambiar sin darse cuenta de lo que se lleva puesto.
    """
    n = cx.execute("SELECT COUNT(*) FROM evidencia WHERE grupo_id=?", (grupo_id,)).fetchone()[0]
    cx.execute("DELETE FROM grupo_evidencia WHERE id=?", (grupo_id,))
    cx.commit()
    return {"borrado": grupo_id, "evidencias_liberadas": n}


def reordenar(cx: sqlite3.Connection, ids: list[int]) -> dict:
    for posicion, gid in enumerate(ids, start=1):
        cx.execute("UPDATE grupo_evidencia SET orden=? WHERE id=?", (posicion, gid))
    cx.commit()
    return {"reordenados": len(ids)}


def mover_varias(cx: sqlite3.Connection, evidencia_ids: list[int],
                 grupo_id: int | None) -> dict:
    """Mueve varias piezas a un grupo de una sola vez. Lo que pide el arrastre múltiple."""
    orden = cx.execute("""SELECT COALESCE(MAX(orden_en_grupo), 0) FROM evidencia
                           WHERE grupo_id IS ?""", (grupo_id,)).fetchone()[0]
    for eid in evidencia_ids:
        orden += 1
        anterior = cx.execute("SELECT grupo_id FROM evidencia WHERE id=?", (eid,)).fetchone()
        cx.execute("UPDATE evidencia SET grupo_id=?, orden_en_grupo=?, actualizado_en=? "
                   "WHERE id=?", (grupo_id, orden, db.ahora(), eid))
        cx.execute("""INSERT INTO revision (evidencia_id, campo, valor_anterior,
                                            valor_nuevo, cuando)
                      VALUES (?, 'grupo', ?, ?, ?)""",
                   (eid, str(anterior["grupo_id"]) if anterior else None,
                    str(grupo_id), db.ahora()))
    cx.commit()
    return {"movidas": len(evidencia_ids), "grupo_id": grupo_id}


# ─────────────────────────────────────────────────────────────── etiquetas ──
def etiquetas(cx: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in cx.execute("""
        SELECT e.*, COUNT(ee.evidencia_id) AS usos FROM etiqueta e
          LEFT JOIN evidencia_etiqueta ee ON ee.etiqueta_id = e.id
         GROUP BY e.id ORDER BY e.nombre""")]


def etiquetar(cx: sqlite3.Connection, evidencia_id: int, nombre: str) -> dict:
    nombre = (nombre or "").strip()
    if not nombre:
        raise GrupoInvalido("la etiqueta necesita un nombre")
    cx.execute("INSERT OR IGNORE INTO etiqueta (nombre) VALUES (?)", (nombre,))
    eid = cx.execute("SELECT id FROM etiqueta WHERE nombre=?", (nombre,)).fetchone()["id"]
    cx.execute("""INSERT OR IGNORE INTO evidencia_etiqueta (evidencia_id, etiqueta_id)
                  VALUES (?,?)""", (evidencia_id, eid))
    cx.commit()
    return {"evidencia_id": evidencia_id, "etiqueta": nombre, "etiqueta_id": eid}


def desetiquetar(cx: sqlite3.Connection, evidencia_id: int, etiqueta_id: int) -> dict:
    cx.execute("DELETE FROM evidencia_etiqueta WHERE evidencia_id=? AND etiqueta_id=?",
               (evidencia_id, etiqueta_id))
    cx.commit()
    return {"evidencia_id": evidencia_id, "etiqueta_id": etiqueta_id}
