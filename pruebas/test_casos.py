"""
Casos: alta, listado, separación entre causas y borrado.

La separación por archivo es la que convierte «ningún cálculo cruza casos» en un hecho
físico. Acá se verifica que sea real y no una promesa de la capa de consultas.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


class Casos(unittest.TestCase):

    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp(prefix="punteo-casos-"))
        from punteo import config
        self._antes = config.DATOS
        config.DATOS = self.carpeta
        self.addCleanup(lambda: setattr(config, "DATOS", self._antes))
        self.addCleanup(shutil.rmtree, self.carpeta, True)

    def crear(self, legajo="OGA-1/2026", caratula="NN s/ Peculado", tipo="remision"):
        from punteo import casos
        return casos.crear(legajo, caratula, tipo)

    def test_alta_y_lectura(self):
        c = self.crear()
        self.assertEqual(c.numero_legajo, "OGA-1/2026")
        self.assertEqual(c.tipo_proceso, "remision")
        self.assertEqual(c.como_dict()["tipo_etiqueta"], "Remisión a juicio")

    def test_falta_el_legajo_o_la_caratula(self):
        from punteo import casos
        for legajo, caratula in (("", "algo"), ("OGA-1/2026", "  ")):
            with self.assertRaises(casos.CasoInvalido):
                casos.crear(legajo, caratula, "remision")

    def test_tipo_de_proceso_desconocido(self):
        from punteo import casos
        with self.assertRaises(casos.CasoInvalido):
            casos.crear("OGA-1/2026", "NN", "ordinario")

    def test_dos_legajos_iguales_no_se_pisan(self):
        a = self.crear()
        b = self.crear()
        self.assertNotEqual(a.slug, b.slug)
        from punteo import casos
        self.assertEqual(len(casos.listar()), 2)

    def test_un_slug_con_puntos_suspensivos_no_lee_otro_disco(self):
        """
        El slug es un nombre de carpeta y llega por la URL. Sin validarlo, `../` alcanza
        para abrir una base de cualquier lado del sistema de archivos.
        """
        from punteo import casos
        for malo in ("../../etc", "..", "/etc/passwd", "CASO", "con espacio", ""):
            with self.assertRaises(casos.CasoNoEncontrado, msg=malo):
                casos.leer(malo)
            with self.assertRaises(casos.CasoNoEncontrado, msg=malo):
                casos.abrir(malo)

    def test_los_datos_de_un_caso_no_estan_en_la_base_del_otro(self):
        from punteo import casos
        from punteo.evidencia import modelo
        a, b = self.crear("OGA-A/2026", "Causa A"), self.crear("OGA-B/2026", "Causa B")

        cx = casos.abrir(a.slug)
        modelo.crear_manual(cx, pagina_inicio=1, descripcion="Pieza de la causa A",
                            estado="incluida")
        cx.close()

        cx = casos.abrir(b.slug)
        try:
            self.assertEqual(len(modelo.listar(cx)["evidencias"]), 0)
            self.assertEqual(modelo.contadores(cx)["incluidas"], 0)
        finally:
            cx.close()

    def test_cada_caso_tiene_su_archivo(self):
        from punteo import config
        a, b = self.crear("OGA-A/2026", "Causa A"), self.crear("OGA-B/2026", "Causa B")
        ra = config.carpeta_caso(a.slug) / "punteo.sqlite"
        rb = config.carpeta_caso(b.slug) / "punteo.sqlite"
        self.assertTrue(ra.exists() and rb.exists())
        self.assertNotEqual(ra, rb)

    def test_dos_hilos_trabajan_en_casos_distintos_sin_pisarse(self):
        """
        El caso activo vive por hilo. Con una variable global, abrir un caso en una
        pestaña le cambiaría el caso al procesamiento que corre en otra.
        """
        from punteo import casos, config
        a, b = self.crear("OGA-A/2026", "Causa A"), self.crear("OGA-B/2026", "Causa B")
        visto = {}

        def trabajar(slug, clave):
            cx = casos.abrir(slug)
            try:
                visto[clave] = (config.caso_activo(), Path(config.BASE).parent.name)
            finally:
                cx.close()

        hilos = [threading.Thread(target=trabajar, args=(a.slug, "a")),
                 threading.Thread(target=trabajar, args=(b.slug, "b"))]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(visto["a"], (a.slug, a.slug))
        self.assertEqual(visto["b"], (b.slug, b.slug))

    def test_sin_caso_abierto_la_base_da_error_y_no_una_carpeta_suelta(self):
        """
        Caer en una carpeta por omisión «por las dudas» es cómo la evidencia de una
        causa termina escrita en la carpeta de otra.
        """
        from punteo import config
        config.activar_caso(None)
        config.fijar_caso_por_omision(None)
        with self.assertRaises(config.SinCasoAbierto):
            _ = config.BASE

    def test_borrar_se_lleva_todo(self):
        from punteo import casos, config
        c = self.crear()
        casos.borrar(c.slug)
        self.assertFalse(config.carpeta_caso(c.slug).exists())
        with self.assertRaises(casos.CasoNoEncontrado):
            casos.leer(c.slug)

    def test_actualizar_el_tipo_de_proceso(self):
        from punteo import casos
        c = self.crear()
        r = casos.actualizar(c.slug, tipo_proceso="abreviado", caratula="Otra carátula")
        self.assertEqual(r.tipo_proceso, "abreviado")
        self.assertEqual(r.caratula, "Otra carátula")
        self.assertIsNotNone(r.actualizado_en)

    def test_la_tabla_caso_es_de_una_fila(self):
        import sqlite3

        from punteo import casos, db
        c = self.crear()
        cx = casos.abrir(c.slug)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                cx.execute("""INSERT INTO caso (id, numero_legajo, caratula, tipo_proceso,
                                                creado_en) VALUES (2,'X','Y','remision',?)""",
                           (db.ahora(),))
        finally:
            cx.close()


class Ingesta(unittest.TestCase):

    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp(prefix="punteo-ingesta-"))
        from punteo import config
        self._antes = config.DATOS
        config.DATOS = self.carpeta
        self.addCleanup(lambda: setattr(config, "DATOS", self._antes))
        self.addCleanup(shutil.rmtree, self.carpeta, True)

        sys.path.insert(0, str(RAIZ / "herramientas"))
        import generar_legajo
        self.legajo = generar_legajo.generar(self.carpeta / "pdf", fojas_desde=100)

        from punteo import casos
        self.caso = casos.crear("OGA-9/2026", "NN s/ Prueba", "remision")
        self.cx = casos.abrir(self.caso.slug)
        self.addCleanup(self.cx.close)

    def test_el_original_queda_de_solo_lectura(self):
        from punteo import ingesta
        r = ingesta.agregar(self.cx, self.legajo["con_texto"].read_bytes(), "legajo.pdf")
        ruta = Path(self.cx.execute("SELECT ruta FROM documento WHERE id=?",
                                    (r.documento_id,)).fetchone()["ruta"])
        self.assertTrue(ruta.exists())
        self.assertEqual(oct(ruta.stat().st_mode)[-3:], "444")

    def test_el_hash_verifica_el_original(self):
        from punteo import almacen, ingesta
        ingesta.agregar(self.cx, self.legajo["con_texto"].read_bytes(), "legajo.pdf")
        sha = self.cx.execute("SELECT sha256 FROM documento").fetchone()["sha256"]
        ok, detalle = almacen.verificar(sha)
        self.assertTrue(ok, detalle)

    def test_la_misma_copia_no_se_procesa_dos_veces(self):
        from punteo import ingesta
        datos = self.legajo["con_texto"].read_bytes()
        a = ingesta.agregar(self.cx, datos, "legajo.pdf")
        b = ingesta.agregar(self.cx, datos, "copia-del-juzgado.pdf")
        self.assertFalse(a.duplicado)
        self.assertTrue(b.duplicado)
        self.assertEqual(a.documento_id, b.documento_id)
        self.assertEqual(self.cx.execute("SELECT COUNT(*) FROM documento").fetchone()[0], 1)
        # Pero queda constancia de que llegó de nuevo: no se pierde el dato.
        self.assertEqual(
            self.cx.execute("SELECT COUNT(*) FROM documento_duplicado").fetchone()[0], 1)

    def test_lo_que_no_es_pdf_se_rechaza_con_el_motivo(self):
        from punteo import ingesta
        r = ingesta.agregar(self.cx, b"esto no es un pdf", "trampa.pdf")
        self.assertIsNotNone(r.error)
        self.assertIn("%PDF", r.error)
        self.assertEqual(self.cx.execute("SELECT COUNT(*) FROM excepcion").fetchone()[0], 1)

    def test_un_archivo_vacio_no_voltea_nada(self):
        from punteo import ingesta
        r = ingesta.agregar(self.cx, b"", "vacio.pdf")
        self.assertIsNotNone(r.error)

    def test_la_numeracion_global_encadena_los_pdf(self):
        from punteo import ingesta
        a = ingesta.agregar(self.cx, self.legajo["con_texto"].read_bytes(), "primero.pdf")
        b = ingesta.agregar(self.cx, self.legajo["escaneado"].read_bytes(), "segundo.pdf")
        globales = [r["numero_global"] for r in self.cx.execute(
            "SELECT numero_global FROM pagina ORDER BY numero_global")]
        self.assertEqual(globales, list(range(1, a.paginas + b.paginas + 1)))
        # Y la página 1 del segundo PDF NO es la página global 1.
        primera_del_segundo = self.cx.execute(
            """SELECT numero_global FROM pagina
                WHERE documento_id=? AND numero_pdf=1""", (b.documento_id,)).fetchone()
        self.assertEqual(primera_del_segundo["numero_global"], a.paginas + 1)


if __name__ == "__main__":
    unittest.main()
