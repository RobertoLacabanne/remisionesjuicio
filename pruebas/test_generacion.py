"""
El generador y la exportación.

Lo central está en `test_invariante.py`. Acá se prueba lo otro que el generador promete:
que respete el orden que aprobó la persona, que arme los bloques donde corresponde, y
que no reorganice nada por su cuenta.
"""
from __future__ import annotations

import unittest

from comun import CasoDePrueba


class Orden(CasoDePrueba):

    def _incluir(self, cuantas=6):
        from punteo.evidencia import modelo
        evs = self.evidencias()[:cuantas]
        for e in evs:
            modelo.decidir(self.cx, e["id"], "incluida")
        return evs

    def test_el_orden_manual_se_respeta_tal_cual(self):
        """
        La promesa textual: el generador nunca cambia por sí solo el orden aprobado.
        Se invierte el orden a propósito y la salida tiene que salir invertida.
        """
        from punteo import generacion
        from punteo.evidencia import modelo
        evs = self._incluir()
        al_reves = [e["id"] for e in reversed(evs)]
        modelo.reordenar(self.cx, al_reves)
        p = generacion.generar(self.cx, criterio="manual")
        salida = [x["evidencia_id"] for x in p["parrafos"] if x["clase"] == "pieza"]
        self.assertEqual(salida, al_reves)

    def test_cronologico_manda_lo_sin_fecha_al_final(self):
        from punteo import generacion
        from punteo.evidencia import modelo
        evs = self._incluir()
        modelo.editar(self.cx, evs[3]["id"], {"fecha_documento": "2020-01-15"})
        modelo.editar(self.cx, evs[1]["id"], {"fecha_documento": "2019-06-02"})
        p = generacion.generar(self.cx, criterio="cronologico", con_encabezados=False)
        ids = [x["evidencia_id"] for x in p["parrafos"] if x["clase"] == "pieza"]
        self.assertEqual(ids[:2], [evs[1]["id"], evs[3]["id"]])

    def test_por_grupos_arma_bloques_con_encabezado(self):
        from punteo import generacion, grupos
        evs = self._incluir()
        g = grupos.crear(self.cx, "Actuaciones policiales",
                         encabezado="ACTUACIONES LABRADAS POR PERSONAL POLICIAL")
        grupos.mover_varias(self.cx, [e["id"] for e in evs[:3]], g["id"])
        p = generacion.generar(self.cx, criterio="grupos", con_encabezados=True)
        encabezados = [x["texto_generado"] for x in p["parrafos"] if x["clase"] == "encabezado"]
        self.assertIn("ACTUACIONES LABRADAS POR PERSONAL POLICIAL", encabezados)

    def test_el_encabezado_del_grupo_le_gana_al_nombre(self):
        from punteo import generacion, grupos
        evs = self._incluir(2)
        g = grupos.crear(self.cx, "Banco ERíos",
                         encabezado="EVIDENCIA REMITIDA POR EL NUEVO BANCO DE ENTRE RÍOS S.A.")
        grupos.mover_varias(self.cx, [e["id"] for e in evs], g["id"])
        p = generacion.generar(self.cx, criterio="grupos")
        encabezados = " ".join(x["texto_generado"] for x in p["parrafos"]
                               if x["clase"] == "encabezado")
        self.assertIn("NUEVO BANCO DE ENTRE RÍOS", encabezados)
        self.assertNotIn("BANCO ERÍOS", encabezados)

    def test_numeracion_por_grupo_reinicia(self):
        from punteo import generacion, grupos
        evs = self._incluir()
        a = grupos.crear(self.cx, "Sector A")
        b = grupos.crear(self.cx, "Sector B")
        grupos.mover_varias(self.cx, [e["id"] for e in evs[:3]], a["id"])
        grupos.mover_varias(self.cx, [e["id"] for e in evs[3:]], b["id"])
        p = generacion.generar(self.cx, criterio="grupos", numeracion="por_grupo")
        numeros = [x["numero"] for x in p["parrafos"] if x["clase"] == "pieza"]
        self.assertEqual(numeros.count("1.-"), 2, "la numeración no reinició en cada sector")

    def test_criterio_desconocido_se_rechaza(self):
        from punteo import generacion
        self._incluir(1)
        with self.assertRaises(ValueError):
            generacion.generar(self.cx, criterio="a_ojo")


class Texto(CasoDePrueba):

    def test_una_testimonial_no_se_introduce_por_otra_testimonial(self):
        """
        La fórmula general produce una frase incorrecta con las declaraciones: «…que
        será introducida al debate mediante la declaración testimonial de Pérez» sobre
        la declaración de Pérez. Una testimonial ES la prueba.
        """
        from punteo import exportacion, generacion, personas
        from punteo.evidencia import modelo
        ev = next(e for e in self.evidencias() if e["tipo"] == "declaracion_testimonial")
        p = personas.buscar_o_crear(self.cx, "ANDRADE, Rubén Osvaldo")
        personas.asociar(self.cx, ev["id"], p["id"])
        modelo.decidir(self.cx, ev["id"], "incluida")
        generacion.generar(self.cx)
        self.assertNotIn("mediante la declaración testimonial", exportacion.a_texto(self.cx))

    def test_en_abreviado_no_se_pide_testigo(self):
        from punteo import casos, exportacion, generacion
        from punteo.evidencia import modelo
        casos.actualizar(self.caso.slug, tipo_proceso="abreviado")
        self.reabrir()
        ev = self.evidencias()[0]
        modelo.decidir(self.cx, ev["id"], "incluida")
        generacion.generar(self.cx)
        salida = exportacion.a_texto(self.cx)
        self.assertNotIn(generacion.FALTA_TESTIGO, salida)
        self.assertNotIn("introducida al debate", salida)
        self.assertEqual(generacion.verificar(self.cx)["sin_testigo"], [])

    def test_el_parrafo_editado_gana_pero_no_pisa_el_generado(self):
        from punteo import exportacion, generacion
        from punteo.evidencia import modelo
        modelo.decidir(self.cx, self.evidencias()[0]["id"], "incluida")
        p = generacion.generar(self.cx)
        parrafo = next(x for x in p["parrafos"] if x["clase"] == "pieza")
        generado = parrafo["texto_generado"]

        generacion.editar_parrafo(self.cx, parrafo["id"], "Texto escrito a mano QQWW")
        self.assertIn("QQWW", exportacion.a_texto(self.cx))
        # El generado sigue estando: volver atrás no obliga a regenerar todo.
        vuelto = generacion.editar_parrafo(self.cx, parrafo["id"], "")
        self.assertEqual(
            next(x for x in vuelto["parrafos"] if x["id"] == parrafo["id"])["texto"], generado)

    def test_la_relacion_parrafo_evidencia_no_se_pierde_al_editar(self):
        from punteo import generacion
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        modelo.decidir(self.cx, ev["id"], "incluida")
        p = generacion.generar(self.cx)
        parrafo = next(x for x in p["parrafos"] if x["clase"] == "pieza")
        vuelto = generacion.editar_parrafo(self.cx, parrafo["id"], "otra cosa")
        self.assertEqual(
            next(x for x in vuelto["parrafos"] if x["id"] == parrafo["id"])["evidencia_id"],
            ev["id"])

    def test_fecha_en_letras(self):
        from punteo.generacion import fecha_en_letras
        self.assertEqual(fecha_en_letras("2024-03-12"), "12 de marzo de 2024")
        self.assertEqual(fecha_en_letras(None), "")
        self.assertEqual(fecha_en_letras("no es una fecha"), "")

    def test_romanos(self):
        from punteo.generacion import romano
        self.assertEqual([romano(n) for n in (1, 4, 5, 9, 14, 40, 90)],
                         ["I", "IV", "V", "IX", "XIV", "XL", "XC"])


class Exportacion(CasoDePrueba):

    def _generar(self):
        from punteo import generacion
        from punteo.evidencia import modelo
        for e in self.evidencias()[:4]:
            modelo.decidir(self.cx, e["id"], "incluida")
        return generacion.generar(self.cx)

    def test_rtf_se_abre_y_lleva_los_acentos(self):
        from punteo import exportacion
        self._generar()
        rtf = exportacion.a_rtf(self.cx)
        self.assertTrue(rtf.startswith(b"{\\rtf1"))
        self.assertTrue(rtf.rstrip().endswith(b"}"))
        # Una ñ o un acento van escapados como \uN?, no crudos.
        self.assertIn(rb"\u", rtf)

    def test_rtf_escapa_las_llaves(self):
        from punteo.exportacion import _rtf_escapar
        self.assertEqual(_rtf_escapar("a{b}c\\d"), "a\\{b\\}c\\\\d")
        self.assertEqual(_rtf_escapar("ñ"), r"\u241?")

    def test_json_es_un_respaldo_completo(self):
        import json
        from punteo import exportacion
        self._generar()
        datos = json.loads(exportacion.a_json(self.cx))
        for clave in ("caso", "documentos", "fojas", "evidencias", "personas",
                      "grupos", "revisiones", "punteo"):
            self.assertIn(clave, datos)
        self.assertEqual(len(datos["evidencias"]), len(self.evidencias()))
        # El respaldo SÍ lleva todo, incluidas las excluidas: no es el escrito.
        self.assertTrue(any(e["estado"] == "pendiente" for e in datos["evidencias"]))
        self.assertTrue(datos["documentos"][0]["sha256"])

    def test_formato_desconocido_se_rechaza(self):
        from punteo import exportacion
        self._generar()
        with self.assertRaises(ValueError):
            exportacion.contenido(self.cx, "docx")

    def test_guardar_escribe_en_la_carpeta_del_caso(self):
        from punteo import config, exportacion
        self._generar()
        ruta = exportacion.guardar(self.cx, "rtf")
        self.assertTrue(ruta.exists())
        self.assertTrue(str(ruta).startswith(str(config.carpeta_caso(self.caso.slug))))


if __name__ == "__main__":
    unittest.main()
