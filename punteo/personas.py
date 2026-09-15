"""
Personas: testigos introductores, peritos, funcionarios, denunciantes.

Dos reglas, y son opuestas entre sí a propósito:

  * no crear cinco registros distintos por cinco variaciones del mismo nombre —«ANDRADE,
    Rubén O.», «Rubén Osvaldo Andrade», «Andrade Ruben»— porque entonces la vista por
    testigo no sirve para nada;
  * **no fusionar identidades en silencio.** Dos personas pueden llamarse parecido, y en
    un legajo penal decir que son la misma es una afirmación, no una comodidad.

La salida de esa tensión es la misma que usa AppUFIL: las coincidencias dudosas se
PROPONEN y las confirma una persona.
"""
from __future__ import annotations

import sqlite3

from . import db
from .castellano import normalizar_nombre

ROLES = {
    "testigo": "Testigo",
    "perito": "Perito",
    "funcionario": "Funcionario interviniente",
    "policia": "Personal policial",
    "denunciante": "Denunciante",
    "victima": "Víctima",
    "imputado": "Imputado",
    "otro": "Otro",
}

FUNCIONES = {
    "introductor": "Introduce al debate",
    "autor": "Autor del documento",
    "interviniente": "Interviniente",
    "mencionado": "Mencionado",
}

# Cuánto se tienen que parecer dos nombres para proponer que son la misma persona.
UMBRAL_FUSION = 0.72


class PersonaInvalida(ValueError):
    pass


def listar(cx: sqlite3.Connection) -> list[dict]:
    """Las personas con cuántas piezas introduce cada una. Es la vista TESTIGOS."""
    return [dict(r) for r in cx.execute("""
        SELECT p.*,
               COUNT(DISTINCT CASE WHEN ep.funcion='introductor' AND e.activa=1
                                   THEN e.id END) AS introduce,
               COUNT(DISTINCT CASE WHEN ep.funcion='introductor' AND e.activa=1
                                    AND e.estado='incluida' THEN e.id END) AS introduce_incluidas
          FROM persona p
          LEFT JOIN evidencia_persona ep ON ep.persona_id = p.id
          LEFT JOIN evidencia e ON e.id = ep.evidencia_id
         GROUP BY p.id ORDER BY p.nombre""")]


def por_testigo(cx: sqlite3.Connection, *, solo_incluidas: bool = False) -> list[dict]:
    """
    La evidencia agrupada por quién la introduce al debate.

    Es lo que contesta la pregunta que hace falta antes de mandar una remisión: qué
    prueba entra por cada testigo, y si alguno quedó cargando veinte piezas que en
    realidad introduce otro.
    """
    condicion = "AND e.estado='incluida'" if solo_incluidas else ""
    filas = cx.execute(f"""
        SELECT p.id, p.nombre, p.rol, p.detalle,
               e.id AS evidencia_id, e.descripcion, e.foja_inicio, e.foja_fin,
               e.estado, e.tipo
          FROM persona p
          JOIN evidencia_persona ep ON ep.persona_id = p.id AND ep.funcion='introductor'
          JOIN v_evidencia e ON e.id = ep.evidencia_id AND e.activa = 1 {condicion}
         ORDER BY p.nombre, e.pagina_inicio""").fetchall()

    por_persona: dict[int, dict] = {}
    for f in filas:
        d = por_persona.setdefault(f["id"], {"id": f["id"], "nombre": f["nombre"],
                                             "rol": f["rol"], "detalle": f["detalle"],
                                             "evidencias": []})
        d["evidencias"].append({k: f[k] for k in
                                ("evidencia_id", "descripcion", "foja_inicio",
                                 "foja_fin", "estado", "tipo")})
    salida = list(por_persona.values())

    # Las piezas sin testigo van en su propio bloque y NO se esconden: en una remisión a
    # juicio, una pieza incluida sin quien la introduzca es el agujero que hay que ver.
    sin = cx.execute(f"""
        SELECT e.id AS evidencia_id, e.descripcion, e.foja_inicio, e.foja_fin,
               e.estado, e.tipo
          FROM v_evidencia e
         WHERE e.activa = 1 AND e.testigo_id IS NULL {condicion}
         ORDER BY e.pagina_inicio""").fetchall()
    if sin:
        salida.append({"id": None, "nombre": "Sin testigo asignado", "rol": None,
                       "detalle": None, "evidencias": [dict(r) for r in sin]})
    return salida


def buscar_o_crear(cx: sqlite3.Connection, nombre: str, *, rol: str | None = None,
                   detalle: str | None = None, documento: str | None = None) -> dict:
    """
    Busca una persona por nombre normalizado y la crea si no está.

    La normalización ordena las palabras, así que «PÉREZ, Juan» y «Juan Pérez» caen en
    la misma clave y no se duplican. Lo que NO hace es unir «Juan Pérez» con «J. Pérez»:
    eso es una conjetura y va por el camino de las propuestas.
    """
    nombre = (nombre or "").strip()
    if not nombre:
        raise PersonaInvalida("la persona necesita un nombre")
    clave = normalizar_nombre(nombre)
    fila = cx.execute("SELECT * FROM persona WHERE nombre_norm=?", (clave,)).fetchone()
    if fila:
        return dict(fila)
    pid = cx.execute("""INSERT INTO persona (nombre, nombre_norm, rol, documento, detalle,
                                             origen, creado_en)
                        VALUES (?,?,?,?,?, 'manual', ?)""",
                     (nombre, clave, rol, documento, detalle, db.ahora())).lastrowid
    cx.commit()
    return dict(cx.execute("SELECT * FROM persona WHERE id=?", (pid,)).fetchone())


def actualizar(cx: sqlite3.Connection, persona_id: int, **campos) -> dict:
    permitidos = {"nombre", "rol", "documento", "detalle"}
    cambios = {k: (v.strip() if isinstance(v, str) else v)
               for k, v in campos.items() if k in permitidos}
    if "nombre" in cambios:
        if not cambios["nombre"]:
            raise PersonaInvalida("la persona necesita un nombre")
        cambios["nombre_norm"] = normalizar_nombre(cambios["nombre"])
    if cambios:
        sets = ", ".join(f"{k}=?" for k in cambios)
        cx.execute(f"UPDATE persona SET {sets} WHERE id=?", (*cambios.values(), persona_id))
        cx.commit()
    fila = cx.execute("SELECT * FROM persona WHERE id=?", (persona_id,)).fetchone()
    if not fila:
        raise KeyError(persona_id)
    return dict(fila)


def borrar(cx: sqlite3.Connection, persona_id: int) -> dict:
    n = cx.execute("SELECT COUNT(*) FROM evidencia_persona WHERE persona_id=?",
                   (persona_id,)).fetchone()[0]
    cx.execute("DELETE FROM persona WHERE id=?", (persona_id,))
    cx.commit()
    return {"borrada": persona_id, "asociaciones_eliminadas": n}


# ────────────────────────────────────────────────── asociación con evidencia ──
def asociar(cx: sqlite3.Connection, evidencia_id: int, persona_id: int,
            funcion: str = "introductor") -> dict:
    if funcion not in FUNCIONES:
        raise PersonaInvalida(f"función desconocida: {funcion!r}")
    if funcion == "introductor":
        # Una pieza entra al debate por UNA persona. Permitir dos convierte la vista por
        # testigo en algo que no se puede leer, y el punteo en una frase imposible de
        # redactar. Si hace falta más de una, es señal de que la pieza son dos.
        anterior = cx.execute("""SELECT persona_id FROM evidencia_persona
                                  WHERE evidencia_id=? AND funcion='introductor'""",
                              (evidencia_id,)).fetchone()
        cx.execute("""DELETE FROM evidencia_persona
                       WHERE evidencia_id=? AND funcion='introductor'""", (evidencia_id,))
        if anterior and anterior["persona_id"] != persona_id:
            _anotar_testigo(cx, evidencia_id, anterior["persona_id"], persona_id)
        elif not anterior:
            _anotar_testigo(cx, evidencia_id, None, persona_id)
    cx.execute("""INSERT OR IGNORE INTO evidencia_persona (evidencia_id, persona_id, funcion)
                  VALUES (?,?,?)""", (evidencia_id, persona_id, funcion))
    cx.commit()
    return {"evidencia_id": evidencia_id, "persona_id": persona_id, "funcion": funcion}


def desasociar(cx: sqlite3.Connection, evidencia_id: int, persona_id: int,
               funcion: str = "introductor") -> dict:
    if funcion == "introductor":
        _anotar_testigo(cx, evidencia_id, persona_id, None)
    cx.execute("""DELETE FROM evidencia_persona
                   WHERE evidencia_id=? AND persona_id=? AND funcion=?""",
               (evidencia_id, persona_id, funcion))
    cx.commit()
    return {"evidencia_id": evidencia_id, "persona_id": persona_id}


def asignar_testigo_varias(cx: sqlite3.Connection, evidencia_ids: list[int],
                           persona_id: int) -> dict:
    """
    El mismo testigo para varias piezas.

    Hace falta de verdad: el policía que firmó el acta de procedimiento suele introducir
    también el acta de secuestro, las fotos y el croquis del mismo operativo, y
    asignarlo de a uno son cuarenta clics.
    """
    for eid in evidencia_ids:
        asociar(cx, eid, persona_id, "introductor")
    return {"asignadas": len(evidencia_ids), "persona_id": persona_id}


def _anotar_testigo(cx, evidencia_id, anterior_id, nuevo_id) -> None:
    def nombre(pid):
        if not pid:
            return None
        f = cx.execute("SELECT nombre FROM persona WHERE id=?", (pid,)).fetchone()
        return f["nombre"] if f else str(pid)
    cx.execute("""INSERT INTO revision (evidencia_id, campo, valor_anterior, valor_nuevo, cuando)
                  VALUES (?, 'testigo', ?, ?, ?)""",
               (evidencia_id, nombre(anterior_id), nombre(nuevo_id), db.ahora()))


# ───────────────────────────────────────────────────── propuestas de fusión ──
def _parecido(a: str, b: str) -> float:
    """Jaccard sobre las palabras del nombre. Simple y suficiente para PROPONER."""
    pa, pb = set(a.split()), set(b.split())
    if not pa or not pb:
        return 0.0
    return len(pa & pb) / len(pa | pb)


def proponer_fusiones(cx: sqlite3.Connection) -> dict:
    """Busca personas que podrían ser la misma. No fusiona: propone."""
    gente = cx.execute("SELECT id, nombre, nombre_norm, documento FROM persona").fetchall()
    decididas = {(r["persona_a"], r["persona_b"]) for r in cx.execute(
        "SELECT persona_a, persona_b FROM fusion_propuesta WHERE estado!='pendiente'")}
    cx.execute("DELETE FROM fusion_propuesta WHERE estado='pendiente'")

    propuestas = 0
    for i, a in enumerate(gente):
        for b in gente[i + 1:]:
            par = (min(a["id"], b["id"]), max(a["id"], b["id"]))
            if par in decididas:
                continue
            score, motivo = _parecido(a["nombre_norm"], b["nombre_norm"]), "nombres parecidos"
            # El documento es una clave fuerte: si coincide, son la misma y la propuesta
            # sale con score 1. Aun así se PROPONE y no se aplica sola.
            if a["documento"] and a["documento"] == b["documento"]:
                score, motivo = 1.0, "mismo documento de identidad"
            if score >= UMBRAL_FUSION:
                cx.execute("""INSERT OR REPLACE INTO fusion_propuesta
                              (persona_a, persona_b, score, motivo, estado, creado_en)
                              VALUES (?,?,?,?, 'pendiente', ?)""",
                           (*par, round(score, 3), motivo, db.ahora()))
                propuestas += 1
    cx.commit()
    return {"propuestas": propuestas}


def fusiones_pendientes(cx: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in cx.execute("""
        SELECT f.id, f.score, f.motivo,
               a.id AS a_id, a.nombre AS a_nombre, b.id AS b_id, b.nombre AS b_nombre
          FROM fusion_propuesta f
          JOIN persona a ON a.id = f.persona_a
          JOIN persona b ON b.id = f.persona_b
         WHERE f.estado='pendiente' ORDER BY f.score DESC""")]


def fusionar(cx: sqlite3.Connection, propuesta_id: int, *, quedarse_con: int) -> dict:
    """
    Aplica una fusión que una persona confirmó. Las asociaciones se mudan al que queda.
    """
    f = cx.execute("SELECT * FROM fusion_propuesta WHERE id=?", (propuesta_id,)).fetchone()
    if not f:
        raise KeyError(propuesta_id)
    if quedarse_con not in (f["persona_a"], f["persona_b"]):
        raise PersonaInvalida("hay que quedarse con una de las dos personas de la propuesta")
    absorbida = f["persona_b"] if quedarse_con == f["persona_a"] else f["persona_a"]

    cx.execute("""UPDATE OR IGNORE evidencia_persona SET persona_id=? WHERE persona_id=?""",
               (quedarse_con, absorbida))
    cx.execute("DELETE FROM evidencia_persona WHERE persona_id=?", (absorbida,))
    cx.execute("DELETE FROM persona WHERE id=?", (absorbida,))
    cx.execute("UPDATE fusion_propuesta SET estado='aceptada' WHERE id=?", (propuesta_id,))
    cx.commit()
    return {"queda": quedarse_con, "absorbida": absorbida}


def rechazar_fusion(cx: sqlite3.Connection, propuesta_id: int) -> dict:
    cx.execute("UPDATE fusion_propuesta SET estado='rechazada' WHERE id=?", (propuesta_id,))
    cx.commit()
    return {"rechazada": propuesta_id}
