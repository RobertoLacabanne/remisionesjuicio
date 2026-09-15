"""
Andamiaje de las pruebas.

Todo lo que se prueba se arma por código. **Nunca datos reales de investigaciones**:
los nombres, los legajos y los organismos que aparecen acá son cadenas inventadas para
que el sistema tenga algo con qué trabajar.

Las pruebas corren sobre un PDF con capa de texto nativa, no sobre uno rasterizado. No
es por comodidad: el OCR de treinta páginas son once segundos y multiplicado por una
suite entera la vuelve una suite que nadie corre. La ruta de OCR tiene su propia prueba,
marcada como lenta, en `test_ocr.py`.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "herramientas"))


class CasoDePrueba(unittest.TestCase):
    """
    Base con un caso armado y listo. Cada prueba tiene su propia carpeta de datos, así
    que no se pisan entre sí ni dejan basura.
    """

    #: Si es True, el legajo se genera sin foliatura impresa.
    SIN_FOLIAR = False
    #: Desde qué número arranca la foliatura impresa.
    FOJAS_DESDE = 400
    #: A partir de qué página global deja de imprimirse la foja.
    SIN_FOLIAR_DESDE: int | None = None

    @classmethod
    def setUpClass(cls):
        cls._carpeta = Path(tempfile.mkdtemp(prefix="punteo-prueba-"))
        os.environ["PUNTEO_DATOS"] = str(cls._carpeta / "datos")

        # La configuración lee PUNTEO_DATOS al importarse, así que el entorno tiene que
        # estar puesto ANTES del primer import. De ahí que estos vayan acá adentro.
        from punteo import config
        config.DATOS = cls._carpeta / "datos"

        import generar_legajo
        cls.legajo = generar_legajo.generar(
            cls._carpeta / "pdf",
            fojas_desde=None if cls.SIN_FOLIAR else cls.FOJAS_DESDE,
            sin_foliar_desde=cls.SIN_FOLIAR_DESDE)
        cls.verdad = cls.legajo["piezas"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._carpeta, ignore_errors=True)

    def setUp(self):
        from punteo import busqueda, casos, foliatura, ingesta, ocr
        from punteo.evidencia import deteccion
        self.caso = casos.crear(f"OGA-{self._testMethodName[:18]}/2026",
                                "NN s/ Peculado (sintético)", "remision")
        self.cx = casos.abrir(self.caso.slug)
        self.addCleanup(self.cx.close)

        ingesta.agregar(self.cx, self.legajo["con_texto"].read_bytes(), "legajo.pdf")
        ocr.leer_caso(self.cx)                  # texto nativo: no invoca Tesseract
        foliatura.detectar(self.cx)
        deteccion.detectar(self.cx)
        busqueda.reindexar(self.cx)

    # ── ayudas ──
    def evidencias(self, **kw):
        from punteo.evidencia import modelo
        return modelo.listar(self.cx, limite=500, **kw)["evidencias"]

    def contadores(self):
        from punteo.evidencia import modelo
        return modelo.contadores(self.cx)

    def reabrir(self):
        """
        Cierra la conexión y abre otra sobre el mismo caso.

        Es lo que prueba que el trabajo sobreviva a cerrar el navegador o reiniciar la
        máquina: si algo vivía sólo en memoria, acá se cae.
        """
        from punteo import casos
        self.cx.close()
        self.cx = casos.abrir(self.caso.slug)
        return self.cx
