"""
Que no se pierda el trabajo.

Todo lo demás se regenera reprocesando el legajo. Lo único irreemplazable es lo que
decidió una persona: cada pieza incluida, cada descripción corregida, cada testigo
asignado. Estas pruebas son las que verifican que eso sobreviva a cerrar el navegador,
a reiniciar la máquina y a volver a procesar.
"""
from __future__ import annotations

import unittest

from comun import CasoDePrueba, pdf_de


class CerrarYVolverAAbrir(CasoDePrueba):

    def test_las_decisiones_sobreviven(self):
        from punteo.evidencia import modelo
        evs = self.evidencias()
        modelo.decidir(self.cx, evs[0]["id"], "incluida")
        modelo.decidir(self.cx, evs[1]["id"], "excluida")
        modelo.editar(self.cx, evs[2]["id"], {"descripcion": "Corregida antes de cerrar"})

        self.reabrir()
        self.assertEqual(modelo.obtener(self.cx, evs[0]["id"])["estado"], "incluida")
        self.assertEqual(modelo.obtener(self.cx, evs[1]["id"])["estado"], "excluida")
        self.assertEqual(modelo.obtener(self.cx, evs[2]["id"])["descripcion"],
                         "Corregida antes de cerrar")

    def test_el_punteo_generado_sobrevive(self):
        from punteo import generacion
        from punteo.evidencia import modelo
        modelo.decidir(self.cx, self.evidencias()[0]["id"], "incluida")
        antes = generacion.generar(self.cx)
        self.reabrir()
        despues = generacion.leer(self.cx)
        self.assertEqual(despues["id"], antes["id"])
        self.assertEqual(len(despues["parrafos"]), len(antes["parrafos"]))

    def test_los_grupos_y_el_orden_sobreviven(self):
        from punteo import grupos
        from punteo.evidencia import modelo
        evs = self.evidencias()
        g = grupos.crear(self.cx, "Pericias", encabezado="INFORMES PERICIALES")
        grupos.mover_varias(self.cx, [e["id"] for e in evs[:3]], g["id"])
        modelo.reordenar(self.cx, [e["id"] for e in reversed(evs)])

        self.reabrir()
        lista = grupos.listar(self.cx)
        pericias = next(x for x in lista if x["nombre"] == "Pericias")
        self.assertEqual(pericias["total"], 3)
        self.assertEqual(pericias["encabezado"], "INFORMES PERICIALES")
        orden = [e["id"] for e in self.evidencias(orden="manual")]
        self.assertEqual(orden[0], evs[-1]["id"])

    def test_los_testigos_sobreviven(self):
        from punteo import personas
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        p = personas.buscar_o_crear(self.cx, "ANDRADE, Rubén Osvaldo", rol="policia",
                                    detalle="Sargento 1º, Comisaría Quinta")
        personas.asociar(self.cx, ev["id"], p["id"])
        self.reabrir()
        self.assertEqual(modelo.obtener(self.cx, ev["id"])["testigo"], "ANDRADE, Rubén Osvaldo")


class HistorialApendice(CasoDePrueba):
    """`revision` es append-only: corregir dos veces no borra la primera corrección."""

    def test_cada_cambio_deja_una_fila(self):
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        modelo.editar(self.cx, ev["id"], {"descripcion": "primera"})
        modelo.editar(self.cx, ev["id"], {"descripcion": "segunda"})
        modelo.editar(self.cx, ev["id"], {"descripcion": "tercera"})
        h = [x for x in modelo.historial(self.cx, ev["id"]) if x["campo"] == "descripcion"]
        self.assertEqual([x["valor_nuevo"] for x in h], ["tercera", "segunda", "primera"])
        self.assertEqual(h[-1]["valor_anterior"], ev["descripcion"])

    def test_la_division_queda_registrada_en_las_tres_filas(self):
        from punteo.evidencia import modelo
        ev = next(e for e in self.evidencias() if e["pagina_fin"] > e["pagina_inicio"])
        r = modelo.dividir(self.cx, ev["id"], ev["pagina_inicio"] + 1)
        madre = modelo.historial(self.cx, ev["id"])
        self.assertTrue(any(x["campo"] == "division" for x in madre))
        for hija in r["nuevas"]:
            self.assertTrue(any(f"división de la evidencia {ev['id']}" in (x["detalle"] or "")
                                for x in modelo.historial(self.cx, hija["id"])))

    def test_el_cambio_en_lote_se_distingue_del_individual(self):
        from punteo.evidencia import modelo
        evs = self.evidencias()[:2]
        modelo.decidir(self.cx, evs[0]["id"], "incluida")
        modelo.decidir_varias(self.cx, [evs[1]["id"]], "incluida")
        uno = modelo.historial(self.cx, evs[0]["id"])[0]
        dos = modelo.historial(self.cx, evs[1]["id"])[0]
        self.assertIsNone(uno["detalle"])
        self.assertEqual(dos["detalle"], "cambio en lote")


class ReprocesarNoPisaElTrabajo(CasoDePrueba):

    def test_volver_a_detectar_no_duplica_ni_borra(self):
        from punteo.evidencia import deteccion, modelo
        evs = self.evidencias()
        modelo.decidir(self.cx, evs[0]["id"], "incluida")
        deteccion.detectar(self.cx)
        self.assertEqual(len(self.evidencias()), len(evs))
        self.assertEqual(modelo.obtener(self.cx, evs[0]["id"])["estado"], "incluida")

    def test_un_pdf_agregado_despues_si_se_detecta(self):
        """
        La secuencia normal de trabajo: llega otro cuerpo del legajo, se lo carga y se
        procesa de nuevo. Antes, la detección se salteaba entera porque el caso ya tenía
        evidencia, y las páginas del PDF nuevo quedaban sin una sola pieza propuesta. El
        aviso salía en el resumen del procesamiento, donde nadie lo relaciona con que
        falta media causa.
        """
        from punteo import ingesta, ocr
        from punteo.evidencia import deteccion, modelo
        evs = self.evidencias()
        modelo.decidir(self.cx, evs[0]["id"], "incluida")
        antes = len(evs)

        ingesta.agregar(self.cx, pdf_de([["ACTA DE SECUESTRO", "Hoja 1 de 1"],
                                         ["DECLARACION TESTIMONIAL", "Comparece el testigo"]]),
                        "cuerpo-dos.pdf")
        ocr.leer_caso(self.cx)
        r = deteccion.detectar(self.cx)

        self.assertGreaterEqual(r["creadas"], 2, "el PDF nuevo no recibió propuestas")
        nuevas = [e for e in self.evidencias() if e["pagina_inicio"] > antes]
        self.assertTrue(nuevas)
        # Y lo de antes quedó intacto: misma cantidad de piezas viejas, misma decisión.
        self.assertEqual(len([e for e in self.evidencias() if e["id"] in
                              {x["id"] for x in evs}]), antes)
        self.assertEqual(modelo.obtener(self.cx, evs[0]["id"])["estado"], "incluida")

    def test_rehacer_no_se_lleva_lo_que_alguien_corrigio(self):
        """
        «Rehacer» reemplaza propuestas, no trabajo. Lo que tiene una corrección, un
        testigo, un sector o una decisión se queda donde está, y lo que se apaga queda
        anotado en el historial.
        """
        from punteo import personas
        from punteo.evidencia import deteccion, modelo
        evs = self.evidencias()
        corregida, con_testigo, incluida, intacta = evs[0], evs[1], evs[2], evs[3]
        modelo.editar(self.cx, corregida["id"], {"descripcion": "Descripción a mano QW77"})
        p = personas.buscar_o_crear(self.cx, "TESTIGO, De Prueba")
        personas.asociar(self.cx, con_testigo["id"], p["id"])
        modelo.decidir(self.cx, incluida["id"], "incluida")

        r = deteccion.rehacer(self.cx)

        vivas = {e["id"] for e in self.evidencias()}
        for e in (corregida, con_testigo, incluida):
            self.assertIn(e["id"], vivas, f"rehacer se llevó la pieza {e['id']}")
        self.assertEqual(modelo.obtener(self.cx, corregida["id"])["descripcion"],
                         "Descripción a mano QW77")
        self.assertNotIn(intacta["id"], vivas, "no se reemplazó ninguna propuesta")
        self.assertGreater(r["creadas"], 0, "rehacer apagó propuestas y no creó ninguna")
        self.assertTrue(any(h["campo"] == "rehacer_deteccion"
                            for h in modelo.historial(self.cx, intacta["id"])))
        # Las páginas de la que se reemplazó siguen cubiertas por una propuesta nueva.
        cubiertas = deteccion.paginas_cubiertas(self.cx)
        for pagina in range(intacta["pagina_inicio"], intacta["pagina_fin"] + 1):
            self.assertIn(pagina, cubiertas)

    def test_una_lista_de_propuestas_vieja_no_duplica_piezas(self):
        """
        Dos detecciones a la vez —el trabajador de fondo y alguien apretando «detectar»—
        arman su lista contra la misma foto del caso. La segunda en escribir tiene que
        darse cuenta de que esas páginas ya están cubiertas, o el legajo termina con cada
        pieza dos veces y decisiones contradictorias sobre el mismo material.
        """
        from punteo import ingesta, ocr
        from punteo.evidencia import deteccion
        ingesta.agregar(self.cx, pdf_de([["ACTA DE ALLANAMIENTO", "Hoja 1 de 1"]]), "otro.pdf")
        ocr.leer_caso(self.cx)

        vieja = deteccion.proponer(self.cx)          # la lista de la primera
        self.assertTrue(vieja)
        deteccion.detectar(self.cx)                  # la segunda escribe primero
        cuantas = len(self.evidencias())
        self.assertEqual(deteccion.guardar(self.cx, vieja)["creadas"], 0)
        self.assertEqual(len(self.evidencias()), cuantas)

    def test_un_pdf_intercalado_entre_dos_no_queda_sin_detectar(self):
        """
        Una unión puede abarcar páginas de dos PDF. Al reordenar, su rango se remapea por
        los extremos, así que un PDF cargado en el medio cae adentro del rango sin haber
        sido nunca parte de esa pieza. Si la cobertura se cree ese rango, las páginas del
        PDF nuevo no reciben ni una propuesta y nadie se entera.
        """
        from punteo import ingesta, ocr
        from punteo.evidencia import deteccion, modelo
        paginas_a = self.cx.execute("SELECT COUNT(*) FROM pagina").fetchone()[0]
        ingesta.agregar(self.cx, pdf_de([["ANEXO DE PLANILLAS SIN TITULO"]]), "anexo.pdf")
        ocr.leer_caso(self.cx)
        deteccion.detectar(self.cx)

        del_anexo = next(e for e in self.evidencias() if e["pagina_inicio"] > paginas_a)
        anterior = next(e for e in self.evidencias() if e["pagina_fin"] == paginas_a)
        modelo.unir(self.cx, [anterior["id"], del_anexo["id"]])

        ingesta.agregar(self.cx, pdf_de([["ACTA DE SECUESTRO", "Hoja 1 de 1"]]), "intercalado.pdf")
        ocr.leer_caso(self.cx)
        docs = {d["nombre_archivo"]: d["id"] for d in ingesta.documentos(self.cx)}
        ingesta.reordenar(self.cx, [docs["legajo.pdf"], docs["intercalado.pdf"],
                                    docs["anexo.pdf"]])
        pagina_nueva = self.cx.execute(
            """SELECT numero_global FROM pagina WHERE documento_id=?""",
            (docs["intercalado.pdf"],)).fetchone()["numero_global"]

        deteccion.detectar(self.cx)
        cubre = [e for e in self.evidencias()
                 if e["pagina_inicio"] <= pagina_nueva <= e["pagina_fin"]
                 and e["documento_id"] == docs["intercalado.pdf"]]
        self.assertTrue(cubre, "el PDF intercalado quedó sin ninguna pieza propuesta")

    def test_una_decision_no_se_guarda_sobre_una_pieza_recien_apagada(self):
        """
        Dos pestañas: en una se decide una pieza mientras en la otra la redetección la
        reemplaza. Entre leer la pieza y escribir la decisión hay una ventana, y escribir
        ahí dentro deja la decisión en una fila que ya no está en la lista: la pantalla
        dice «guardado» y al escrito no llega nada.
        """
        from unittest import mock

        from punteo import casos
        from punteo.evidencia import modelo
        ev = self.evidencias()[0]
        otra = casos.abrir(self.caso.slug)
        self.addCleanup(otra.close)

        original = modelo._fila

        def apagar_en_el_medio(cx, eid):
            fila = original(cx, eid)
            otra.execute("UPDATE evidencia SET activa=0 WHERE id=?", (eid,))
            otra.commit()
            return fila

        with mock.patch.object(modelo, "_fila", apagar_en_el_medio):
            with self.assertRaises(modelo.OperacionInvalida):
                modelo.decidir(self.cx, ev["id"], "incluida")
        estado = self.cx.execute("SELECT estado FROM evidencia WHERE id=?",
                                 (ev["id"],)).fetchone()["estado"]
        self.assertEqual(estado, "pendiente")

    def test_una_union_deshecha_no_tapa_a_la_pieza_del_medio(self):
        """
        Unir la primera con la tercera y deshacer deja una fila apagada cuyo rango pasa
        por encima de la segunda. Si esa fila cuenta como cobertura, la segunda pieza
        desaparece de la lista al redetectar y nadie se entera.
        """
        from punteo.evidencia import deteccion, modelo
        a, b, c = self.evidencias()[:3]
        union = modelo.unir(self.cx, [a["id"], c["id"]])
        modelo.deshacer(self.cx, union["id"])

        deteccion.rehacer(self.cx)
        cubren_b = [e for e in self.evidencias()
                    if e["pagina_inicio"] <= b["pagina_inicio"] <= e["pagina_fin"]]
        self.assertTrue(cubren_b, "la pieza del medio quedó sin ninguna propuesta")

    def test_descartar_una_union_de_dos_pdf_no_devuelve_las_paginas_del_segundo(self):
        """
        La unión cubre sólo las páginas de su documento. Si además se descarta, sus
        partes tienen que seguir contando: si no, la siguiente detección vuelve a
        proponer como nuevas las páginas del segundo PDF que alguien ya descartó.
        """
        from punteo import ingesta, ocr
        from punteo.evidencia import deteccion, modelo
        paginas_a = self.cx.execute("SELECT COUNT(*) FROM pagina").fetchone()[0]
        ingesta.agregar(self.cx, pdf_de([["ANEXO DE PLANILLAS SIN TITULO"]]), "anexo.pdf")
        ocr.leer_caso(self.cx)
        deteccion.detectar(self.cx)
        anexo = next(e for e in self.evidencias() if e["pagina_inicio"] > paginas_a)
        anterior = next(e for e in self.evidencias() if e["pagina_fin"] == paginas_a)
        union = modelo.unir(self.cx, [anterior["id"], anexo["id"]])
        modelo.descartar(self.cx, union["id"])
        antes = len(self.evidencias())

        r = deteccion.detectar(self.cx)
        self.assertEqual(r["creadas"], 0, "volvieron páginas que se habían descartado")
        self.assertEqual(len(self.evidencias()), antes)

    def test_rehacer_respeta_el_orden_elegido_a_mano(self):
        """Elegir el orden del escrito es trabajo, aunque la pieza siga pendiente."""
        from punteo.evidencia import deteccion, modelo
        evs = self.evidencias()
        modelo.reordenar(self.cx, [e["id"] for e in reversed(evs)])
        deteccion.rehacer(self.cx)
        vivas = {e["id"] for e in self.evidencias()}
        for e in evs:
            self.assertIn(e["id"], vivas, "rehacer se llevó una pieza reordenada a mano")

    def test_volver_a_foliar_no_pisa_lo_confirmado(self):
        from punteo import foliatura
        foliatura.fijar(self.cx, 1, "901")
        foliatura.confirmar_tramo(self.cx, 2, 5)
        foliatura.detectar(self.cx)
        fila = self.cx.execute(
            "SELECT foja_etiqueta, foja_origen FROM pagina WHERE numero_global=1").fetchone()
        self.assertEqual(fila["foja_etiqueta"], "901")
        self.assertEqual(fila["foja_origen"], "manual")
        confirmadas = self.cx.execute(
            "SELECT COUNT(*) FROM pagina WHERE foja_origen='confirmada'").fetchone()[0]
        self.assertEqual(confirmadas, 4)

    def test_volver_a_leer_no_relee_lo_leido(self):
        from punteo import ocr
        r = ocr.leer_caso(self.cx)
        self.assertEqual(r["paginas"], 0, "volvió a leer páginas que ya tenían texto")


class MigracionDeEsquema(CasoDePrueba):
    """
    Migrar una base con trabajo adentro es la operación más peligrosa del sistema: si
    sale mal, se lleva lo único que no se regenera.
    """

    def test_una_base_mas_nueva_no_se_abre_a_la_fuerza(self):
        """
        Abrir con un programa viejo una base que escribió uno nuevo le sacaba las
        garantías que el nuevo agregó —y le bajaba el número de versión— sin decir nada.
        """
        from punteo import casos, db
        self.cx.execute(f"PRAGMA user_version={db.ESQUEMA_VERSION + 5}")
        self.cx.commit()
        self.cx.close()
        with self.assertRaises(db.BaseMasNueva):
            casos.abrir(self.caso.slug)
        # Y no la tocó: la versión sigue donde estaba.
        from punteo import config
        cx = db.conectar(config.carpeta_caso(self.caso.slug) / "punteo.sqlite")
        try:
            self.assertEqual(cx.execute("PRAGMA user_version").fetchone()[0],
                             db.ESQUEMA_VERSION + 5)
            cx.execute(f"PRAGMA user_version={db.ESQUEMA_VERSION}")
            cx.commit()
        finally:
            cx.close()
        self.cx = casos.abrir(self.caso.slug)       # para el cleanup de la clase base

    def test_una_foja_heredada_no_pasa_por_leida(self):
        """
        En una base anterior a `foja_lectura` no se sabe si el número se leyó o se
        dedujo. La migración lo dice —`desconocida`— en lugar de dejar un NULL que la
        pantalla lee como «todo en orden».
        """
        from punteo import casos
        self.cx.execute("DROP VIEW IF EXISTS v_evidencia_incluida")
        self.cx.execute("DROP VIEW IF EXISTS v_contadores")
        self.cx.execute("DROP VIEW IF EXISTS v_evidencia")
        try:
            self.cx.execute("ALTER TABLE pagina DROP COLUMN foja_lectura")
        except Exception as e:                       # SQLite viejo: no se puede probar acá
            self.skipTest(f"esta versión de SQLite no puede sacar la columna: {e}")
        self.cx.execute("PRAGMA user_version=1")
        self.cx.commit()
        self.cx.close()

        self.cx = casos.abrir(self.caso.slug)        # acá corre la migración
        heredadas = self.cx.execute(
            """SELECT COUNT(*) FROM pagina
                WHERE foja_origen='detectada' AND foja_lectura IS NOT 'desconocida'"""
        ).fetchone()[0]
        self.assertEqual(heredadas, 0)
        self.assertTrue(self.evidencias()[0]["foja_interpolada"],
                        "una foja de procedencia desconocida pasó por leída")


class ReordenarDocumentos(CasoDePrueba):
    """
    Reordenar los PDF corre la numeración global debajo de la evidencia ya cargada.
    Es una de las formas más fáciles de perder el trabajo sin que se note.
    """

    def test_las_piezas_siguen_apuntando_a_sus_paginas(self):
        from punteo import ingesta
        from punteo.evidencia import modelo
        ingesta.agregar(self.cx, self.legajo["con_texto"].read_bytes(), "otro.pdf")
        docs = ingesta.documentos(self.cx)
        if len(docs) < 2:
            self.skipTest("el segundo PDF entró como copia exacta del primero")

        ev = self.evidencias()[0]
        texto_antes = ev["texto_origen"][:60]
        ingesta.reordenar(self.cx, [docs[1]["id"], docs[0]["id"]])
        despues = modelo.obtener(self.cx, ev["id"])
        pagina = self.cx.execute("SELECT texto FROM pagina WHERE numero_global=?",
                                 (despues["pagina_inicio"],)).fetchone()
        self.assertIn(texto_antes.split()[0], pagina["texto"])


if __name__ == "__main__":
    unittest.main()
