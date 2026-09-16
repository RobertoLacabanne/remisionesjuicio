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


class LoExcluidoNoVuelvePorOtraPuerta(CasoDePrueba):
    """
    Unir y dividir arman piezas NUEVAS con el texto de las viejas.

    Es el camino por el que una excluida vuelve al escrito sin dejar de estar excluida:
    la unión copia la descripción de su primera parte y la división la de su origen, y la
    pieza nueva nace pendiente, con su propio número y sin nada que la ate a la decisión
    anterior. El control por estado de la pieza no lo ve, porque el estado de la pieza
    nueva es legítimo.
    """

    def _excluida_con_marca(self):
        from punteo.evidencia import modelo
        evs = self.evidencias()
        victima = evs[0]
        modelo.editar(self.cx, victima["id"], {"descripcion": "CADENA EXCLUIDA ZZUN"})
        modelo.decidir(self.cx, victima["id"], "excluida")
        return victima, evs

    def test_no_se_une_una_pieza_excluida(self):
        from punteo.evidencia import modelo
        victima, evs = self._excluida_con_marca()
        with self.assertRaises(modelo.OperacionInvalida):
            modelo.unir(self.cx, [victima["id"], evs[1]["id"]])
        # Y las piezas quedaron como estaban: el rechazo no apagó nada.
        self.assertTrue(modelo.obtener(self.cx, victima["id"])["activa"])
        self.assertTrue(modelo.obtener(self.cx, evs[1]["id"])["activa"])

    def test_no_se_divide_una_pieza_excluida(self):
        from punteo.evidencia import modelo
        evs = self.evidencias()
        larga = next(e for e in evs if e["pagina_fin"] > e["pagina_inicio"])
        modelo.decidir(self.cx, larga["id"], "excluida")
        with self.assertRaises(modelo.OperacionInvalida):
            modelo.dividir(self.cx, larga["id"], larga["pagina_inicio"] + 1)

    def test_una_union_que_ya_traia_una_excluida_no_se_puede_incluir(self):
        """
        El caso de una base armada antes de que unir controlara esto: la unión ya existe
        y su parte quedó excluida. Incluirla tiene que fallar igual.
        """
        from punteo.evidencia import modelo
        evs = self.evidencias()
        union = modelo.unir(self.cx, [evs[0]["id"], evs[1]["id"]])
        self.cx.execute("UPDATE evidencia SET estado='excluida' WHERE id=?", (evs[0]["id"],))
        self.cx.commit()
        with self.assertRaises(modelo.OperacionInvalida):
            modelo.decidir(self.cx, union["id"], "incluida")
        with self.assertRaises(modelo.OperacionInvalida):
            modelo.decidir_varias(self.cx, [union["id"]], "incluida")

    def _union_con_parte_excluida(self):
        """Una unión incluida cuya parte quedó excluida, escrito a mano en la base."""
        from punteo.evidencia import modelo
        victima, evs = self._excluida_con_marca()
        modelo.decidir(self.cx, victima["id"], "pendiente")
        union = modelo.unir(self.cx, [victima["id"], evs[1]["id"]])
        modelo.decidir(self.cx, union["id"], "incluida")
        return victima, union

    def test_la_segunda_barrera_ataja_la_union_con_parte_excluida(self):
        """
        Se saltea la decisión escribiendo el estado a mano, que es lo que deja una base
        armada antes de esta regla, y el generador tiene que cortar igual.
        """
        from punteo import generacion
        victima, _ = self._union_con_parte_excluida()
        self.cx.execute("UPDATE evidencia SET estado='excluida' WHERE id=?", (victima["id"],))
        self.cx.commit()
        with self.assertRaises(generacion.EvidenciaNoIncluida):
            generacion.generar(self.cx)

    def test_excluir_una_parte_despues_de_generar_frena_la_exportacion(self):
        from punteo import exportacion, generacion
        victima, _ = self._union_con_parte_excluida()
        generacion.generar(self.cx)
        self.assertIn("ZZUN", exportacion.a_texto(self.cx))   # antes de excluir, sale

        self.cx.execute("UPDATE evidencia SET estado='excluida' WHERE id=?", (victima["id"],))
        self.cx.commit()
        self.assertFalse(generacion.revalidar(self.cx)["al_dia"])
        with self.assertRaises(exportacion.PunteoDesactualizado):
            exportacion.a_texto(self.cx)

    def test_restaurar_no_revive_una_parte_absorbida(self):
        """
        `activa = 0` también es lo que deja una unión. Encender esa fila por el camino de
        «restaurar» ponía la misma prueba dos veces —la parte y la unión que la
        contiene— con la decisión vieja de la parte.
        """
        from punteo.evidencia import modelo
        evs = self.evidencias()
        modelo.unir(self.cx, [evs[0]["id"], evs[1]["id"]])
        with self.assertRaises(modelo.OperacionInvalida):
            modelo.restaurar(self.cx, evs[0]["id"])
        self.assertFalse(modelo.obtener(self.cx, evs[0]["id"])["activa"])

    def test_restaurar_no_revive_una_parte_de_una_union_anidada(self):
        """
        La unión que absorbió a la parte puede estar apagada ella misma, absorbida por
        otra: mirar sólo la unión directa deja pasar la cadena larga, y la parte vuelve
        con su decisión vieja mientras la unión de arriba sigue en el escrito.
        """
        from punteo.evidencia import modelo
        evs = self.evidencias()
        u = modelo.unir(self.cx, [evs[0]["id"], evs[1]["id"]])
        modelo.unir(self.cx, [u["id"], evs[2]["id"]])
        with self.assertRaises(modelo.OperacionInvalida):
            modelo.restaurar(self.cx, evs[0]["id"])
        self.assertFalse(modelo.obtener(self.cx, evs[0]["id"])["activa"])

    def test_no_se_deshace_una_union_que_ya_fue_absorbida(self):
        from punteo.evidencia import modelo
        evs = self.evidencias()
        u = modelo.unir(self.cx, [evs[0]["id"], evs[1]["id"]])
        v = modelo.unir(self.cx, [u["id"], evs[2]["id"]])
        with self.assertRaises(modelo.OperacionInvalida):
            modelo.deshacer(self.cx, u["id"])
        self.assertTrue(modelo.obtener(self.cx, v["id"])["activa"])
        # Deshaciendo desde arriba sí se puede, que es el orden que corresponde.
        modelo.deshacer(self.cx, v["id"])
        self.assertTrue(modelo.obtener(self.cx, u["id"])["activa"])

    def test_restaurar_no_revive_una_pieza_ya_dividida(self):
        from punteo.evidencia import modelo
        larga = next(e for e in self.evidencias() if e["pagina_fin"] > e["pagina_inicio"])
        modelo.dividir(self.cx, larga["id"], larga["pagina_inicio"] + 1)
        with self.assertRaises(modelo.OperacionInvalida):
            modelo.restaurar(self.cx, larga["id"])

    def test_restaurar_sigue_devolviendo_lo_descartado(self):
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        modelo.descartar(self.cx, ev["id"])
        self.assertTrue(modelo.restaurar(self.cx, ev["id"])["activa"])


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
