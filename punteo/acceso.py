"""
La puerta: quién puede abrir el legajo.

Por qué existe
--------------
En `127.0.0.1` la aplicación la ve sólo quien está sentado en esa máquina, y con eso
alcanza mientras se trabaja en el escritorio. Pero apenas el servidor escucha en otra
dirección —la red de la fiscalía, un contenedor publicado, un servicio en internet—
cambia quién puede entrar: pasa de «el que está sentado acá» a «cualquiera que sepa la
dirección». Un legajo penal no puede quedar así.

La regla, y por qué se decide sola
----------------------------------
Hace falta clave cuando el proceso NO escucha en loopback. Se deduce de la dirección de
escucha y no de una opción aparte, a propósito: una opción aparte se olvida, y lo que
queda abierto es un legajo.

Hay un solo caso donde esa regla se equivoca, y es adentro de un contenedor. Ahí el
proceso está obligado a escuchar en `0.0.0.0` —si escuchara en loopback no lo alcanzaría
ni el propio Docker— pero quién llega de verdad lo decide la publicación del puerto, que
en `docker-compose.yml` es `127.0.0.1:8714:8714`, o sea sólo esa máquina. Pedir clave
ahí sería pedírsela a quien ya está sentado en la computadora.

Para ese caso, y sólo para ese, existe `PUNTEO_ACCESO=abierto`. Significa «quién puede
llegar a este puerto ya está restringido afuera de este proceso». **Ponerla en una
instalación sin contenedor deja el legajo abierto de par en par.**

Lo que esto NO resuelve, y hay que decirlo
------------------------------------------
El tráfico va en HTTP plano. Quien pueda mirar los paquetes de esa red puede leer lo que
se transmite, la clave incluida. Para eso haría falta HTTPS con un certificado, y un
certificado propio en una máquina sin internet trae su propio lío de instalación en cada
equipo. La decisión tomada es: modo red para una red de fiscalía bajo control, loopback
—el modo por omisión— para todo lo demás, y HTTPS por delante si alguna vez sale a
internet de verdad.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import secrets
import socket
import threading
import time
from html import escape

# Sin caracteres que se confundan al leerlos de una pantalla y tipearlos en un teléfono:
# nada de O contra 0, ni I contra 1 contra l.
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LARGO = 6
# Largo mínimo cuando la clave la pone una variable de entorno. Es más exigente que la
# generada porque una clave escrita a mano tiende a ser corta y memorable, y esa variable
# se usa justamente cuando el servicio sale a internet.
LARGO_MINIMO_PUESTA = 12

# Tras varios intentos fallidos desde la misma dirección, cada intento nuevo espera. No
# es una cárcel: es que probar un millón de combinaciones deje de ser gratis.
INTENTOS_LIBRES = 5
ESPERA_BASE = 1.5
ESPERA_MAXIMA = 30.0

COOKIE = "punteo_acceso"
VIDA_SESION = 12 * 3600          # una jornada de trabajo


def es_local(host: str) -> bool:
    """¿La dirección de escucha deja entrar sólo a esta misma máquina?"""
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def hace_falta_clave(host: str) -> bool:
    modo = os.environ.get("PUNTEO_ACCESO", "auto").strip().lower()
    if modo == "abierto":
        return False
    if modo == "clave":
        return True
    return not es_local(host)


def host_de(cabecera: str) -> str:
    """El nombre de la cabecera `Host`, sin el puerto y sin los corchetes de IPv6."""
    h = (cabecera or "").strip()
    if h.startswith("["):
        return h[1:h.index("]")].lower() if "]" in h else ""
    return (h.rsplit(":", 1)[0] if ":" in h else h).lower()


def host_permitido(cabecera: str, escucha: str, con_clave: bool) -> bool:
    """
    ¿La dirección por la que llegó este pedido es una de las que este proceso reconoce?

    Es la defensa contra el rebinding de DNS, que es la forma en que un legajo se escapa
    de una máquina donde «todo está en 127.0.0.1». Un sitio cualquiera hace que su
    dominio resuelva a 127.0.0.1; el navegador considera que su JavaScript y este
    servidor son el MISMO ORIGEN —el del dominio— y desde ahí puede leer todo lo que
    conteste la API y mandarlo a donde quiera. Escuchar en loopback no lo impide: la
    cabecera `Host` es lo único que distingue «entraron por 127.0.0.1» de «entraron por
    un dominio que apunta acá».

    Con clave no hace falta: la cookie es `SameSite=Strict` y va atada al origen por el
    que alguien entró, así que el pedido del atacante llega sin sesión.

    `PUNTEO_HOSTS` existe para la instalación que sirve por un nombre propio —un alias
    de la red de la fiscalía— sin poner clave. Es una decisión explícita, como
    `PUNTEO_ACCESO=abierto`.
    """
    if con_clave:
        return True
    nombre = host_de(cabecera)
    if not nombre:
        return False
    if es_local(nombre):
        return True
    permitidos = {h.strip().lower()
                  for h in os.environ.get("PUNTEO_HOSTS", "").split(",") if h.strip()}
    if escucha and not es_local(escucha) and escucha not in ("0.0.0.0", "::"):
        permitidos.add(escucha.strip().lower())
    return nombre in permitidos


def direccion_en_la_red() -> str | None:
    """
    La IP de esta máquina en su red, para poder dictarla por teléfono.

    No sale a internet: abre un socket UDP hacia una dirección que no se usa y le
    pregunta al sistema qué interfaz habría elegido. No se manda un solo paquete.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


class ClaveInsegura(RuntimeError):
    """La clave puesta a mano es demasiado corta para lo que se le va a pedir."""


class Porteria:
    """
    Decide quién pasa. Una instancia por proceso.

    Guarda las sesiones en memoria a propósito: reiniciar el servidor cierra todas las
    sesiones, que es lo que uno espera de un reinicio y no hay que acordarse de hacerlo.
    """

    def __init__(self, *, exigir: bool, clave: str | None = None):
        self.exigir = exigir
        self._lock = threading.Lock()
        self._sesiones: dict[str, float] = {}
        self._fallidos: dict[str, tuple[int, float]] = {}

        self.generada = False
        if not exigir:
            self.clave = None
            return
        puesta = (clave or os.environ.get("PUNTEO_CLAVE") or "").strip()
        if puesta:
            if len(puesta) < LARGO_MINIMO_PUESTA:
                raise ClaveInsegura(
                    f"PUNTEO_CLAVE tiene {len(puesta)} caracteres y hacen falta al menos "
                    f"{LARGO_MINIMO_PUESTA}. Una clave corta en un servicio que sale a "
                    f"internet se adivina.")
            self.clave = puesta
        else:
            self.clave = "".join(secrets.choice(ALFABETO) for _ in range(LARGO))
            self.generada = True

    # ── el anuncio del arranque ──
    def anuncio(self, host: str, puerto: int) -> list[str]:
        """Qué imprimir en la terminal al levantar. Es donde se lee la clave generada."""
        lineas = []
        if not self.exigir:
            if not es_local(host):
                lineas.append("  ATENCIÓN: escucha fuera de esta máquina y SIN clave.")
                lineas.append("  Eso sólo es correcto si el puerto ya está restringido")
                lineas.append("  afuera de este proceso (por ejemplo, docker-compose).")
            return lineas
        ip = direccion_en_la_red()
        if ip:
            lineas.append(f"  Desde otro equipo de la red:  http://{ip}:{puerto}")
        if self.generada:
            lineas += ["", f"  CLAVE DE ACCESO:  {self.clave}", "",
                       "  Se genera nueva en cada arranque y se muestra una sola vez."]
        else:
            lineas.append("  Clave: la que pusiste en PUNTEO_CLAVE.")
        return lineas

    # ── el trámite ──
    def _limpiar(self, ahora: float) -> None:
        vencidas = [t for t, hasta in self._sesiones.items() if hasta < ahora]
        for t in vencidas:
            self._sesiones.pop(t, None)

    def tiene_permiso(self, cookies: str) -> bool:
        if not self.exigir:
            return True
        token = self._token_de(cookies)
        if not token:
            return False
        ahora = time.time()
        with self._lock:
            self._limpiar(ahora)
            return self._sesiones.get(token, 0) > ahora

    @staticmethod
    def _token_de(cookies: str) -> str | None:
        for parte in (cookies or "").split(";"):
            nombre, _, valor = parte.strip().partition("=")
            if nombre == COOKIE and valor:
                return valor
        return None

    def espera_de(self, ip: str) -> float:
        """Cuánto tiene que esperar esta dirección antes de que le acepten otro intento."""
        with self._lock:
            intentos, ultimo = self._fallidos.get(ip, (0, 0.0))
        if intentos <= INTENTOS_LIBRES:
            return 0.0
        castigo = min(ESPERA_MAXIMA, ESPERA_BASE * (2 ** (intentos - INTENTOS_LIBRES - 1)))
        return max(0.0, castigo - (time.time() - ultimo))

    def intentar(self, ip: str, clave: str) -> str | None:
        """
        Devuelve el token de sesión si la clave es correcta, o None.

        La comparación es `hmac.compare_digest` y no `==`: comparar cadenas corta en el
        primer carácter distinto, y ese tiempo, medido muchas veces, filtra la clave.
        """
        if not self.exigir:
            return "abierto"
        if self.espera_de(ip) > 0:
            return None
        if not hmac.compare_digest((clave or "").strip(), self.clave or ""):
            with self._lock:
                intentos, _ = self._fallidos.get(ip, (0, 0.0))
                self._fallidos[ip] = (intentos + 1, time.time())
            return None
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._fallidos.pop(ip, None)
            self._sesiones[token] = time.time() + VIDA_SESION
        return token

    def cerrar(self, cookies: str) -> None:
        token = self._token_de(cookies)
        if token:
            with self._lock:
                self._sesiones.pop(token, None)


# ────────────────────────────────────────────────────────── la pantalla ──
def pagina(error: str = "", espera: float = 0.0) -> bytes:
    """
    La pantalla de la clave. Se escribe acá y no en `web/` a propósito: es lo único que
    se sirve antes de saber quién está del otro lado, y no puede depender de que el
    resto de la interfaz esté disponible ni traer nada más que lo que necesita.
    """
    aviso = ""
    if espera > 0:
        aviso = (f'<p class="mal">Demasiados intentos. Esperá '
                 f'{int(espera) + 1} segundos.</p>')
    elif error:
        aviso = f'<p class="mal">{escape(error)}</p>'

    return f"""<!doctype html>
<html lang="es-AR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Punteo de Evidencia</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center;
         background:#1E242C; color:#F4F6F8;
         font-family:'Segoe UI',system-ui,sans-serif; }}
  form {{ width:min(340px, 90vw); text-align:center; }}
  .marca {{ display:flex; align-items:center; justify-content:center; gap:10px;
            margin-bottom:26px; }}
  .filete {{ width:3px; height:30px; background:#B08442; border-radius:2px; }}
  .marca b {{ font-size:1.1rem; font-weight:680; }}
  .marca small {{ display:block; font-size:.6rem; letter-spacing:.09em;
                  text-transform:uppercase; color:#A8B4C0; }}
  label {{ display:block; font-size:.74rem; letter-spacing:.06em;
           text-transform:uppercase; color:#A8B4C0; margin-bottom:7px; }}
  input {{ width:100%; padding:11px 13px; font-size:1.3rem; text-align:center;
           letter-spacing:.22em; text-transform:uppercase;
           font-family:ui-monospace,Menlo,monospace;
           border:1px solid #3A4552; border-radius:5px;
           background:#0C1014; color:#F4F6F8; }}
  input:focus {{ outline:2px solid #2F5D82; outline-offset:2px; }}
  button {{ width:100%; margin-top:12px; padding:10px; font:inherit; font-weight:600;
            border:0; border-radius:5px; background:#2F5D82; color:#fff; cursor:pointer; }}
  .mal {{ color:#F08B8B; font-size:.85rem; margin:0 0 12px; }}
  .pie {{ margin-top:22px; font-size:.72rem; color:#6E7885; line-height:1.5; }}
</style></head>
<body>
  <form method="post" action="/acceso">
    <div class="marca"><span class="filete"></span>
      <span><b>Punteo</b><small>de evidencia</small></span></div>
    {aviso}
    <label for="clave">Clave de acceso</label>
    <input id="clave" name="clave" autofocus autocomplete="off" autocapitalize="characters"
           inputmode="text" maxlength="64">
    <button type="submit">Entrar</button>
    <p class="pie">La muestra una sola vez la terminal donde se levantó el servidor.</p>
  </form>
</body></html>""".encode("utf-8")
