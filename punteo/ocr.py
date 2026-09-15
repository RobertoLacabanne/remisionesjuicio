"""
Lectura de página — texto con coordenadas.

Dos rutas, y la página decide cuál:

  * el PDF trae capa de texto nativa  -> se lee directo, exacto, confianza 1,0;
  * es un escaneo                     -> se rasteriza en memoria y va a Tesseract.

Las dos devuelven lo mismo: una lista de `Palabra` con su recuadro en PUNTOS PDF,
origen arriba-izquierda. Esa unidad común es lo que permite resaltar en la imagen el
fragmento que sustenta una pieza de evidencia.

Lo que NO se hace, y es la diferencia grande con AppUFIL: no se guarda la imagen de
cada página. El OCR trabaja sobre un pixmap en memoria y lo descarta. A 200 DPI un PNG
por página son unos 500 KB, y un legajo de 5.000 páginas son dos gigas y medio de
imágenes que en su mayoría nadie va a mirar. El visor pide la página que está mirando
y esa se rasteriza en el momento (ver `imagen_pagina`).
"""
from __future__ import annotations

import io
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image

from . import config, db


@dataclass
class Palabra:
    texto: str
    x0: float; y0: float; x1: float; y1: float     # puntos PDF
    conf: float                                     # 0..1


@dataclass
class Lectura:
    ruta: str                 # nativo | ocr
    palabras: list[Palabra]
    confianza: float
    ancho_pt: float
    alto_pt: float
    rotacion: int
    ms: int

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palabras)


class SinOCR(RuntimeError):
    """Tesseract no está instalado o no se puede invocar."""


def hay_ocr() -> tuple[bool, str]:
    try:
        return True, f"Tesseract {pytesseract.get_tesseract_version()}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def idiomas_ocr() -> list[str]:
    try:
        return list(pytesseract.get_languages(config=""))
    except Exception:
        return []


# ──────────────────────────────────────────────────────────── rasterización ──
def _pixmap(ruta_pdf: Path, numero_pdf: int, dpi: int) -> Image.Image:
    escala = dpi / config.PT_POR_PULGADA
    with pymupdf.open(ruta_pdf) as doc:
        pix = doc[numero_pdf - 1].get_pixmap(matrix=pymupdf.Matrix(escala, escala))
        return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def tiene_tinta(im: Image.Image) -> bool:
    """¿La hoja tiene algo escrito? Una página en blanco no se endereza ni se interroga."""
    h = im.convert("L").histogram()
    total = sum(h)
    return bool(total) and sum(h[:200]) / total > 0.004


def detectar_rotacion(im: Image.Image) -> int:
    """
    Cuántos grados hay que girar la página para dejarla derecha.

    Alguien apoya la hoja de costado en el escáner y esa foja se pierde entera: el motor
    no reconoce una palabra y la pieza de evidencia que estaba ahí desaparece sin dejar
    rastro. Pasa seguido y es barato de arreglar.

    Devuelve 0 si no está seguro: girar una página derecha es peor que no girar la
    torcida.
    """
    try:
        datos = pytesseract.image_to_osd(im, output_type=pytesseract.Output.DICT)
    except Exception:
        return 0
    grados = int(datos.get("rotate", 0)) % 360
    conf = float(datos.get("orientation_conf", 0) or 0)
    return grados if grados in (90, 180, 270) and conf >= config.CONFIANZA_ORIENTACION else 0


# ───────────────────────────────────────────────────────────── ruta: nativa ──
def leer_nativo(ruta_pdf: Path, numero_pdf: int) -> Lectura:
    t0 = time.perf_counter()
    palabras = []
    with pymupdf.open(ruta_pdf) as doc:
        pag = doc[numero_pdf - 1]
        for x0, y0, x1, y1, w, *_ in pag.get_text("words"):
            if w.strip():
                palabras.append(Palabra(w, x0, y0, x1, y1, 1.0))
        ancho, alto = pag.rect.width, pag.rect.height
    return Lectura("nativo", palabras, 1.0, ancho, alto, 0,
                   int((time.perf_counter() - t0) * 1000))


# ──────────────────────────────────────────────────────────────── ruta: OCR ──
def leer_ocr(im: Image.Image, dpi: int) -> Lectura:
    t0 = time.perf_counter()
    escala = dpi / config.PT_POR_PULGADA
    datos = pytesseract.image_to_data(im, lang=config.OCR_IDIOMA,
                                      config=config.OCR_CONFIG,
                                      output_type=pytesseract.Output.DICT)
    palabras, confs = [], []
    for i, texto in enumerate(datos["text"]):
        texto = (texto or "").strip()
        if not texto:
            continue
        try:
            c = float(datos["conf"][i])
        except (TypeError, ValueError):
            c = -1.0
        if c < 0:
            continue
        conf = c / 100.0
        x, y = datos["left"][i] / escala, datos["top"][i] / escala
        w, h = datos["width"][i] / escala, datos["height"][i] / escala
        palabras.append(Palabra(texto, x, y, x + w, y + h, conf))
        confs.append(conf)
    media = sum(confs) / len(confs) if confs else 0.0
    return Lectura("ocr", palabras, media, im.width / escala, im.height / escala, 0,
                   int((time.perf_counter() - t0) * 1000))


def _enderezar_si_mejora(im: Image.Image, dpi: int, primera: Lectura) -> tuple[int, Lectura, Image.Image]:
    """
    Endereza sólo si al releer sale MEJOR. Devuelve (grados, lectura buena, imagen).

    La lección es de AppUFIL y vale repetirla porque costó descubrirla: el detector de
    orientación de Tesseract acierta el ÁNGULO con mucha seguridad sobre una página
    densa y con poca sobre una hoja escasa, pero en ninguno de los dos casos se
    equivocó diciendo que una página derecha estaba torcida.

    De ahí las dos reglas: si dice que está derecha se le cree y no se prueba nada; si
    sugiere un ángulo, la decisión no la toma él sino el RESULTADO. Así el umbral de
    confianza del detector deja de ser crítico y las páginas simplemente borrosas no
    pagan lecturas de más.
    """
    sugerido = detectar_rotacion(im)
    if not sugerido:
        return 0, primera, im

    mejor_rot, mejor_lec, mejor_im = 0, primera, im
    for g in [sugerido] + [x for x in (90, 180, 270) if x != sugerido]:
        girada = im.rotate(-g, expand=True)      # PIL gira antihorario; acá se piensa horario
        try:
            lec = leer_ocr(girada, dpi)
        except Exception:
            continue
        if lec.confianza > mejor_lec.confianza + config.MEJORA_MINIMA_GIRO:
            mejor_rot, mejor_lec, mejor_im = g, lec, girada
            break                                 # con una que mejore claramente alcanza
    mejor_lec.rotacion = mejor_rot
    return mejor_rot, mejor_lec, mejor_im


# ──────────────────────────────────────────────────────────── orquestación ──
def leer_pagina(ruta_pdf: Path, numero_pdf: int, tiene_texto_nativo: bool) -> Lectura:
    """Todo el trabajo de UNA página. No toca la base: se puede correr en paralelo."""
    if tiene_texto_nativo:
        lec = leer_nativo(ruta_pdf, numero_pdf)
        if lec.palabras:
            return lec
        # La capa de texto prometía y no cumplió. Pasa con PDF donde el texto es un
        # sello o un pie de página sobre una imagen. Se cae a OCR en vez de dar por
        # leída una página de la que no se sacó una palabra.

    im = _pixmap(ruta_pdf, numero_pdf, config.DPI_OCR)
    lec = leer_ocr(im, config.DPI_OCR)
    if lec.confianza < config.CONFIANZA_SOSPECHA_GIRO and tiene_tinta(im):
        _, lec, _ = _enderezar_si_mejora(im, config.DPI_OCR, lec)
    return lec


def _guardar(cx: sqlite3.Connection, pagina_id: int, lec: Lectura) -> None:
    cx.execute("DELETE FROM palabra WHERE pagina_id=?", (pagina_id,))
    cx.executemany(
        """INSERT INTO palabra (pagina_id, orden, texto, x0, y0, x1, y1, conf)
           VALUES (?,?,?,?,?,?,?,?)""",
        [(pagina_id, i, p.texto, p.x0, p.y0, p.x1, p.y1, p.conf)
         for i, p in enumerate(lec.palabras)])
    cx.execute("""UPDATE pagina SET texto=?, ruta_lectura=?, confianza=?, rotacion=?,
                         ancho_pt=?, alto_pt=?, leida_en=? WHERE id=?""",
               (lec.texto, lec.ruta, lec.confianza, lec.rotacion,
                lec.ancho_pt, lec.alto_pt, db.ahora(), pagina_id))


def leer_caso(cx: sqlite3.Connection, *, avance=None, seguir=None) -> dict:
    """
    Lee todas las páginas que falten, repartidas entre los núcleos disponibles.

    Se reparte por PÁGINA y no por documento: el OCR domina el tiempo, cada página es
    independiente, y repartiendo por archivo los núcleos quedarían esperando al PDF más
    largo. Tesseract usa varios hilos por su cuenta y eso pelea con el pool, así que se
    lo limita a uno y se corren varios en paralelo.

    `seguir` se consulta entre página y página: si devuelve False, se corta. Cortar es
    seguro porque se confirma cada pocas páginas, así que al reanudar se retoma desde
    la que faltaba y no se repite nada.
    """
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    trabajos = [(r["id"], Path(r["ruta"]), r["numero_pdf"], bool(r["tiene_texto_nativo"]))
                for r in cx.execute("""
        SELECT p.id, p.numero_pdf, p.tiene_texto_nativo, d.ruta
          FROM pagina p JOIN documento d ON d.id = p.documento_id
         WHERE p.texto IS NULL
         ORDER BY p.numero_global""")]
    total = len(trabajos)
    if not total:
        return {"paginas": 0, "hechas": 0, "fallidas": 0, "cortado": False}

    hechas = fallidas = 0
    cortado = False
    obreros = max(1, min(config.NUCLEOS_OCR, total))
    with ThreadPoolExecutor(max_workers=obreros) as pool:
        futuros = {pool.submit(leer_pagina, ruta, nro, nativo): pid
                   for pid, ruta, nro, nativo in trabajos}
        for fut in as_completed(futuros):
            if seguir is not None and not seguir():
                cortado = True
                for otro in futuros:
                    otro.cancel()
                break
            pid = futuros[fut]
            try:
                _guardar(cx, pid, fut.result())
            except Exception as e:
                fallidas += 1
                db.anotar_excepcion(cx, "lectura_fallida",
                                    f"{type(e).__name__}: {e}", pagina_id=pid)
            hechas += 1
            # Confirmar cada tanto y no al final: un corte de luz a los ochenta minutos
            # no puede costar los ochenta minutos.
            if hechas % config.CONFIRMAR_CADA == 0:
                cx.commit()
            if avance:
                avance(hechas, total)
    cx.commit()
    return {"paginas": total, "hechas": hechas, "fallidas": fallidas, "cortado": cortado}


# ───────────────────────────────────────────────── la imagen para el visor ──
def imagen_pagina(cx: sqlite3.Connection, numero_global: int, *,
                  dpi: int | None = None) -> tuple[bytes, str]:
    """
    La imagen de una página, para el visor. Se rasteriza en el momento y se cachea.

    Devuelve (bytes, tipo MIME). JPEG y no PNG: para un escaneo pesa entre un quinto y
    un décimo, y la caché de un legajo grande es la diferencia entre doscientos megas y
    dos gigas. La caché es descartable —se puede borrar entera sin perder nada— y por
    eso vive en `derivados/`.
    """
    dpi = dpi or config.DPI_VISOR
    fila = cx.execute("""SELECT p.numero_pdf, p.rotacion, d.ruta
                           FROM pagina p JOIN documento d ON d.id = p.documento_id
                          WHERE p.numero_global=?""", (numero_global,)).fetchone()
    if not fila:
        raise KeyError(f"no hay página global {numero_global}")

    cache = Path(config.DERIVADOS) / f"p{numero_global:06d}-{dpi}.jpg"
    if cache.exists():
        return cache.read_bytes(), "image/jpeg"

    im = _pixmap(Path(fila["ruta"]), fila["numero_pdf"], dpi)
    # Se aplica la MISMA rotación que se usó para leer. Si no, el recuadro que resalta
    # el fragmento de una evidencia cae en otro lado de la imagen que se ve en pantalla.
    if fila["rotacion"]:
        im = im.rotate(-fila["rotacion"], expand=True)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True)
    datos = buf.getvalue()

    cache.parent.mkdir(parents=True, exist_ok=True)
    try:
        cache.write_bytes(datos)
        _podar_cache(cache.parent)
    except OSError:
        pass          # sin caché anda igual, sólo más lento
    return datos, "image/jpeg"


def _podar_cache(carpeta: Path) -> None:
    """Borra las imágenes más viejas cuando la caché pasa del tope."""
    tope = config.CACHE_IMAGENES_MB * 1024 * 1024
    archivos = [(p.stat().st_atime, p.stat().st_size, p) for p in carpeta.glob("p*.jpg")]
    total = sum(s for _, s, _ in archivos)
    if total <= tope:
        return
    for _, size, p in sorted(archivos):
        try:
            p.unlink()
        except OSError:
            continue
        total -= size
        if total <= tope * 0.8:      # se baja con margen, para no podar en cada pedido
            break
