"""
Ingesta — de un PDF a filas de `documento` y `pagina`.

Acá no se lee nada del contenido todavía: se registra qué entró, cuántas páginas tiene
cada archivo y qué lugar ocupa cada página en la numeración global del caso. La lectura
es otra etapa, corre en segundo plano y puede tardar horas.

La numeración global es la que hace que el legajo sea UNO aunque venga en seis PDF. Si
el usuario reordena los archivos, se recalcula entera.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from . import almacen, config, db
from .almacen import ArchivoInvalido, OriginalAlterado, OriginalSinProteger

SIN_PROTEGER = ("el original quedó guardado pero el sistema de archivos NO lo dejó de "
                "sólo lectura: cualquiera con acceso a la carpeta puede modificarlo")


@dataclass
class ResultadoIngesta:
    documento_id: int | None
    nombre: str
    paginas: int
    duplicado: bool = False
    error: str | None = None
    advertencia: str | None = None

    def como_dict(self) -> dict:
        return {"documento_id": self.documento_id, "nombre": self.nombre,
                "paginas": self.paginas, "duplicado": self.duplicado,
                "error": self.error, "advertencia": self.advertencia}


def _metadatos(ruta: Path) -> tuple[int, list[tuple[float, float, bool]]]:
    """Devuelve (páginas, [(ancho_pt, alto_pt, tiene_texto_nativo), ...])."""
    paginas = []
    with pymupdf.open(ruta) as doc:
        for p in doc:
            texto = p.get_text("text").strip()
            paginas.append((p.rect.width, p.rect.height,
                            len(texto) >= config.MINIMO_TEXTO_NATIVO))
        return doc.page_count, paginas


def agregar(cx: sqlite3.Connection, datos: bytes, nombre: str) -> ResultadoIngesta:
    """Guarda el PDF y lo registra. No lee el contenido."""
    nombre = Path(nombre or "").name.strip() or "sin-nombre.pdf"
    try:
        g = almacen.guardar(datos, nombre)
    except ArchivoInvalido as e:
        db.anotar_excepcion(cx, "pdf_invalido", f"{nombre}: {e}")
        cx.commit()
        return ResultadoIngesta(None, nombre, 0, error=str(e))
    except OriginalAlterado as e:
        db.anotar_excepcion(cx, "original_alterado", str(e))
        cx.commit()
        return ResultadoIngesta(None, nombre, 0, error=str(e))
    except OriginalSinProteger as e:
        db.anotar_excepcion(cx, "original_sin_proteger", str(e))
        cx.commit()
        return ResultadoIngesta(None, nombre, 0, error=str(e))

    # Si llegó hasta acá sin protegerse es porque quien instaló lo aceptó a propósito.
    # Igual no pasa callado: queda en las excepciones del caso y la pantalla lo dice.
    advertencia = None
    if not g.protegido:
        advertencia = SIN_PROTEGER
        db.anotar_excepcion(cx, "original_sin_proteger", f"{nombre}: {g.ruta.name}")

    ya = cx.execute("SELECT id, paginas FROM documento WHERE sha256=?", (g.sha256,)).fetchone()
    if ya:
        # Copia exacta de algo que ya está. No se borra ni se vuelve a procesar: se
        # registra el hecho y se sigue. Que el mismo PDF llegue dos veces es normal
        # —lo manda el juzgado y también la policía— y no es un error de nadie.
        cx.execute("""INSERT OR IGNORE INTO documento_duplicado (sha256, nombre, visto_en)
                      VALUES (?,?,?)""", (g.sha256, nombre, db.ahora()))
        cx.commit()
        return ResultadoIngesta(ya["id"], nombre, ya["paginas"], duplicado=True,
                                advertencia=advertencia)

    try:
        n_pag, paginas = _metadatos(g.ruta)
    except Exception as e:
        db.anotar_excepcion(cx, "pdf_ilegible", f"{nombre}: {type(e).__name__}: {e}")
        cx.commit()
        return ResultadoIngesta(None, nombre, 0,
                                error=f"el PDF no se puede abrir ({type(e).__name__})")
    if n_pag == 0:
        db.anotar_excepcion(cx, "pdf_sin_paginas", nombre)
        cx.commit()
        return ResultadoIngesta(None, nombre, 0, error="el PDF no tiene páginas")

    orden = (cx.execute("SELECT COALESCE(MAX(orden), 0) FROM documento").fetchone()[0]) + 1
    offset = cx.execute("SELECT COALESCE(SUM(paginas), 0) FROM documento").fetchone()[0]

    doc_id = cx.execute(
        """INSERT INTO documento (sha256, nombre_archivo, ruta, bytes, paginas, orden,
                                  offset_global, ingerido_en)
           VALUES (?,?,?,?,?,?,?,?)""",
        (g.sha256, nombre, str(g.ruta), g.bytes, n_pag, orden, offset, db.ahora())
    ).lastrowid

    cx.executemany(
        """INSERT INTO pagina (documento_id, numero_pdf, numero_global,
                               ancho_pt, alto_pt, tiene_texto_nativo)
           VALUES (?,?,?,?,?,?)""",
        [(doc_id, i, offset + i, ancho, alto, 1 if nativo else 0)
         for i, (ancho, alto, nativo) in enumerate(paginas, start=1)])
    cx.commit()
    return ResultadoIngesta(doc_id, nombre, n_pag, advertencia=advertencia)


def reordenar(cx: sqlite3.Connection, orden_ids: list[int]) -> None:
    """
    Cambia el orden de los PDF del legajo y recalcula la numeración global.

    Hace falta de verdad: los archivos llegan con nombres como «escaneo_2.pdf» y el
    orden alfabético casi nunca es el orden del expediente. Y como la numeración global
    es la referencia técnica cuando no hay foliatura, tenerla mal es tenerlo todo mal.

    Recalcular mueve las páginas debajo de la evidencia ya cargada, así que también se
    corren los rangos de las piezas. Se hace en una transacción: a mitad de camino la
    base quedaría con dos numeraciones conviviendo.
    """
    actuales = [r["id"] for r in cx.execute("SELECT id FROM documento ORDER BY orden")]
    if sorted(orden_ids) != sorted(actuales):
        raise ValueError("la lista de reordenamiento no coincide con los documentos del caso")

    viejo = {r["numero_global"]: r["id"] for r in
             cx.execute("SELECT id, numero_global FROM pagina")}

    cx.execute("BEGIN")
    try:
        offset = 0
        # Las páginas tienen UNIQUE(numero_global) y se pisarían entre sí a mitad de la
        # renumeración. Se las corre primero a un rango imposible —negativo— y después
        # se las baja al definitivo.
        cx.execute("UPDATE pagina SET numero_global = -numero_global")
        for nuevo_orden, doc_id in enumerate(orden_ids, start=1):
            n = cx.execute("SELECT paginas FROM documento WHERE id=?", (doc_id,)).fetchone()["paginas"]
            cx.execute("UPDATE documento SET orden=?, offset_global=? WHERE id=?",
                       (nuevo_orden, offset, doc_id))
            cx.execute("""UPDATE pagina SET numero_global = ? + numero_pdf
                           WHERE documento_id = ?""", (offset, doc_id))
            offset += n

        # Las piezas de evidencia apuntan a páginas globales. Se las remapea por id de
        # página, que es lo único estable a través de una renumeración.
        nuevo = {r["id"]: r["numero_global"] for r in
                 cx.execute("SELECT id, numero_global FROM pagina")}
        traduccion = {g: nuevo[pid] for g, pid in viejo.items() if pid in nuevo}
        for ev in cx.execute("SELECT id, pagina_inicio, pagina_fin FROM evidencia").fetchall():
            ini = traduccion.get(ev["pagina_inicio"], ev["pagina_inicio"])
            fin = traduccion.get(ev["pagina_fin"], ev["pagina_fin"])
            if (ini, fin) != (ev["pagina_inicio"], ev["pagina_fin"]):
                cx.execute("UPDATE evidencia SET pagina_inicio=?, pagina_fin=? WHERE id=?",
                           (ini, fin, ev["id"]))
        # Los tramos de foliatura quedan sin sentido con otra numeración: se borran y
        # se vuelven a detectar. Las fojas CONFIRMADAS no se tocan, que es lo que
        # importa: el trabajo de una persona no se pierde por reordenar archivos.
        #
        # Se suelta el vínculo en TODAS las páginas antes de borrar, incluidas las
        # confirmadas. Si no, esas filas quedan apuntando a un tramo inexistente y
        # SQLite aborta la transacción por clave foránea.
        cx.execute("UPDATE pagina SET tramo_id = NULL")
        cx.execute("DELETE FROM tramo_foliatura")
        cx.execute("""UPDATE pagina SET foja_etiqueta=NULL, foja_num=NULL, foja_sufijo='',
                             foja_origen='desconocida', foja_confianza=NULL, foja_lectura=NULL
                       WHERE foja_origen = 'detectada'""")
        cx.execute("COMMIT")
    except Exception:
        cx.execute("ROLLBACK")
        raise


def documentos(cx: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in cx.execute("""
        SELECT d.*,
               (SELECT COUNT(*) FROM pagina p
                 WHERE p.documento_id = d.id AND p.texto IS NOT NULL) AS paginas_leidas
          FROM documento d ORDER BY d.orden""")]
