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


def pdf_de(paginas: list[list[str]]) -> bytes:
    """
    Un PDF chico con capa de texto: cada página es la lista de sus renglones.

    Sirve para los casos que necesitan un legajo distinto del sintético grande —un
    segundo PDF que se agrega después, dos documentos seguidos del mismo tipo— sin pagar
    el costo de generar el legajo entero otra vez.
    """
    import pymupdf
    doc = pymupdf.open()
    doc.set_metadata({"keywords": "PUNTEO-LEGAJO-SINTETICO-DE-PRUEBA"})
    for lineas in paginas:
        pag = doc.new_page(width=595, height=842)
        y = 56
        for linea in lineas:
            pag.insert_text((56, y), linea, fontname="helv", fontsize=12)
            y += 24
        # El cuerpo hace que la página supere el mínimo de texto nativo: sin él, la
        # ingesta la tomaría por escaneada y la mandaría a Tesseract.
        pag.insert_textbox(pymupdf.Rect(56, y + 10, 539, 780),
                           "Cuerpo del documento a los fines de la prueba. " * 12,
                           fontname="tiro", fontsize=10.5)
    datos = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return datos


class CasoVacio(unittest.TestCase):
    """
    Un caso sin nada adentro, para las pruebas que necesitan un legajo armado a medida.

    El legajo sintético grande sirve para el recorrido completo, pero un caso límite
    —dos actas seguidas con su contador de hojas— se lee mucho mejor con cuatro páginas
    escritas ahí mismo que buscándolo adentro de treinta y nueve.
    """

    def setUp(self):
        from punteo import casos, config
        self._carpeta = Path(tempfile.mkdtemp(prefix="punteo-vacio-"))
        self._datos = config.DATOS
        config.DATOS = self._carpeta / "datos"
        self.addCleanup(lambda: setattr(config, "DATOS", self._datos))
        self.addCleanup(shutil.rmtree, self._carpeta, True)

        self.caso = casos.crear(f"OGA-{self._testMethodName[:18]}/2026",
                                "NN s/ Prueba armada a mano", "remision")
        self.cx = casos.abrir(self.caso.slug)
        self.addCleanup(self.cx.close)

    def cargar(self, paginas: list[list[str]], nombre: str = "legajo.pdf"):
        """Ingiere un PDF escrito acá mismo y lo lee. Sin Tesseract: capa nativa."""
        from punteo import ingesta, ocr
        ingesta.agregar(self.cx, pdf_de(paginas), nombre)
        ocr.leer_caso(self.cx)

    def evidencias(self, **kw):
        from punteo.evidencia import modelo
        return modelo.listar(self.cx, limite=500, **kw)["evidencias"]


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
