"""
La ruta de OCR, con Tesseract de verdad.

Son lentas —treinta y nueve páginas son unos once segundos— y por eso no corren en la
suite normal:

    python3 -m pruebas.correr --lentas

Corren sobre el MISMO legajo sintético que las demás, pero rasterizado: sin capa de
texto, como sale de un escáner. Es la única forma de verificar que el sistema entero se
sostiene cuando lo único que hay es una imagen.
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

LENTAS = os.environ.get("PUNTEO_PRUEBAS_LENTAS") == "1"


@unittest.skipUnless(LENTAS, "pruebas lentas: usar --lentas")
class LegajoEscaneado(unittest.TestCase):
    """Todo el recorrido sobre un PDF sin capa de texto."""

    @classmethod
    def setUpClass(cls):
        from punteo import ocr
        hay, detalle = ocr.hay_ocr()
        if not hay:
            raise unittest.SkipTest(f"no hay Tesseract en esta máquina: {detalle}")
        if ocr.config.OCR_IDIOMA not in ocr.idiomas_ocr():
            raise unittest.SkipTest(f"falta el idioma {ocr.config.OCR_IDIOMA}")

        cls.carpeta = Path(tempfile.mkdtemp(prefix="punteo-ocr-"))
        from punteo import config
        cls._antes = config.DATOS
        config.DATOS = cls.carpeta / "datos"

        import generar_legajo
        cls.legajo = generar_legajo.generar(cls.carpeta / "pdf", fojas_desde=400)

        from punteo import busqueda, casos, foliatura, ingesta
        from punteo.evidencia import deteccion
        cls.caso = casos.crear("OGA-OCR/2026", "NN s/ Escaneado", "remision")
        cls.cx = casos.abrir(cls.caso.slug)
        ingesta.agregar(cls.cx, cls.legajo["escaneado"].read_bytes(), "escaneado.pdf")
        cls.lectura = ocr.leer_caso(cls.cx)
        foliatura.detectar(cls.cx)
        deteccion.detectar(cls.cx)
        busqueda.reindexar(cls.cx)

    @classmethod
    def tearDownClass(cls):
        from punteo import config
        cls.cx.close()
        config.DATOS = cls._antes
        shutil.rmtree(cls.carpeta, ignore_errors=True)

    def test_se_leyeron_todas_las_paginas(self):
        self.assertEqual(self.lectura["fallidas"], 0)
        self.assertEqual(self.lectura["hechas"], self.lectura["paginas"])
        sin_texto = self.cx.execute(
            "SELECT COUNT(*) FROM pagina WHERE texto IS NULL").fetchone()[0]
        self.assertEqual(sin_texto, 0)

    def test_la_ruta_registrada_es_ocr_y_no_nativa(self):
        rutas = {r["ruta_lectura"] for r in self.cx.execute(
            "SELECT DISTINCT ruta_lectura FROM pagina")}
        self.assertEqual(rutas, {"ocr"})

    def test_las_palabras_tienen_coordenadas_en_puntos(self):
        fila = self.cx.execute("""SELECT p.ancho_pt, p.alto_pt, w.x0, w.y0, w.x1, w.y1
                                    FROM palabra w JOIN pagina p ON p.id = w.pagina_id
                                   LIMIT 1""").fetchone()
        self.assertLessEqual(fila["x1"], fila["ancho_pt"] + 2)
        self.assertLessEqual(fila["y1"], fila["alto_pt"] + 2)
        self.assertGreaterEqual(fila["x0"], -1)

    def test_la_foliatura_sale_del_papel_escaneado(self):
        filas = self.cx.execute("""SELECT numero_global, foja_num FROM pagina
                                    ORDER BY numero_global""").fetchall()
        aciertos = sum(1 for f in filas if f["foja_num"] == f["numero_global"] + 399)
        self.assertGreaterEqual(aciertos / len(filas), 0.95,
                                f"sólo {aciertos} de {len(filas)} fojas correctas")

    def test_las_piezas_se_detectan_igual_que_con_texto_nativo(self):
        import generar_legajo
        esperado, g = [], 0
        for _tipo, _titulo, _cuerpo, n in generar_legajo.PIEZAS:
            esperado.append((g + 1, g + n))
            g += n
        from punteo.evidencia import modelo
        obtenido = [(e["pagina_inicio"], e["pagina_fin"])
                    for e in modelo.listar(self.cx, limite=500)["evidencias"]]
        self.assertEqual(obtenido, esperado)

    def test_la_confianza_se_guarda_y_es_creible(self):
        media = self.cx.execute("SELECT AVG(confianza) FROM pagina").fetchone()[0]
        self.assertGreater(media, 0.5)
        self.assertLessEqual(media, 1.0)

    def test_buscar_sin_tilde_encuentra_con_tilde(self):
        from punteo import busqueda
        r = busqueda.en_paginas(self.cx, "informatico")
        self.assertTrue(r, "«informatico» no encontró «INFORMÁTICO»")

    def test_la_imagen_del_visor_se_rasteriza_bajo_demanda(self):
        from punteo import config, ocr
        datos, mime = ocr.imagen_pagina(self.cx, 3)
        self.assertEqual(mime, "image/jpeg")
        self.assertGreater(len(datos), 5000)
        self.assertTrue(datos.startswith(b"\xff\xd8"))
        # Y NO se guardó una imagen por cada página del legajo al procesar.
        cacheadas = len(list(Path(config.DERIVADOS).glob("p*.jpg")))
        self.assertLessEqual(cacheadas, 2,
                             "se rasterizaron páginas que nadie pidió")


@unittest.skipUnless(LENTAS, "pruebas lentas: usar --lentas")
class PaginasDificiles(unittest.TestCase):
    """Página de costado, página en blanco y página ilegible."""

    def setUp(self):
        import pymupdf
        self.carpeta = Path(tempfile.mkdtemp(prefix="punteo-dificil-"))
        self.addCleanup(shutil.rmtree, self.carpeta, True)
        self.doc = pymupdf.open()

    def _pdf(self, nombre="dificil.pdf"):
        ruta = self.carpeta / nombre
        self.doc.save(ruta)
        return ruta

    def test_una_pagina_en_blanco_no_rompe_nada(self):
        from punteo import ocr
        self.doc.new_page(width=595, height=842)
        lec = ocr.leer_pagina(self._pdf(), 1, tiene_texto_nativo=False)
        self.assertEqual(lec.ruta, "ocr")
        self.assertEqual(len(lec.palabras), 0)
        self.assertEqual(lec.confianza, 0.0)

    def test_una_pagina_de_costado_se_endereza(self):
        """
        Alguien apoya la hoja de costado en el escáner y esa foja se pierde entera: el
        motor no reconoce una palabra y la pieza que estaba ahí desaparece sin rastro.
        """
        import pymupdf

        from punteo import ocr
        pag = self.doc.new_page(width=595, height=842)
        caja = pymupdf.Rect(60, 60, 535, 780)
        pag.insert_textbox(caja, ("DECLARACION TESTIMONIAL comparece el testigo ante "
                                  "esta unidad fiscal y manifiesta lo siguiente ") * 8,
                           fontname="helv", fontsize=12)
        derecha = self._pdf("derecha.pdf")

        girado = pymupdf.open()
        origen = pymupdf.open(derecha)
        nueva = girado.new_page(width=842, height=595)
        nueva.show_pdf_page(nueva.rect, origen, 0, rotate=90)
        ruta_girada = self.carpeta / "girada.pdf"
        girado.save(ruta_girada)

        lec = ocr.leer_pagina(ruta_girada, 1, tiene_texto_nativo=False)
        texto = " ".join(p.texto for p in lec.palabras).upper()
        self.assertIn("TESTIMONIAL", texto,
                      f"la página de costado no se enderezó (rot={lec.rotacion}, "
                      f"conf={lec.confianza:.2f})")

    def test_una_pagina_ilegible_se_marca_y_no_se_traga(self):
        """
        Lo que el sistema NO puede hacer es dar por leída una página de la que no sacó
        nada. Se cuenta, se ve y se puede filtrar.
        """
        import pymupdf

        from punteo import casos, config, ocr
        from punteo.evidencia import modelo
        config.DATOS = self.carpeta / "datos"
        pag = self.doc.new_page(width=595, height=842)
        # Ruido gráfico: tinta en la hoja, nada legible.
        for i in range(0, 800, 7):
            pag.draw_line(pymupdf.Point(20, i), pymupdf.Point(575, i + 3),
                          color=(0.35, 0.35, 0.35), width=1.4)
        ruta = self._pdf("ilegible.pdf")

        caso = casos.crear("OGA-ILEG/2026", "NN s/ Ilegible", "remision")
        cx = casos.abrir(caso.slug)
        try:
            from punteo import ingesta
            ingesta.agregar(cx, ruta.read_bytes(), "ilegible.pdf")
            ocr.leer_caso(cx)
            fila = cx.execute("SELECT texto, confianza FROM pagina").fetchone()
            self.assertIsNotNone(fila["texto"], "la página quedó sin marca de leída")
            pobre = cx.execute("""SELECT COUNT(*) FROM pagina
                                   WHERE confianza < ?""",
                               (config.CONFIANZA_PAGINA_POBRE,)).fetchone()[0]
            self.assertEqual(pobre, 1, f"no se marcó como mal leída (conf={fila['confianza']})")

            from punteo.evidencia import deteccion
            deteccion.detectar(cx)
            evs = modelo.listar(cx)["evidencias"]
            if evs:
                self.assertIn("ocr_pobre", evs[0]["advertencias"])
        finally:
            cx.close()


if __name__ == "__main__":
    unittest.main()
