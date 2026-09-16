"""
Exportación del punteo.

RTF, texto plano y JSON. Los tres se arman acá y ninguno vuelve a consultar la
evidencia: lo que se exporta es lo que está en `punteo_parrafo`, que ya pasó por las
barreras del generador.

Con una excepción que es justamente la TERCERA vez que se controla lo mismo: antes de
escribir, se revalida que cada párrafo corresponda a una evidencia que siga incluida. El
agujero que tapa es concreto y no hipotético: se genera el punteo, alguien excluye una
pieza después, y el archivo que se exporta media hora más tarde sigue teniéndola.

RTF y no DOCX en el MVP porque RTF se escribe con la biblioteca estándar y abre igual en
Word y en LibreOffice. La arquitectura queda partida para que DOCX entre después sin
tocar el generador: lo único que hace falta es otra función `a_docx(punteo)`.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import config, generacion


class PunteoDesactualizado(RuntimeError):
    """
    Un párrafo del punteo apunta a evidencia que ya no está incluida.

    No se exporta a medias ni se saltea el párrafo en silencio: se corta y se dice
    exactamente cuál es. Exportar un escrito al que le falta un renglón sin avisar es
    peor que no exportar.
    """


def _control_previo(cx: sqlite3.Connection, punteo_id: int | None) -> dict:
    punteo = generacion.leer(cx, punteo_id)
    estado = generacion.revalidar(cx, punteo["id"])
    if estado["desactualizados"]:
        detalle = "; ".join(f"{d['numero']} {d['texto']}… (ahora {d['estado_actual']})"
                            for d in estado["desactualizados"][:5])
        raise PunteoDesactualizado(
            f"{len(estado['desactualizados'])} párrafo(s) del punteo ya no corresponden "
            f"a evidencia incluida: {detalle}. Volvé a generar el punteo antes de exportar.")
    # Lo mismo vale para lo que cambió DESPUÉS de generar: corregir una descripción,
    # confirmar una foja o asignar un testigo deja el texto guardado diciendo lo de
    # antes. Se exportaba igual, sin ninguna señal de que el archivo ya no era el caso.
    if estado["cambiados"]:
        detalle = "; ".join(f"{d['numero']} decía «{d['texto']}…» y ahora es «{d['ahora']}…»"
                            for d in estado["cambiados"][:3])
        raise PunteoDesactualizado(
            f"{len(estado['cambiados'])} párrafo(s) quedaron con datos viejos: {detalle}. "
            f"Volvé a generar el punteo antes de exportar.")
    if not estado["al_dia"]:
        # Cualquier diferencia frena, y las categorías de arriba sólo sirven para
        # explicar cuál. Controlar una por una dejaba pasar lo que no estuviera en la
        # lista —una pieza incluida después, un encabezado de sector reescrito— y eso es
        # un escrito al que le falta prueba ofrecida, que es el error que más caro sale.
        faltan = (f"{estado['incluidas_nuevas']} pieza(s) incluidas no están en el punteo"
                  if estado["incluidas_nuevas"] else "cambió algo desde que se generó")
        raise PunteoDesactualizado(
            f"el punteo no está al día: {faltan}. Volvé a generarlo antes de exportar.")
    return punteo


def _caso(cx: sqlite3.Connection) -> dict:
    fila = cx.execute("SELECT * FROM caso WHERE id=1").fetchone()
    return dict(fila) if fila else {}


# ──────────────────────────────────────────────────────────────────── texto ──
def a_texto(cx: sqlite3.Connection, punteo_id: int | None = None) -> str:
    punteo = _control_previo(cx, punteo_id)
    caso = _caso(cx)
    lineas = [f"Legajo {caso.get('numero_legajo', '')} — {caso.get('caratula', '')}".strip(" —"),
              "PRUEBA OFRECIDA", ""]
    for p in punteo["parrafos"]:
        if p["clase"] == "encabezado":
            lineas += ["", f"{p['numero']} {p['texto']}", ""]
        else:
            lineas.append(f"{p['numero']} {p['texto']}")
    return "\n".join(lineas).strip() + "\n"


# ────────────────────────────────────────────────────────────────────── RTF ──
def _rtf_escapar(texto: str) -> str:
    """
    Escapa para RTF. Lo no ASCII va como `\\uN?`, que es lo que entiende Word.

    Es la parte que más se equivoca al escribirla a mano y por eso está sola: las llaves
    y la barra son sintaxis de RTF, y una ñ sin escapar rompe el archivo entero o, peor,
    lo abre con la palabra cambiada.
    """
    salida = []
    for c in texto:
        if c in "\\{}":
            salida.append("\\" + c)
        elif ord(c) < 128:
            salida.append(c)
        else:
            # RTF usa enteros de 16 bits con signo.
            n = ord(c)
            salida.append(f"\\u{n if n < 32768 else n - 65536}?")
    return "".join(salida)


def a_rtf(cx: sqlite3.Connection, punteo_id: int | None = None) -> bytes:
    punteo = _control_previo(cx, punteo_id)
    caso = _caso(cx)

    partes = [r"{\rtf1\ansi\ansicpg1252\deff0",
              r"{\fonttbl{\f0\froman\fcharset0 Times New Roman;}}",
              r"\paperw11906\paperh16838\margl1701\margr1134\margt1134\margb1134",
              r"\f0\fs24\sl360\slmult1"]

    encabezado = f"Legajo {caso.get('numero_legajo', '')} — {caso.get('caratula', '')}"
    partes.append(r"\qc\b " + _rtf_escapar(encabezado.strip(" —")) + r"\b0\par")
    partes.append(r"\qc\b PRUEBA OFRECIDA\b0\par\par")

    for p in punteo["parrafos"]:
        if p["clase"] == "encabezado":
            partes.append(r"\par\ql\b " + _rtf_escapar(f"{p['numero']} {p['texto']}")
                          + r"\b0\par")
        else:
            # Justificado y con sangría de primera línea: es como se presenta un escrito
            # en el fuero, y llegar con el formato puesto ahorra el retoque a mano que
            # es donde se pierde el tiempo.
            partes.append(r"\qj\fi567 " + _rtf_escapar(f"{p['numero']} {p['texto']}")
                          + r"\par")

    partes.append("}")
    return "\n".join(partes).encode("cp1252", errors="replace")


# ───────────────────────────────────────────────────────────────────── JSON ──
def a_json(cx: sqlite3.Connection, punteo_id: int | None = None) -> str:
    """
    Respaldo estructurado. Lleva TODO lo que hace falta para reconstruir el trabajo:
    el caso, los documentos con su hash, las piezas con su estado y su anclaje, las
    personas, los grupos y el punteo generado.

    Acá sí se exporta la evidencia completa —incluidas, excluidas y pendientes— porque
    esto no es el escrito: es el respaldo. Lo que no puede pasar es que una excluida
    llegue al RTF o al texto, y de eso se ocupan las barreras del generador.
    """
    caso = _caso(cx)
    datos = {
        "formato": "punteo-evidencia/1",
        "caso": caso,
        "documentos": [dict(r) for r in cx.execute(
            "SELECT id, sha256, nombre_archivo, paginas, orden, ingerido_en FROM documento "
            "ORDER BY orden")],
        "fojas": [dict(r) for r in cx.execute(
            "SELECT numero_global, numero_pdf, documento_id, foja_etiqueta, foja_origen "
            "FROM pagina ORDER BY numero_global")],
        "grupos": [dict(r) for r in cx.execute(
            "SELECT * FROM grupo_evidencia ORDER BY orden")],
        "personas": [dict(r) for r in cx.execute("SELECT * FROM persona ORDER BY nombre")],
        "evidencias": [dict(r) for r in cx.execute(
            "SELECT * FROM v_evidencia WHERE activa=1 ORDER BY orden_salida, pagina_inicio")],
        "revisiones": [dict(r) for r in cx.execute("SELECT * FROM revision ORDER BY id")],
    }
    try:
        datos["punteo"] = generacion.leer(cx, punteo_id)
    except KeyError:
        datos["punteo"] = None
    return json.dumps(datos, ensure_ascii=False, indent=2)


# ───────────────────────────────────────────────────────────── a un archivo ──
FORMATOS = {"rtf": ("rtf", "application/rtf"),
            "txt": ("txt", "text/plain; charset=utf-8"),
            "json": ("json", "application/json; charset=utf-8")}


def contenido(cx: sqlite3.Connection, formato: str,
              punteo_id: int | None = None) -> tuple[bytes, str, str]:
    """Devuelve (bytes, nombre sugerido, tipo MIME)."""
    if formato not in FORMATOS:
        raise ValueError(f"formato desconocido: {formato!r}")
    caso = _caso(cx)
    base = (caso.get("numero_legajo") or "punteo").replace("/", "-").replace(" ", "")
    extension, mime = FORMATOS[formato]
    nombre = f"punteo-{base}.{extension}"
    if formato == "rtf":
        return a_rtf(cx, punteo_id), nombre, mime
    if formato == "txt":
        return a_texto(cx, punteo_id).encode("utf-8"), nombre, mime
    return a_json(cx, punteo_id).encode("utf-8"), nombre, mime


def guardar(cx: sqlite3.Connection, formato: str, punteo_id: int | None = None) -> Path:
    """Escribe el archivo en la carpeta `export/` del caso y devuelve la ruta."""
    datos, nombre, _ = contenido(cx, formato, punteo_id)
    destino = Path(config.EXPORT) / nombre
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)
    return destino
