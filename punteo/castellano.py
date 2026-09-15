"""
Normalización de texto en castellano.

Existe por una razón concreta y medible: `COLLATE NOCASE` de SQLite es ASCII, así que
«BENÍTEZ» y «benitez» le resultan distintos por la Í, y ni siquiera `lower()` la baja.
Buscar un apellido sin acento —que es como lo escribe cualquiera, y como lo devuelve el
OCR la mitad de las veces— no puede dar cero cuando el apellido está.
"""
from __future__ import annotations

import re
import unicodedata

# Lo que el OCR confunde seguido en mayúsculas. No se corrige el texto original: esto
# se usa sólo para comparar nombres entre sí.
_CONFUSIONES = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B"})


def sin_tildes(texto: str) -> str:
    """Quita tildes y diéresis, conserva la ñ como n."""
    descompuesto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def normalizar(texto: str | None) -> str:
    """Minúsculas, sin tildes, sin puntuación, con espacios colapsados."""
    if not texto:
        return ""
    t = sin_tildes(texto).lower()
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def normalizar_nombre(nombre: str | None) -> str:
    """
    Clave de comparación de un nombre de persona.

    Además de lo de arriba, ordena las palabras alfabéticamente: «PÉREZ, Juan Carlos» y
    «Juan Carlos Pérez» son la misma persona escrita de dos maneras, y en un legajo
    aparecen las dos. Ordenar no decide que sean la misma —eso lo decide una persona—
    pero hace que la coincidencia se PROPONGA, que es lo que hace falta.
    """
    base = normalizar(nombre)
    if not base:
        return ""
    return " ".join(sorted(base.split()))


def clave_ocr(texto: str | None) -> str:
    """Normalización más agresiva, para detectar duplicados sobre texto de OCR."""
    t = sin_tildes(texto or "").upper().translate(_CONFUSIONES)
    return re.sub(r"[^A-Z0-9]+", "", t)


def titulo(texto: str) -> str:
    """Capitalización de títulos en castellano: no se capitalizan las preposiciones."""
    menores = {"de", "del", "la", "las", "el", "los", "y", "e", "en", "a", "por", "con"}
    palabras = normalizar(texto).split()
    return " ".join(p if i and p in menores else p.capitalize()
                    for i, p in enumerate(palabras))
