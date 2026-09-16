"""
El modelo de evidencia: listar, decidir, editar, dividir, unir, crear a mano.

Tres reglas gobiernan todo este módulo:

  * **lo detectado no se pisa.** Lo que corrige una persona va a las columnas `_final`;
    las `_detectada` se escriben una sola vez, al detectar. Toda lectura pasa por
    `v_evidencia`, que resuelve cuál vale;
  * **no se borra nada.** Dividir, unir y descartar apagan la fila (`activa = 0`) y
    dejan el rastro, para poder contestar «¿de dónde salió esta pieza?» y para deshacer;
  * **cada cambio deja una fila en `revision`.** Append-only: corregir dos veces no
    puede borrar la explicación de la primera corrección.
"""
from __future__ import annotations

import json
import sqlite3

from .. import config, db
from . import catalogo

ESTADOS = ("pendiente", "incluida", "excluida")

# Campos que una persona puede editar, y a qué columna van. El mapa existe para que la
# API no pueda escribir una columna que no corresponde: lo que no está acá, no se toca.
CAMPOS_EDITABLES = {
    "descripcion": "descripcion_final",
    "tipo": "tipo_final",
    "subtipo": "subtipo_final",
    "foja_inicio": "foja_inicio_final",
    "foja_fin": "foja_fin_final",
    "observaciones": "observaciones",
    "fecha_documento": "fecha_documento",
}


class EvidenciaNoEncontrada(KeyError):
    pass


class OperacionInvalida(ValueError):
    pass


def _anotar(cx: sqlite3.Connection, evidencia_id: int | None, campo: str,
            anterior, nuevo, detalle: str | None = None) -> None:
    cx.execute("""INSERT INTO revision (evidencia_id, campo, valor_anterior, valor_nuevo,
                                        detalle, cuando)
                  VALUES (?,?,?,?,?,?)""",
               (evidencia_id, campo,
                None if anterior is None else str(anterior),
                None if nuevo is None else str(nuevo), detalle, db.ahora()))


def _fila(cx: sqlite3.Connection, evidencia_id: int) -> sqlite3.Row:
    f = cx.execute("SELECT * FROM v_evidencia WHERE id=?", (evidencia_id,)).fetchone()
    if not f:
        raise EvidenciaNoEncontrada(evidencia_id)
    return f


# Las aristas de la genealogía de una pieza: de una unión a cada una de sus partes, y de
# una mitad a la pieza que se dividió. `_ARRIBA` va hacia atrás —de qué salió ésta— y
# `_ABAJO` hacia adelante —qué salió de ésta—.
#
# Las aristas van en una subconsulta para que la parte recursiva nombre al CTE una sola
# vez, que es lo que acepta cualquier SQLite y no sólo los nuevos. Y el recorrido usa
# `UNION` y no `UNION ALL` para que una genealogía con un ciclo —deshacer y volver a unir
# lo mismo— termine en lugar de girar para siempre.
_ARRIBA = """SELECT union_id AS desde, parte_id AS hacia FROM evidencia_parte
             UNION ALL
             SELECT id, origen_id FROM evidencia
              WHERE origen = 'division' AND origen_id IS NOT NULL"""
_ABAJO = """SELECT parte_id AS desde, union_id AS hacia FROM evidencia_parte
            UNION ALL
            SELECT origen_id, id FROM evidencia
             WHERE origen = 'division' AND origen_id IS NOT NULL"""

_GENEALOGIA = """
WITH RECURSIVE rama(id) AS (
  SELECT ?
  UNION
  SELECT a.hacia FROM ({aristas}) a JOIN rama r ON a.desde = r.id
)
SELECT e.id FROM evidencia e JOIN rama r ON r.id = e.id
 WHERE e.id <> ? AND {condicion} ORDER BY e.id"""

_LINAJE_EXCLUIDO = _GENEALOGIA.format(aristas=_ARRIBA, condicion="e.estado = 'excluida'")
_DERIVADAS_ACTIVAS = _GENEALOGIA.format(aristas=_ABAJO, condicion="e.activa = 1")
_DERIVADAS = _GENEALOGIA.format(aristas=_ABAJO, condicion="1 = 1")


def procedencia_excluida(cx: sqlite3.Connection, evidencia_id: int) -> list[int]:
    """
    Las piezas excluidas de las que salió ésta, por unión o por división.

    Una pieza nueva hereda las páginas, el texto y la descripción de lo que la formó. Si
    algo de eso estaba excluido, incluirla es sacar por la ventana lo que se excluyó por
    la puerta: la descripción de la excluida llega al escrito con otro número de pieza.
    """
    return [r["id"] for r in cx.execute(_LINAJE_EXCLUIDO, (evidencia_id, evidencia_id))]


def derivadas_activas(cx: sqlite3.Connection, evidencia_id: int,
                      excepto: tuple[int, ...] = ()) -> list[int]:
    """
    Qué piezas activas salieron de ésta, en toda la cadena: la unión que la absorbió, la
    unión que absorbió a esa unión, las mitades en que se partió.

    Es lo que hay que mirar antes de volver a encender una fila: si lo que salió de ella
    sigue en la lista, encenderla pone la misma prueba dos veces en el escrito.
    """
    fuera = set(excepto)
    return [r["id"] for r in cx.execute(_DERIVADAS_ACTIVAS, (evidencia_id, evidencia_id))
            if r["id"] not in fuera]


# Lo que apagó o encendió una fila. Sirve para contestar POR QUÉ está apagada, que es
# distinto de saber que lo está: una descartada se restaura, una absorbida por una unión
# se recupera deshaciendo esa unión.
_EVENTOS_DE_APAGADO = ("descarte", "restauracion", "union", "division",
                       "deshacer_union", "deshacer_division")


def representa_sus_paginas(cx: sqlite3.Connection, evidencia_id: int, activa: bool) -> bool:
    """
    ¿Esta fila sigue hablando por las páginas de su rango?

    Sí cuando está activa, cuando una persona la descartó —descartar es decir «eso no es
    una pieza», y esa decisión vale— y cuando lo que salió de ella sigue en pie, activo
    o descartado: una parte absorbida por una unión está representada por esa unión, y
    si la unión se descartó, el descarte alcanza también a las partes. Sin esto último,
    descartar una unión de dos PDF devolvía a la lista las páginas del segundo, porque
    la unión sólo cubre las de su propio documento.

    No cuando la apagó un `deshacer` o una redetección: ahí la fila es un rastro del
    historial y sus páginas las representa otra. Contarla igual hacía desaparecer de la
    lista una pieza vecina que su rango tocaba de paso.
    """
    if activa or _descartada(cx, evidencia_id):
        return True
    for r in cx.execute(_DERIVADAS, (evidencia_id, evidencia_id)).fetchall():
        fila = cx.execute("SELECT activa FROM evidencia WHERE id=?", (r["id"],)).fetchone()
        if fila["activa"] or _descartada(cx, r["id"]):
            return True
    return False


def _descartada(cx: sqlite3.Connection, evidencia_id: int) -> bool:
    return _por_que_apagada(cx, evidencia_id) == "descarte"


def _por_que_apagada(cx: sqlite3.Connection, evidencia_id: int) -> str | None:
    fila = cx.execute(
        f"""SELECT campo FROM revision WHERE evidencia_id = ?
             AND campo IN ({','.join('?' * len(_EVENTOS_DE_APAGADO))})
           ORDER BY id DESC LIMIT 1""",
        (evidencia_id, *_EVENTOS_DE_APAGADO)).fetchone()
    return fila["campo"] if fila else None


def _exigir_procedencia_limpia(cx: sqlite3.Connection, evidencia_id: int) -> None:
    excluidas = procedencia_excluida(cx, evidencia_id)
    if excluidas:
        raise OperacionInvalida(
            f"la pieza #{evidencia_id} contiene material de "
            f"{', '.join(f'#{i}' for i in excluidas)}, que está excluida: no se puede "
            f"incluir. Deshacé la unión o la división y decidí de nuevo sobre las partes")


def nivel_confianza(valor: float | None) -> str:
    if valor is None:
        return "manual"
    if valor >= config.CONFIANZA_ALTA:
        return "alta"
    return "media" if valor >= config.CONFIANZA_MEDIA else "baja"


def como_dict(fila: sqlite3.Row) -> dict:
    """Una evidencia lista para la interfaz, con todo lo derivado ya resuelto."""
    d = dict(fila)
    d["tipo_etiqueta"] = catalogo.etiqueta(d.get("tipo"))
    d["familia"] = catalogo.familia(d.get("tipo"))
    d["confianza_nivel"] = nivel_confianza(d.get("confianza"))
    try:
        d["advertencias"] = json.loads(d.get("advertencias") or "[]")
    except (TypeError, ValueError):
        d["advertencias"] = []
    # Estas dos advertencias se calculan al vuelo y NO se guardan, a propósito: hablan
    # del estado de ahora, no del momento de la detección. Guardadas quedarían viejas
    # apenas alguien confirme una foja o asigne un testigo, y una advertencia vieja es
    # peor que ninguna porque se deja de mirar.
    if d.get("foja_origen") in ("desconocida", "detectada"):
        d["advertencias"] = d["advertencias"] + ["foja_sin_confirmar"]
    if not d.get("foja_inicio"):
        d["advertencias"] = d["advertencias"] + ["sin_foja"]
    d["modificada"] = bool(d.get("modificada"))
    d["activa"] = bool(d.get("activa"))
    if d.get("pagina_inicio") and d.get("pagina_fin"):
        d["paginas"] = d["pagina_fin"] - d["pagina_inicio"] + 1
    return d


def cita_fojas(fila) -> str:
    """
    Cómo se cita el rango en el escrito: «fs. 342/346», «fs. 411», «fs. 411 vta.».

    Si no hay foja, NO inventa una a partir de la página: devuelve el marcador visible
    que corresponde, para que quien lea el borrador vea que ahí falta un dato y no un
    número plausible.
    """
    ini = (fila["foja_inicio"] if not isinstance(fila, dict) else fila.get("foja_inicio"))
    fin = (fila["foja_fin"] if not isinstance(fila, dict) else fila.get("foja_fin"))
    if not ini:
        return "fs. [FOJA PENDIENTE]"
    return f"fs. {ini}" if not fin or fin == ini else f"fs. {ini}/{fin}"


# ─────────────────────────────────────────────────────────────────── listar ──
_ORDENES = {
    "manual":      "orden_salida, pagina_inicio",
    "pagina":      "pagina_inicio, id",
    "grupos":      "grupo_orden IS NULL, grupo_orden, orden_en_grupo, pagina_inicio",
    # `fecha_documento IS NULL` primero: lo que no tiene fecha cierta va al final y se
    # muestra como SIN FECHA. Inventarle una para poder ordenar sería lo contrario de
    # lo que este sistema hace.
    "cronologico": "fecha_documento IS NULL, fecha_documento, pagina_inicio",
    "tipo":        "tipo IS NULL, tipo, pagina_inicio",
    "testigo":     "testigo IS NULL, testigo, pagina_inicio",
}

_FILTROS = {
    "incluidas":   "estado = 'incluida'",
    "excluidas":   "estado = 'excluida'",
    "pendientes":  "estado = 'pendiente'",
    "sin_testigo": "testigo IS NULL",
    "sin_foja":    "foja_inicio IS NULL",
    "foja_sin_confirmar": "foja_origen IN ('desconocida','detectada')",
    "baja_confianza": f"confianza IS NOT NULL AND confianza < {config.CONFIANZA_MEDIA}",
    "modificadas": "modificada",
    "manuales":    "origen = 'manual'",
    "duplicados":  ("id IN (SELECT evidencia_a FROM duplicado_posible WHERE estado='abierto'"
                    " UNION SELECT evidencia_b FROM duplicado_posible WHERE estado='abierto')"),
}


def listar(cx: sqlite3.Connection, *, filtro: str = "todas", orden: str = "manual",
           texto: str | None = None, grupo_id: int | None = None,
           tipo: str | None = None, desde: int = 0, limite: int = 200) -> dict:
    """
    El checklist. Paginado siempre: una lista de ochocientas piezas en el DOM es lo que
    convierte una herramienta rápida en una que hay que esperar.
    """
    condiciones = ["activa = 1"]
    params: list = []
    if filtro in _FILTROS:
        condiciones.append(_FILTROS[filtro])
    if grupo_id is not None:
        condiciones.append("grupo_id = ?" if grupo_id else "grupo_id IS NULL")
        if grupo_id:
            params.append(grupo_id)
    if tipo:
        condiciones.append("tipo = ?")
        params.append(tipo)
    if texto:
        condiciones.append("(descripcion LIKE ? OR texto_origen LIKE ? OR testigo LIKE ?)")
        params += [f"%{texto}%"] * 3

    donde = " AND ".join(condiciones)
    total = cx.execute(f"SELECT COUNT(*) FROM v_evidencia WHERE {donde}", params).fetchone()[0]
    filas = cx.execute(
        f"SELECT * FROM v_evidencia WHERE {donde} "
        f"ORDER BY {_ORDENES.get(orden, _ORDENES['manual'])} LIMIT ? OFFSET ?",
        (*params, limite, desde)).fetchall()
    return {"total": total, "desde": desde, "limite": limite,
            "evidencias": [como_dict(f) for f in filas]}


def obtener(cx: sqlite3.Connection, evidencia_id: int) -> dict:
    d = como_dict(_fila(cx, evidencia_id))
    d["personas"] = [dict(r) for r in cx.execute("""
        SELECT p.id, p.nombre, p.rol, p.detalle, ep.funcion
          FROM evidencia_persona ep JOIN persona p ON p.id = ep.persona_id
         WHERE ep.evidencia_id = ? ORDER BY ep.funcion, p.nombre""", (evidencia_id,))]
    d["etiquetas"] = [dict(r) for r in cx.execute("""
        SELECT e.id, e.nombre, e.color FROM evidencia_etiqueta ee
          JOIN etiqueta e ON e.id = ee.etiqueta_id
         WHERE ee.evidencia_id = ? ORDER BY e.nombre""", (evidencia_id,))]
    d["duplicados"] = [dict(r) for r in cx.execute("""
        SELECT d.id, d.score, d.motivo,
               CASE WHEN d.evidencia_a=? THEN d.evidencia_b ELSE d.evidencia_a END AS otra_id
          FROM duplicado_posible d
         WHERE (d.evidencia_a=? OR d.evidencia_b=?) AND d.estado='abierto'""",
        (evidencia_id, evidencia_id, evidencia_id))]
    return d


def historial(cx: sqlite3.Connection, evidencia_id: int) -> list[dict]:
    return [dict(r) for r in cx.execute(
        "SELECT * FROM revision WHERE evidencia_id=? ORDER BY id DESC", (evidencia_id,))]


# ────────────────────────────────────────────────────────────────── decidir ──
def decidir(cx: sqlite3.Connection, evidencia_id: int, estado: str) -> dict:
    """Incluir, excluir o dejar pendiente. Es LA decisión del sistema."""
    if estado not in ESTADOS:
        raise OperacionInvalida(f"estado desconocido: {estado!r}")
    previo = _fila(cx, evidencia_id)
    if not previo["activa"]:
        raise OperacionInvalida("esta pieza está apagada: salió de una división o una unión")
    if estado == "incluida":
        _exigir_procedencia_limpia(cx, evidencia_id)
    if previo["estado"] != estado:
        # La condición viaja en el UPDATE y no queda sólo en la lectura de arriba: entre
        # una cosa y la otra, otra pestaña o el procesamiento de fondo pueden haber
        # apagado la pieza, y contestar «guardado» sobre una fila que ya no está en la
        # lista es la peor forma de fallar: la decisión se pierde sin que nadie lo sepa.
        cur = cx.execute("""UPDATE evidencia SET estado=?, decidido_en=?, actualizado_en=?
                             WHERE id=? AND activa=1""",
                         (estado, db.ahora(), db.ahora(), evidencia_id))
        if not cur.rowcount:
            cx.rollback()
            raise OperacionInvalida(
                "esta pieza se apagó mientras la decidías: recargá la lista y fijate qué "
                "la reemplazó")
        _anotar(cx, evidencia_id, "estado", previo["estado"], estado)
        cx.commit()
    return obtener(cx, evidencia_id)


def decidir_varias(cx: sqlite3.Connection, ids: list[int], estado: str) -> dict:
    """
    Cambio de estado en lote, para el checklist.

    Sirve para RECTIFICAR, no para decidir por primera vez: la interfaz sólo lo ofrece
    sobre piezas que ya tienen estado. La regla de «no decidir sin ver» se sostiene en
    la pantalla, que es donde puede sostenerse; acá se deja constancia de que el cambio
    fue en lote para que el historial no mienta sobre cómo se tomó.
    """
    if estado not in ESTADOS:
        raise OperacionInvalida(f"estado desconocido: {estado!r}")
    # Se controla todo el lote antes de escribir nada: rechazar a mitad de camino dejaría
    # la mitad de las piezas cambiadas y un mensaje de error que no dice cuáles.
    if estado == "incluida":
        for eid in ids:
            _exigir_procedencia_limpia(cx, eid)
    cambiadas = 0
    for eid in ids:
        try:
            previo = _fila(cx, eid)
        except EvidenciaNoEncontrada:
            continue
        if not previo["activa"] or previo["estado"] == estado:
            continue
        cur = cx.execute("""UPDATE evidencia SET estado=?, decidido_en=?, actualizado_en=?
                             WHERE id=? AND activa=1""",
                         (estado, db.ahora(), db.ahora(), eid))
        if not cur.rowcount:
            continue
        _anotar(cx, eid, "estado", previo["estado"], estado, detalle="cambio en lote")
        cambiadas += 1
    cx.commit()
    return {"cambiadas": cambiadas, "estado": estado}


# ─────────────────────────────────────────────────────────────────── editar ──
def editar(cx: sqlite3.Connection, evidencia_id: int, campos: dict) -> dict:
    """
    Corrige lo que detectó la máquina. Escribe en las columnas `_final`.

    Pasar `None` o cadena vacía en un campo lo devuelve a lo detectado, que es distinto
    de dejarlo en blanco: es «no lo corrijo más, vale lo que leyó el sistema».
    """
    previo = _fila(cx, evidencia_id)
    aplicados = {}
    for campo, valor in campos.items():
        columna = CAMPOS_EDITABLES.get(campo)
        if not columna:
            continue
        if isinstance(valor, str):
            valor = valor.strip() or None
        anterior = previo[campo] if campo in previo.keys() else None
        if campo == "tipo" and valor and valor not in catalogo.POR_CLAVE:
            raise OperacionInvalida(f"tipo desconocido: {valor!r}")
        cur = cx.execute(f"UPDATE evidencia SET {columna}=?, actualizado_en=? "
                         f"WHERE id=? AND activa=1", (valor, db.ahora(), evidencia_id))
        if not cur.rowcount:
            cx.rollback()
            raise OperacionInvalida(
                "esta pieza está apagada: la corrección no se guardó. Recargá la lista")
        _anotar(cx, evidencia_id, campo, anterior, valor)
        aplicados[campo] = valor
    if aplicados:
        cx.commit()
    return obtener(cx, evidencia_id)


def asignar_grupo(cx: sqlite3.Connection, evidencia_id: int, grupo_id: int | None) -> dict:
    previo = _fila(cx, evidencia_id)
    orden = cx.execute("""SELECT COALESCE(MAX(orden_en_grupo), 0) + 1 FROM evidencia
                           WHERE grupo_id IS ?""", (grupo_id,)).fetchone()[0]
    cx.execute("UPDATE evidencia SET grupo_id=?, orden_en_grupo=?, actualizado_en=? WHERE id=?",
               (grupo_id, orden, db.ahora(), evidencia_id))
    _anotar(cx, evidencia_id, "grupo", previo["grupo_nombre"], grupo_id)
    cx.commit()
    return obtener(cx, evidencia_id)


def reordenar(cx: sqlite3.Connection, ids: list[int], *, dentro_del_grupo: bool = False) -> dict:
    """
    Fija el orden que eligió la persona. El generador lo respeta tal cual.

    Es la operación que sostiene «el generador nunca cambia por sí solo el orden
    aprobado»: acá se escribe, y en `generacion.py` se lee sin volver a ordenar.

    Queda anotado en `revision`, y no es prolijidad: elegir el orden del escrito es
    trabajo de una persona, y lo que no deja rastro en el historial es lo que la
    redetección da por descartable y reemplaza.
    """
    columna = "orden_en_grupo" if dentro_del_grupo else "orden_salida"
    movidas = 0
    for posicion, eid in enumerate(ids, start=1):
        previo = cx.execute(f"SELECT {columna} FROM evidencia WHERE id=?", (eid,)).fetchone()
        if previo is None or previo[columna] == posicion:
            continue
        cx.execute(f"UPDATE evidencia SET {columna}=?, actualizado_en=? WHERE id=?",
                   (posicion, db.ahora(), eid))
        _anotar(cx, eid, "orden", previo[columna], posicion, detalle=columna)
        movidas += 1
    cx.commit()
    return {"reordenadas": movidas, "criterio": columna}


# ────────────────────────────────────────────────────── crear, dividir, unir ──
def crear_manual(cx: sqlite3.Connection, *, pagina_inicio: int, pagina_fin: int | None = None,
                 tipo: str | None = None, descripcion: str = "",
                 foja_inicio: str | None = None, foja_fin: str | None = None,
                 observaciones: str | None = None, estado: str = "pendiente",
                 grupo_id: int | None = None,
                 x0=None, y0=None, x1=None, y1=None) -> dict:
    """
    La evidencia que el sistema no detectó y una persona carga a mano.

    Es indispensable: la detección nunca va a encontrar todo. Y se integra exactamente
    igual que la automática —mismo checklist, mismo generador, mismo orden— salvo en una
    cosa: no tiene confianza, porque no hay nada que medir en algo que escribió una
    persona. En la pantalla eso se ve como «manual», no como «confianza desconocida».
    """
    pagina_fin = pagina_fin or pagina_inicio
    if pagina_fin < pagina_inicio:
        raise OperacionInvalida("la página final es anterior a la inicial")
    if estado not in ESTADOS:
        raise OperacionInvalida(f"estado desconocido: {estado!r}")
    if tipo and tipo not in catalogo.POR_CLAVE:
        raise OperacionInvalida(f"tipo desconocido: {tipo!r}")
    if not (descripcion or "").strip():
        raise OperacionInvalida("una evidencia cargada a mano necesita una descripción")

    pag = cx.execute("SELECT documento_id FROM pagina WHERE numero_global=?",
                     (pagina_inicio,)).fetchone()
    orden = cx.execute("SELECT COALESCE(MAX(orden_salida), 0) + 1 FROM evidencia").fetchone()[0]
    eid = cx.execute("""
        INSERT INTO evidencia (documento_id, pagina_inicio, pagina_fin, x0, y0, x1, y1,
                               tipo_final, descripcion_final, foja_inicio_final,
                               foja_fin_final, observaciones, estado, origen,
                               confianza, advertencias, grupo_id, orden_salida, creado_en)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'manual',NULL,'[]',?,?,?)""",
        (pag["documento_id"] if pag else None, pagina_inicio, pagina_fin,
         x0, y0, x1, y1, tipo, descripcion.strip(), foja_inicio, foja_fin,
         observaciones, estado, grupo_id, orden, db.ahora())).lastrowid
    _anotar(cx, eid, "alta", None, descripcion.strip(), detalle="cargada a mano")
    cx.commit()
    return obtener(cx, eid)


def dividir(cx: sqlite3.Connection, evidencia_id: int, pagina_corte: int) -> dict:
    """
    Parte una pieza en dos. `pagina_corte` es la PRIMERA página de la segunda mitad.

    El caso típico es un oficio con su respuesta incorporada inmediatamente después: la
    detección ve un título y corta una vez, pero son dos piezas y se ofrecen distinto.

    **Las dos mitades nacen `pendiente`, aunque la original estuviera incluida.** Es
    deliberado y vale escribir por qué: dividir cambia QUÉ ES cada pieza, así que la
    decisión anterior no se aplica a ninguna de las dos. Heredar «incluida» significaría
    que una mitad que la persona nunca miró entra al escrito porque el todo estaba
    aprobado. Entre dos teclas de más y una pieza ofrecida sin leer, el sistema elige
    las dos teclas.

    **Una pieza excluida no se divide.** Las mitades heredan su descripción y su texto, y
    como nacen pendientes, incluir una sacaría al escrito lo que la persona excluyó. Se
    pide volverla a pendiente primero, que es una decisión que queda en el historial.
    """
    previo = _fila(cx, evidencia_id)
    if not previo["activa"]:
        raise OperacionInvalida("esta pieza ya está apagada")
    if previo["estado"] == "excluida" or procedencia_excluida(cx, evidencia_id):
        raise OperacionInvalida(
            f"la pieza #{evidencia_id} está excluida o salió de una excluida: pasala a "
            f"pendiente antes de dividirla")
    ini, fin = previo["pagina_inicio"], previo["pagina_fin"]
    if ini is None or fin is None:
        raise OperacionInvalida("la pieza no tiene rango de páginas")
    if not (ini < pagina_corte <= fin):
        raise OperacionInvalida(
            f"el corte tiene que caer dentro del rango (páginas {ini} a {fin}) "
            f"y no en la primera página")

    ahora = db.ahora()
    nuevas = []
    for desde, hasta, sufijo in ((ini, pagina_corte - 1, "(primera parte)"),
                                 (pagina_corte, fin, "(segunda parte)")):
        fi = cx.execute("SELECT foja_etiqueta FROM pagina WHERE numero_global=?",
                        (desde,)).fetchone()
        ff = cx.execute("SELECT foja_etiqueta FROM pagina WHERE numero_global=?",
                        (hasta,)).fetchone()
        texto = _texto_de_paginas(cx, desde, hasta)
        eid = cx.execute("""
            INSERT INTO evidencia (documento_id, pagina_inicio, pagina_fin, texto_origen,
                                   tipo_detectado, descripcion_detectada,
                                   foja_inicio_detectada, foja_fin_detectada,
                                   tipo_final, observaciones,
                                   estado, origen, origen_id, confianza, advertencias,
                                   grupo_id, orden_salida, fecha_documento, creado_en)
            VALUES (?,?,?,?,?,?,?,?,?,?,'pendiente','division',?,?,?,?,?,?,?)""",
            (previo["documento_id"], desde, hasta, texto,
             previo["tipo_detectado"], f"{previo['descripcion']} {sufijo}".strip(),
             fi["foja_etiqueta"] if fi else None, ff["foja_etiqueta"] if ff else None,
             previo["tipo"], previo["observaciones"],
             evidencia_id, previo["confianza"], previo["advertencias"] or "[]",
             previo["grupo_id"], previo["orden_salida"], previo["fecha_documento"],
             ahora)).lastrowid
        # Las personas asociadas se copian a las dos mitades: el testigo que introduce
        # un acta introduce las dos partes del acta. Es más fácil sacar una que
        # acordarse de volver a poner las dos.
        cx.execute("""INSERT INTO evidencia_persona (evidencia_id, persona_id, funcion)
                      SELECT ?, persona_id, funcion FROM evidencia_persona
                       WHERE evidencia_id = ?""", (eid, evidencia_id))
        _anotar(cx, eid, "alta", None, f"páginas {desde}-{hasta}",
                detalle=f"división de la evidencia {evidencia_id}")
        nuevas.append(eid)

    cx.execute("UPDATE evidencia SET activa=0, actualizado_en=? WHERE id=?", (ahora, evidencia_id))
    _anotar(cx, evidencia_id, "division", f"páginas {ini}-{fin}",
            f"{nuevas[0]} y {nuevas[1]}", detalle=f"corte en la página {pagina_corte}")
    cx.commit()
    return {"origen": evidencia_id, "nuevas": [obtener(cx, e) for e in nuevas]}


def unir(cx: sqlite3.Connection, ids: list[int]) -> dict:
    """
    Junta varias piezas en una. Las partes quedan apagadas pero enteras.

    Igual que la división: la unión nace `pendiente`.

    **Una pieza excluida no se une.** La primera versión lo permitía con una advertencia
    (`union_con_excluida`) y la advertencia no alcanzaba: la unión copia la descripción
    de su primera parte, así que excluir A, unirla con B e incluir la unión sacaba al
    escrito la descripción de A con A todavía excluida. Una advertencia se lee por encima
    en la pieza número trescientos; una barrera no.
    """
    if len(ids) < 2:
        raise OperacionInvalida("hacen falta al menos dos piezas para unir")
    filas = [_fila(cx, i) for i in ids]
    if any(not f["activa"] for f in filas):
        raise OperacionInvalida("alguna de las piezas ya está apagada")
    if any(f["pagina_inicio"] is None for f in filas):
        raise OperacionInvalida("alguna de las piezas no tiene rango de páginas")
    excluidas = [f["id"] for f in filas
                 if f["estado"] == "excluida" or procedencia_excluida(cx, f["id"])]
    if excluidas:
        raise OperacionInvalida(
            f"no se puede unir: {', '.join(f'#{i}' for i in excluidas)} está excluida o "
            f"salió de una excluida. Pasala a pendiente primero: unirla metería en una "
            f"pieza nueva texto que se decidió no ofrecer")

    filas.sort(key=lambda f: f["pagina_inicio"])
    ini = min(f["pagina_inicio"] for f in filas)
    fin = max(f["pagina_fin"] or f["pagina_inicio"] for f in filas)
    ahora = db.ahora()

    adv = []
    if len({f["tipo"] for f in filas}) > 1:
        adv.append("union_de_tipos_distintos")

    fi = cx.execute("SELECT foja_etiqueta FROM pagina WHERE numero_global=?", (ini,)).fetchone()
    ff = cx.execute("SELECT foja_etiqueta FROM pagina WHERE numero_global=?", (fin,)).fetchone()
    eid = cx.execute("""
        INSERT INTO evidencia (documento_id, pagina_inicio, pagina_fin, texto_origen,
                               tipo_detectado, descripcion_detectada,
                               foja_inicio_detectada, foja_fin_detectada, tipo_final,
                               estado, origen, confianza, advertencias, grupo_id,
                               orden_salida, fecha_documento, creado_en)
        VALUES (?,?,?,?,?,?,?,?,?,'pendiente','union',?,?,?,?,?,?)""",
        (filas[0]["documento_id"], ini, fin, _texto_de_paginas(cx, ini, fin),
         filas[0]["tipo_detectado"], filas[0]["descripcion"],
         fi["foja_etiqueta"] if fi else None, ff["foja_etiqueta"] if ff else None,
         filas[0]["tipo"],
         min((f["confianza"] for f in filas if f["confianza"] is not None), default=None),
         json.dumps(adv, ensure_ascii=False), filas[0]["grupo_id"],
         filas[0]["orden_salida"],
         next((f["fecha_documento"] for f in filas if f["fecha_documento"]), None),
         ahora)).lastrowid

    for orden, f in enumerate(filas):
        cx.execute("""INSERT INTO evidencia_parte (union_id, parte_id, orden)
                      VALUES (?,?,?)""", (eid, f["id"], orden))
        cx.execute("""INSERT OR IGNORE INTO evidencia_persona (evidencia_id, persona_id, funcion)
                      SELECT ?, persona_id, funcion FROM evidencia_persona
                       WHERE evidencia_id = ?""", (eid, f["id"]))
        cx.execute("UPDATE evidencia SET activa=0, actualizado_en=? WHERE id=?", (ahora, f["id"]))
        _anotar(cx, f["id"], "union", f["estado"], eid,
                detalle=f"absorbida por la evidencia {eid}")
    _anotar(cx, eid, "alta", None, f"páginas {ini}-{fin}",
            detalle=f"unión de {', '.join(str(f['id']) for f in filas)}")
    cx.commit()
    return obtener(cx, eid)


def deshacer(cx: sqlite3.Connection, evidencia_id: int) -> dict:
    """
    Deshace una división o una unión: apaga lo que salió y vuelve a encender el origen.

    Es la razón por la que no se borra nada. Sin esto, dividir mal una pieza de treinta
    fojas obligaría a rehacerla a mano.
    """
    fila = _fila(cx, evidencia_id)
    ahora = db.ahora()
    if not fila["activa"]:
        # Deshacer sobre una fila ya apagada reencendía lo que estaba adentro de otra
        # pieza que sigue viva: la misma prueba quedaba dos veces en la lista.
        raise OperacionInvalida(
            "esta pieza está apagada: deshacé primero lo que la absorbió, o restaurala si "
            "fue descartada")
    if fila["origen"] == "union":
        partes = [r["parte_id"] for r in cx.execute(
            "SELECT parte_id FROM evidencia_parte WHERE union_id=? ORDER BY orden",
            (evidencia_id,))]
        if not partes:
            raise OperacionInvalida("esta unión no tiene partes registradas")
        for p in partes:
            vivas = derivadas_activas(cx, p, excepto=(evidencia_id, *partes))
            if vivas:
                raise OperacionInvalida(
                    f"la parte #{p} también está adentro de "
                    f"{', '.join(f'#{i}' for i in vivas)}: deshacé eso primero")
        cx.execute("UPDATE evidencia SET activa=0, actualizado_en=? WHERE id=?", (ahora, evidencia_id))
        for p in partes:
            cx.execute("UPDATE evidencia SET activa=1, actualizado_en=? WHERE id=?", (ahora, p))
        _anotar(cx, evidencia_id, "deshacer_union", evidencia_id, ",".join(map(str, partes)))
        cx.commit()
        return {"restauradas": partes, "apagada": evidencia_id}

    if fila["origen"] == "division" and fila["origen_id"]:
        hermanas = [r["id"] for r in cx.execute(
            "SELECT id FROM evidencia WHERE origen='division' AND origen_id=?",
            (fila["origen_id"],))]
        vivas = derivadas_activas(cx, fila["origen_id"], excepto=tuple(hermanas))
        if vivas:
            raise OperacionInvalida(
                f"alguna mitad de esta pieza quedó adentro de "
                f"{', '.join(f'#{i}' for i in vivas)}: deshacé eso primero")
        for h in hermanas:
            cx.execute("UPDATE evidencia SET activa=0, actualizado_en=? WHERE id=?", (ahora, h))
        cx.execute("UPDATE evidencia SET activa=1, actualizado_en=? WHERE id=?",
                   (ahora, fila["origen_id"]))
        _anotar(cx, fila["origen_id"], "deshacer_division",
                ",".join(map(str, hermanas)), fila["origen_id"])
        cx.commit()
        return {"restauradas": [fila["origen_id"]], "apagada": hermanas}

    raise OperacionInvalida("esta pieza no salió de una división ni de una unión")


def descartar(cx: sqlite3.Connection, evidencia_id: int) -> dict:
    """
    Saca una pieza de la lista sin borrarla. Para detecciones espurias: una carátula,
    una hoja en blanco, un separador que el sistema tomó por documento.

    Distinto de `excluida`: excluir es una decisión sobre prueba que existe; descartar
    es decir que eso nunca fue una pieza. En el punteo ninguna de las dos aparece; en la
    pantalla, excluida se cuenta y descartada no.
    """
    fila = _fila(cx, evidencia_id)
    cx.execute("UPDATE evidencia SET activa=0, actualizado_en=? WHERE id=?",
               (db.ahora(), evidencia_id))
    _anotar(cx, evidencia_id, "descarte", fila["estado"], "descartada")
    cx.commit()
    return {"descartada": evidencia_id}


def restaurar(cx: sqlite3.Connection, evidencia_id: int) -> dict:
    """
    Vuelve a encender una pieza DESCARTADA. Nada más que eso.

    `activa = 0` también es lo que queda de una unión o una división, y encender una de
    esas filas por este camino ponía la misma prueba dos veces en la lista —la parte y la
    unión que la contiene— con la decisión vieja de la parte: una pieza incluida hace una
    semana volvía al escrito sin que nadie la mirara. Para eso está `deshacer`.
    """
    fila = _fila(cx, evidencia_id)
    if fila["activa"]:
        return obtener(cx, evidencia_id)
    motivo = _por_que_apagada(cx, evidencia_id)
    if motivo != "descarte":
        raise OperacionInvalida(
            {"union": "esta pieza la absorbió una unión: para recuperarla, deshacé la unión",
             "division": "esta pieza se dividió: para recuperarla, deshacé la división"}
            .get(motivo, "esta pieza no se apagó por un descarte: no se restaura por acá"))
    # Y aunque el último movimiento haya sido un descarte, lo que salió de ella puede
    # seguir vivo por otro camino —una unión de uniones, una mitad absorbida después—.
    vivas = derivadas_activas(cx, evidencia_id)
    if vivas:
        raise OperacionInvalida(
            f"lo que salió de esta pieza sigue en la lista: "
            f"{', '.join(f'#{i}' for i in vivas)}. Restaurarla pondría la misma prueba dos veces")
    cx.execute("UPDATE evidencia SET activa=1, actualizado_en=? WHERE id=?",
               (db.ahora(), evidencia_id))
    _anotar(cx, evidencia_id, "restauracion", "descartada", "activa")
    cx.commit()
    return obtener(cx, evidencia_id)


def _texto_de_paginas(cx: sqlite3.Connection, desde: int, hasta: int) -> str:
    filas = cx.execute("""SELECT texto FROM pagina
                           WHERE numero_global BETWEEN ? AND ? ORDER BY numero_global""",
                       (desde, hasta)).fetchall()
    return " ".join(f["texto"] or "" for f in filas)[:1200]


def contadores(cx: sqlite3.Connection) -> dict:
    return dict(cx.execute("SELECT * FROM v_contadores").fetchone())
