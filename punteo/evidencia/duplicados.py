"""
Posibles duplicados.

Se detectan y se muestran. **No se eliminan ni se fusionan solos**, y la razón es que
en un legajo los duplicados verdaderos existen y son relevantes: el mismo informe
puede estar agregado dos veces, una por el juzgado y otra por la policía, y a veces
conviene ofrecer las dos ubicaciones. Decidir eso es de la persona.

Lo que sí se hace es no dejar que pasen desapercibidos, que es lo que ocurre cuando un
legajo tiene ochocientas piezas.
"""
from __future__ import annotations

import sqlite3

from .. import db
from ..castellano import clave_ocr, normalizar

# Cuánto se tienen que parecer dos piezas para proponerlas como duplicado. Bajo esto
# se llena de ruido y la gente deja de mirar las propuestas, que es peor que no tenerlas.
UMBRAL = 0.62
# Cuántas piezas mira como máximo. La comparación es de a pares y crece al cuadrado:
# con ochocientas piezas son trescientos veinte mil pares, que en SQLite y Python es
# medio minuto. Se acota por ventana de páginas, que además es lo correcto: dos piezas
# a trescientas fojas de distancia rara vez son la misma.
VENTANA_PAGINAS = 400


def _fichas(texto: str | None) -> set[str]:
    """Trigramas de palabras. Aguantan mejor el ruido del OCR que comparar cadenas."""
    palabras = normalizar(texto).split()
    if len(palabras) < 3:
        return set(palabras)
    return {" ".join(palabras[i:i + 3]) for i in range(len(palabras) - 2)}


def _parecido(a: str | None, b: str | None) -> float:
    fa, fb = _fichas(a), _fichas(b)
    if not fa or not fb:
        return 0.0
    return len(fa & fb) / len(fa | fb)


def detectar(cx: sqlite3.Connection) -> dict:
    """Recorre las piezas activas y propone los pares que se parecen."""
    filas = cx.execute("""SELECT id, tipo, descripcion, texto_origen, pagina_inicio,
                                 pagina_fin
                            FROM v_evidencia WHERE activa = 1
                           ORDER BY pagina_inicio""").fetchall()
    cx.execute("DELETE FROM duplicado_posible WHERE estado='abierto'")
    descartados = {(r["evidencia_a"], r["evidencia_b"]) for r in cx.execute(
        "SELECT evidencia_a, evidencia_b FROM duplicado_posible WHERE estado='descartado'")}

    propuestos = 0
    for i, a in enumerate(filas):
        for b in filas[i + 1:]:
            if (a["pagina_inicio"] or 0) and (b["pagina_inicio"] or 0):
                if b["pagina_inicio"] - a["pagina_inicio"] > VENTANA_PAGINAS:
                    break                      # ordenadas: de acá en adelante, más lejos
            par = (min(a["id"], b["id"]), max(a["id"], b["id"]))
            if par in descartados:
                continue

            motivos, score = [], 0.0
            if a["tipo"] and a["tipo"] == b["tipo"]:
                score += 0.15
                motivos.append("mismo tipo")
            # La descripción pesa más que el cuerpo: dos actas distintas comparten
            # muchísima fórmula, y el título es lo que las distingue.
            sim_desc = _parecido(a["descripcion"], b["descripcion"])
            sim_texto = _parecido(a["texto_origen"], b["texto_origen"])
            score += 0.5 * sim_desc + 0.35 * sim_texto
            if sim_desc > 0.85:
                motivos.append("misma descripción")
            if sim_texto > 0.7:
                motivos.append("texto casi idéntico")
            if clave_ocr(a["descripcion"]) and \
               clave_ocr(a["descripcion"]) == clave_ocr(b["descripcion"]):
                score = max(score, 0.9)
                motivos.append("título idéntico")

            if score >= UMBRAL:
                cx.execute("""INSERT OR REPLACE INTO duplicado_posible
                              (evidencia_a, evidencia_b, score, motivo, estado, creado_en)
                              VALUES (?,?,?,?, 'abierto', ?)""",
                           (*par, round(min(1.0, score), 3), ", ".join(motivos), db.ahora()))
                propuestos += 1
    cx.commit()
    return {"propuestos": propuestos}


def listar(cx: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in cx.execute("""
        SELECT d.id, d.score, d.motivo, d.estado,
               a.id AS a_id, a.descripcion AS a_desc, a.foja_inicio AS a_foja,
               a.estado AS a_estado, a.pagina_inicio AS a_pagina,
               b.id AS b_id, b.descripcion AS b_desc, b.foja_inicio AS b_foja,
               b.estado AS b_estado, b.pagina_inicio AS b_pagina
          FROM duplicado_posible d
          JOIN v_evidencia a ON a.id = d.evidencia_a
          JOIN v_evidencia b ON b.id = d.evidencia_b
         WHERE d.estado = 'abierto' AND a.activa = 1 AND b.activa = 1
         ORDER BY d.score DESC""")]


def descartar(cx: sqlite3.Connection, duplicado_id: int) -> dict:
    """
    «No son la misma cosa.» Queda registrado para que no se vuelva a proponer en la
    próxima corrida: una propuesta que reaparece después de descartarla es la forma más
    rápida de que la gente deje de mirar las propuestas.
    """
    cx.execute("UPDATE duplicado_posible SET estado='descartado' WHERE id=?", (duplicado_id,))
    cx.commit()
    return {"descartado": duplicado_id}
