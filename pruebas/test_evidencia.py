"""
El modelo de evidencia: dividir, unir, cargar a mano, descartar y deshacer.

Todas estas operaciones comparten una regla: **no se borra nada**. Se apaga la fila y
queda el rastro, para poder contestar «¿de dónde salió esta pieza?» y para poder
deshacer sin reprocesar el legajo.
"""
from __future__ import annotations

import unittest

from comun import CasoDePrueba


class Dividir(CasoDePrueba):

    def _larga(self):
        return next(e for e in self.evidencias() if e["pagina_fin"] - e["pagina_inicio"] >= 2)

    def test_parte_en_dos_y_apaga_la_original(self):
        from punteo.evidencia import modelo
        ev = self._larga()
        corte = ev["pagina_inicio"] + 1
        r = modelo.dividir(self.cx, ev["id"], corte)
        a, b = r["nuevas"]
        self.assertEqual(a["pagina_inicio"], ev["pagina_inicio"])
        self.assertEqual(a["pagina_fin"], corte - 1)
        self.assertEqual(b["pagina_inicio"], corte)
        self.assertEqual(b["pagina_fin"], ev["pagina_fin"])
        self.assertFalse(modelo.obtener(self.cx, ev["id"])["activa"])

    def test_las_mitades_nacen_pendientes_aunque_la_original_estuviera_incluida(self):
        """
        Deliberado: dividir cambia QUÉ ES cada pieza, así que la decisión anterior no se
        aplica a ninguna de las dos. Heredar «incluida» significaría que una mitad que
        nadie miró entra al escrito porque el todo estaba aprobado.
        """
        from punteo.evidencia import modelo
        ev = self._larga()
        modelo.decidir(self.cx, ev["id"], "incluida")
        for nueva in modelo.dividir(self.cx, ev["id"], ev["pagina_inicio"] + 1)["nuevas"]:
            self.assertEqual(nueva["estado"], "pendiente")

    def test_el_testigo_se_copia_a_las_dos_mitades(self):
        from punteo import personas
        from punteo.evidencia import modelo
        ev = self._larga()
        p = personas.buscar_o_crear(self.cx, "ANDRADE, Rubén Osvaldo", rol="policia")
        personas.asociar(self.cx, ev["id"], p["id"])
        for nueva in modelo.dividir(self.cx, ev["id"], ev["pagina_inicio"] + 1)["nuevas"]:
            self.assertEqual(nueva["testigo"], "ANDRADE, Rubén Osvaldo")

    def test_no_se_puede_cortar_fuera_del_rango(self):
        from punteo.evidencia import modelo
        ev = self._larga()
        for corte in (ev["pagina_inicio"], ev["pagina_fin"] + 1, 0):
            with self.assertRaises(modelo.OperacionInvalida):
                modelo.dividir(self.cx, ev["id"], corte)

    def test_deshacer_devuelve_la_original(self):
        from punteo.evidencia import modelo
        ev = self._larga()
        nuevas = modelo.dividir(self.cx, ev["id"], ev["pagina_inicio"] + 1)["nuevas"]
        modelo.deshacer(self.cx, nuevas[0]["id"])
        self.assertTrue(modelo.obtener(self.cx, ev["id"])["activa"])
        for n in nuevas:
            self.assertFalse(modelo.obtener(self.cx, n["id"])["activa"])


class Unir(CasoDePrueba):

    def test_une_dos_consecutivas(self):
        from punteo.evidencia import modelo
        a, b = self.evidencias()[:2]
        u = modelo.unir(self.cx, [a["id"], b["id"]])
        self.assertEqual(u["pagina_inicio"], a["pagina_inicio"])
        self.assertEqual(u["pagina_fin"], b["pagina_fin"])
        self.assertEqual(u["origen"], "union")
        self.assertEqual(u["estado"], "pendiente")
        for x in (a, b):
            self.assertFalse(modelo.obtener(self.cx, x["id"])["activa"])

    def test_no_se_une_si_alguna_parte_esta_excluida(self):
        """
        Antes esto salía con una advertencia. No alcanzaba: la unión copia la descripción
        de su primera parte, así que el texto excluido llegaba al escrito adentro de una
        pieza nueva que nadie relacionaba con la decisión anterior. Ahora hay que volver
        la parte a pendiente, que es una decisión y queda en el historial.
        """
        from punteo.evidencia import modelo
        a, b = self.evidencias()[:2]
        modelo.decidir(self.cx, b["id"], "excluida")
        with self.assertRaises(modelo.OperacionInvalida):
            modelo.unir(self.cx, [a["id"], b["id"]])
        modelo.decidir(self.cx, b["id"], "pendiente")
        u = modelo.unir(self.cx, [a["id"], b["id"]])
        self.assertEqual(u["estado"], "pendiente")

    def test_deshacer_devuelve_las_partes(self):
        from punteo.evidencia import modelo
        a, b = self.evidencias()[:2]
        u = modelo.unir(self.cx, [a["id"], b["id"]])
        modelo.deshacer(self.cx, u["id"])
        self.assertFalse(modelo.obtener(self.cx, u["id"])["activa"])
        for x in (a, b):
            self.assertTrue(modelo.obtener(self.cx, x["id"])["activa"])

    def test_hacen_falta_dos(self):
        from punteo.evidencia import modelo
        a = self.evidencias()[0]
        with self.assertRaises(modelo.OperacionInvalida):
            modelo.unir(self.cx, [a["id"]])


class EvidenciaCargadaAMano(CasoDePrueba):

    def test_se_integra_igual_que_la_automatica(self):
        from punteo import exportacion, generacion
        from punteo.evidencia import modelo
        nueva = modelo.crear_manual(
            self.cx, pagina_inicio=5, pagina_fin=6, tipo="acta_secuestro",
            descripcion="Acta de secuestro que el sistema no detectó",
            foja_inicio="404", foja_fin="405", estado="incluida")
        self.assertEqual(nueva["origen"], "manual")
        self.assertIsNone(nueva["confianza"])
        self.assertEqual(nueva["confianza_nivel"], "manual")

        generacion.generar(self.cx)
        self.assertIn("que el sistema no detectó", exportacion.a_texto(self.cx))

    def test_las_fojas_en_blanco_salen_de_la_pagina_y_no_pasan_por_escritas(self):
        """
        El formulario ofrece las fojas de la página. Si se guardan igual, quedan en las
        columnas `_final` y el sistema las trata como verificadas por una persona: una
        pieza de cinco fojas salía «fs. 400», sin marca y sin el rango.
        """
        from punteo.evidencia import modelo
        nueva = modelo.crear_manual(
            self.cx, pagina_inicio=5, pagina_fin=7, descripcion="Planilla sin título",
            foja_inicio="", foja_fin="   ")
        self.assertEqual(nueva["foja_origen"], "detectada")
        self.assertEqual(nueva["foja_inicio"], "404")
        self.assertEqual(nueva["foja_fin"], "406")
        self.assertFalse(nueva["foja_firme"])
        self.assertIsNone(self.cx.execute(
            "SELECT foja_inicio_final FROM evidencia WHERE id=?", (nueva["id"],)).fetchone()[0])

    def test_sin_descripcion_no_se_crea(self):
        from punteo.evidencia import modelo
        with self.assertRaises(modelo.OperacionInvalida):
            modelo.crear_manual(self.cx, pagina_inicio=1, descripcion="   ")

    def test_rango_invertido_se_rechaza(self):
        from punteo.evidencia import modelo
        with self.assertRaises(modelo.OperacionInvalida):
            modelo.crear_manual(self.cx, pagina_inicio=9, pagina_fin=3, descripcion="algo")


class DescartarYRestaurar(CasoDePrueba):

    def test_descartar_no_borra(self):
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        antes = len(self.evidencias())
        modelo.descartar(self.cx, ev["id"])
        self.assertEqual(len(self.evidencias()), antes - 1)
        # Sigue en la base, apagada.
        self.assertIsNotNone(self.cx.execute(
            "SELECT 1 FROM evidencia WHERE id=?", (ev["id"],)).fetchone())
        modelo.restaurar(self.cx, ev["id"])
        self.assertEqual(len(self.evidencias()), antes)

    def test_descartar_es_distinto_de_excluir(self):
        """
        Excluir es una decisión sobre prueba que existe; descartar es decir que eso nunca
        fue una pieza. En el punteo ninguna de las dos aparece; en los contadores,
        excluida se cuenta y descartada no.
        """
        from punteo.evidencia import modelo
        a, b = self.evidencias()[:2]
        modelo.decidir(self.cx, a["id"], "excluida")
        modelo.descartar(self.cx, b["id"])
        c = self.contadores()
        self.assertEqual(c["excluidas"], 1)
        self.assertNotIn(b["id"], [e["id"] for e in self.evidencias()])


class Estados(CasoDePrueba):

    def test_de_incluir_a_excluir_y_vuelta(self):
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        for estado in ("incluida", "excluida", "pendiente", "incluida"):
            r = modelo.decidir(self.cx, ev["id"], estado)
            self.assertEqual(r["estado"], estado)
        historial = [h["valor_nuevo"] for h in modelo.historial(self.cx, ev["id"])
                     if h["campo"] == "estado"]
        self.assertEqual(historial, ["incluida", "pendiente", "excluida", "incluida"])

    def test_estado_desconocido_se_rechaza(self):
        from punteo.evidencia import modelo
        with self.assertRaises(modelo.OperacionInvalida):
            modelo.decidir(self.cx, self.evidencias()[0]["id"], "quizas")

    def test_en_lote(self):
        from punteo.evidencia import modelo
        ids = [e["id"] for e in self.evidencias()[:4]]
        r = modelo.decidir_varias(self.cx, ids, "incluida")
        self.assertEqual(r["cambiadas"], 4)
        self.assertEqual(self.contadores()["incluidas"], 4)

    def test_no_se_puede_decidir_sobre_una_apagada(self):
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        modelo.descartar(self.cx, ev["id"])
        with self.assertRaises(modelo.OperacionInvalida):
            modelo.decidir(self.cx, ev["id"], "incluida")


class Duplicados(CasoDePrueba):

    def test_se_proponen_pero_no_se_eliminan(self):
        from punteo.evidencia import duplicados, modelo
        # Dos declaraciones testimoniales con el mismo título: el caso real de duplicado
        # dudoso, que a veces es el mismo documento agregado dos veces y a veces no.
        antes = len(self.evidencias())
        r = duplicados.detectar(self.cx)
        self.assertGreater(r["propuestos"], 0)
        self.assertEqual(len(self.evidencias()), antes, "se borró algo solo")

    def test_descartar_una_propuesta_no_la_devuelve(self):
        from punteo.evidencia import duplicados
        duplicados.detectar(self.cx)
        lista = duplicados.listar(self.cx)
        self.assertTrue(lista)
        duplicados.descartar(self.cx, lista[0]["id"])
        duplicados.detectar(self.cx)
        restantes = [d["id"] for d in duplicados.listar(self.cx)]
        self.assertNotIn(lista[0]["id"], restantes)

    def test_dos_fechas_ciertas_y_distintas_no_son_la_misma_pieza(self):
        """
        Siete actas del mismo sumario comparten el membrete, la fórmula de juramento y
        el artículo 275 del Código Penal transcripto entero. Se parecen al noventa por
        ciento y son siete testigos distintos: el primer legajo real proponía veintiún
        duplicados y ninguno lo era.
        """
        from punteo.evidencia import duplicados, modelo
        evs = self.evidencias()
        a, b = evs[0], evs[1]
        modelo.editar(self.cx, a["id"], {"descripcion": "Acta de declaración testimonial"})
        modelo.editar(self.cx, b["id"], {"descripcion": "Acta de declaración testimonial"})

        self.cx.execute("UPDATE evidencia SET fecha_documento=NULL WHERE id IN (?,?)",
                        (a["id"], b["id"]))
        self.cx.commit()
        duplicados.detectar(self.cx)
        pares = {(d["a_id"], d["b_id"]) for d in duplicados.listar(self.cx)}
        self.assertIn((a["id"], b["id"]), pares, "sin fechas, el par se propone")

        self.cx.execute("UPDATE evidencia SET fecha_documento='2025-09-01' WHERE id=?", (a["id"],))
        self.cx.execute("UPDATE evidencia SET fecha_documento='2025-09-03' WHERE id=?", (b["id"],))
        self.cx.commit()
        duplicados.detectar(self.cx)
        pares = {(d["a_id"], d["b_id"]) for d in duplicados.listar(self.cx)}
        self.assertNotIn((a["id"], b["id"]), pares)

    def test_la_misma_fecha_sigue_proponiendose(self):
        """El duplicado verdadero: el mismo informe agregado dos veces, misma fecha."""
        from punteo.evidencia import duplicados, modelo
        evs = self.evidencias()
        a, b = evs[0], evs[1]
        modelo.editar(self.cx, a["id"], {"descripcion": "Informe pericial contable"})
        modelo.editar(self.cx, b["id"], {"descripcion": "Informe pericial contable"})
        self.cx.execute("UPDATE evidencia SET fecha_documento='2025-09-01' WHERE id IN (?,?)",
                        (a["id"], b["id"]))
        self.cx.commit()
        duplicados.detectar(self.cx)
        pares = {(d["a_id"], d["b_id"]) for d in duplicados.listar(self.cx)}
        self.assertIn((a["id"], b["id"]), pares)


class Testigos(CasoDePrueba):

    def test_una_pieza_entra_por_un_solo_introductor(self):
        from punteo import personas
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        a = personas.buscar_o_crear(self.cx, "PRIMERO, Uno")
        b = personas.buscar_o_crear(self.cx, "SEGUNDO, Dos")
        personas.asociar(self.cx, ev["id"], a["id"])
        personas.asociar(self.cx, ev["id"], b["id"])
        self.assertEqual(modelo.obtener(self.cx, ev["id"])["testigo"], "SEGUNDO, Dos")
        cuantos = self.cx.execute("""SELECT COUNT(*) FROM evidencia_persona
                                      WHERE evidencia_id=? AND funcion='introductor'""",
                                  (ev["id"],)).fetchone()[0]
        self.assertEqual(cuantos, 1)

    def test_el_mismo_nombre_escrito_distinto_no_duplica(self):
        from punteo import personas
        a = personas.buscar_o_crear(self.cx, "PÉREZ, Juan Carlos")
        b = personas.buscar_o_crear(self.cx, "juan carlos perez")
        self.assertEqual(a["id"], b["id"])

    def test_los_parecidos_se_proponen_pero_no_se_fusionan(self):
        from punteo import personas
        personas.buscar_o_crear(self.cx, "ANDRADE, Rubén Osvaldo")
        personas.buscar_o_crear(self.cx, "ANDRADE, Rubén")
        r = personas.proponer_fusiones(self.cx)
        self.assertGreaterEqual(r["propuestas"], 1)
        self.assertEqual(len(personas.listar(self.cx)), 2, "se fusionó solo")

    def test_las_piezas_sin_testigo_tienen_su_bloque(self):
        from punteo import personas
        bloques = personas.por_testigo(self.cx)
        sin = [b for b in bloques if b["id"] is None]
        self.assertEqual(len(sin), 1)
        self.assertGreater(len(sin[0]["evidencias"]), 0)


if __name__ == "__main__":
    unittest.main()
