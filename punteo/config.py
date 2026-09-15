"""
Configuración y constantes. Todo por ruta relativa: el proyecto es portable y se
copia a una máquina desconectada tal como está.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Lo que es del programa y no de la causa. Constantes de verdad: si alguna de estas se
# resolviera por hilo, un pedido sin caso abierto se quedaría sin esquema y sin interfaz.
ESQUEMA = RAIZ / "punteo" / "esquema.sql"
WEB     = RAIZ / "punteo" / "web"
# Las fuentes son las de AppUFIL: OFL, ya están en disco y no hay razón para bajar
# otras. Si el proyecto se muda a su propio repositorio, hay que copiar esa carpeta.
FUENTES = Path(os.environ.get("PUNTEO_FUENTES", RAIZ.parent / "assets" / "fuentes"))

DATOS = Path(os.environ.get("PUNTEO_DATOS", RAIZ / "datos"))


# ── El caso abierto ─────────────────────────────────────────────────────────
# Cuál es el caso activo se guarda POR HILO, no en una variable global: el servidor
# atiende pedidos en varios hilos y el procesamiento corre en otro, así que un valor
# compartido significaría que abrir un caso en una pestaña le cambia el caso al trabajo
# que está corriendo en otra. Esa es exactamente la mezcla que separar por archivo
# existe para evitar.
_local = threading.local()
CASO_POR_OMISION: str | None = os.environ.get("PUNTEO_CASO", "").strip() or None
_BASE_FIJA = os.environ.get("PUNTEO_BASE", "").strip()


def caso_activo() -> str | None:
    return getattr(_local, "caso", CASO_POR_OMISION)


def activar_caso(slug: str | None) -> None:
    """Cambia el caso sobre el que trabaja ESTE hilo. Base y derivados se mueven juntos."""
    _local.caso = slug or None


def fijar_caso_por_omision(slug: str | None) -> None:
    """
    El caso con el que arranca cualquier hilo que no diga otra cosa.

    Se hace con una variable de módulo y no con la de hilo justamente porque tiene que
    alcanzar a los hilos de petición, que todavía no existen cuando se llama.
    """
    global CASO_POR_OMISION
    CASO_POR_OMISION = slug or None


def carpeta_casos() -> Path:
    return DATOS / "casos"


def carpeta_caso(slug: str) -> Path:
    return carpeta_casos() / slug


def _base() -> Path:
    if _BASE_FIJA:                       # lo que usan las pruebas
        return Path(_BASE_FIJA)
    slug = caso_activo()
    if not slug:
        raise SinCasoAbierto("no hay ningún caso abierto en este hilo")
    return carpeta_caso(slug) / "punteo.sqlite"


def _por_caso(sub: str) -> Path:
    if _BASE_FIJA:
        return Path(_BASE_FIJA).parent / sub
    slug = caso_activo()
    if not slug:
        raise SinCasoAbierto("no hay ningún caso abierto en este hilo")
    return carpeta_caso(slug) / sub


class SinCasoAbierto(RuntimeError):
    """
    Se pidió la base o una carpeta sin haber abierto un caso.

    Es un error explícito y no un valor por omisión a propósito: caer en una carpeta
    suelta «por las dudas» es cómo la evidencia de una causa termina escrita en la
    carpeta de otra.
    """


_DINAMICAS = {
    "BASE":       _base,
    "ORIGINALES": lambda: _por_caso("originales"),
    "DERIVADOS":  lambda: _por_caso("derivados"),
    "EXPORT":     lambda: _por_caso("export"),
    "RESPALDOS":  lambda: _por_caso("respaldos"),
}


def __getattr__(nombre: str):
    """Resuelve BASE, ORIGINALES, DERIVADOS… según el caso activo en este hilo."""
    fn = _DINAMICAS.get(nombre)
    if fn is None:
        raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")
    return fn()


# ── Lectura de página ───────────────────────────────────────────────────────
# DPI al que se rasteriza para hacer OCR. 200 es el punto donde Tesseract deja de
# mejorar con escaneos de oficina; subir a 300 cuesta el doble de tiempo y de memoria
# para ganar décimas.
DPI_OCR = int(os.environ.get("PUNTEO_DPI_OCR", 200))
# DPI al que se sirve la imagen al visor. Más bajo que el de OCR: en pantalla no se
# nota y baja mucho el peso de la caché.
DPI_VISOR = int(os.environ.get("PUNTEO_DPI_VISOR", 150))
PT_POR_PULGADA = 72.0

# Cuánto puede ocupar la caché de imágenes de página antes de que se empiecen a borrar
# las más viejas. Las imágenes son regenerables: no se pierde nada al borrarlas.
CACHE_IMAGENES_MB = int(os.environ.get("PUNTEO_CACHE_MB", 512))

NUCLEOS_OCR = int(os.environ.get("PUNTEO_NUCLEOS", os.cpu_count() or 2))
CONFIRMAR_CADA = 10          # páginas entre commits, para que un corte no cueste todo

OCR_IDIOMA = os.environ.get("PUNTEO_OCR_IDIOMA", "spa")
OCR_CONFIG = "--oem 1 --psm 6"

# Una capa de texto de cuatro caracteres sueltos no es una capa de texto: es el pie de
# página que el escáner metió encima de una imagen.
MINIMO_TEXTO_NATIVO = 40

# Debajo de esta confianza la página se considera mal leída. Se muestra, se cuenta y se
# puede filtrar: la persona tiene que saber qué parte del legajo el sistema no leyó.
CONFIANZA_PAGINA_POBRE = 0.55
# Debajo de esta confianza, y con tinta en la hoja, se sospecha que esté de costado.
CONFIANZA_SOSPECHA_GIRO = 0.75
CONFIANZA_ORIENTACION = 0.6
MEJORA_MINIMA_GIRO = 0.12

# ── Evidencia ───────────────────────────────────────────────────────────────
# Umbrales de los tres niveles de confianza que muestra la interfaz. No reemplazan la
# revisión humana: sirven para ordenar por dónde empezar y para filtrar.
CONFIANZA_ALTA = 0.75
CONFIANZA_MEDIA = 0.55

MAX_BYTES_PDF = 500 * 1024 * 1024

PUERTO = int(os.environ.get("PUNTEO_PUERTO", 8714))
HOST = os.environ.get("PUNTEO_HOST", "127.0.0.1")
