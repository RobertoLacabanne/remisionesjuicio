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
from dataclasses import dataclass
from pathlib import Path

from . import config


class ArchivoInvalido(ValueError):
    pass


@dataclass
class Guardado:
    sha256: str
    ruta: Path
    bytes: int
    ya_estaba: bool


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


def guardar(datos: bytes, nombre: str) -> Guardado:
    """Escribe el original en la carpeta del caso activo y lo deja de sólo lectura."""
    validar(datos, nombre)
    sha = sha256_de(datos)
    destino = Path(config.ORIGINALES) / sha[:2] / f"{sha}.pdf"
    if destino.exists():
        return Guardado(sha, destino, len(datos), True)

    destino.parent.mkdir(parents=True, exist_ok=True)
    # Se escribe a un parcial y se renombra. El renombrado es atómico en el mismo
    # sistema de archivos: un corte de luz a mitad de la escritura deja un `.parcial`
    # que no engaña a nadie, en vez de un PDF truncado con el nombre de un hash que
    # dice que su contenido es otro.
    parcial = destino.with_suffix(".parcial")
    parcial.write_bytes(datos)
    parcial.rename(destino)
    try:
        destino.chmod(0o444)
    except OSError:
        pass
    return Guardado(sha, destino, len(datos), False)


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
    return True, "sin cambios"
