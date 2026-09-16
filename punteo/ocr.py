"""
Lectura de página — texto con coordenadas.

Tres rutas, y la página decide cuál:

  * el PDF trae capa de texto nativa  -> se lee directo, exacto, confianza 1,0;
  * es un escaneo                     -> se rasteriza en memoria y va a Tesseract;
  * es un escaneo con texto encima    -> las dos cosas, juntas (ver `leer_pagina`).

Todas devuelven lo mismo: una lista de `Palabra` con su recuadro en PUNTOS PDF,
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
from PIL import Image, ImageDraw

from . import config, db


@dataclass
class Palabra:
    texto: str
    x0: float; y0: float; x1: float; y1: float     # puntos PDF
    conf: float                                     # 0..1


@dataclass
class Lectura:
    ruta: str                 # nativo | ocr | mixta
    palabras: list[Palabra]
    confianza: float
    ancho_pt: float
    alto_pt: float
    rotacion: int
    ms: int
    # Qué parte de la hoja está tapada por imágenes, y si alguna puede tener texto que la
    # capa nativa no trae. Sólo lo calcula la ruta nativa, y es lo que decide si además
    # hace falta leer la imagen.
    cobertura_imagen: float = 0.0
    imagen_por_leer: bool = False

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
def _imagenes(pag, palabras_sin_girar: list[Palabra]) -> tuple[float, bool]:
    """
    Qué fracción de la hoja ocupan las imágenes, y si alguna puede tener texto sin leer.

    La fracción sola no alcanza. Un escaneo es una imagen del tamaño de la página, pero
    un acta escaneada pegada al cuarenta por ciento de una hoja digital también es un
    documento, y con un umbral de «media página» su texto quedaba afuera de la búsqueda
    y de la detección. Se mira además cada imagen grande por separado: si casi no tiene
    texto nativo encima, lo que dice está en la imagen y hay que leerlo. Los escudos y
    las firmas quedan debajo del tamaño mínimo y no mandan la hoja al OCR.

    Las dos cosas se calculan en el marco SIN girar de la página, que es en el que
    PyMuPDF devuelve tanto las imágenes como las palabras.
    """
    hoja = pag.rect * pag.derotation_matrix
    area = hoja.width * hoja.height
    if not area:
        return 0.0, False
    tapado, por_leer = 0.0, False
    for info in pag.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & hoja
        if r.is_empty:
            continue
        tapado += r.width * r.height
        if r.width * r.height >= config.IMAGEN_MINIMA_OCR * area:
            encima = sum(1 for p in palabras_sin_girar
                         if r.contains(pymupdf.Point((p.x0 + p.x1) / 2, (p.y0 + p.y1) / 2)))
            if encima < config.PALABRAS_QUE_EXPLICAN_UNA_IMAGEN:
                por_leer = True
    cobertura = min(1.0, tapado / area)
    return cobertura, por_leer or cobertura >= config.COBERTURA_IMAGEN_OCR


def leer_nativo(ruta_pdf: Path, numero_pdf: int) -> Lectura:
    t0 = time.perf_counter()
    sin_girar = []
    with pymupdf.open(ruta_pdf) as doc:
        pag = doc[numero_pdf - 1]
        for x0, y0, x1, y1, w, *_ in pag.get_text("words"):
            if w.strip():
                sin_girar.append(Palabra(w, x0, y0, x1, y1, 1.0))
        cobertura, por_leer = _imagenes(pag, sin_girar)
        # PyMuPDF devuelve las palabras en el marco de la página SIN girar, y la hoja
        # (`rect`) y la imagen del visor en el marco girado. En una página con /Rotate
        # eso dejaba el resaltado en otro lado de la foja y la foliatura buscando el
        # número en el margen equivocado. Todo se pasa al marco girado, que es el que se
        # ve y el mismo en que devuelve el OCR.
        giro = pag.rotation_matrix
        palabras = []
        for p in sin_girar:
            r = pymupdf.Rect(p.x0, p.y0, p.x1, p.y1) * giro
            palabras.append(Palabra(p.texto, r.x0, r.y0, r.x1, r.y1, 1.0))
        ancho, alto = pag.rect.width, pag.rect.height
    return Lectura("nativo", palabras, 1.0, ancho, alto, 0,
                   int((time.perf_counter() - t0) * 1000), cobertura, por_leer)


def _solapa(p: Palabra, otras: list[Palabra], margen: float = 2.0) -> bool:
    """¿El centro de esta palabra cae adentro de alguna de las otras?"""
    cx, cy = (p.x0 + p.x1) / 2, (p.y0 + p.y1) / 2
    return any(o.x0 - margen <= cx <= o.x1 + margen and o.y0 - margen <= cy <= o.y1 + margen
               for o in otras)


def _tinta_sin_leer(im: Image.Image, palabras: list[Palabra], dpi: int) -> float:
    """
    Qué fracción de la hoja es tinta que ninguna palabra leída explica.

    Se tapan con blanco los recuadros de todo lo que se leyó —nativo y OCR— y se cuenta
    lo oscuro que queda. Un cuerpo escaneado que el OCR no pudo leer deja mucha tinta
    afuera; un membrete o un fondo con la capa de texto completa encima, poca.
    """
    escala = dpi / config.PT_POR_PULGADA
    gris = im.convert("L")
    dibujo = ImageDraw.Draw(gris)
    for p in palabras:
        dibujo.rectangle((p.x0 * escala - 3, p.y0 * escala - 3,
                          p.x1 * escala + 3, p.y1 * escala + 3), fill=255)
    h = gris.histogram()
    return sum(h[:128]) / (sum(h) or 1)


def _combinar(nativa: Lectura, ocr: Lectura, im: Image.Image | None = None,
              dpi: int = 0) -> Lectura:
    """
    Junta lo que traía la capa de texto con lo que leyó el OCR en la imagen.

    Lo nativo se queda tal cual —es exacto— y del OCR se suma sólo lo que no está encima
    de una palabra nativa: la página se rasteriza entera, así que el OCR también lee el
    sello que ya venía como texto, y contarlo dos veces ensucia la búsqueda y la
    detección.

    La confianza es la de lo que HUBO que leer con OCR, no la de la capa nativa: una
    página con el cuerpo escaneado y un pie digital no se leyó al cien por ciento, y un
    1,0 en la pantalla escondería justamente la parte dudosa.

    Que el OCR no encuentre nada fuera de lo nativo NO prueba que la imagen sea fondo.
    El caso que lo mostró: un escaneo ilegible con el sello digital encima, donde el OCR
    lee sólo el sello; tomarlo por fondo devolvía la lectura nativa con confianza 1,0 y
    el cuerpo quedaba afuera sin aviso. Se mira entonces la tinta que queda fuera de todo
    lo leído: si hay, la página vuelve con confianza cero y aparece entre las mal
    leídas —también una foto sin epígrafe, que el sistema de verdad no leyó—; si no hay,
    la imagen era fondo y vale lo nativo. Lo mismo si el OCR no devolvió ni una palabra,
    ni siquiera el sello, que también está dibujado en la imagen.
    """
    extra = [p for p in ocr.palabras if not _solapa(p, nativa.palabras)]
    palabras = (sorted(nativa.palabras + extra, key=lambda p: (round(p.y0, 1), p.x0))
                if extra else nativa.palabras)
    # El control de tinta corre SIEMPRE, no sólo cuando el OCR no sumó nada: con que
    # leyera un número de foja suelto, la página salía con la confianza de ese número y
    # el cuerpo ilegible quedaba afuera igual, sin figurar entre las mal leídas.
    queda_tinta = (not ocr.palabras or (
        im is not None
        and _tinta_sin_leer(im, nativa.palabras + ocr.palabras, dpi) > config.TINTA_SIN_LEER))
    if queda_tinta:
        return Lectura("mixta", palabras, 0.0, nativa.ancho_pt, nativa.alto_pt, 0,
                       nativa.ms + ocr.ms, nativa.cobertura_imagen)
    if not extra:
        return nativa
    confianza = sum(p.conf for p in extra) / len(extra)
    return Lectura("mixta", palabras, confianza, nativa.ancho_pt, nativa.alto_pt, 0,
                   nativa.ms + ocr.ms, nativa.cobertura_imagen)


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
    """
    Todo el trabajo de UNA página. No toca la base: se puede correr en paralelo.

    La capa de texto sola no alcanza para decidir que la página está leída. El caso que
    lo mostró es de todos los días: un escaneo con el sello de firma digital encima. El
    sello trae texto nativo de sobra, la página pasaba por digital, y el cuerpo —que es
    una imagen— nunca llegaba al OCR: quedaba indexado el sello, se perdía el contenido
    para la búsqueda y la detección, y la pantalla decía confianza 1,0. Ahora, si la hoja
    está tapada por imágenes, se lee también la imagen y se junta.
    """
    nativa = None
    if tiene_texto_nativo:
        nativa = leer_nativo(ruta_pdf, numero_pdf)
        if nativa.palabras and not nativa.imagen_por_leer:
            return nativa
        # O la capa de texto prometía y no trajo nada, o trae algo pero la hoja es una
        # imagen. En los dos casos hay que leer la imagen.

    im = _pixmap(ruta_pdf, numero_pdf, config.DPI_OCR)
    lec = leer_ocr(im, config.DPI_OCR)
    if lec.confianza < config.CONFIANZA_SOSPECHA_GIRO and tiene_tinta(im):
        _, lec, _ = _enderezar_si_mejora(im, config.DPI_OCR, lec)
    if nativa is not None and nativa.palabras and not lec.rotacion:
        # Con la página girada, las coordenadas del OCR están en otro marco que las de la
        # capa nativa, y juntarlas pondría el sello en cualquier lado. Ahí vale el OCR
        # solo, que igual lee el sello porque la imagen se rasteriza entera.
        return _combinar(nativa, lec, im, config.DPI_OCR)
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
def pagina_para_imagen(cx: sqlite3.Connection, numero_global: int) -> sqlite3.Row:
    fila = cx.execute("""SELECT p.numero_pdf, p.rotacion, d.ruta, d.sha256
                           FROM pagina p JOIN documento d ON d.id = p.documento_id
                          WHERE p.numero_global=?""", (numero_global,)).fetchone()
    if not fila:
        raise KeyError(f"no hay página global {numero_global}")
    return fila


def identidad_imagen(fila: sqlite3.Row, dpi: int) -> str:
    """
    Qué imagen es ésta, sin depender de la numeración del caso.

    El número global NO sirve para identificarla: reordenar los PDF se lo cambia a todas
    las páginas, y una caché con esa clave devolvía la hoja de otro documento con los
    datos del correcto al lado. Decidir sobre una pieza mirando otra foja es exactamente
    lo que este sistema existe para que no pase.

    La identidad es el documento —su SHA-256, que no cambia nunca—, la página adentro de
    ese PDF, la rotación con la que se leyó y el DPI. La rotación entra porque se fija al
    leer la página: la imagen pedida antes de procesar sale derecha y la de después,
    girada, y son dos imágenes distintas del mismo papel.
    """
    return f"{fila['sha256'][:16]}-p{fila['numero_pdf']:05d}-r{fila['rotacion'] or 0}-{dpi}"


def imagen_pagina(cx: sqlite3.Connection, numero_global: int, *,
                  dpi: int | None = None) -> tuple[bytes, str]:
    """La imagen de una página del caso, resolviendo primero de qué página se trata."""
    return imagen_de(pagina_para_imagen(cx, numero_global), dpi=dpi)


def imagen_de(fila: sqlite3.Row, *, dpi: int | None = None) -> tuple[bytes, str]:
    """
    La imagen de una página, para el visor. Se rasteriza en el momento y se cachea.

    Recibe la fila ya resuelta y no el número de página a propósito: quien sirve la
    imagen necesita la identidad para la etiqueta del navegador, y si la busca por su
    cuenta puede leerla antes de un reordenamiento y los bytes después. Serviría la hoja
    de un documento con la etiqueta de otro, que es la misma confusión que esa etiqueta
    existe para evitar.

    Devuelve (bytes, tipo MIME). JPEG y no PNG: para un escaneo pesa entre un quinto y
    un décimo, y la caché de un legajo grande es la diferencia entre doscientos megas y
    dos gigas. La caché es descartable —se puede borrar entera sin perder nada— y por
    eso vive en `derivados/`.
    """
    dpi = dpi or config.DPI_VISOR
    cache = Path(config.DERIVADOS) / f"{identidad_imagen(fila, dpi)}.jpg"
    if cache.exists():
        try:
            # Se marca el uso a mano en lugar de confiar en la fecha de acceso del
            # sistema de archivos: casi todos los Linux modernos montan con `relatime`
            # y no actualizan `atime` en cada lectura, así que el podado por «lo menos
            # usado» terminaba borrando por orden de creación, que es justo al revés de
            # lo que conviene mientras alguien revisa un tramo del legajo.
            os.utime(cache, None)
        except OSError:
            pass
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
    """Borra las imágenes menos usadas cuando la caché pasa del tope."""
    tope = config.CACHE_IMAGENES_MB * 1024 * 1024
    archivos = []
    for p in carpeta.glob("*.jpg"):
        try:
            st = p.stat()
        except OSError:
            continue          # se borró entre el listado y el stat
        archivos.append((st.st_mtime, st.st_size, p))
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
