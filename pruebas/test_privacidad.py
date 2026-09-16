"""
Nada sale de la máquina.

Esta aplicación se usa con documentación judicial sensible. La regla es que no haya una
sola llamada de red: ni CDN, ni fuentes remotas, ni analytics, ni OCR en la nube, ni
modelo remoto.

Una regla así se rompe de la forma más inocente —alguien agrega un `<link>` a Google
Fonts para que se vea mejor— y no se nota hasta que alguien mira el tráfico de la
máquina de la fiscalía. Por eso está acá y no en un documento.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

PAQUETE = RAIZ / "punteo"
WEB = PAQUETE / "web"


def _fuentes_python():
    return [p for p in PAQUETE.rglob("*.py")]


class SinRed(unittest.TestCase):

    # La única excepción, anotada acá y no en un comentario suelto para que agregar otra
    # sea una decisión y no un descuido: `acceso.py` abre un socket UDP hacia una
    # dirección que no existe y le pregunta al sistema operativo qué interfaz habría
    # elegido, para poder mostrar en la terminal la IP que hay que dictar por teléfono.
    # No se manda un solo paquete y no hay ninguna conexión. Está probado abajo.
    IMPORTA_SOCKET = {"acceso.py"}

    def test_ningun_modulo_importa_biblioteca_de_red(self):
        prohibidos = re.compile(
            r"^\s*(?:import|from)\s+(urllib\.request|requests|httpx|aiohttp|socket|"
            r"http\.client|ftplib|smtplib|telnetlib)\b", re.MULTILINE)
        for p in _fuentes_python():
            # El servidor local usa http.server, que escucha y no sale; y urllib.parse,
            # que sólo parsea cadenas. Están permitidos por nombre exacto.
            texto = p.read_text(encoding="utf-8")
            m = prohibidos.search(texto)
            if m and m.group(1) == "socket" and p.name in self.IMPORTA_SOCKET:
                continue
            self.assertIsNone(m, f"{p.name} importa {m.group(1) if m else ''}")

    def test_el_unico_socket_no_manda_nada(self):
        """
        Lo que se permite arriba es preguntarle al sistema por su propia interfaz. Un
        `connect` UDP no despierta tráfico; lo que lo despertaría es mandar algo, y eso
        no puede aparecer.
        """
        import inspect

        from punteo import acceso
        codigo = inspect.getsource(acceso.direccion_en_la_red)
        for prohibido in ("send", "recv", "SOCK_STREAM"):
            self.assertNotIn(prohibido, codigo, f"el socket de acceso.py hace {prohibido}")
        self.assertIn("SOCK_DGRAM", codigo)

    # Los espacios de nombres XML no son direcciones que se descarguen: son
    # identificadores, y el navegador jamás los pide. Están listados uno por uno y no
    # como un patrón amplio, para que agregar una excepción nueva sea una decisión y no
    # un descuido.
    NO_SON_PEDIDOS = ("http://www.w3.org/2000/svg", "http://www.w3.org/1999/xhtml",
                      "http://www.w3.org/1999/xlink")

    def test_no_hay_urls_externas_en_el_codigo(self):
        url = re.compile(r"https?://(?!127\.0\.0\.1|localhost)[\w.-]+", re.IGNORECASE)
        for p in list(_fuentes_python()) + list(WEB.glob("*.*")):
            for linea in p.read_text(encoding="utf-8").splitlines():
                for permitido in self.NO_SON_PEDIDOS:
                    linea = linea.replace(permitido, "")
                # Las direcciones que aparecen en comentarios de documentación no son
                # llamadas. Se permite sólo en líneas comentadas.
                limpia = linea.strip()
                if limpia.startswith(("#", "*", "//", "--")) or limpia.startswith("<!--"):
                    continue
                m = url.search(linea)
                self.assertIsNone(m, f"{p.name}: {linea.strip()[:90]}")

    def test_la_interfaz_no_pide_nada_de_afuera(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        for atributo in re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', html):
            self.assertFalse(atributo.startswith(("http://", "https://", "//")),
                             f"la interfaz pide {atributo}")

    def test_el_css_no_trae_fuentes_de_un_cdn(self):
        css = (WEB / "estilo.css").read_text(encoding="utf-8")
        self.assertNotIn("fonts.googleapis", css)
        self.assertNotIn("@import url(http", css.replace(" ", ""))
        for u in re.findall(r"url\(['\"]?([^'\")]+)", css):
            self.assertTrue(u.startswith("/"), f"el CSS trae {u} de afuera")

    def test_el_servidor_escucha_en_la_maquina(self):
        from punteo import config
        self.assertEqual(config.HOST, "127.0.0.1")

    def test_el_registro_no_guarda_contenido_de_documentos(self):
        """
        El log es otro lugar por donde un legajo se puede filtrar. `log_message` sólo
        puede escribir método, ruta y código.
        """
        import inspect

        from punteo import servidor
        codigo = inspect.getsource(servidor.Manejador.log_message)
        for prohibido in ("texto", "cuerpo", "descripcion", "palabra"):
            self.assertNotIn(prohibido, codigo.split('"""')[-1],
                             f"log_message menciona «{prohibido}»")


class SinTelemetria(unittest.TestCase):

    def test_no_hay_analytics_en_la_interfaz(self):
        sospechosos = ("gtag", "analytics", "sentry", "mixpanel", "posthog",
                       "navigator.sendBeacon", "datadog")
        for p in WEB.glob("*.*"):
            texto = p.read_text(encoding="utf-8").lower()
            for s in sospechosos:
                self.assertNotIn(s.lower(), texto, f"{p.name} tiene {s}")

    def test_el_unico_fetch_es_a_rutas_propias(self):
        js = (WEB / "app.js").read_text(encoding="utf-8")
        for destino in re.findall(r"fetch\(\s*([`'\"])([^`'\"]*)", js):
            self.assertTrue(destino[1].startswith(("/", "$")),
                            f"fetch a {destino[1]}")


sys.path.insert(0, str(Path(__file__).resolve().parent))
from comun import CasoVacio, pdf_de  # noqa: E402


class OriginalInmutable(CasoVacio):
    """
    El original se escribe una vez, queda en 0444 y no se reescribe. Es la restricción
    de la que depende poder decir que el documento del legajo es el que entró.

    La versión anterior de esta prueba buscaba cadenas en el código fuente: pasaba
    aunque el `chmod` fallara en silencio o aunque un archivo alterado se aceptara con
    el nombre de otro hash. Ahora se prueba lo que pasa.
    """

    def _cargar(self, datos: bytes, nombre: str = "legajo.pdf"):
        from punteo import ingesta
        return ingesta.agregar(self.cx, datos, nombre)

    def _ruta(self, documento_id: int) -> Path:
        return Path(self.cx.execute("SELECT ruta FROM documento WHERE id=?",
                                    (documento_id,)).fetchone()["ruta"])

    def test_queda_de_solo_lectura_y_no_se_reescribe(self):
        datos = pdf_de([["ACTA DE SECUESTRO"]])
        r = self._cargar(datos)
        ruta = self._ruta(r.documento_id)
        self.assertFalse(ruta.stat().st_mode & 0o222, "el original quedó escribible")
        antes = ruta.stat().st_mtime_ns

        otra = self._cargar(datos, "copia.pdf")
        self.assertTrue(otra.duplicado)
        self.assertIsNone(otra.advertencia)
        self.assertEqual(ruta.stat().st_mtime_ns, antes, "se volvió a escribir el original")

    def test_un_archivo_alterado_con_el_nombre_del_hash_no_se_acepta(self):
        """
        Que exista un archivo con el nombre del hash no prueba que sea ese documento. Se
        aceptaba sin mirarlo, y el caso quedaba registrando un hash que no es el suyo.
        """
        from punteo import almacen
        datos = pdf_de([["ACTA DE SECUESTRO"]])
        ruta = self._ruta(self._cargar(datos).documento_id)
        ruta.chmod(0o644)
        ruta.write_bytes(datos + b"\n% alterado a mano\n")
        ruta.chmod(0o444)

        with self.assertRaises(almacen.OriginalAlterado):
            almacen.guardar(datos, "otra-vez.pdf")
        r = self._cargar(datos, "otra-vez.pdf")
        self.assertIsNotNone(r.error)
        self.assertEqual(self.cx.execute(
            "SELECT COUNT(*) FROM excepcion WHERE clase='original_alterado'").fetchone()[0], 1)
        # Y no se «arregló» sobrescribiendo: el archivo sigue como quedó, para mirarlo.
        self.assertTrue(ruta.read_bytes().endswith(b"% alterado a mano\n"))
        ok, _ = almacen.verificar(almacen.sha256_de(datos))
        self.assertFalse(ok)

    def test_si_no_se_puede_proteger_la_carga_se_corta(self):
        """
        La invariante es 0444. Un `chmod` que falla ya no se traga: la carga no sigue y
        queda anotado por qué.
        """
        import os
        from unittest import mock
        os.environ.pop("PUNTEO_ORIGINALES_SIN_PROTECCION", None)
        with mock.patch("pathlib.Path.chmod", side_effect=OSError("permiso ignorado")):
            r = self._cargar(pdf_de([["DECLARACION TESTIMONIAL"]]))
        self.assertIsNotNone(r.error)
        self.assertIn("PUNTEO_ORIGINALES_SIN_PROTECCION", r.error)
        self.assertEqual(self.cx.execute("SELECT COUNT(*) FROM documento").fetchone()[0], 0)
        self.assertEqual(self.cx.execute(
            "SELECT COUNT(*) FROM excepcion WHERE clase='original_sin_proteger'"
        ).fetchone()[0], 1)

    def test_aceptarlo_a_proposito_deja_cargar_pero_avisa(self):
        """
        Para las carpetas que no pueden respetar el permiso existe una decisión
        explícita. Con ella la carga sigue, pero no en silencio.
        """
        import os
        from unittest import mock
        os.environ["PUNTEO_ORIGINALES_SIN_PROTECCION"] = "aceptar"
        self.addCleanup(os.environ.pop, "PUNTEO_ORIGINALES_SIN_PROTECCION", None)
        with mock.patch("pathlib.Path.chmod", side_effect=OSError("permiso ignorado")):
            r = self._cargar(pdf_de([["DECLARACION TESTIMONIAL"]]))
        self.assertIsNone(r.error)
        self.assertIsNotNone(r.advertencia)
        self.assertEqual(self.cx.execute(
            "SELECT COUNT(*) FROM excepcion WHERE clase='original_sin_proteger'"
        ).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
