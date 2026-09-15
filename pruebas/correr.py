"""
Corredor de las pruebas.

    python3 -m pruebas.correr                 toda la suite
    python3 -m pruebas.correr test_invariante  un archivo
    python3 -m pruebas.correr --lentas         incluye las que hacen OCR de verdad

`unittest` de la biblioteca estándar y nada más: la máquina de producción no tiene
internet y una dependencia de test es una dependencia igual.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
sys.path.insert(0, str(AQUI))


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if "--lentas" in argv:
        argv.remove("--lentas")
        os.environ["PUNTEO_PRUEBAS_LENTAS"] = "1"

    cargador = unittest.TestLoader()
    if argv:
        suite = unittest.TestSuite(cargador.loadTestsFromName(n) for n in argv)
    else:
        suite = cargador.discover(str(AQUI), pattern="test_*.py", top_level_dir=str(AQUI))

    resultado = unittest.TextTestRunner(verbosity=2).run(suite)
    if not os.environ.get("PUNTEO_PRUEBAS_LENTAS"):
        print("\n(las pruebas lentas —OCR de verdad— no corrieron: usá --lentas)")
    return 0 if resultado.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
