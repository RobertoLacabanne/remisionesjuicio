"""
La puerta.

Lo que se verifica no es que la clave funcione —eso es lo fácil— sino las dos cosas que
salen caras si fallan: que **el modo con clave no se pueda saltear por ninguna ruta**, y
que la regla que decide si hace falta clave no se equivoque hacia el lado abierto.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


class CuandoHaceFaltaClave(unittest.TestCase):
    """La regla se deduce de la dirección de escucha, no de una opción que se olvida."""

    def setUp(self):
        self._antes = os.environ.pop("PUNTEO_ACCESO", None)
        self.addCleanup(lambda: os.environ.__setitem__("PUNTEO_ACCESO", self._antes)
                        if self._antes else None)

    def test_loopback_no_pide_clave(self):
        from punteo import acceso
        for host in ("127.0.0.1", "localhost", "::1", ""):
            self.assertTrue(acceso.es_local(host), host)
            self.assertFalse(acceso.hace_falta_clave(host), host)

    def test_cualquier_otra_direccion_pide_clave(self):
        from punteo import acceso
        for host in ("0.0.0.0", "192.168.1.40", "10.0.0.5", "no-es-una-ip"):
            self.assertFalse(acceso.es_local(host), host)
            self.assertTrue(acceso.hace_falta_clave(host), host)

    def test_abierto_desactiva_la_clave_y_solo_eso(self):
        from punteo import acceso
        os.environ["PUNTEO_ACCESO"] = "abierto"
        self.assertFalse(acceso.hace_falta_clave("0.0.0.0"))

    def test_clave_la_exige_aunque_sea_loopback(self):
        from punteo import acceso
        os.environ["PUNTEO_ACCESO"] = "clave"
        self.assertTrue(acceso.hace_falta_clave("127.0.0.1"))

    def test_un_valor_raro_no_abre_la_puerta(self):
        """
        Lo importante de esta prueba es hacia qué lado falla. Un valor mal escrito
        —`PUNTEO_ACCESO=si`, `=true`, un espacio de más— tiene que caer en el
        comportamiento automático, nunca en «abierto».
        """
        from punteo import acceso
        for valor in ("si", "true", "1", "ABIERTO ", "", "opened", "abierta"):
            os.environ["PUNTEO_ACCESO"] = valor
            abierto = valor.strip().lower() == "abierto"
            self.assertEqual(acceso.hace_falta_clave("0.0.0.0"), not abierto, valor)


class LaClave(unittest.TestCase):

    def test_la_generada_es_legible_de_una_pantalla(self):
        from punteo import acceso
        p = acceso.Porteria(exigir=True)
        self.assertTrue(p.generada)
        self.assertEqual(len(p.clave), acceso.LARGO)
        # Sin caracteres que se confundan al dictarlos o tipearlos en un teléfono.
        for prohibido in "O0Il1":
            self.assertNotIn(prohibido, acceso.ALFABETO)

    def test_una_clave_puesta_a_mano_y_corta_se_rechaza(self):
        from punteo import acceso
        with self.assertRaises(acceso.ClaveInsegura):
            acceso.Porteria(exigir=True, clave="1234")

    def test_una_clave_puesta_a_mano_y_larga_se_acepta(self):
        from punteo import acceso
        p = acceso.Porteria(exigir=True, clave="clave-larga-de-verdad")
        self.assertFalse(p.generada)
        self.assertEqual(p.clave, "clave-larga-de-verdad")

    def test_la_correcta_abre_y_la_incorrecta_no(self):
        from punteo import acceso
        p = acceso.Porteria(exigir=True)
        self.assertIsNone(p.intentar("1.2.3.4", "MALMAL"))
        token = p.intentar("1.2.3.4", p.clave)
        self.assertTrue(token)
        self.assertTrue(p.tiene_permiso(f"{acceso.COOKIE}={token}"))

    def test_sin_cookie_no_hay_permiso(self):
        from punteo import acceso
        p = acceso.Porteria(exigir=True)
        for cookies in ("", "otra=cosa", f"{acceso.COOKIE}=", f"{acceso.COOKIE}=inventado"):
            self.assertFalse(p.tiene_permiso(cookies), repr(cookies))

    def test_salir_invalida_la_sesion(self):
        from punteo import acceso
        p = acceso.Porteria(exigir=True)
        token = p.intentar("1.2.3.4", p.clave)
        galleta = f"{acceso.COOKIE}={token}"
        self.assertTrue(p.tiene_permiso(galleta))
        p.cerrar(galleta)
        self.assertFalse(p.tiene_permiso(galleta))

    def test_probar_a_lo_bruto_deja_de_ser_gratis(self):
        from punteo import acceso
        p = acceso.Porteria(exigir=True)
        for _ in range(acceso.INTENTOS_LIBRES):
            p.intentar("9.9.9.9", "MALMAL")
        self.assertEqual(p.espera_de("9.9.9.9"), 0.0)
        p.intentar("9.9.9.9", "MALMAL")
        self.assertGreater(p.espera_de("9.9.9.9"), 0.0)
        # Y el castigo es de esa dirección, no de todo el mundo.
        self.assertEqual(p.espera_de("8.8.8.8"), 0.0)

    def test_acertar_limpia_el_castigo(self):
        from punteo import acceso
        p = acceso.Porteria(exigir=True)
        for _ in range(acceso.INTENTOS_LIBRES + 2):
            p.intentar("7.7.7.7", "MALMAL")
        p._fallidos["7.7.7.7"] = (acceso.INTENTOS_LIBRES + 2, 0.0)   # castigo ya cumplido
        self.assertTrue(p.intentar("7.7.7.7", p.clave))
        self.assertEqual(p.espera_de("7.7.7.7"), 0.0)

    def test_la_pantalla_no_muestra_la_clave(self):
        from punteo import acceso
        p = acceso.Porteria(exigir=True)
        html = acceso.pagina().decode("utf-8")
        self.assertNotIn(p.clave, html)

    def test_la_pantalla_escapa_lo_que_le_pasan(self):
        from punteo import acceso
        html = acceso.pagina("<script>alert(1)</script>").decode("utf-8")
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)


class ElServidorConClave(unittest.TestCase):
    """
    De punta a punta, con un servidor de verdad: es la única forma de comprobar que la
    puerta no se pueda saltear por una ruta que alguien agregó sin acordarse del control.
    """

    @classmethod
    def setUpClass(cls):
        from punteo import acceso, casos, config, servidor
        cls.carpeta = Path(tempfile.mkdtemp(prefix="punteo-puerta-"))
        cls._datos = config.DATOS
        config.DATOS = cls.carpeta / "datos"
        cls.caso = casos.crear("OGA-PUERTA/2026", "NN s/ Prueba", "remision")

        cls.porteria_antes = servidor.PORTERIA
        servidor.PORTERIA = acceso.Porteria(exigir=True, clave="clave-de-prueba-larga")
        cls.clave = "clave-de-prueba-larga"

        from http.server import ThreadingHTTPServer
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), servidor.Manejador)
        cls.srv.daemon_threads = True
        cls.puerto = cls.srv.server_address[1]
        cls.hilo = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.hilo.start()

    @classmethod
    def tearDownClass(cls):
        from punteo import config, servidor
        cls.srv.shutdown(); cls.srv.server_close()
        servidor.PORTERIA = cls.porteria_antes
        config.DATOS = cls._datos
        shutil.rmtree(cls.carpeta, ignore_errors=True)

    def url(self, ruta):
        return f"http://127.0.0.1:{self.puerto}{ruta}"

    def pedir(self, ruta, abridor=None, datos=None):
        abrir = abridor.open if abridor else urllib.request.urlopen
        try:
            r = abrir(urllib.request.Request(self.url(ruta), data=datos))
            return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_sin_sesion_ninguna_ruta_entrega_nada(self):
        """
        El barrido es el punto: no se prueba «la raíz pide clave», se prueba que
        NINGUNA ruta conteste con datos. Una ruta nueva que se olvide del control es
        exactamente la forma en que esto se rompe dentro de seis meses.
        """
        rutas = ["/", "/estilo.css", "/app.js", "/api/estado", "/api/catalogo",
                 "/api/casos", f"/api/caso/{self.caso.slug}",
                 f"/api/caso/{self.caso.slug}/evidencias",
                 f"/api/caso/{self.caso.slug}/paginas",
                 f"/api/caso/{self.caso.slug}/punteo",
                 f"/api/caso/{self.caso.slug}/punteo/exportar?formato=txt",
                 f"/api/caso/{self.caso.slug}/pagina/1/imagen",
                 f"/api/caso/{self.caso.slug}/buscar?q=algo",
                 "/fuentes/Archivo-Variable.ttf"]
        for ruta in rutas:
            codigo, cuerpo = self.pedir(ruta)
            if ruta.startswith("/api/"):
                self.assertEqual(codigo, 401, ruta)
                self.assertIn(b"sesion", cuerpo.replace(b"\xc3\xb3", b"o").lower(), ruta)
            else:
                self.assertEqual(codigo, 200, ruta)
                self.assertIn(b"Clave de acceso", cuerpo, f"{ruta} no devolvió la puerta")
            self.assertNotIn(self.clave.encode(), cuerpo, ruta)

    def test_con_la_clave_correcta_se_entra_y_se_trabaja(self):
        import urllib.parse
        abridor = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar()))
        codigo, _ = self.pedir(
            "/acceso", abridor,
            urllib.parse.urlencode({"clave": self.clave}).encode())
        self.assertIn(codigo, (200, 303))

        codigo, cuerpo = self.pedir("/api/estado", abridor)
        self.assertEqual(codigo, 200)
        self.assertIn(b'"version"', cuerpo)

        codigo, cuerpo = self.pedir("/", abridor)
        self.assertEqual(codigo, 200)
        self.assertIn(b"Punteo de Evidencia", cuerpo)
        self.assertNotIn(b"Clave de acceso", cuerpo)

    def test_con_la_clave_incorrecta_no(self):
        import urllib.parse
        codigo, cuerpo = self.pedir(
            "/acceso", None, urllib.parse.urlencode({"clave": "no-es"}).encode())
        self.assertEqual(codigo, 401)
        self.assertIn(b"incorrecta", cuerpo)

    def test_una_cookie_inventada_no_sirve(self):
        pedido = urllib.request.Request(self.url("/api/estado"))
        from punteo import acceso
        pedido.add_header("Cookie", f"{acceso.COOKIE}=" + "x" * 43)
        try:
            r = urllib.request.urlopen(pedido)
            self.fail(f"entró con una cookie inventada: {r.status}")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)


class ElServidorSinClave(unittest.TestCase):
    """En loopback y sin clave, la aplicación no puede quedar pidiendo nada."""

    def test_la_porteria_abierta_deja_pasar(self):
        from punteo import acceso
        p = acceso.Porteria(exigir=False)
        self.assertTrue(p.tiene_permiso(""))
        self.assertIsNone(p.clave)
        self.assertEqual(p.anuncio("127.0.0.1", 8714), [])

    def test_pero_avisa_si_escucha_afuera_sin_clave(self):
        from punteo import acceso
        p = acceso.Porteria(exigir=False)
        anuncio = " ".join(p.anuncio("0.0.0.0", 8714))
        self.assertIn("ATENCIÓN", anuncio)
        self.assertIn("SIN clave", anuncio)


if __name__ == "__main__":
    unittest.main()
