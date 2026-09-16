"""
Almacén de originales.

Cuando un PDF entra al sistema, ese archivo pasa a ser EL original a los efectos del
legajo. Se escribe una sola vez y no se toca nunca más:

  * se guarda bajo su propio SHA-256 y no bajo el nombre que traía, porque dos personas
    pueden subir «legajo.pdf» el mismo día;
  * el nombre original se conserva en la base, no en el sistema de archivos;
  * se le sacan los permisos de escritura. No es infalible —root puede todo— pero
    convierte un accidente en un error explícito;
  * si el contenido ya estaba, no se vuelve a escribir: se registra como copia exacta.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from . import config


class ArchivoInvalido(ValueError):
    pass


class OriginalAlterado(RuntimeError):
    """
    Ya hay un archivo guardado con el hash de este documento y su contenido es otro.

    No se reemplaza: el original no se reescribe nunca, ni siquiera para «arreglarlo».
    Lo que corresponde es que una persona mire qué pasó con ese archivo.
    """


class OriginalSinProteger(RuntimeError):
    """
    El original quedó escrito pero el sistema de archivos no lo dejó de sólo lectura.

    La invariante es que el original se guarda en 0444, así que esto corta la carga. Hay
    carpetas que ignoran el permiso —algunas montadas en un contenedor, algunos discos de
    red—, y para esas existe `PUNTEO_ORIGINALES_SIN_PROTECCION=aceptar`: una decisión
    explícita de quien instala, como `PUNTEO_ACCESO=abierto`, nunca un efecto
    secundario. Con esa variable la carga sigue, pero queda anotada y se avisa.
    """


def acepta_sin_proteccion() -> bool:
    return os.environ.get("PUNTEO_ORIGINALES_SIN_PROTECCION", "").strip().lower() == "aceptar"


@dataclass
class Guardado:
    sha256: str
    ruta: Path
    bytes: int
    ya_estaba: bool
    # Si el archivo quedó de sólo lectura. Sólo puede ser False cuando quien instaló
    # aceptó explícitamente trabajar así (ver `OriginalSinProteger`).
    protegido: bool = True


def sha256_de(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def sha256_de_archivo(ruta: Path, bloque: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:                # solo lectura, siempre
        for trozo in iter(lambda: f.read(bloque), b""):
            h.update(trozo)
    return h.hexdigest()


def validar(datos: bytes, nombre: str) -> None:
    if not datos:
        raise ArchivoInvalido("el archivo llegó vacío")
    if len(datos) > config.MAX_BYTES_PDF:
        raise ArchivoInvalido(f"pesa más de {config.MAX_BYTES_PDF // (1024*1024)} MB")
    # Se mira el contenido y no la extensión: un `.pdf` que no empieza con %PDF es un
    # archivo mal nombrado, y decírselo ahora es mucho mejor que fallar al rasterizar.
    if not datos.lstrip()[:5].startswith(b"%PDF"):
        raise ArchivoInvalido(f"«{nombre}» no es un PDF: no empieza con %PDF")


def _proteger(ruta: Path) -> bool:
    """
    Deja el archivo de sólo lectura y comprueba que haya quedado así.

    La primera versión hacía el `chmod` y, si fallaba, seguía como si nada: el sistema
    registraba como protegido un original que cualquiera podía sobrescribir. Ahora se
    mira el resultado, y si no quedó protegido se corta, salvo aceptación explícita.
    """
    try:
        ruta.chmod(0o444)
        protegido = not (ruta.stat().st_mode & 0o222)
    except OSError:
        protegido = False
    if not protegido and not acepta_sin_proteccion():
        raise OriginalSinProteger(
            f"el sistema de archivos no dejó {ruta.name} en sólo lectura. Si esta carpeta "
            f"no puede respetar ese permiso y se acepta trabajar así, hay que declararlo "
            f"con PUNTEO_ORIGINALES_SIN_PROTECCION=aceptar")
    return protegido


def guardar(datos: bytes, nombre: str) -> Guardado:
    """Escribe el original en la carpeta del caso activo y lo deja de sólo lectura."""
    validar(datos, nombre)
    sha = sha256_de(datos)
    destino = Path(config.ORIGINALES) / sha[:2] / f"{sha}.pdf"
    if destino.exists():
        # Que exista un archivo con ese nombre no prueba que sea este documento. Antes se
        # daba por bueno sin mirarlo, y un archivo alterado —a mano, por el disco, por
        # una copia a medias— quedaba registrado con un hash que no es el suyo.
        actual = sha256_de_archivo(destino)
        if actual != sha:
            raise OriginalAlterado(
                f"ya hay un original guardado con el hash de «{nombre}» y su contenido "
                f"no coincide (hoy hashea {actual[:12]}…). No se reemplaza: hay que "
                f"revisar qué le pasó a {destino.name}")
        return Guardado(sha, destino, len(datos), True, _proteger(destino))

    destino.parent.mkdir(parents=True, exist_ok=True)
    # Se escribe a un parcial y se renombra. El renombrado es atómico en el mismo
    # sistema de archivos: un corte de luz a mitad de la escritura deja un `.parcial`
    # que no engaña a nadie, en vez de un PDF truncado con el nombre de un hash que
    # dice que su contenido es otro.
    parcial = destino.with_suffix(".parcial")
    parcial.write_bytes(datos)
    parcial.rename(destino)
    return Guardado(sha, destino, len(datos), False, _proteger(destino))


def ruta_de(sha: str) -> Path:
    return Path(config.ORIGINALES) / sha[:2] / f"{sha}.pdf"


def verificar(sha: str) -> tuple[bool, str]:
    """
    ¿El original sigue siendo el que era? Rehashea y compara.

    Es lo que contesta «¿alguien tocó el archivo desde que lo cargamos?», que en un
    legajo penal hace falta poder contestar.
    """
    ruta = ruta_de(sha)
    if not ruta.exists():
        return False, "el archivo no está donde debería"
    actual = sha256_de_archivo(ruta)
    if actual != sha:
        return False, f"el contenido cambió: ahora hashea {actual[:12]}…"
    if ruta.stat().st_mode & 0o222:
        return True, "sin cambios, pero el archivo NO está protegido contra escritura"
    return True, "sin cambios"
