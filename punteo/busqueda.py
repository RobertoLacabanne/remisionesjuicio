"""
Búsqueda sobre el legajo.

Dos búsquedas y conviene no confundirlas, porque contestan cosas distintas:

  * sobre el TEXTO DE LAS PÁGINAS — «dónde dice maestranza» — devuelve fojas, con el
    fragmento donde apareció. Sirve para encontrar;
  * sobre las PIEZAS DE EVIDENCIA — «traeme los oficios» — devuelve piezas, con su
    estado. Sirve para trabajar.

El índice es SQLite FTS5, que viene con Python. Sin servicio aparte, sin nada que se
pueda caer un martes a la mañana.
"""
from __future__ import annotations

import re
import sqlite3

MAX = 200
CONTEXTO = 90        # caracteres alrededor de la coincidencia


def reindexar(cx: sqlite3.Connection) -> int:
    """Rehace el índice de texto. Una fila por página leída."""
    cx.execute("DELETE FROM pagina_texto")
    n = 0
    for p in cx.execute("""SELECT id, numero_global, texto FROM pagina
                            WHERE texto IS NOT NULL AND texto != ''
                            ORDER BY numero_global"""):
        cx.execute("INSERT INTO pagina_texto (texto, pagina_id, numero_global) VALUES (?,?,?)",
                   (p["texto"], p["id"], p["numero_global"]))
        n += 1
    cx.commit()
    return n


def preparar(consulta: str) -> str:
    """
    Pasa lo que escribió una persona a sintaxis de FTS5, sin que pueda romperla.

    Todo término se entrecomilla, así un guion o un paréntesis no vuelan la consulta. Lo
    que va entre comillas se respeta como frase exacta; un término suelto admite prefijo
    —`perez` encuentra `perezosa`— porque el que busca no sabe cómo termina la palabra
    en el papel.
    """
    partes = re.findall(r'"([^"]+)"|(\S+)', (consulta or "").strip())
    tokens = []
    for frase, suelto in partes:
        if frase:
            tokens.append('"' + frase.replace('"', "") + '"')
        elif suelto:
            limpio = re.sub(r'["*()]', " ", suelto).strip()
            if limpio:
                tokens.append('"' + limpio + '"' + ("*" if len(limpio) >= 3 else ""))
    return " AND ".join(tokens)


def _fragmento(texto: str, consulta: str) -> str:
    """El pedacito donde apareció, para no tener que abrir la página para saber si sirve."""
    if not texto:
        return ""
    termino = re.split(r"\s+", (consulta or "").strip().strip('"'))[0]
    if termino:
        m = re.search(re.escape(termino), texto, re.IGNORECASE)
        if m:
            desde = max(0, m.start() - CONTEXTO)
            hasta = min(len(texto), m.end() + CONTEXTO)
            return ("…" if desde else "") + texto[desde:hasta].strip() + \
                   ("…" if hasta < len(texto) else "")
    return texto[:CONTEXTO * 2].strip() + ("…" if len(texto) > CONTEXTO * 2 else "")


def en_paginas(cx: sqlite3.Connection, consulta: str, limite: int = MAX) -> list[dict]:
    """Dónde dice eso. Devuelve páginas con su foja y el fragmento."""
    q = preparar(consulta)
    if not q:
        return []
    try:
        filas = cx.execute("""
            SELECT t.pagina_id, t.numero_global, p.foja_etiqueta, p.foja_origen, p.texto
              FROM pagina_texto t JOIN pagina p ON p.id = t.pagina_id
             WHERE pagina_texto MATCH ? ORDER BY rank LIMIT ?""", (q, limite)).fetchall()
    except sqlite3.OperationalError:
        # Una consulta que FTS5 no puede parsear no puede voltear la pantalla: se
        # devuelve vacío y el que busca prueba de nuevo.
        return []
    return [{"pagina_id": f["pagina_id"], "numero_global": f["numero_global"],
             "foja": f["foja_etiqueta"], "foja_origen": f["foja_origen"],
             "fragmento": _fragmento(f["texto"], consulta)} for f in filas]


def en_evidencias(cx: sqlite3.Connection, consulta: str, limite: int = MAX) -> list[dict]:
    """Qué piezas hablan de eso. Devuelve evidencia con su estado."""
    if not (consulta or "").strip():
        return []
    patron = f"%{consulta.strip()}%"
    return [dict(r) for r in cx.execute("""
        SELECT id, descripcion, tipo, estado, foja_inicio, foja_fin, pagina_inicio,
               testigo, confianza
          FROM v_evidencia
         WHERE activa = 1 AND (descripcion LIKE ? OR texto_origen LIKE ? OR testigo LIKE ?)
         ORDER BY pagina_inicio LIMIT ?""", (patron, patron, patron, limite))]


def buscar(cx: sqlite3.Connection, consulta: str) -> dict:
    """Las dos búsquedas, separadas. Un resultado de cada una dice una cosa distinta."""
    return {"consulta": consulta,
            "paginas": en_paginas(cx, consulta),
            "evidencias": en_evidencias(cx, consulta)}
