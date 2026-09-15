"""
Detección de piezas.

Lo que se verifica no es que acierte siempre —no va a acertar siempre— sino que
**se equivoque para el lado barato**: partir de más, que se arregla con dos clics,
y nunca esconder una pieza adentro de otra, que es prueba que no ve nadie.
"""
from __future__ import annotations

import unittest

from comun import CasoDePrueba


class CortaDondeCorresponde(CasoDePrueba):

    def _esperado(self):
        return [(p["pagina_inicio"], p["pagina_fin"]) for p in self.verdad]

    def test_encuentra_todas_las_piezas(self):
        self.assertEqual(len(self.evidencias()), len(self.verdad))

    def test_los_rangos_de_pagina_son_exactos(self):
        obtenido = [(e["pagina_inicio"], e["pagina_fin"]) for e in self.evidencias()]
        self.assertEqual(obtenido, self._esperado())

    def test_el_tipo_sale_del_titulo(self):
        obtenido = [e["tipo"] for e in self.evidencias()]
        self.assertEqual(obtenido, [p["tipo"] for p in self.verdad])

    def test_evidencia_de_una_sola_pagina(self):
        una = [e for e in self.evidencias() if e["pagina_inicio"] == e["pagina_fin"]]
        self.assertTrue(una, "ninguna pieza de una página: el corte junta de más")

    def test_evidencia_multipagina(self):
        varias = [e for e in self.evidencias() if e["pagina_fin"] > e["pagina_inicio"]]
        self.assertTrue(varias)
        for e in varias:
            self.assertGreater(e["pagina_fin"], e["pagina_inicio"])

    def test_dos_piezas_consecutivas_del_mismo_tipo_no_se_juntan(self):
        """
        Dos declaraciones testimoniales seguidas son dos piezas y no una. Es el caso
        donde la marca de continuidad y el título repetido se contradicen.
        """
        testimoniales = [e for e in self.evidencias()
                         if e["tipo"] == "declaracion_testimonial"]
        self.assertEqual(len(testimoniales), 2)
        self.assertNotEqual(testimoniales[0]["pagina_inicio"], testimoniales[1]["pagina_inicio"])

    def test_el_oficio_y_su_respuesta_son_dos(self):
        tipos = [e["tipo"] for e in self.evidencias()]
        self.assertIn("oficio", tipos)
        self.assertIn("respuesta_oficio", tipos)

    def test_toda_pieza_nace_pendiente(self):
        """La IA propone; la persona decide. Nada entra a la salida sin decisión humana."""
        for e in self.evidencias():
            self.assertEqual(e["estado"], "pendiente")

    def test_toda_pieza_tiene_anclaje_documental(self):
        for e in self.evidencias():
            self.assertIsNotNone(e["pagina_inicio"])
            self.assertIsNotNone(e["documento_id"])
            self.assertTrue(e["texto_origen"], f"la pieza {e['id']} no guardó su respaldo")

    def test_volver_a_detectar_no_pisa_el_trabajo_hecho(self):
        from punteo.evidencia import deteccion
        antes = len(self.evidencias())
        r = deteccion.detectar(self.cx)
        self.assertEqual(r["creadas"], 0)
        self.assertEqual(r["ya_habia"], antes)
        self.assertIsNotNone(r["motivo"])
        self.assertEqual(len(self.evidencias()), antes)


class NoSeComeUnaPieza(CasoDePrueba):
    """
    La regresión del bug que más caro salía.

    «Se transcriben A CONTINUACIÓN los intercambios…» es prosa jurídica corriente, y la
    primera versión del detector la tomaba por marca de continuidad. La transcripción de
    conversaciones quedaba adentro del informe del gabinete, donde nadie la habría visto.
    """

    def test_la_transcripcion_es_su_propia_pieza(self):
        tipos = [e["tipo"] for e in self.evidencias()]
        self.assertIn("conversaciones", tipos)
        self.assertIn("pericia_informatica", tipos)

        conv = next(e for e in self.evidencias() if e["tipo"] == "conversaciones")
        peri = next(e for e in self.evidencias() if e["tipo"] == "pericia_informatica")
        self.assertGreater(conv["pagina_inicio"], peri["pagina_fin"],
                           "la transcripción quedó adentro del informe del gabinete")

    def test_a_continuacion_no_es_marca_de_continuidad(self):
        from punteo.evidencia.deteccion import _CONTINUACION
        self.assertIsNone(_CONTINUACION.search("SE TRANSCRIBEN A CONTINUACION LOS INTERCAMBIOS"))
        self.assertIsNone(_CONTINUACION.search("SE DETALLA A CONTINUACION"))
        # Y las que sí lo son, siguen siéndolo.
        for marca in ("ACTA DE SECUESTRO (CONTINUACION 2/3)", "CONTINUACION 2 DE 3",
                      "CONTINUA AL DORSO", "HOJA 3 DE 8", "PAG. 2/5"):
            self.assertIsNotNone(_CONTINUACION.search(marca), marca)

    def test_un_titulo_al_principio_de_linea_se_reconoce(self):
        """
        El título nunca es lo primero de la página: arriba está la foja sellada y el
        membrete del organismo. Los patrones anclados a `^` tienen que ser MULTILINE.
        """
        from punteo.evidencia import catalogo
        encabezado = "415\nMINISTERIO PUBLICO FISCAL - ENTRE RIOS\nOFICIO Nº 1174"
        tipo, fuerza = catalogo.reconocer(encabezado)
        self.assertEqual(tipo.clave, "oficio")
        self.assertGreater(fuerza, 0.5)


class Catalogo(unittest.TestCase):

    def setUp(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    def test_lo_especifico_le_gana_a_lo_generico(self):
        from punteo.evidencia import catalogo
        self.assertEqual(catalogo.reconocer("ACTA DE SECUESTRO")[0].clave, "acta_secuestro")
        self.assertEqual(catalogo.reconocer("ACTA DE ALLANAMIENTO")[0].clave, "acta_allanamiento")
        self.assertEqual(catalogo.reconocer("ACTA")[0].clave, "acta")

    def test_lo_que_no_reconoce_igual_se_propone(self):
        """
        Una pieza que no se propone es una que nadie va a mirar. Sin tipo, pero existe.
        """
        from punteo.evidencia import catalogo
        tipo, fuerza = catalogo.reconocer("UN DOCUMENTO QUE NO SE PARECE A NADA")
        self.assertEqual(tipo.clave, "sin_clasificar")
        self.assertEqual(fuerza, 0.0)

    def test_una_mencion_de_paso_pesa_menos_que_un_titulo(self):
        from punteo.evidencia import catalogo
        titulo = catalogo.reconocer("ACTA DE SECUESTRO")[1]
        mencion = catalogo.reconocer(
            "INFORME PERICIAL\n" + "x" * 120 + "\nconforme el ACTA DE SECUESTRO de fs. 120")[1]
        self.assertGreater(titulo, mencion)

    def test_los_tipos_no_tienen_claves_repetidas(self):
        from punteo.evidencia import catalogo
        claves = [t.clave for t in catalogo.TIPOS]
        self.assertEqual(len(claves), len(set(claves)))

    def test_toda_familia_del_catalogo_esta_declarada(self):
        from punteo.evidencia import catalogo
        for t in catalogo.TIPOS:
            self.assertIn(t.familia, catalogo.FAMILIAS, t.clave)


class Fechas(unittest.TestCase):
    """Nunca se infiere una fecha. Si no está completa, no está."""

    def setUp(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    def test_las_que_se_pueden_afirmar(self):
        from punteo.evidencia.deteccion import detectar_fecha
        self.assertEqual(detectar_fecha("labrada el 12/03/2024 en Paraná"), "2024-03-12")
        self.assertEqual(detectar_fecha("a los 5 de agosto de 2023"), "2023-08-05")
        self.assertEqual(detectar_fecha("el 1 de setiembre de 2022"), "2022-09-01")

    def test_las_que_no(self):
        from punteo.evidencia.deteccion import detectar_fecha
        # Sin año no hay fecha. Completarlo con el año del legajo sería inventar.
        self.assertIsNone(detectar_fecha("a los doce días del mes de marzo"))
        self.assertIsNone(detectar_fecha("sin fecha alguna"))
        self.assertIsNone(detectar_fecha("expediente 4412/99012"))
        self.assertIsNone(detectar_fecha("el 45/13/2024"))


if __name__ == "__main__":
    unittest.main()
