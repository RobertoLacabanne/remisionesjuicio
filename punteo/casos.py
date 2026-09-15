"""
Alta, listado y apertura de casos.

Cada caso es una carpeta con su propia base. Separar por archivo y no por una columna
`caso_id` convierte «ningún cálculo cruza casos» en un hecho físico en lugar de un
WHERE que alguien puede olvidarse de escribir: respaldar un caso es copiar una carpeta,
borrarlo es borrarla, y una consulta mal escrita no puede traer evidencia de otra causa
porque esa evidencia no está en la base que la consulta abrió.
"""
from __future__ import annotations

import re
import shutil
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path

from . import config, db
from .castellano import sin_tildes

TIPOS_PROCESO = ("remision", "abreviado")

ETIQUETA_TIPO = {
    "remision": "Remisión a juicio",
    "abreviado": "Procedimiento abreviado",
}


class CasoInvalido(ValueError):
    pass


class CasoNoEncontrado(KeyError):
    pass


@dataclass
class Caso:
    slug: str
    numero_legajo: str
    caratula: str
    tipo_proceso: str
    observaciones: str | None
    creado_en: str
    actualizado_en: str | None = None
    documentos: int = 0
    paginas: int = 0
    evidencias: int = 0
    incluidas: int = 0
    pendientes: int = 0

    def como_dict(self) -> dict:
        d = asdict(self)
        d["tipo_etiqueta"] = ETIQUETA_TIPO.get(self.tipo_proceso, self.tipo_proceso)
        return d


def slugificar(numero_legajo: str, caratula: str) -> str:
    """
    Nombre de carpeta a partir del legajo y la carátula.

    Lleva el número adelante porque es como se busca un legajo, y un trozo de la
    carátula atrás porque un número suelto no le dice nada a quien mira la carpeta
    desde el explorador de archivos seis meses después.
    """
    def limpiar(t: str) -> str:
        t = sin_tildes(t or "").lower()
        return re.sub(r"[^a-z0-9]+", "-", t).strip("-")

    base = "-".join(p for p in (limpiar(numero_legajo), limpiar(caratula)[:40]) if p)
    return (base or "caso")[:80]


def _slug_valido(slug: str) -> bool:
    """
    Un slug es un nombre de carpeta y llega por la URL. Sin esto, `../` en el nombre
    del caso alcanza para leer una base de otro lado del disco.
    """
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", slug or ""))


def crear(numero_legajo: str, caratula: str, tipo_proceso: str,
          observaciones: str | None = None) -> Caso:
    numero_legajo = (numero_legajo or "").strip()
    caratula = (caratula or "").strip()
    if not numero_legajo:
        raise CasoInvalido("falta el número de legajo")
    if not caratula:
        raise CasoInvalido("falta la carátula")
    if tipo_proceso not in TIPOS_PROCESO:
        raise CasoInvalido(f"tipo de proceso desconocido: {tipo_proceso!r}")

    slug = slugificar(numero_legajo, caratula)
    carpeta = config.carpeta_caso(slug)
    # Dos legajos distintos pueden slugificar igual. Se desempata con un sufijo en vez
    # de rechazar el alta: el que está cargando un caso no tiene por qué saber que hay
    # otro parecido, y hacerlo elegir otro nombre no arregla nada.
    n = 2
    while carpeta.exists():
        slug = f"{slugificar(numero_legajo, caratula)[:76]}-{n}"
        carpeta = config.carpeta_caso(slug)
        n += 1

    carpeta.mkdir(parents=True)
    for sub in ("originales", "derivados", "export"):
        (carpeta / sub).mkdir(exist_ok=True)

    cx = db.abrir(carpeta / "punteo.sqlite")
    try:
        cx.execute("""INSERT INTO caso (id, numero_legajo, caratula, tipo_proceso,
                                        observaciones, creado_en)
                      VALUES (1,?,?,?,?,?)""",
                   (numero_legajo, caratula, tipo_proceso, observaciones or None, db.ahora()))
        cx.commit()
    finally:
        cx.close()
    return leer(slug)


def leer(slug: str) -> Caso:
    """Datos del caso, con sus contadores."""
    if not _slug_valido(slug):
        raise CasoNoEncontrado(slug)
    base = config.carpeta_caso(slug) / "punteo.sqlite"
    if not base.exists():
        raise CasoNoEncontrado(slug)
    cx = db.abrir(base)
    try:
        fila = cx.execute("SELECT * FROM caso WHERE id=1").fetchone()
        if not fila:
            raise CasoNoEncontrado(slug)
        cuenta = cx.execute("""
            SELECT (SELECT COUNT(*) FROM documento) AS documentos,
                   (SELECT COUNT(*) FROM pagina)    AS paginas,
                   (SELECT COUNT(*) FROM evidencia WHERE activa=1) AS evidencias,
                   (SELECT COUNT(*) FROM evidencia WHERE activa=1 AND estado='incluida')
                        AS incluidas,
                   (SELECT COUNT(*) FROM evidencia WHERE activa=1 AND estado='pendiente')
                        AS pendientes""").fetchone()
        return Caso(slug=slug, numero_legajo=fila["numero_legajo"],
                    caratula=fila["caratula"], tipo_proceso=fila["tipo_proceso"],
                    observaciones=fila["observaciones"], creado_en=fila["creado_en"],
                    actualizado_en=fila["actualizado_en"],
                    documentos=cuenta["documentos"], paginas=cuenta["paginas"],
                    evidencias=cuenta["evidencias"], incluidas=cuenta["incluidas"],
                    pendientes=cuenta["pendientes"])
    finally:
        cx.close()


def listar() -> list[Caso]:
    """Todos los casos, el más nuevo primero."""
    raiz = config.carpeta_casos()
    if not raiz.exists():
        return []
    casos = []
    for carpeta in sorted(raiz.iterdir()):
        if not carpeta.is_dir() or not (carpeta / "punteo.sqlite").exists():
            continue
        try:
            casos.append(leer(carpeta.name))
        except (CasoNoEncontrado, sqlite3.DatabaseError):
            # Una carpeta con una base ilegible no puede voltear el listado entero: se
            # saltea y el resto se muestra. Que falte de la lista ya es la señal.
            continue
    return sorted(casos, key=lambda c: c.creado_en, reverse=True)


def actualizar(slug: str, **campos) -> Caso:
    """Cambia la carátula, el tipo de proceso o las observaciones de un caso."""
    permitidos = {"numero_legajo", "caratula", "tipo_proceso", "observaciones"}
    cambios = {k: v for k, v in campos.items() if k in permitidos and v is not None}
    if not cambios:
        return leer(slug)
    if "tipo_proceso" in cambios and cambios["tipo_proceso"] not in TIPOS_PROCESO:
        raise CasoInvalido(f"tipo de proceso desconocido: {cambios['tipo_proceso']!r}")
    cx = db.abrir(config.carpeta_caso(slug) / "punteo.sqlite")
    try:
        sets = ", ".join(f"{k}=?" for k in cambios)
        cx.execute(f"UPDATE caso SET {sets}, actualizado_en=? WHERE id=1",
                   (*cambios.values(), db.ahora()))
        cx.commit()
    finally:
        cx.close()
    return leer(slug)


def borrar(slug: str) -> None:
    """
    Borra el caso entero, carpeta incluida.

    No hay papelera y no hay borrado parcial: o está o no está. Lo que sí hay es que
    esto no se llama nunca desde una acción de un solo clic — ver la interfaz, que pide
    escribir el número de legajo para confirmar.
    """
    if not _slug_valido(slug):
        raise CasoNoEncontrado(slug)
    carpeta = config.carpeta_caso(slug)
    if not carpeta.exists():
        raise CasoNoEncontrado(slug)
    # Los originales están en 0444 y `rmtree` no puede con ellos en todos los sistemas.
    for p in carpeta.rglob("*"):
        if p.is_file():
            try:
                p.chmod(0o644)
            except OSError:
                pass
    shutil.rmtree(carpeta)


def abrir(slug: str) -> sqlite3.Connection:
    """
    Conexión a la base del caso, y deja el caso activo en ESTE hilo.

    Las dos cosas juntas a propósito: casi todo el código de abajo resuelve sus rutas
    contra `config.CASO`, así que abrir la base sin activar el caso produce un estado
    donde la base es de una causa y las imágenes de otra.
    """
    if not _slug_valido(slug):
        raise CasoNoEncontrado(slug)
    base = config.carpeta_caso(slug) / "punteo.sqlite"
    if not base.exists():
        raise CasoNoEncontrado(slug)
    config.activar_caso(slug)
    return db.abrir(base)
