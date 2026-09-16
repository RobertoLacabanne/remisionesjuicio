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
        cacheadas = len(list(Path(config.DERIVADOS).glob("*.jpg")))
        self.assertLessEqual(cacheadas, 2,
                             "se rasterizaron páginas que nadie pidió")


class PaginasMixtas(unittest.TestCase):
    """
    Un escaneo con el sello de firma digital encima: texto nativo de sobra, y el cuerpo
    es una imagen. La primera versión leía el sello, daba la página por leída con
    confianza 1,0, y el cuerpo nunca pasaba por el OCR.

    Tesseract se reemplaza por una lectura fija: lo que se prueba es la decisión de qué
    leer y cómo juntarlo, no el motor. Por eso corren en la suite normal.
    """

    PIE = "Documento firmado digitalmente por FUNCIONARIO DE PRUEBA el dia de la fecha"

    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp(prefix="punteo-mixta-"))
        self.addCleanup(shutil.rmtree, self.carpeta, True)

    def _pdf(self, *, con_imagen: bool, con_pie: bool = True, imagen=None,
             rotacion: int = 0, nombre: str = "pagina.pdf", tinta: bool = True) -> Path:
        import io

        import pymupdf
        from PIL import Image, ImageDraw
        doc = pymupdf.open()
        pag = doc.new_page(width=595, height=842)
        if con_imagen:
            im = Image.new("RGB", (298, 421), "white" if tinta else (246, 244, 238))
            dibujo = ImageDraw.Draw(im)
            for y in range(40, 380, 14) if tinta else ():   # renglones: tinta en la hoja
                dibujo.line((20, y, 270, y), fill="black", width=2)
            buf = io.BytesIO()
            im.save(buf, "PNG")
            pag.insert_image(pymupdf.Rect(imagen) if imagen else pag.rect,
                             stream=buf.getvalue())
        if con_pie:
            pag.insert_text((40, 820), self.PIE, fontname="helv", fontsize=8)
        if rotacion:
            pag.set_rotation(rotacion)
        ruta = self.carpeta / nombre
        doc.save(ruta)
        doc.close()
        return ruta

    def _ocr_falso(self, palabras):
        from punteo import ocr

        def leer(im, dpi):
            return ocr.Lectura("ocr", palabras, 0.81, 595, 842, 0, 1)
        return leer

    def test_el_cuerpo_escaneado_se_lee_aunque_haya_sello_digital(self):
        from unittest import mock

        from punteo import ocr
        cuerpo = [ocr.Palabra("DECLARACION", 60, 80, 200, 96, 0.8),
                  ocr.Palabra("TESTIMONIAL", 210, 80, 350, 96, 0.82)]
        # La imagen sin renglones dibujados: acá el cuerpo es lo que el OCR «leyó», y no
        # queda tinta sin explicar. El caso contrario está en la prueba de abajo.
        with mock.patch.object(ocr, "leer_ocr", self._ocr_falso(cuerpo)):
            lec = ocr.leer_pagina(self._pdf(con_imagen=True, tinta=False), 1,
                                  tiene_texto_nativo=True)
        texto = " ".join(p.texto for p in lec.palabras)
        self.assertEqual(lec.ruta, "mixta")
        self.assertIn("TESTIMONIAL", texto, "el cuerpo escaneado no se leyó")
        self.assertIn("firmado", texto, "se perdió el texto nativo")
        self.assertLess(lec.confianza, 1.0, "una lectura parcial salió con confianza 1,0")
        self.assertAlmostEqual(lec.confianza, 0.81, places=2)

    def test_lo_que_el_ocr_lee_encima_del_sello_no_se_duplica(self):
        from unittest import mock

        from punteo import ocr
        nativa = ocr.leer_nativo(self._pdf(con_imagen=True), 1)
        sello = nativa.palabras[0]
        repetida = ocr.Palabra(sello.texto, sello.x0, sello.y0, sello.x1, sello.y1, 0.9)
        cuerpo = ocr.Palabra("INFORME", 60, 80, 160, 96, 0.7)
        with mock.patch.object(ocr, "leer_ocr", self._ocr_falso([repetida, cuerpo])):
            lec = ocr.leer_pagina(self._pdf(con_imagen=True), 1, tiene_texto_nativo=True)
        self.assertEqual([p.texto for p in lec.palabras].count(sello.texto), 1)

    def test_una_imagen_que_no_agrega_nada_deja_la_lectura_nativa(self):
        """
        Una hoja con fondo y todo el texto digital: el OCR lee lo mismo que ya traía la
        capa nativa —porque la imagen se rasteriza con el texto encima— y nada más.
        Vale lo nativo, sin marcarla como mal leída.
        """
        from unittest import mock

        from punteo import ocr
        ruta = self._pdf(con_imagen=True, tinta=False)
        mismas = [ocr.Palabra(p.texto, p.x0, p.y0, p.x1, p.y1, 0.93)
                  for p in ocr.leer_nativo(ruta, 1).palabras]
        with mock.patch.object(ocr, "leer_ocr", self._ocr_falso(mismas)):
            lec = ocr.leer_pagina(ruta, 1, tiene_texto_nativo=True)
        self.assertEqual(lec.ruta, "nativo")
        self.assertEqual(lec.confianza, 1.0)

    def test_si_el_ocr_solo_lee_el_sello_el_cuerpo_no_pasa_por_leido(self):
        """
        Un cuerpo escaneado ilegible con el sello digital encima: el OCR lee el sello y
        nada más. Eso no prueba que la imagen sea fondo, y darla por leída con 1,0
        dejaba el cuerpo afuera de la búsqueda y la detección sin ningún aviso.
        """
        from unittest import mock

        from punteo import config, ocr
        ruta = self._pdf(con_imagen=True)
        sello = [ocr.Palabra(p.texto, p.x0, p.y0, p.x1, p.y1, 0.93)
                 for p in ocr.leer_nativo(ruta, 1).palabras]
        with mock.patch.object(ocr, "leer_ocr", self._ocr_falso(sello)):
            lec = ocr.leer_pagina(ruta, 1, tiene_texto_nativo=True)
        self.assertEqual(lec.ruta, "mixta")
        self.assertLess(lec.confianza, config.CONFIANZA_PAGINA_POBRE)

    def test_una_palabra_suelta_no_tapa_un_cuerpo_ilegible(self):
        """
        Si el OCR lee el sello y además un número de foja, la página no puede salir con
        la confianza de ese número: el cuerpo sigue sin leer. Lo leído se conserva, y la
        página va a las mal leídas.
        """
        from unittest import mock

        from punteo import config, ocr
        ruta = self._pdf(con_imagen=True)
        leido = [ocr.Palabra(p.texto, p.x0, p.y0, p.x1, p.y1, 0.93)
                 for p in ocr.leer_nativo(ruta, 1).palabras]
        leido.append(ocr.Palabra("412", 540, 20, 570, 34, 0.98))
        with mock.patch.object(ocr, "leer_ocr", self._ocr_falso(leido)):
            lec = ocr.leer_pagina(ruta, 1, tiene_texto_nativo=True)
        self.assertIn("412", [p.texto for p in lec.palabras])
        self.assertLess(lec.confianza, config.CONFIANZA_PAGINA_POBRE)

    def test_si_el_ocr_no_lee_nada_la_pagina_no_pasa_por_perfecta(self):
        """
        Que el OCR no devuelva ni una palabra —ni siquiera el sello, que también está
        dibujado en la imagen— no prueba que la imagen sea fondo: prueba que la lectura
        falló. Esa página tiene que aparecer entre las mal leídas.
        """
        from unittest import mock

        from punteo import config, ocr
        with mock.patch.object(ocr, "leer_ocr", self._ocr_falso([])):
            lec = ocr.leer_pagina(self._pdf(con_imagen=True), 1, tiene_texto_nativo=True)
        self.assertEqual(lec.ruta, "mixta")
        self.assertLess(lec.confianza, config.CONFIANZA_PAGINA_POBRE)
        self.assertTrue(lec.palabras, "se perdió el texto nativo")

    def test_un_documento_escaneado_chico_tambien_se_lee(self):
        """
        Un acta escaneada pegada al cuarenta por ciento de una hoja digital no llega a
        «media página», y con ese único criterio su texto no se leía nunca.
        """
        from unittest import mock

        from punteo import ocr
        cuerpo = [ocr.Palabra("OFICIO", 80, 120, 150, 136, 0.9)]
        ruta = self._pdf(con_imagen=True, imagen=(40, 60, 420, 480))
        self.assertLess(ocr.leer_nativo(ruta, 1).cobertura_imagen, 0.5)
        with mock.patch.object(ocr, "leer_ocr", self._ocr_falso(cuerpo)):
            lec = ocr.leer_pagina(ruta, 1, tiene_texto_nativo=True)
        self.assertIn("OFICIO", [p.texto for p in lec.palabras])

    def test_un_escudo_en_el_membrete_no_manda_la_hoja_al_ocr(self):
        from unittest import mock

        from punteo import ocr

        def no_llamar(*a, **kw):
            raise AssertionError("un escudo mandó la hoja entera al OCR")
        ruta = self._pdf(con_imagen=True, imagen=(40, 30, 110, 100))
        with mock.patch.object(ocr, "leer_ocr", no_llamar):
            lec = ocr.leer_pagina(ruta, 1, tiene_texto_nativo=True)
        self.assertEqual(lec.ruta, "nativo")

    def test_en_una_pagina_girada_las_palabras_quedan_donde_se_ven(self):
        """
        PyMuPDF da las palabras en el marco sin girar y la hoja y su imagen en el girado.
        Sin pasarlas al mismo marco, el resaltado caía en otro lado de la foja, la
        foliatura buscaba el número en el margen equivocado y el sello no se reconocía
        como el mismo texto que el OCR leyó en la imagen.
        """
        from punteo import ocr
        derecha = ocr.leer_nativo(self._pdf(con_imagen=False, nombre="derecha.pdf"), 1)
        girada = ocr.leer_nativo(self._pdf(con_imagen=False, rotacion=90,
                                           nombre="girada.pdf"), 1)
        self.assertEqual((girada.ancho_pt, girada.alto_pt), (842, 595))
        for p in girada.palabras:
            self.assertLessEqual(p.x1, girada.ancho_pt + 1)
            self.assertLessEqual(p.y1, girada.alto_pt + 1)
        # Y es la misma palabra, girada: el pie de la hoja derecha queda sobre el borde
        # izquierdo de la hoja acostada.
        d, g = derecha.palabras[0], girada.palabras[0]
        self.assertEqual(d.texto, g.texto)
        self.assertGreater(d.y0, 800)
        self.assertLess(g.x0, 100, f"la palabra girada quedó en x={g.x0}")

    def test_un_pdf_digital_sin_imagenes_no_pasa_por_el_ocr(self):
        from unittest import mock

        from punteo import ocr

        def no_llamar(*a, **kw):
            raise AssertionError("se mandó al OCR una página digital")
        with mock.patch.object(ocr, "leer_ocr", no_llamar):
            lec = ocr.leer_pagina(self._pdf(con_imagen=False), 1, tiene_texto_nativo=True)
        self.assertEqual(lec.ruta, "nativo")
        self.assertLess(lec.cobertura_imagen, 0.01)

    def test_la_ingesta_marca_la_pagina_como_nativa_y_la_lectura_la_corrige(self):
        """El sello supera el mínimo de texto nativo: por eso hacía falta mirar la imagen."""
        from punteo import ingesta
        _, paginas = ingesta._metadatos(self._pdf(con_imagen=True))
        self.assertTrue(paginas[0][2])


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
