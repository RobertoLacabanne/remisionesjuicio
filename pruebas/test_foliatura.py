"""
La foja no es la página del PDF.

En el escrito se cita «fs. 342/346». Si ese número sale de la página del PDF, la cita es
falsa y el error llega a un tribunal. Esta prueba existe para que la distinción no se
pueda romper sin que algo se ponga rojo.
"""
from __future__ import annotations

import unittest

from comun import CasoDePrueba


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
