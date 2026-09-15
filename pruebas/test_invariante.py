"""
LA PRUEBA QUE NO SE BORRA.

    usuario marca una evidencia como EXCLUIDA  →  el generador NO puede incluirla.

Es el único error que este sistema no puede cometer. Si alguna vez falla algo de acá,
no se arregla la prueba: se arregla el sistema.

La segunda mitad de la invariante tiene el mismo peso: si una persona corrigió la
descripción, la foja o el testigo, la salida usa **el valor corregido**. Un sistema que
respeta la exclusión pero imprime la descripción vieja falla por el otro lado.

Se prueba por los cuatro caminos que llegan a la salida —la vista, el generador, el
texto y el RTF— porque de nada sirve que la vista filtre si la exportación lee de otro
lado.
"""
from __future__ import annotations

import unittest

from comun import CasoDePrueba


class ExcluidoNuncaSale(CasoDePrueba):

    def _excluir_una(self):
        from punteo.evidencia import modelo
        evs = self.evidencias()
        for e in evs:
            modelo.decidir(self.cx, e["id"], "incluida")
        victima = evs[3]
        modelo.decidir(self.cx, victima["id"], "excluida")
        return victima, evs

    def test_la_vista_no_la_devuelve(self):
        victima, _ = self._excluir_una()
        ids = [r["id"] for r in self.cx.execute("SELECT id FROM v_evidencia_incluida")]
        self.assertNotIn(victima["id"], ids)

    def test_el_generador_no_la_escribe(self):
        from punteo import generacion
        victima, evs = self._excluir_una()
        p = generacion.generar(self.cx)
        self.assertNotIn(victima["id"], [x["evidencia_id"] for x in p["parrafos"]])
        self.assertEqual(p["total_piezas"], len(evs) - 1)

    def test_ni_su_texto_aparece_en_la_salida(self):
        """
        No alcanza con que no esté el id: lo que llega al escrito es el TEXTO.

        Una pieza podría colarse por otro camino —arrastrada por una unión, copiada en
        una descripción— y el control por identificador no lo vería.
        """
        from punteo import exportacion, generacion
        from punteo.evidencia import modelo
        victima, _ = self._excluir_una()
        modelo.editar(self.cx, victima["id"],
                      {"descripcion": "CADENA IRREPETIBLE QUE NO PUEDE SALIR ZZQX"})
        generacion.generar(self.cx)
        self.assertNotIn("ZZQX", exportacion.a_texto(self.cx))
        self.assertNotIn(b"ZZQX", exportacion.a_rtf(self.cx))

    def test_excluir_despues_de_generar_frena_la_exportacion(self):
        """
        El agujero más realista: se genera el punteo, alguien excluye una pieza después,
        y media hora más tarde se exporta el archivo que todavía la tiene.

        El texto guardado NO se actualiza solo —sería pisarle la edición a quien lo esté
        corrigiendo— así que la exportación se niega y dice cuál es.
        """
        from punteo import exportacion, generacion
        from punteo.evidencia import modelo
        evs = self.evidencias()
        for e in evs[:5]:
            modelo.decidir(self.cx, e["id"], "incluida")
        generacion.generar(self.cx)
        modelo.decidir(self.cx, evs[2]["id"], "excluida")

        self.assertFalse(generacion.revalidar(self.cx)["al_dia"])
        with self.assertRaises(exportacion.PunteoDesactualizado):
            exportacion.a_texto(self.cx)
        with self.assertRaises(exportacion.PunteoDesactualizado):
            exportacion.a_rtf(self.cx)

    def test_la_segunda_barrera_ataja_si_la_primera_falla(self):
        """
        Se simula que la vista devolvió algo que no debía, y se verifica que el
        generador lo atrape igual. Es la razón por la que la redundancia existe.
        """
        from punteo import generacion
        from punteo.evidencia import modelo
        evs = self.evidencias()
        modelo.decidir(self.cx, evs[0]["id"], "excluida")
        with self.assertRaises(generacion.EvidenciaNoIncluida):
            generacion._verificar_incluida(self.cx, {"id": evs[0]["id"]})

    def test_una_pieza_apagada_tampoco_sale(self):
        """
        `activa = 0` es lo que queda de una división, de una unión o de un descarte. Esa
        fila sigue en la base con su estado anterior, así que si la puerta filtrara sólo
        por estado, una pieza incluida que después se dividió saldría dos veces: entera
        y en mitades.
        """
        from punteo import generacion
        from punteo.evidencia import modelo
        evs = self.evidencias()
        larga = next(e for e in evs if e["pagina_fin"] > e["pagina_inicio"])
        modelo.decidir(self.cx, larga["id"], "incluida")
        modelo.dividir(self.cx, larga["id"], larga["pagina_inicio"] + 1)

        ids = [r["id"] for r in self.cx.execute("SELECT id FROM v_evidencia_incluida")]
        self.assertNotIn(larga["id"], ids)
        # Y las dos mitades tampoco: nacen pendientes, no heredan la decisión.
        mitades = [r["id"] for r in self.cx.execute(
            "SELECT id FROM evidencia WHERE origen='division' AND origen_id=?", (larga["id"],))]
        self.assertEqual(len(mitades), 2)
        for m in mitades:
            self.assertNotIn(m, ids)

    def test_cero_incluidas_no_genera_nada(self):
        """Con nada marcado, el generador se niega. No produce un escrito vacío."""
        from punteo import generacion
        self.assertEqual(self.contadores()["incluidas"], 0)
        with self.assertRaises(generacion.NadaQueGenerar):
            generacion.generar(self.cx)


class LoCorregidoEsLoQueSale(CasoDePrueba):
    """La otra mitad: lo que corrigió una persona tapa lo que detectó la máquina."""

    def test_la_descripcion_corregida(self):
        from punteo import exportacion, generacion
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        detectada = ev["descripcion"]
        modelo.editar(self.cx, ev["id"], {"descripcion": "Descripción corregida a mano WXYZ"})
        modelo.decidir(self.cx, ev["id"], "incluida")
        generacion.generar(self.cx)
        salida = exportacion.a_texto(self.cx)
        self.assertIn("WXYZ", salida)
        self.assertNotIn(detectada, salida)
        # Y lo detectado no se perdió: sigue en su columna.
        self.assertEqual(
            self.cx.execute("SELECT descripcion_detectada FROM evidencia WHERE id=?",
                            (ev["id"],)).fetchone()[0], detectada)

    def test_la_foja_corregida(self):
        from punteo import exportacion, generacion
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        modelo.editar(self.cx, ev["id"], {"foja_inicio": "1201", "foja_fin": "1204"})
        modelo.decidir(self.cx, ev["id"], "incluida")
        generacion.generar(self.cx)
        salida = exportacion.a_texto(self.cx)
        self.assertIn("fs. 1201/1204", salida)
        self.assertNotIn("fs. 400", salida)

    def test_el_testigo_corregido(self):
        from punteo import exportacion, generacion, personas
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        uno = personas.buscar_o_crear(self.cx, "PRIMERO, Testigo")
        personas.asociar(self.cx, ev["id"], uno["id"])
        otro = personas.buscar_o_crear(self.cx, "SEGUNDO, Testigo")
        personas.asociar(self.cx, ev["id"], otro["id"])     # reemplaza al anterior
        modelo.decidir(self.cx, ev["id"], "incluida")
        generacion.generar(self.cx)
        salida = exportacion.a_texto(self.cx)
        self.assertIn("SEGUNDO, Testigo", salida)
        self.assertNotIn("PRIMERO, Testigo", salida)

    def test_volver_a_lo_detectado(self):
        """Vaciar el campo final devuelve lo detectado, no deja la pieza sin descripción."""
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        detectada = ev["descripcion"]
        modelo.editar(self.cx, ev["id"], {"descripcion": "otra cosa"})
        self.assertEqual(modelo.obtener(self.cx, ev["id"])["descripcion"], "otra cosa")
        modelo.editar(self.cx, ev["id"], {"descripcion": ""})
        self.assertEqual(modelo.obtener(self.cx, ev["id"])["descripcion"], detectada)


if __name__ == "__main__":
    unittest.main()
