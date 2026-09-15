"""
Que no se pierda el trabajo.

Todo lo demás se regenera reprocesando el legajo. Lo único irreemplazable es lo que
decidió una persona: cada pieza incluida, cada descripción corregida, cada testigo
asignado. Estas pruebas son las que verifican que eso sobreviva a cerrar el navegador,
a reiniciar la máquina y a volver a procesar.
"""
from __future__ import annotations

import unittest

from comun import CasoDePrueba


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
