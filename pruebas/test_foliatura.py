"""
La foja no es la página del PDF.

En el escrito se cita «fs. 342/346». Si ese número sale de la página del PDF, la cita es
falsa y el error llega a un tribunal. Esta prueba existe para que la distinción no se
pueda romper sin que algo se ponga rojo.
"""
from __future__ import annotations

import unittest

from comun import CasoDePrueba, CasoVacio


class FojaYPaginaSonDistintas(CasoDePrueba):
    FOJAS_DESDE = 400

    def test_la_foja_detectada_no_coincide_con_la_pagina(self):
        filas = self.cx.execute("""SELECT numero_global, foja_num FROM pagina
                                    ORDER BY numero_global""").fetchall()
        self.assertTrue(filas)
        for f in filas:
            self.assertEqual(f["foja_num"], f["numero_global"] + 399)
            self.assertNotEqual(f["foja_num"], f["numero_global"])

    def test_el_tramo_tiene_su_desplazamiento(self):
        tramos = self.cx.execute("SELECT * FROM tramo_foliatura").fetchall()
        self.assertEqual(len(tramos), 1)
        self.assertEqual(tramos[0]["desplazamiento"], 399)
        self.assertEqual(tramos[0]["zona"], "sup_der")
        self.assertEqual(tramos[0]["paginas_interpoladas"], 0)

    def test_la_detectada_es_una_conjetura_hasta_que_alguien_la_confirma(self):
        from punteo import foliatura
        r = foliatura.resumen(self.cx)
        self.assertEqual(r["confirmadas"], 0)
        self.assertGreater(r["detectadas"], 0)

        n = foliatura.confirmar_tramo(self.cx, 1, 10)
        self.assertEqual(n, 10)
        r = foliatura.resumen(self.cx)
        self.assertEqual(r["confirmadas"], 10)

    def test_el_generador_marca_la_foja_sin_confirmar(self):
        from punteo import exportacion, generacion
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        modelo.decidir(self.cx, ev["id"], "incluida")
        generacion.generar(self.cx, exigir_foja_confirmada=True)
        self.assertIn(generacion.FOJA_A_CONFIRMAR, exportacion.a_texto(self.cx))

    def test_confirmada_sale_limpia(self):
        from punteo import exportacion, foliatura, generacion
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        foliatura.confirmar_tramo(self.cx, 1, 100)
        modelo.decidir(self.cx, ev["id"], "incluida")
        generacion.generar(self.cx, exigir_foja_confirmada=True)
        salida = exportacion.a_texto(self.cx)
        self.assertNotIn(generacion.FOJA_A_CONFIRMAR, salida)
        self.assertIn("fs. 400", salida)

    def test_corregir_la_foja_de_una_pagina_corre_la_de_la_evidencia(self):
        """
        La foja no está congelada adentro de la evidencia: se deriva de la página. Si
        alguien corrige la foliatura, la cita de todas las piezas que pasan por ahí se
        corrige sola. Con la foja congelada habría que acordarse de recalcularla, y
        nadie se acuerda.
        """
        from punteo import foliatura
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        self.assertEqual(ev["foja_inicio"], "400")
        foliatura.fijar(self.cx, ev["pagina_inicio"], "912 bis")
        self.assertEqual(modelo.obtener(self.cx, ev["id"])["foja_inicio"], "912 bis")

    def test_la_foja_a_mano_le_gana_a_la_de_la_pagina(self):
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        modelo.editar(self.cx, ev["id"], {"foja_inicio": "77"})
        actualizada = modelo.obtener(self.cx, ev["id"])
        self.assertEqual(actualizada["foja_inicio"], "77")
        self.assertEqual(actualizada["foja_origen"], "manual")


class LosDosExtremosDelRango(CasoDePrueba):
    """
    Confirmar dónde empieza una pieza no dice nada sobre dónde termina.

    «fs. 409/413» tiene dos números y los dos van al escrito. Con un solo campo de
    origen —el del inicio— confirmar la primera foja hacía pasar por verificado todo el
    rango, y el 413 salía sin marca aunque lo hubiera puesto la máquina.
    """
    FOJAS_DESDE = 400

    def _multipagina(self):
        return next(e for e in self.evidencias() if e["pagina_fin"] > e["pagina_inicio"])

    def test_confirmar_el_inicio_no_alcanza(self):
        from punteo import exportacion, foliatura, generacion
        from punteo.evidencia import modelo
        ev = self._multipagina()
        foliatura.confirmar_tramo(self.cx, ev["pagina_inicio"], ev["pagina_inicio"])
        actual = modelo.obtener(self.cx, ev["id"])
        self.assertEqual(actual["foja_origen"], "confirmada")
        self.assertEqual(actual["foja_fin_origen"], "detectada")
        self.assertFalse(actual["foja_firme"])

        modelo.decidir(self.cx, ev["id"], "incluida")
        generacion.generar(self.cx, exigir_foja_confirmada=True)
        self.assertIn(generacion.FOJA_A_CONFIRMAR, exportacion.a_texto(self.cx))

    def test_con_los_dos_extremos_confirmados_sale_limpia(self):
        from punteo import exportacion, foliatura, generacion
        from punteo.evidencia import modelo
        ev = self._multipagina()
        foliatura.confirmar_tramo(self.cx, ev["pagina_inicio"], ev["pagina_fin"])
        self.assertTrue(modelo.obtener(self.cx, ev["id"])["foja_firme"])
        modelo.decidir(self.cx, ev["id"], "incluida")
        generacion.generar(self.cx, exigir_foja_confirmada=True)
        self.assertNotIn(generacion.FOJA_A_CONFIRMAR, exportacion.a_texto(self.cx))

    def test_sin_la_foja_del_final_la_cita_no_se_encoge(self):
        """
        Una pieza de cinco hojas sin la foja del final salía «fs. 409»: no como un dato
        que falta, sino como una pieza de una sola foja. El hueco tiene que verse.
        """
        from punteo import exportacion, foliatura, generacion
        from punteo.evidencia import modelo
        ev = self._multipagina()
        for pagina in range(ev["pagina_inicio"] + 1, ev["pagina_fin"] + 1):
            foliatura.fijar(self.cx, pagina, None)          # se borran las fojas del resto
        actual = modelo.obtener(self.cx, ev["id"])
        self.assertIsNone(actual["foja_fin"])
        self.assertIn("sin_foja_final", actual["advertencias"])

        modelo.decidir(self.cx, ev["id"], "incluida")
        self.assertTrue(generacion.verificar(self.cx)["sin_foja_final"])
        self.assertFalse(generacion.verificar(self.cx)["listo"])
        generacion.generar(self.cx)
        salida = exportacion.a_texto(self.cx)
        self.assertIn(f"/{generacion.FALTA_FOJA}", salida)

    def test_una_foja_interpolada_se_distingue_de_una_leida(self):
        """
        Interpolar adentro de un tramo probado es correcto, pero no es lo mismo que
        haberla leído: es justo donde una hoja intercalada corre la numeración. La
        página lo guarda, el checklist lo advierte y el chequeo previo lo cuenta.
        """
        from punteo import foliatura, generacion
        from punteo.evidencia import modelo
        ev = self._multipagina()
        self.cx.execute("UPDATE pagina SET foja_lectura='interpolada' WHERE numero_global=?",
                        (ev["pagina_fin"],))
        self.cx.commit()
        actual = modelo.obtener(self.cx, ev["id"])
        self.assertTrue(actual["foja_interpolada"])
        self.assertIn("foja_interpolada", actual["advertencias"])

        foliatura.confirmar_tramo(self.cx, ev["pagina_inicio"], ev["pagina_fin"])
        modelo.decidir(self.cx, ev["id"], "incluida")
        v = generacion.verificar(self.cx)
        self.assertTrue(v["foja_interpolada"], "una foja deducida pasó por leída")
        self.assertEqual(v["foja_sin_confirmar"], [])

    def test_una_foliatura_que_salta_adentro_del_rango_se_avisa(self):
        """
        Los dos extremos confirmados no dicen nada del medio: entre la foja 400 y la 402
        puede haber una 900 de otro tramo, y «fs. 400/402» la tapa.
        """
        from punteo import exportacion, foliatura, generacion
        from punteo.evidencia import modelo
        ev = next(e for e in self.evidencias() if e["pagina_fin"] - e["pagina_inicio"] >= 2)
        medio = ev["pagina_inicio"] + 1
        foliatura.fijar(self.cx, medio, "900")
        foliatura.confirmar_tramo(self.cx, ev["pagina_inicio"], ev["pagina_fin"])
        modelo.decidir(self.cx, ev["id"], "incluida")

        self.assertTrue(generacion.verificar(self.cx)["fojas_discontinuas"])
        generacion.generar(self.cx)
        self.assertIn(generacion.FOJAS_DISCONTINUAS, exportacion.a_texto(self.cx))

    def test_una_serie_con_vuelta_no_es_discontinua(self):
        """«411» y «411 vta.» son la misma hoja: el número se repite y eso está bien."""
        from punteo import foliatura, generacion
        from punteo.evidencia import modelo
        ev = next(e for e in self.evidencias() if e["pagina_fin"] - e["pagina_inicio"] >= 2)
        for pagina in range(ev["pagina_inicio"], ev["pagina_fin"] + 1):
            foliatura.fijar(self.cx, pagina, "500" if pagina == ev["pagina_inicio"]
                            else "500 vta." if pagina == ev["pagina_inicio"] + 1 else "501")
        modelo.decidir(self.cx, ev["id"], "incluida")
        self.assertFalse(generacion.rango_discontinuo(
            self.cx, modelo.obtener(self.cx, ev["id"])))

    def test_una_foja_cargada_a_mano_no_queda_como_deducida(self):
        """
        Si una persona escribió los dos extremos, la advertencia de «se dedujo de la
        serie» no corresponde: el número es suyo.
        """
        from punteo.evidencia import modelo
        ev = next(e for e in self.evidencias() if e["pagina_fin"] > e["pagina_inicio"])
        for pagina in (ev["pagina_inicio"], ev["pagina_fin"]):
            self.cx.execute("UPDATE pagina SET foja_lectura='interpolada' WHERE numero_global=?",
                            (pagina,))
        self.cx.commit()
        self.assertTrue(modelo.obtener(self.cx, ev["id"])["foja_interpolada"])
        modelo.editar(self.cx, ev["id"], {"foja_inicio": "701", "foja_fin": "704"})
        actual = modelo.obtener(self.cx, ev["id"])
        self.assertFalse(actual["foja_interpolada"])
        self.assertTrue(actual["foja_firme"])

    def test_la_foliatura_dice_cuantas_dedujo(self):
        from punteo import foliatura
        r = foliatura.resumen(self.cx)
        self.assertIn("interpoladas", r)
        leidas = self.cx.execute(
            "SELECT COUNT(*) FROM pagina WHERE foja_lectura='leida'").fetchone()[0]
        self.assertEqual(leidas, r["detectadas"] - r["interpoladas"])


class LegajoSinFoliar(CasoDePrueba):
    """Un legajo sin foliar es un caso normal, no un error."""
    SIN_FOLIAR = True

    def test_no_inventa_fojas(self):
        r = self.cx.execute("""SELECT COUNT(*) FROM pagina
                                WHERE foja_etiqueta IS NOT NULL""").fetchone()[0]
        self.assertEqual(r, 0)
        self.assertEqual(self.cx.execute("SELECT COUNT(*) FROM tramo_foliatura").fetchone()[0], 0)

    def test_el_sistema_funciona_igual(self):
        self.assertGreater(len(self.evidencias()), 10)
        self.assertGreater(self.cx.execute("SELECT COUNT(*) FROM pagina").fetchone()[0], 30)

    def test_la_salida_deja_un_marcador_visible(self):
        """
        Sin foja, el escrito sale con el hueco a la vista y no con un número plausible.
        Quien lo lea tiene que tropezarse con la falta, no pasarla por alto.
        """
        from punteo import exportacion, generacion
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        modelo.decidir(self.cx, ev["id"], "incluida")
        generacion.generar(self.cx)
        self.assertIn(generacion.FALTA_FOJA, exportacion.a_texto(self.cx))

    def test_se_puede_cargar_la_foja_despues(self):
        from punteo import foliatura
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        foliatura.fijar(self.cx, ev["pagina_inicio"], "88")
        self.assertEqual(modelo.obtener(self.cx, ev["id"])["foja_inicio"], "88")
        self.assertEqual(modelo.obtener(self.cx, ev["id"])["foja_origen"], "manual")


class FoliaturaQueSeCorta(CasoDePrueba):
    """El legajo está foliado hasta la mitad y después no. Pasa seguido."""
    FOJAS_DESDE = 500
    SIN_FOLIAR_DESDE = 20

    def test_el_tramo_termina_donde_termina_la_foliatura(self):
        tramos = self.cx.execute(
            "SELECT * FROM tramo_foliatura ORDER BY desde_global").fetchall()
        self.assertEqual(len(tramos), 1)
        self.assertEqual(tramos[0]["desde_global"], 1)
        self.assertLess(tramos[0]["hasta_global"], 20)

    def test_las_paginas_de_atras_quedan_sin_foja(self):
        sin = self.cx.execute("""SELECT COUNT(*) FROM pagina
                                  WHERE numero_global >= 20
                                    AND foja_etiqueta IS NOT NULL""").fetchone()[0]
        self.assertEqual(sin, 0, "se inventaron fojas donde el papel no las tiene")


class DosSeriesQueSeContradicen(CasoVacio):
    """
    La paginación interna de un documento no es la foliatura del legajo.

    El caso que lo hizo evidente fue un legajo de verdad: dos informes seguidos, cada
    uno numerando sus propias hojas al pie —1, 2, 3…— y el detector los tomó por dos
    tramos de foliatura, con confianzas de 0.8 y 0.89. Ofrecía «foja 3» para una hoja
    que en el papel es la foja 1130, sellada a mano. Alcanzaba con que alguien
    confirmara el tramo para que ese número entrara a un requerimiento.

    Lo que los delata no es la zona ni la confianza: es que se contradicen. La foja no
    retrocede cuando avanza la página, y dos hojas distintas no son la misma foja.
    """

    def _tramo(self, desde, hasta, desplazamiento):
        from punteo.foliatura import Tramo
        return Tramo("inf_der", desde, hasta, desplazamiento, hasta - desde + 1, 0)

    def test_dos_tramos_que_se_pisan_caen_los_dos(self):
        from punteo import foliatura
        # fojas 3–6 en las páginas 4–7, y fojas 2–11 en las páginas 30–39: la foja
        # retrocede de 6 a 2 mientras la página avanza de 7 a 30.
        quedan, caen = foliatura.coherentes(
            [self._tramo(4, 7, -1), self._tramo(30, 39, -28)])
        self.assertEqual(quedan, [])
        self.assertEqual(len(caen), 2,
                         "no se elige el más creíble: la contradicción no dice cuál era")

    def test_un_tramo_que_no_contradice_a_nadie_sobrevive(self):
        from punteo import foliatura
        # 100–109 y 200–209 en páginas que avanzan: dos etapas de foliatura, normal.
        quedan, caen = foliatura.coherentes(
            [self._tramo(1, 10, 99), self._tramo(50, 59, 150)])
        self.assertEqual(len(quedan), 2)
        self.assertEqual(caen, [])

    def test_el_que_se_salva_no_se_lleva_puesto_al_que_no(self):
        from punteo import foliatura
        quedan, caen = foliatura.coherentes(
            [self._tramo(1, 10, 99),      # fojas 100–109
             self._tramo(20, 29, 80),     # fojas 100–109 otra vez: choca con el primero
             self._tramo(60, 69, 240)])   # fojas 300–309: no choca con nadie
        self.assertEqual([t.desde_global for t in quedan], [60])
        self.assertEqual([t.desde_global for t in caen], [1, 20])

    def test_sobre_el_papel_no_queda_ninguna_foja(self):
        """De punta a punta: dos documentos que se numeran solos no dan foliatura."""
        from punteo import foliatura
        # Cada documento numera sus hojas al pie, a la derecha, desde 1.
        paginas = []
        for doc in range(2):
            for hoja in range(1, 7):
                paginas.append((f"INFORME DEL ORGANISMO {doc + 1}", str(hoja)))
        self.cargar_con_pie(paginas)
        r = foliatura.detectar(self.cx)

        self.assertEqual(r["tramos"], 0)
        self.assertEqual(r["paginas_con_foja"], 0)
        self.assertEqual(r["series_descartadas"], 2)
        sin_foja = self.cx.execute(
            "SELECT COUNT(*) FROM pagina WHERE foja_etiqueta IS NOT NULL").fetchone()[0]
        self.assertEqual(sin_foja, 0, "se ofreció como foja la hoja interna de un informe")

    def test_la_serie_descartada_queda_con_su_motivo(self):
        """
        Descartar en silencio es peor que no descartar: quien mira el legajo ve números
        en el margen, ve «no se detectó foliatura», y no sabe si el sistema miró.
        """
        from punteo import foliatura
        paginas = []
        for doc in range(2):
            for hoja in range(1, 7):
                paginas.append((f"INFORME DEL ORGANISMO {doc + 1}", str(hoja)))
        self.cargar_con_pie(paginas)
        foliatura.detectar(self.cx)

        r = foliatura.resumen(self.cx)
        self.assertEqual(r["tramos"], [])
        self.assertEqual(len(r["tramos_descartados"]), 2)
        for t in r["tramos_descartados"]:
            self.assertEqual(t["descartado"], foliatura.MOTIVO_CONTRADICCION)


class ElSelloDeFolioSinNumero(CasoVacio):
    """
    «FOLIO Nº ____» impreso y el número a mano adentro. Es como se folia de verdad en
    buena parte de los legajos, y Tesseract no lee manuscrita.

    Una hoja así no tiene foja para el sistema, pero sí la tiene en el papel. Dejarla
    junto a las hojas sin foliar invita a pasarla de largo; marcarla dice dónde hay un
    número para copiar.
    """

    def test_el_sello_del_margen_se_marca(self):
        from punteo import foliatura
        self.cargar_con_sello(["ACTA DE DECLARACIÓN TESTIMONIAL"] * 3)
        foliatura.detectar(self.cx)

        filas = self.cx.execute("""SELECT foja_etiqueta, foja_origen, foja_lectura
                                     FROM pagina ORDER BY numero_global""").fetchall()
        self.assertTrue(filas)
        for f in filas:
            self.assertIsNone(f["foja_etiqueta"], "se inventó un número que nadie leyó")
            self.assertEqual(f["foja_origen"], "desconocida")
            self.assertEqual(f["foja_lectura"], "sello_ilegible")
        self.assertEqual(foliatura.resumen(self.cx)["sellos_sin_leer"], len(filas))

    def test_borrar_una_foja_a_mano_devuelve_la_marca_del_sello(self):
        """
        El sello no se va porque alguien haya cargado y después borrado la foja. Sin
        esto, la hoja se quedaba sin esa pista hasta el próximo reproceso, que es
        justamente cuando nadie la está mirando.
        """
        from punteo import foliatura
        self.cargar_con_sello(["ACTA DE DECLARACIÓN TESTIMONIAL"] * 3)
        foliatura.detectar(self.cx)

        foliatura.fijar(self.cx, 1, "1130")
        self.assertIsNone(self.cx.execute(
            "SELECT foja_lectura FROM pagina WHERE numero_global=1").fetchone()[0])

        r = foliatura.fijar(self.cx, 1, None)
        self.assertTrue(r["sello_sin_leer"])
        self.assertEqual(self.cx.execute(
            "SELECT foja_lectura FROM pagina WHERE numero_global=1").fetchone()[0],
            "sello_ilegible")

    def test_la_palabra_folio_en_el_cuerpo_no_cuenta(self):
        """
        «obrante a folio 23» habla de otra pieza, no de esta hoja.

        Por eso el sello se busca en el margen y no en el texto: en prosa jurídica la
        palabra aparece todo el tiempo citando fojas ajenas, y marcar cada una de esas
        páginas sería mandar a revisar medio legajo por nada.
        """
        from punteo import foliatura
        self.cargar([["ACTA DE DECLARACIÓN TESTIMONIAL",
                      "En la ciudad de Paraná, a los 3 días del mes de marzo de 2026,",
                      "comparece el testigo citado conforme lo resuelto oportunamente,",
                      "y se agrega el informe obrante a folio 23 del legajo."]] * 3)
        foliatura.detectar(self.cx)

        marcadas = self.cx.execute("""SELECT COUNT(*) FROM pagina
                                       WHERE foja_lectura='sello_ilegible'""").fetchone()[0]
        self.assertEqual(marcadas, 0)


class EtiquetasDeFoja(unittest.TestCase):
    """La foja no es un entero: «411 vta.» y «411 bis» existen y hay que guardarlas."""

    def test_partir(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from punteo.foliatura import etiqueta_foja, partir_etiqueta

        self.assertEqual(partir_etiqueta("411"), (411, ""))
        self.assertEqual(partir_etiqueta("411 vta."), (411, "vta"))
        self.assertEqual(partir_etiqueta("411vlta"), (411, "vta"))
        self.assertEqual(partir_etiqueta("411 bis"), (411, "bis"))
        self.assertEqual(partir_etiqueta("fs. 411"), (411, ""))
        self.assertEqual(partir_etiqueta("-411-"), (411, ""))
        self.assertIsNone(partir_etiqueta("no es una foja"))
        self.assertIsNone(partir_etiqueta("99999"))
        self.assertIsNone(partir_etiqueta("0"))

        self.assertEqual(etiqueta_foja(411, "vta"), "411 vta.")
        self.assertEqual(etiqueta_foja(411), "411")
        self.assertIsNone(etiqueta_foja(None))


if __name__ == "__main__":
    unittest.main()
