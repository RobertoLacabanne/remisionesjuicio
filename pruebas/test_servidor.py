"""
El servidor, de punta a punta.

Lo que se prueba acá no es que las rutas contesten —eso ya lo cubren las pruebas de cada
módulo— sino lo que sólo se ve del lado HTTP: qué imagen devuelve el visor después de
reordenar los PDF, y qué pedidos pueden cambiar el legajo.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from comun import pdf_de  # noqa: E402


class ConServidor(unittest.TestCase):
    """Un servidor de verdad, en loopback y sin clave, con un caso chico adentro."""

    @classmethod
    def setUpClass(cls):
        from punteo import acceso, casos, config, ingesta, ocr, servidor
        cls.carpeta = Path(tempfile.mkdtemp(prefix="punteo-servidor-"))
        cls._datos = config.DATOS
        config.DATOS = cls.carpeta / "datos"

        cls.caso = casos.crear("OGA-SRV/2026", "NN s/ Servidor", "remision")
        cx = casos.abrir(cls.caso.slug)
        try:
            ingesta.agregar(cx, pdf_de([["ACTA DE SECUESTRO", "Documento A"]]), "a.pdf")
            ingesta.agregar(cx, pdf_de([["DECLARACION TESTIMONIAL", "Documento B"]]), "b.pdf")
            ocr.leer_caso(cx)
            from punteo.evidencia import deteccion
            deteccion.detectar(cx)
        finally:
            cx.close()

        cls._porteria = servidor.PORTERIA
        servidor.PORTERIA = acceso.Porteria(exigir=False)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), servidor.Manejador)
        cls.srv.daemon_threads = True
        cls.puerto = cls.srv.server_address[1]
        cls.hilo = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.hilo.start()

    @classmethod
    def tearDownClass(cls):
        from punteo import config, servidor
        cls.srv.shutdown()
        cls.srv.server_close()
        servidor.PORTERIA = cls._porteria
        config.DATOS = cls._datos
        shutil.rmtree(cls.carpeta, ignore_errors=True)

    def url(self, ruta: str) -> str:
        return f"http://127.0.0.1:{self.puerto}{ruta}"

    def pedir(self, ruta: str, metodo: str = "GET", cuerpo: bytes | None = None,
              cabeceras: dict | None = None):
        pedido = urllib.request.Request(self.url(ruta), data=cuerpo, method=metodo,
                                        headers=cabeceras or {})
        try:
            r = urllib.request.urlopen(pedido)
            return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def cx(self):
        from punteo import casos
        return casos.abrir(self.caso.slug)


class LaImagenEsLaDeLaPaginaQueSeEstaMirando(ConServidor):
    """
    La dirección de la imagen lleva el número de página del caso, y ese número se mueve:
    reordenar los PDF se lo cambia a todas. Si el navegador guarda la imagen por esa
    dirección, después de reordenar muestra la hoja de otro documento con la foja y la
    evidencia de la nueva al lado, y alguien decide mirando el papel equivocado.
    """

    def test_se_revalida_en_vez_de_guardarse_un_dia_entero(self):
        codigo, datos, cabeceras = self.pedir(f"/api/caso/{self.caso.slug}/pagina/1/imagen")
        self.assertEqual(codigo, 200)
        self.assertTrue(datos.startswith(b"\xff\xd8"))
        self.assertIn("no-cache", cabeceras["Cache-Control"])
        self.assertNotIn("max-age=86400", cabeceras["Cache-Control"])
        self.assertTrue(cabeceras.get("ETag"))

        # Con la etiqueta en la mano, el servidor no manda la imagen de nuevo.
        codigo, cuerpo, _ = self.pedir(f"/api/caso/{self.caso.slug}/pagina/1/imagen",
                                       cabeceras={"If-None-Match": cabeceras["ETag"]})
        self.assertEqual(codigo, 304)
        self.assertEqual(cuerpo, b"")

    def test_la_etiqueta_y_los_bytes_salen_de_la_misma_lectura(self):
        """
        Si la etiqueta se calcula en una consulta y la imagen en otra, un reordenamiento
        entre las dos devuelve la hoja de un documento con la etiqueta del otro, y a
        partir de ahí el navegador guarda esa mezcla.
        """
        from punteo import ingesta, ocr
        cx = self.cx()
        try:
            fila = ocr.pagina_para_imagen(cx, 1)
            identidad = ocr.identidad_imagen(fila, 150)
            docs = [d["id"] for d in ingesta.documentos(cx)]
            ingesta.reordenar(cx, list(reversed(docs)))     # la numeración se movió
            datos, _ = ocr.imagen_de(fila, dpi=150)          # pero la fila leída no
        finally:
            cx.close()
        self.assertTrue(datos.startswith(b"\xff\xd8"))
        # La identidad no depende del número global, así que sigue siendo la misma hoja.
        cx = self.cx()
        try:
            ingesta.reordenar(cx, list(reversed([d["id"] for d in ingesta.documentos(cx)])))
            self.assertEqual(identidad, ocr.identidad_imagen(ocr.pagina_para_imagen(cx, 1), 150))
        finally:
            cx.close()

    def test_reordenar_los_pdf_cambia_la_etiqueta_y_la_imagen(self):
        from punteo import ingesta
        ruta = f"/api/caso/{self.caso.slug}/pagina/1/imagen"
        _, imagen_a, cab_a = self.pedir(ruta)

        cx = self.cx()
        try:
            docs = [d["id"] for d in ingesta.documentos(cx)]
            ingesta.reordenar(cx, list(reversed(docs)))
        finally:
            cx.close()

        codigo, imagen_b, cab_b = self.pedir(ruta)
        self.assertEqual(codigo, 200)
        self.assertNotEqual(cab_a["ETag"], cab_b["ETag"],
                            "la etiqueta no cambió: el navegador se queda con la vieja")
        self.assertNotEqual(imagen_a, imagen_b,
                            "la página 1 sigue mostrando la hoja del otro documento")
        # Y la etiqueta vieja ya no vale: pedirla con ella devuelve la imagen nueva.
        codigo, _, _ = self.pedir(ruta, cabeceras={"If-None-Match": cab_a["ETag"]})
        self.assertEqual(codigo, 200)


class NadieCambiaElLegajoDeAfuera(ConServidor):
    """
    Dos cosas que se veían bien y no lo eran: que alcanzara con pedir una dirección para
    apagar una pieza, y que cualquier sitio abierto en el mismo navegador pudiera mandar
    ese pedido. Escuchar en 127.0.0.1 no protege de ninguna de las dos.
    """

    def _una_pieza(self) -> int:
        cx = self.cx()
        try:
            from punteo.evidencia import modelo
            return modelo.listar(cx)["evidencias"][0]["id"]
        finally:
            cx.close()

    def _activa(self, eid: int) -> bool:
        cx = self.cx()
        try:
            return bool(cx.execute("SELECT activa FROM evidencia WHERE id=?",
                                   (eid,)).fetchone()["activa"])
        finally:
            cx.close()

    def test_un_get_no_descarta_una_pieza(self):
        eid = self._una_pieza()
        codigo, cuerpo, cabeceras = self.pedir(
            f"/api/caso/{self.caso.slug}/evidencia/{eid}/descartar")
        self.assertEqual(codigo, 405, cuerpo)
        self.assertIn("POST", cabeceras.get("Allow", ""))
        self.assertTrue(self._activa(eid), "un GET apagó la pieza")

    def test_un_get_no_deshace_ni_desagrupa(self):
        eid = self._una_pieza()
        for accion in ("restaurar", "deshacer", "grupo", "estado"):
            codigo, _, _ = self.pedir(f"/api/caso/{self.caso.slug}/evidencia/{eid}/{accion}")
            self.assertEqual(codigo, 405, accion)
        self.assertTrue(self._activa(eid))

    def test_un_pedido_de_otro_sitio_no_pasa(self):
        eid = self._una_pieza()
        for cabeceras in ({"Origin": "http://otro-sitio.example"},
                          {"Sec-Fetch-Site": "cross-site"},
                          {"Origin": f"http://127.0.0.1:{self.puerto + 1}"}):
            codigo, cuerpo, _ = self.pedir(
                f"/api/caso/{self.caso.slug}/evidencia/{eid}/descartar",
                metodo="POST", cuerpo=b"{}", cabeceras=cabeceras)
            self.assertEqual(codigo, 403, f"{cabeceras}: {cuerpo}")
        self.assertTrue(self._activa(eid))

    def test_el_pedido_de_la_propia_interfaz_si_pasa(self):
        eid = self._una_pieza()
        codigo, cuerpo, _ = self.pedir(
            f"/api/caso/{self.caso.slug}/evidencia/{eid}/descartar", metodo="POST",
            cuerpo=b"{}", cabeceras={"Origin": f"http://127.0.0.1:{self.puerto}",
                                     "Sec-Fetch-Site": "same-origin",
                                     "Content-Type": "application/json"})
        self.assertEqual(codigo, 200, cuerpo)
        self.assertFalse(self._activa(eid))
        # Y se deja como estaba, que las pruebas de esta clase comparten el caso.
        self.pedir(f"/api/caso/{self.caso.slug}/evidencia/{eid}/restaurar", metodo="POST",
                   cuerpo=b"{}", cabeceras={"Origin": f"http://127.0.0.1:{self.puerto}"})

    def test_una_direccion_que_no_es_la_de_este_servidor_no_pasa(self):
        """
        El rebinding de DNS: un dominio del atacante que resuelve a 127.0.0.1 queda como
        mismo origen para el navegador, y desde ahí se lee el legajo entero. La cabecera
        `Host` es lo único que lo distingue.
        """
        codigo, _, _ = self.pedir(f"/api/caso/{self.caso.slug}/evidencias",
                                  cabeceras={"Host": "legajos.sitio-ajeno.example"})
        self.assertEqual(codigo, 403)
        codigo, _, _ = self.pedir("/api/estado", cabeceras={"Host": "localhost:8714"})
        self.assertEqual(codigo, 200)


class LaListaSePuedeControlar(ConServidor):
    """
    La interfaz junta la lista por tandas y después la compara contra la lista de
    números completa. Eso sólo sirve si las dos vienen en el mismo orden estable.
    """

    def test_la_lista_de_numeros_coincide_con_las_tandas(self):
        import json
        base = f"/api/caso/{self.caso.slug}/evidencias"
        _, cuerpo, _ = self.pedir(f"{base}?solo_ids=1")
        control = json.loads(cuerpo)
        juntadas, desde = [], 0
        while True:
            _, cuerpo, _ = self.pedir(f"{base}?desde={desde}&limite=1")
            tanda = json.loads(cuerpo)
            juntadas += [e["id"] for e in tanda["evidencias"]]
            desde += len(tanda["evidencias"])
            if not tanda["evidencias"] or desde >= tanda["total"]:
                break
        self.assertEqual(control["ids"], juntadas)
        self.assertEqual(control["total"], len(juntadas))


class QueDireccionesSeAceptan(unittest.TestCase):

    def setUp(self):
        import os
        self._antes = os.environ.pop("PUNTEO_HOSTS", None)
        self.addCleanup(lambda: os.environ.__setitem__("PUNTEO_HOSTS", self._antes)
                        if self._antes else None)

    def test_las_de_esta_maquina(self):
        from punteo import acceso
        for h in ("127.0.0.1:8714", "localhost:8714", "[::1]:8714", "127.0.0.1"):
            self.assertTrue(acceso.host_permitido(h, "127.0.0.1", False), h)

    def test_ninguna_otra_mientras_no_haya_clave(self):
        from punteo import acceso
        for h in ("legajos.example", "192.168.1.40:8714", "", "  "):
            self.assertFalse(acceso.host_permitido(h, "127.0.0.1", False), repr(h))

    def test_con_clave_la_cookie_es_la_barrera(self):
        from punteo import acceso
        self.assertTrue(acceso.host_permitido("punteo.fiscalia.example", "0.0.0.0", True))

    def test_se_puede_declarar_una_a_mano(self):
        import os

        from punteo import acceso
        os.environ["PUNTEO_HOSTS"] = "punteo.ufil.local"
        self.assertTrue(acceso.host_permitido("punteo.ufil.local:8714", "0.0.0.0", False))
        self.assertFalse(acceso.host_permitido("otra.ufil.local", "0.0.0.0", False))

    def test_la_direccion_de_escucha_se_acepta_sola(self):
        from punteo import acceso
        self.assertTrue(acceso.host_permitido("192.168.1.40:8714", "192.168.1.40", False))


if __name__ == "__main__":
    unittest.main()
