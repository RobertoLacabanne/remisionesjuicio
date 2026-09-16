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
        # Y no quedó un punteo a medio escribir: cortar en la mitad del armado deshace
        # todo, porque un punteo con la mitad de las piezas es peor que ninguno.
        self.assertEqual(
            self.cx.execute("SELECT COUNT(*) FROM punteo_generado").fetchone()[0], 0)

    def test_nadie_puede_excluir_en_el_medio_del_armado(self):
        """
        La segunda barrera controla y después se escribe. Si entre las dos cosas otra
        pestaña puede excluir una pieza, el control ya no dice nada de lo que se guarda.
        Mientras se arma el punteo, cualquier otra escritura tiene que esperar.
        """
        import sqlite3
        from unittest import mock

        from punteo import casos, generacion
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        modelo.decidir(self.cx, ev["id"], "incluida")
        otra = casos.abrir(self.caso.slug)
        self.addCleanup(otra.close)
        otra.execute("PRAGMA busy_timeout = 0")

        original = generacion._escribir
        intentos = []

        def excluir_en_el_medio(cx, parrafos, ajustes):
            try:
                otra.execute("UPDATE evidencia SET estado='excluida' WHERE id=?", (ev["id"],))
                otra.commit()
                intentos.append("pasó")
            except sqlite3.OperationalError:
                otra.rollback()
                intentos.append("esperó")
            return original(cx, parrafos, ajustes)

        with mock.patch.object(generacion, "_escribir", excluir_en_el_medio):
            generacion.generar(self.cx)
        self.assertEqual(intentos, ["esperó"],
                         "otra conexión pudo escribir en el medio del armado")

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


class CorregirDespuesDeGenerar(CasoDePrueba):
    """
    El punteo se guarda como texto. Todo lo que se corrija después queda afuera de ese
    texto, y el archivo sale con el dato viejo y con cara de estar al día: es la misma
    falla que excluir una pieza después de generar, por los otros campos.
    """

    def _generar_con(self, cuantas=3):
        from punteo import generacion
        from punteo.evidencia import modelo
        evs = self.evidencias()[:cuantas]
        for e in evs:
            modelo.decidir(self.cx, e["id"], "incluida")
        generacion.generar(self.cx)
        return evs

    def test_corregir_la_descripcion_frena_la_exportacion(self):
        from punteo import exportacion, generacion
        from punteo.evidencia import modelo
        evs = self._generar_con()
        modelo.editar(self.cx, evs[0]["id"], {"descripcion": "Descripción corregida PP42"})

        estado = generacion.revalidar(self.cx)
        self.assertFalse(estado["al_dia"])
        self.assertTrue(estado["cambiados"])
        with self.assertRaises(exportacion.PunteoDesactualizado):
            exportacion.a_texto(self.cx)
        # Y al regenerar, sale el dato corregido.
        generacion.generar(self.cx)
        self.assertIn("PP42", exportacion.a_texto(self.cx))

    def test_confirmar_la_foja_despues_de_generar_tambien_cuenta(self):
        from punteo import exportacion, foliatura, generacion
        evs = self._generar_con(1)
        self.assertIn(generacion.FOJA_A_CONFIRMAR, exportacion.a_texto(self.cx))
        foliatura.confirmar_tramo(self.cx, evs[0]["pagina_inicio"], evs[0]["pagina_fin"])
        with self.assertRaises(exportacion.PunteoDesactualizado):
            exportacion.a_texto(self.cx)
        generacion.generar(self.cx)
        self.assertNotIn(generacion.FOJA_A_CONFIRMAR, exportacion.a_texto(self.cx))

    def test_asignar_un_testigo_despues_de_generar_tambien_cuenta(self):
        from punteo import exportacion, generacion, personas
        evs = self._generar_con(1)
        p = personas.buscar_o_crear(self.cx, "NUEVO, Testigo")
        personas.asociar(self.cx, evs[0]["id"], p["id"])
        with self.assertRaises(exportacion.PunteoDesactualizado):
            exportacion.a_texto(self.cx)

    def test_reordenar_despues_de_generar_tambien_cuenta(self):
        from punteo import exportacion, generacion
        from punteo.evidencia import modelo
        evs = self._generar_con()
        modelo.reordenar(self.cx, [e["id"] for e in reversed(evs)])
        self.assertTrue(generacion.revalidar(self.cx)["reordenado"])
        with self.assertRaises(exportacion.PunteoDesactualizado):
            exportacion.a_texto(self.cx)

    def test_incluir_otra_pieza_despues_de_generar_frena_la_exportacion(self):
        """
        El escrito saldría sin una prueba que la persona decidió ofrecer. Es lo mismo que
        exportar de más, pero al revés, y se nota menos.
        """
        from punteo import exportacion, generacion
        from punteo.evidencia import modelo
        self._generar_con(2)
        modelo.decidir(self.cx, self.evidencias()[5]["id"], "incluida")
        estado = generacion.revalidar(self.cx)
        self.assertFalse(estado["al_dia"])
        self.assertEqual(estado["incluidas_nuevas"], 1)
        with self.assertRaises(exportacion.PunteoDesactualizado):
            exportacion.a_texto(self.cx)

    def test_cambiar_el_tipo_de_proceso_frena_la_exportacion(self):
        """
        En abreviado la frase no lleva testigo introductor y en remisión sí. Cambiar el
        tipo de proceso después de generar deja un escrito redactado para el otro.
        """
        from punteo import casos, exportacion, generacion
        casos.actualizar(self.caso.slug, tipo_proceso="abreviado")
        self.reabrir()
        self._generar_con(1)
        self.assertNotIn("introducida al debate", exportacion.a_texto(self.cx))

        casos.actualizar(self.caso.slug, tipo_proceso="remision")
        self.reabrir()
        self.assertFalse(generacion.revalidar(self.cx)["al_dia"])
        with self.assertRaises(exportacion.PunteoDesactualizado):
            exportacion.a_texto(self.cx)
        generacion.generar(self.cx)
        self.assertIn("introducida al debate", exportacion.a_texto(self.cx))

    def test_la_edicion_de_un_encabezado_vuelve_a_su_propio_sector(self):
        """
        Dos sectores pueden tener el mismo encabezado. Los encabezados no tienen pieza,
        así que sin la clave del sector la edición del segundo se pegaba en el primero.
        """
        from punteo import generacion, grupos
        from punteo.evidencia import modelo
        evs = self.evidencias()[:4]
        for e in evs:
            modelo.decidir(self.cx, e["id"], "incluida")
        a = grupos.crear(self.cx, "Sector A", encabezado="DOCUMENTAL")
        b = grupos.crear(self.cx, "Sector B", encabezado="DOCUMENTAL")
        grupos.mover_varias(self.cx, [evs[0]["id"], evs[1]["id"]], a["id"])
        grupos.mover_varias(self.cx, [evs[2]["id"], evs[3]["id"]], b["id"])

        punteo = generacion.generar(self.cx, criterio="grupos")
        encabezados = [p for p in punteo["parrafos"] if p["clase"] == "encabezado"]
        self.assertEqual(len(encabezados), 2)
        generacion.editar_parrafo(self.cx, encabezados[1]["id"], "SOLO EL SECTOR B")

        nuevo = generacion.generar(self.cx, criterio="grupos")
        textos = [p["texto"] for p in nuevo["parrafos"] if p["clase"] == "encabezado"]
        self.assertEqual(textos, ["DOCUMENTAL", "SOLO EL SECTOR B"])

    def test_un_punteo_intacto_se_exporta(self):
        from punteo import exportacion, generacion
        self._generar_con()
        self.assertTrue(generacion.revalidar(self.cx)["al_dia"])
        self.assertIn("PRUEBA OFRECIDA", exportacion.a_texto(self.cx))

    def test_la_edicion_a_mano_sobrevive_si_su_pieza_no_cambio(self):
        """
        Regenerar no puede costar el texto que alguien escribió. Si la pieza no cambió en
        nada que salga al escrito, su párrafo editado se traslada al punteo nuevo.
        """
        from punteo import exportacion, generacion
        from punteo.evidencia import modelo
        evs = self._generar_con()
        punteo = generacion.leer(self.cx)
        parrafo = next(x for x in punteo["parrafos"]
                       if x["evidencia_id"] == evs[1]["id"])
        generacion.editar_parrafo(self.cx, parrafo["id"], "Redacción propia MM55")
        modelo.editar(self.cx, evs[0]["id"], {"descripcion": "Otra descripción"})

        nuevo = generacion.generar(self.cx)
        self.assertEqual(nuevo["ediciones_trasladadas"], 1)
        self.assertEqual(nuevo["ediciones_no_trasladadas"], 0)
        self.assertIn("MM55", exportacion.a_texto(self.cx))

    def test_la_edicion_de_una_pieza_que_cambio_no_se_arrastra(self):
        """
        Al revés: si la pieza cambió, arrastrar la edición sería volver a escribir el
        dato viejo arriba del corregido. Se avisa cuántas quedaron atrás, y el punteo
        anterior sigue entero en la base.
        """
        from punteo import generacion
        from punteo.evidencia import modelo
        evs = self._generar_con()
        punteo = generacion.leer(self.cx)
        parrafo = next(x for x in punteo["parrafos"] if x["evidencia_id"] == evs[0]["id"])
        generacion.editar_parrafo(self.cx, parrafo["id"], "Redacción vieja con la foja de antes")
        modelo.editar(self.cx, evs[0]["id"], {"descripcion": "Descripción corregida"})

        nuevo = generacion.generar(self.cx)
        self.assertEqual(nuevo["ediciones_no_trasladadas"], 1)
        self.assertIn("Descripción corregida",
                      " ".join(x["texto"] for x in nuevo["parrafos"]))
        viejo = generacion.leer(self.cx, punteo["id"])
        self.assertIn("Redacción vieja",
                      " ".join(x["texto"] for x in viejo["parrafos"]))


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
