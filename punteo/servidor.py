"""
Servidor local.

Biblioteca estándar de Python y nada más. Ni framework, ni Node, ni paso de compilación
en la máquina de destino. Tres razones concretas:

  * que el sistema ande desconectado se cumple solo: no hay un recurso que no salga de
    este disco;
  * el día que el que lo instaló no está, alguien puede leer este archivo y entender qué
    hace;
  * dos o tres personas sobre una máquina no justifican nada más grande.

Escucha en 127.0.0.1 por omisión: no se expone a la red ni por accidente.
"""
from __future__ import annotations

import json
import mimetypes
import re
import sqlite3
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import (busqueda, casos, config, exportacion, foliatura, generacion, grupos,
               ingesta, ocr, personas)
from .almacen import ArchivoInvalido
from .evidencia import catalogo, deteccion, duplicados, modelo
from .trabajo import Procesador

# Un trabajador POR CASO. Con uno solo, procesar el caso A dejaría al B esperando sin
# motivo, y peor: el avance que ve la pantalla sería el del otro caso.
_PROCESADORES: dict[str, Procesador] = {}
_CANDADO = threading.Lock()


class ErrorHTTP(Exception):
    def __init__(self, codigo: int, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def _procesador(slug: str) -> Procesador:
    with _CANDADO:
        if slug not in _PROCESADORES:
            _PROCESADORES[slug] = Procesador(caso=slug,
                                             ruta_base=config.carpeta_caso(slug) / "punteo.sqlite")
        return _PROCESADORES[slug]


def _cx(slug: str) -> sqlite3.Connection:
    """Conexión al caso, y lo deja activo en ESTE hilo de petición."""
    try:
        return casos.abrir(slug)
    except casos.CasoNoEncontrado:
        raise ErrorHTTP(404, f"no existe el caso «{slug}»")


def _entero(valor, nombre: str, por_omision=None):
    if valor in (None, ""):
        if por_omision is None:
            raise ErrorHTTP(400, f"falta {nombre}")
        return por_omision
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ErrorHTTP(400, f"{nombre} tiene que ser un número entero")


# ════════════════════════════════════════════════════════════ los manejadores ══
def api_estado(pet) -> dict:
    """Lo que hay en esta máquina. Es lo primero que conviene mirar en una instalación."""
    hay_ocr, detalle = ocr.hay_ocr()
    idiomas = ocr.idiomas_ocr()
    return {
        "version": __import__("punteo").__version__,
        "ocr": {"disponible": hay_ocr, "detalle": detalle, "idiomas": idiomas,
                "idioma_configurado": config.OCR_IDIOMA,
                "idioma_presente": config.OCR_IDIOMA in idiomas},
        "datos": str(config.DATOS),
        "casos": len(casos.listar()),
    }


def api_catalogo(pet) -> dict:
    return {"tipos": catalogo.como_lista(),
            "familias": catalogo.FAMILIAS,
            "roles": personas.ROLES,
            "funciones": personas.FUNCIONES,
            "criterios": generacion.CRITERIOS,
            "tipos_proceso": casos.ETIQUETA_TIPO}


def api_casos(pet) -> dict:
    if pet.metodo == "POST":
        c = pet.cuerpo_json()
        try:
            return casos.crear(c.get("numero_legajo", ""), c.get("caratula", ""),
                               c.get("tipo_proceso", "remision"),
                               c.get("observaciones")).como_dict()
        except casos.CasoInvalido as e:
            raise ErrorHTTP(400, str(e))
    return {"casos": [c.como_dict() for c in casos.listar()]}


def api_caso(pet, slug: str) -> dict:
    if pet.metodo == "DELETE":
        confirmacion = pet.cuerpo_json().get("numero_legajo", "")
        caso = casos.leer(slug)
        # Se pide escribir el número de legajo. Borrar un caso se lleva el trabajo de
        # revisión, que es lo único del sistema que no se regenera.
        if confirmacion.strip() != caso.numero_legajo:
            raise ErrorHTTP(400, "para borrar hay que escribir el número de legajo exacto")
        casos.borrar(slug)
        return {"borrado": slug}
    if pet.metodo == "PATCH":
        try:
            return casos.actualizar(slug, **pet.cuerpo_json()).como_dict()
        except casos.CasoInvalido as e:
            raise ErrorHTTP(400, str(e))
    cx = _cx(slug)
    try:
        c = casos.leer(slug).como_dict()
        c["documentos_detalle"] = ingesta.documentos(cx)
        c["contadores"] = modelo.contadores(cx)
        c["foliatura"] = foliatura.resumen(cx)
        c["tiene_punteo"] = bool(cx.execute(
            "SELECT 1 FROM punteo_generado LIMIT 1").fetchone())
        return c
    finally:
        cx.close()


def api_documentos(pet, slug: str) -> dict:
    cx = _cx(slug)
    try:
        if pet.metodo == "POST":
            nombre = unquote(pet.cabecera("X-Nombre-Archivo", "documento.pdf"))
            if not pet.cuerpo:
                raise ErrorHTTP(400, "no llegó ningún archivo")
            try:
                r = ingesta.agregar(cx, pet.cuerpo, nombre)
            except ArchivoInvalido as e:
                raise ErrorHTTP(400, str(e))
            if r.error:
                raise ErrorHTTP(400, r.error)
            return r.como_dict()
        return {"documentos": ingesta.documentos(cx)}
    finally:
        cx.close()


def api_documentos_orden(pet, slug: str) -> dict:
    cx = _cx(slug)
    try:
        ids = pet.cuerpo_json().get("ids") or []
        try:
            ingesta.reordenar(cx, [int(i) for i in ids])
        except ValueError as e:
            raise ErrorHTTP(400, str(e))
        return {"documentos": ingesta.documentos(cx)}
    finally:
        cx.close()


def api_procesar(pet, slug: str) -> dict:
    _cx(slug).close()                     # valida que el caso exista
    return _procesador(slug).arrancar()


def api_detener(pet, slug: str) -> dict:
    return _procesador(slug).detener()


def api_progreso(pet, slug: str) -> dict:
    return _procesador(slug).estado.como_dict()


def api_paginas(pet, slug: str) -> dict:
    cx = _cx(slug)
    try:
        desde = _entero(pet.consulta("desde"), "desde", 1)
        limite = min(500, _entero(pet.consulta("limite"), "limite", 100))
        filas = cx.execute("""
            SELECT p.numero_global, p.numero_pdf, p.foja_etiqueta, p.foja_origen,
                   p.foja_confianza, p.confianza, p.documento_id, d.nombre_archivo,
                   -- El tamaño va en la lista y no en el pedido de cada página: el
                   -- visor lo necesita para ubicar el recuadro del fragmento, y pedirlo
                   -- de a una página sería una ida y vuelta por cada foja que se pasa.
                   p.ancho_pt, p.alto_pt, p.rotacion,
                   (p.texto IS NOT NULL) AS leida
              FROM pagina p JOIN documento d ON d.id = p.documento_id
             WHERE p.numero_global >= ? ORDER BY p.numero_global LIMIT ?""",
            (desde, limite)).fetchall()
        total = cx.execute("SELECT COUNT(*) FROM pagina").fetchone()[0]
        return {"total": total, "paginas": [dict(f) for f in filas]}
    finally:
        cx.close()


def api_pagina(pet, slug: str, numero: str) -> dict:
    cx = _cx(slug)
    try:
        n = _entero(numero, "página")
        fila = cx.execute("""SELECT p.*, d.nombre_archivo FROM pagina p
                               JOIN documento d ON d.id = p.documento_id
                              WHERE p.numero_global=?""", (n,)).fetchone()
        if not fila:
            raise ErrorHTTP(404, f"no hay página {n}")
        d = dict(fila)
        d["evidencias"] = [modelo.como_dict(r) for r in cx.execute("""
            SELECT * FROM v_evidencia
             WHERE activa=1 AND pagina_inicio <= ? AND pagina_fin >= ?
             ORDER BY pagina_inicio""", (n, n))]
        return d
    finally:
        cx.close()


def api_pagina_foja(pet, slug: str, numero: str) -> dict:
    cx = _cx(slug)
    try:
        try:
            return foliatura.fijar(cx, _entero(numero, "página"),
                                   pet.cuerpo_json().get("foja"))
        except ValueError as e:
            raise ErrorHTTP(400, str(e))
    finally:
        cx.close()


def api_foliatura(pet, slug: str) -> dict:
    cx = _cx(slug)
    try:
        if pet.metodo == "POST":
            c = pet.cuerpo_json()
            if c.get("accion") == "detectar":
                return {**foliatura.detectar(cx), **foliatura.resumen(cx)}
            n = foliatura.confirmar_tramo(cx, _entero(c.get("desde"), "desde"),
                                          _entero(c.get("hasta"), "hasta"))
            return {"confirmadas": n, **foliatura.resumen(cx)}
        return foliatura.resumen(cx)
    finally:
        cx.close()


def api_evidencias(pet, slug: str) -> dict:
    cx = _cx(slug)
    try:
        if pet.metodo == "POST":
            c = pet.cuerpo_json()
            try:
                return modelo.crear_manual(
                    cx, pagina_inicio=_entero(c.get("pagina_inicio"), "pagina_inicio"),
                    pagina_fin=_entero(c.get("pagina_fin"), "pagina_fin", None),
                    tipo=c.get("tipo"), descripcion=c.get("descripcion", ""),
                    foja_inicio=c.get("foja_inicio"), foja_fin=c.get("foja_fin"),
                    observaciones=c.get("observaciones"),
                    estado=c.get("estado", "pendiente"), grupo_id=c.get("grupo_id"),
                    x0=c.get("x0"), y0=c.get("y0"), x1=c.get("x1"), y1=c.get("y1"))
            except modelo.OperacionInvalida as e:
                raise ErrorHTTP(400, str(e))
        return modelo.listar(
            cx, filtro=pet.consulta("filtro", "todas"),
            orden=pet.consulta("orden", "manual"), texto=pet.consulta("q"),
            grupo_id=(_entero(pet.consulta("grupo"), "grupo", 0) or None)
                     if pet.consulta("grupo") not in (None, "") else None,
            tipo=pet.consulta("tipo"),
            desde=_entero(pet.consulta("desde"), "desde", 0),
            limite=min(500, _entero(pet.consulta("limite"), "limite", 200)))
    finally:
        cx.close()


def api_evidencia(pet, slug: str, eid: str) -> dict:
    cx = _cx(slug)
    try:
        i = _entero(eid, "evidencia")
        try:
            if pet.metodo == "PATCH":
                return modelo.editar(cx, i, pet.cuerpo_json())
            return modelo.obtener(cx, i)
        except modelo.EvidenciaNoEncontrada:
            raise ErrorHTTP(404, f"no existe la evidencia {i}")
        except modelo.OperacionInvalida as e:
            raise ErrorHTTP(400, str(e))
    finally:
        cx.close()


def api_evidencia_accion(pet, slug: str, eid: str, accion: str) -> dict:
    cx = _cx(slug)
    try:
        i = _entero(eid, "evidencia")
        c = pet.cuerpo_json()
        try:
            if accion == "estado":
                return modelo.decidir(cx, i, c.get("estado", ""))
            if accion == "dividir":
                return modelo.dividir(cx, i, _entero(c.get("pagina_corte"), "pagina_corte"))
            if accion == "descartar":
                return modelo.descartar(cx, i)
            if accion == "restaurar":
                return modelo.restaurar(cx, i)
            if accion == "deshacer":
                return modelo.deshacer(cx, i)
            if accion == "grupo":
                return modelo.asignar_grupo(cx, i, c.get("grupo_id"))
            if accion == "historial":
                return {"historial": modelo.historial(cx, i)}
            if accion == "etiqueta":
                if pet.metodo == "DELETE":
                    return grupos.desetiquetar(cx, i, _entero(c.get("etiqueta_id"), "etiqueta"))
                return grupos.etiquetar(cx, i, c.get("nombre", ""))
            if accion == "testigo":
                if pet.metodo == "DELETE":
                    return personas.desasociar(cx, i, _entero(c.get("persona_id"), "persona"))
                persona = (personas.buscar_o_crear(cx, c["nombre"], rol=c.get("rol"),
                                                   detalle=c.get("detalle"))
                           if c.get("nombre") else {"id": _entero(c.get("persona_id"), "persona")})
                return personas.asociar(cx, i, persona["id"],
                                        c.get("funcion", "introductor"))
        except modelo.EvidenciaNoEncontrada:
            raise ErrorHTTP(404, f"no existe la evidencia {i}")
        except (modelo.OperacionInvalida, personas.PersonaInvalida,
                grupos.GrupoInvalido) as e:
            raise ErrorHTTP(400, str(e))
        raise ErrorHTTP(404, f"acción desconocida: {accion}")
    finally:
        cx.close()


def api_evidencias_lote(pet, slug: str, accion: str) -> dict:
    cx = _cx(slug)
    try:
        c = pet.cuerpo_json()
        ids = [int(i) for i in (c.get("ids") or [])]
        try:
            if accion == "estado":
                return modelo.decidir_varias(cx, ids, c.get("estado", ""))
            if accion == "orden":
                return modelo.reordenar(cx, ids,
                                        dentro_del_grupo=bool(c.get("dentro_del_grupo")))
            if accion == "unir":
                return modelo.unir(cx, ids)
            if accion == "grupo":
                return grupos.mover_varias(cx, ids, c.get("grupo_id"))
            if accion == "testigo":
                persona = (personas.buscar_o_crear(cx, c["nombre"], rol=c.get("rol"),
                                                   detalle=c.get("detalle"))
                           if c.get("nombre") else {"id": _entero(c.get("persona_id"), "persona")})
                return personas.asignar_testigo_varias(cx, ids, persona["id"])
        except (modelo.OperacionInvalida, personas.PersonaInvalida) as e:
            raise ErrorHTTP(400, str(e))
        raise ErrorHTTP(404, f"acción desconocida: {accion}")
    finally:
        cx.close()


def api_detectar(pet, slug: str) -> dict:
    cx = _cx(slug)
    try:
        if pet.cuerpo_json().get("rehacer"):
            # Rehacer borra lo detectado automáticamente que nadie decidió todavía. Lo
            # que una persona ya incluyó o excluyó NO se toca: el trabajo de revisión no
            # se pierde por volver a correr la detección.
            cx.execute("""UPDATE evidencia SET activa=0
                           WHERE origen='automatica' AND estado='pendiente' AND activa=1""")
            cx.commit()
        return {**deteccion.detectar(cx), **duplicados.detectar(cx),
                "contadores": modelo.contadores(cx)}
    finally:
        cx.close()


def api_grupos(pet, slug: str) -> dict:
    cx = _cx(slug)
    try:
        try:
            if pet.metodo == "POST":
                c = pet.cuerpo_json()
                return grupos.crear(cx, c.get("nombre", ""), descripcion=c.get("descripcion"),
                                    color=c.get("color"), encabezado=c.get("encabezado"))
            return {"grupos": grupos.listar(cx), "etiquetas": grupos.etiquetas(cx)}
        except grupos.GrupoInvalido as e:
            raise ErrorHTTP(400, str(e))
    finally:
        cx.close()


def api_grupo(pet, slug: str, gid: str) -> dict:
    cx = _cx(slug)
    try:
        i = _entero(gid, "grupo")
        try:
            if pet.metodo == "DELETE":
                return grupos.borrar(cx, i)
            return grupos.actualizar(cx, i, **pet.cuerpo_json())
        except grupos.GrupoInvalido as e:
            raise ErrorHTTP(400, str(e))
        except KeyError:
            raise ErrorHTTP(404, f"no existe el grupo {i}")
    finally:
        cx.close()


def api_grupos_orden(pet, slug: str) -> dict:
    cx = _cx(slug)
    try:
        return grupos.reordenar(cx, [int(i) for i in pet.cuerpo_json().get("ids") or []])
    finally:
        cx.close()


def api_personas(pet, slug: str) -> dict:
    cx = _cx(slug)
    try:
        try:
            if pet.metodo == "POST":
                c = pet.cuerpo_json()
                return personas.buscar_o_crear(cx, c.get("nombre", ""), rol=c.get("rol"),
                                               detalle=c.get("detalle"),
                                               documento=c.get("documento"))
            return {"personas": personas.listar(cx),
                    "fusiones": personas.fusiones_pendientes(cx)}
        except personas.PersonaInvalida as e:
            raise ErrorHTTP(400, str(e))
    finally:
        cx.close()


def api_persona(pet, slug: str, pid: str) -> dict:
    cx = _cx(slug)
    try:
        i = _entero(pid, "persona")
        try:
            if pet.metodo == "DELETE":
                return personas.borrar(cx, i)
            return personas.actualizar(cx, i, **pet.cuerpo_json())
        except personas.PersonaInvalida as e:
            raise ErrorHTTP(400, str(e))
        except KeyError:
            raise ErrorHTTP(404, f"no existe la persona {i}")
    finally:
        cx.close()


def api_testigos(pet, slug: str) -> dict:
    cx = _cx(slug)
    try:
        return {"testigos": personas.por_testigo(
            cx, solo_incluidas=pet.consulta("solo_incluidas") == "1")}
    finally:
        cx.close()


def api_fusiones(pet, slug: str) -> dict:
    cx = _cx(slug)
    try:
        c = pet.cuerpo_json()
        accion = c.get("accion")
        if accion == "proponer":
            return {**personas.proponer_fusiones(cx),
                    "fusiones": personas.fusiones_pendientes(cx)}
        if accion == "rechazar":
            return personas.rechazar_fusion(cx, _entero(c.get("id"), "id"))
        if accion == "aceptar":
            try:
                return personas.fusionar(cx, _entero(c.get("id"), "id"),
                                         quedarse_con=_entero(c.get("quedarse_con"), "quedarse_con"))
            except personas.PersonaInvalida as e:
                raise ErrorHTTP(400, str(e))
        raise ErrorHTTP(400, "acción desconocida")
    finally:
        cx.close()


def api_duplicados(pet, slug: str) -> dict:
    cx = _cx(slug)
    try:
        if pet.metodo == "POST":
            c = pet.cuerpo_json()
            if c.get("accion") == "detectar":
                return {**duplicados.detectar(cx), "duplicados": duplicados.listar(cx)}
            return duplicados.descartar(cx, _entero(c.get("id"), "id"))
        return {"duplicados": duplicados.listar(cx)}
    finally:
        cx.close()


def api_buscar(pet, slug: str) -> dict:
    cx = _cx(slug)
    try:
        return busqueda.buscar(cx, pet.consulta("q", ""))
    finally:
        cx.close()


def api_punteo(pet, slug: str) -> dict:
    cx = _cx(slug)
    try:
        if pet.metodo == "POST":
            c = pet.cuerpo_json()
            try:
                return generacion.generar(
                    cx, criterio=c.get("criterio", "manual"),
                    con_encabezados=c.get("con_encabezados", True),
                    numeracion=c.get("numeracion", "continua"),
                    plantilla=c.get("plantilla"),
                    exigir_foja_confirmada=c.get("exigir_foja_confirmada", True))
            except generacion.NadaQueGenerar as e:
                raise ErrorHTTP(409, str(e))
            except generacion.EvidenciaNoIncluida as e:
                # Que esto llegue acá significa que la primera barrera falló y la
                # atajó la segunda. Es un error del sistema: 500, y con el detalle.
                raise ErrorHTTP(500, str(e))
            except ValueError as e:
                raise ErrorHTTP(400, str(e))
        try:
            return {**generacion.leer(cx), "revalidacion": generacion.revalidar(cx)}
        except KeyError:
            raise ErrorHTTP(404, "todavía no se generó ningún punteo")
    finally:
        cx.close()


def api_punteo_verificar(pet, slug: str) -> dict:
    cx = _cx(slug)
    try:
        return generacion.verificar(cx)
    finally:
        cx.close()


def api_punteo_parrafo(pet, slug: str, pid: str) -> dict:
    cx = _cx(slug)
    try:
        try:
            return generacion.editar_parrafo(cx, _entero(pid, "párrafo"),
                                             pet.cuerpo_json().get("texto"))
        except KeyError:
            raise ErrorHTTP(404, f"no existe el párrafo {pid}")
    finally:
        cx.close()


# ═══════════════════════════════════════════════════════════════ la tabla ══
# (método, patrón, función). El orden importa: gana el primero que pega.
RUTAS = [
    ("GET",    r"/api/estado$",                                  api_estado),
    ("GET",    r"/api/catalogo$",                                api_catalogo),
    ("*",      r"/api/casos$",                                   api_casos),
    ("*",      r"/api/caso/([\w-]+)$",                           api_caso),
    ("*",      r"/api/caso/([\w-]+)/documentos$",                api_documentos),
    ("POST",   r"/api/caso/([\w-]+)/documentos/orden$",          api_documentos_orden),
    ("POST",   r"/api/caso/([\w-]+)/procesar$",                  api_procesar),
    ("POST",   r"/api/caso/([\w-]+)/procesar/detener$",          api_detener),
    ("GET",    r"/api/caso/([\w-]+)/progreso$",                  api_progreso),
    ("GET",    r"/api/caso/([\w-]+)/paginas$",                   api_paginas),
    ("GET",    r"/api/caso/([\w-]+)/pagina/(\d+)$",              api_pagina),
    ("POST",   r"/api/caso/([\w-]+)/pagina/(\d+)/foja$",         api_pagina_foja),
    ("*",      r"/api/caso/([\w-]+)/foliatura$",                 api_foliatura),
    ("POST",   r"/api/caso/([\w-]+)/detectar$",                  api_detectar),
    ("*",      r"/api/caso/([\w-]+)/evidencias$",                api_evidencias),
    ("*",      r"/api/caso/([\w-]+)/evidencias/(\w+)$",          api_evidencias_lote),
    ("*",      r"/api/caso/([\w-]+)/evidencia/(\d+)$",           api_evidencia),
    ("*",      r"/api/caso/([\w-]+)/evidencia/(\d+)/(\w+)$",     api_evidencia_accion),
    ("POST",   r"/api/caso/([\w-]+)/grupos/orden$",              api_grupos_orden),
    ("*",      r"/api/caso/([\w-]+)/grupos$",                    api_grupos),
    ("*",      r"/api/caso/([\w-]+)/grupo/(\d+)$",               api_grupo),
    ("*",      r"/api/caso/([\w-]+)/personas$",                  api_personas),
    ("*",      r"/api/caso/([\w-]+)/persona/(\d+)$",             api_persona),
    ("POST",   r"/api/caso/([\w-]+)/fusiones$",                  api_fusiones),
    ("GET",    r"/api/caso/([\w-]+)/testigos$",                  api_testigos),
    ("*",      r"/api/caso/([\w-]+)/duplicados$",                api_duplicados),
    ("GET",    r"/api/caso/([\w-]+)/buscar$",                    api_buscar),
    ("GET",    r"/api/caso/([\w-]+)/punteo/verificar$",          api_punteo_verificar),
    ("PATCH",  r"/api/caso/([\w-]+)/punteo/parrafo/(\d+)$",      api_punteo_parrafo),
    ("*",      r"/api/caso/([\w-]+)/punteo$",                    api_punteo),
]
RUTAS = [(m, re.compile(p), f) for m, p, f in RUTAS]


class Manejador(BaseHTTPRequestHandler):
    server_version = "Punteo"
    protocol_version = "HTTP/1.1"

    # ── ayudas para los manejadores ──
    @property
    def metodo(self) -> str:
        return self.command

    def cabecera(self, nombre: str, por_omision: str = "") -> str:
        return self.headers.get(nombre) or por_omision

    def consulta(self, nombre: str, por_omision=None):
        return self._consulta.get(nombre, [por_omision])[0]

    def cuerpo_json(self) -> dict:
        if not self.cuerpo:
            return {}
        try:
            datos = json.loads(self.cuerpo.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ErrorHTTP(400, "el cuerpo del pedido no es JSON válido")
        return datos if isinstance(datos, dict) else {"valor": datos}

    # ── el despacho ──
    def do_GET(self):    self._atender()
    def do_POST(self):   self._atender()
    def do_PATCH(self):  self._atender()
    def do_DELETE(self): self._atender()

    def _atender(self):
        partido = urlparse(self.path)
        ruta = unquote(partido.path)
        self._consulta = parse_qs(partido.query)
        largo = int(self.headers.get("Content-Length") or 0)
        self.cuerpo = self.rfile.read(largo) if largo else b""

        try:
            # Las dos rutas que no devuelven JSON se atienden antes de la tabla.
            m = re.fullmatch(r"/api/caso/([\w-]+)/pagina/(\d+)/imagen", ruta)
            if m and self.command == "GET":
                return self._imagen(m.group(1), int(m.group(2)))
            m = re.fullmatch(r"/api/caso/([\w-]+)/punteo/exportar", ruta)
            if m and self.command == "GET":
                return self._exportar(m.group(1), self.consulta("formato", "rtf"))

            for metodo, patron, fn in RUTAS:
                encontrado = patron.fullmatch(ruta)
                if not encontrado:
                    continue
                if metodo != "*" and metodo != self.command:
                    continue
                return self._json(200, fn(self, *encontrado.groups()))

            if ruta.startswith("/api/"):
                raise ErrorHTTP(404, f"no existe {ruta}")
            return self._estatico(ruta)

        except ErrorHTTP as e:
            self._json(e.codigo, {"error": e.mensaje})
        except BrokenPipeError:
            pass                       # el navegador cerró; no es un error del servidor
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    # ── respuestas ──
    def _json(self, codigo: int, datos) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _binario(self, datos: bytes, mime: str, *, descarga: str | None = None,
                 cache: str = "no-store") -> None:
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", cache)
        if descarga:
            self.send_header("Content-Disposition", f'attachment; filename="{descarga}"')
        self.end_headers()
        self.wfile.write(datos)

    def _imagen(self, slug: str, numero: int) -> None:
        cx = _cx(slug)
        try:
            dpi = self.consulta("dpi")
            datos, mime = ocr.imagen_pagina(cx, numero,
                                            dpi=int(dpi) if dpi and dpi.isdigit() else None)
            # La imagen de una página no cambia nunca: el original es inmutable. Se
            # puede cachear fuerte y eso es lo que hace que pasar páginas se sienta
            # instantáneo al volver sobre las que ya se miraron.
            self._binario(datos, mime, cache="private, max-age=86400")
        except KeyError:
            self._json(404, {"error": f"no hay página {numero}"})
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"error": f"no se pudo rasterizar la página: {e}"})
        finally:
            cx.close()

    def _exportar(self, slug: str, formato: str) -> None:
        cx = _cx(slug)
        try:
            datos, nombre, mime = exportacion.contenido(cx, formato)
            self._binario(datos, mime, descarga=nombre)
        except exportacion.PunteoDesactualizado as e:
            self._json(409, {"error": str(e)})
        except KeyError:
            self._json(404, {"error": "todavía no se generó ningún punteo"})
        except ValueError as e:
            self._json(400, {"error": str(e)})
        finally:
            cx.close()

    ESTATICOS = {"/": "index.html", "": "index.html"}

    def _estatico(self, ruta: str) -> None:
        if ruta.startswith("/fuentes/"):
            base, nombre = Path(config.FUENTES), ruta[len("/fuentes/"):]
        else:
            base = Path(config.WEB)
            nombre = self.ESTATICOS.get(ruta, ruta.lstrip("/"))
        destino = (base / nombre).resolve()
        # `..` en la ruta alcanza para leer cualquier archivo del disco. Se comprueba
        # después de resolver, que es lo único que sirve: comprobar antes se saltea con
        # una codificación distinta.
        if not str(destino).startswith(str(base.resolve())) or not destino.is_file():
            return self._json(404, {"error": f"no existe {ruta}"})
        mime = mimetypes.guess_type(destino.name)[0] or "application/octet-stream"
        if mime.startswith("text/") or mime in ("application/javascript",):
            mime += "; charset=utf-8"
        cache = "public, max-age=604800" if ruta.startswith("/fuentes/") else "no-store"
        self._binario(destino.read_bytes(), mime, cache=cache)

    def log_message(self, formato, *args):
        """
        Registro mínimo: método, ruta, código. NUNCA contenido de documentos ni texto
        OCR. En un legajo penal, el log es otro lugar donde el legajo se puede filtrar.
        """
        print(f"  {self.command:<6} {self.path.split('?')[0]:<52} {args[1] if len(args) > 1 else ''}")


def servir(puerto: int | None = None, host: str | None = None) -> None:
    puerto = puerto or config.PUERTO
    host = host or config.HOST
    config.carpeta_casos().mkdir(parents=True, exist_ok=True)
    servidor = ThreadingHTTPServer((host, puerto), Manejador)
    servidor.daemon_threads = True
    print(f"Punteo de Evidencia — http://{host}:{puerto}")
    print(f"  datos en {config.DATOS}")
    if host != "127.0.0.1":
        print("  ATENCIÓN: está escuchando fuera de esta máquina.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nchau")
    finally:
        servidor.server_close()
