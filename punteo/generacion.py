"""
El generador del punteo.

ESTA ES LA REGLA CRÍTICA DEL SISTEMA:

    el generador recibe únicamente evidencias cuyo estado es INCLUIDA.

Nunca vuelve a analizar el expediente, nunca agrega nada por su cuenta, y nunca
reordena: la salida se construye desde datos estructurados que una persona revisó, en
el orden que esa persona aprobó.

La invariante `EXCLUIDO = IMPOSIBLE QUE APAREZCA EN LA SALIDA` se sostiene con tres
barreras que fallan por separado, y las tres tienen que quedar en pie:

  1. **en la base** — la vista `v_evidencia_incluida` filtra por estado y por `activa`,
     y es lo único que este módulo consulta;
  2. **en el código** — `_verificar_incluida` revisa el estado de CADA pieza antes de
     escribirla, aunque ya venga filtrada de la vista. La redundancia se paga sola: las
     dos barreras las escriben caminos distintos y si una queda mal, la otra sigue;
  3. **en las pruebas** — `pruebas/test_invariante.py`, que no se borra.

La segunda mitad de la invariante importa igual: si una persona corrigió la
descripción, la foja o el testigo, la salida usa **el valor corregido**. Un sistema que
respeta la exclusión pero imprime la descripción vieja falla por el otro lado. Eso lo
garantiza `v_evidencia`, que resuelve `COALESCE(final, detectado)` y es de donde sale
`v_evidencia_incluida`.
"""
from __future__ import annotations

import sqlite3

from . import db
from .evidencia import catalogo
from .evidencia.modelo import cita_fojas, como_dict

CRITERIOS = {
    "manual": "Orden manual",
    "grupos": "Por sectores",
    "cronologico": "Cronológico",
    "tipo": "Por tipo de prueba",
    "testigo": "Por testigo introductor",
}

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")

ROMANOS = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
           (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))

# Marcadores visibles. Cuando falta un dato, el borrador lo dice con todas las letras en
# lugar de escribir un número plausible que nadie verificó. Quien lea el texto tiene que
# tropezarse con el hueco, no pasarlo por alto.
FALTA_FOJA = "[FOJA PENDIENTE]"
FOJA_A_CONFIRMAR = "[FOJA A CONFIRMAR]"
FALTA_TESTIGO = "[TESTIGO PENDIENTE]"
FOJAS_DISCONTINUAS = "[RANGO DE FOJAS A REVISAR]"

PLANTILLAS = {
    "remision": "{descripcion}{fecha}, obrante a {fojas}{testigo}.",
    "abreviado": "{descripcion}{fecha}, obrante a {fojas}.",
}

# Excepciones por familia de prueba. Existen porque la fórmula general produce una
# frase incorrecta en un caso muy común: «Declaración testimonial de Pérez, obrante a
# fs. 410/412, que será introducida al debate mediante la declaración testimonial de
# Pérez». Una testimonial no se introduce por otra testimonial: ES la prueba, y quien
# declara comparece. Lo mismo con los efectos secuestrados, que se exhiben.
#
# Son plantillas y no `if`: el usuario las puede cambiar desde la pantalla, y lo que
# acá se define es sólo el punto de partida razonable.
PLANTILLAS_POR_FAMILIA = {
    "testimonial": "{descripcion}{fecha}, obrante a {fojas}.",
    "material": "{descripcion}{fecha}, según constancias de {fojas}{testigo}.",
}


class NadaQueGenerar(RuntimeError):
    """No hay ni una pieza marcada para incluir. No es un error: es un estado."""


class EvidenciaNoIncluida(RuntimeError):
    """
    Llegó al generador algo que no está incluido.

    Si esto se levanta alguna vez, la primera barrera falló y la segunda la atajó. Es
    un error del sistema y no del usuario, y por eso rompe fuerte en vez de saltear la
    pieza en silencio.
    """


def romano(n: int) -> str:
    salida = []
    for valor, letra in ROMANOS:
        while n >= valor:
            salida.append(letra)
            n -= valor
    return "".join(salida)


def fecha_en_letras(iso: str | None) -> str:
    """De «2024-03-12» a «12 de marzo de 2024». Vacío si no hay fecha: no se inventa."""
    if not iso:
        return ""
    try:
        a, m, d = (int(x) for x in iso.split("-")[:3])
        return f"{d} de {MESES[m - 1]} de {a}"
    except (ValueError, IndexError):
        return ""


# ─────────────────────────────────────────────────────────── las tres barreras ──
def _incluidas(cx: sqlite3.Connection) -> list[dict]:
    """
    PRIMERA BARRERA. La única consulta de este módulo, y va contra la vista que sólo
    devuelve lo incluido y activo. No hay otra lectura de `evidencia` en todo el archivo.
    """
    return [como_dict(f) for f in cx.execute("SELECT * FROM v_evidencia_incluida")]


# De qué piezas salió una pieza: las partes de una unión y el origen de una división,
# hacia atrás. La consulta está escrita acá y no se importa de `evidencia/modelo.py` a
# propósito: la segunda barrera vale justamente porque es otro código. Si la de allá
# queda mal, ésta sigue en pie.
_ORIGEN_EXCLUIDO = """
WITH RECURSIVE linaje(id) AS (
  SELECT ?
  UNION
  SELECT a.hacia FROM (
      SELECT union_id AS desde, parte_id AS hacia FROM evidencia_parte
      UNION ALL
      SELECT id, origen_id FROM evidencia WHERE origen = 'division' AND origen_id IS NOT NULL
  ) a JOIN linaje l ON a.desde = l.id
)
SELECT e.id FROM evidencia e JOIN linaje l ON l.id = e.id
 WHERE e.id <> ? AND e.estado = 'excluida' ORDER BY e.id"""


def _origen_excluido(cx: sqlite3.Connection, evidencia_id: int) -> list[int]:
    return [r["id"] for r in cx.execute(_ORIGEN_EXCLUIDO, (evidencia_id, evidencia_id))]


def _verificar_incluida(cx: sqlite3.Connection, ev: dict) -> None:
    """
    SEGUNDA BARRERA. Se relee el estado de la pieza desde la tabla, no desde la vista,
    y se exige que siga incluida y activa.

    Es redundante con la vista a propósito. El día que alguien agregue un segundo camino
    de generación, o cambie la vista, o pase una lista armada a mano, esta línea es la
    que evita que una pieza excluida termine en un escrito firmado.

    Y se mira de dónde SALIÓ la pieza. Una unión copia la descripción de su primera parte
    y una división la de su origen: si esa parte o ese origen están excluidos, el estado
    propio de la pieza dice «incluida» y el texto que sale es el que se excluyó.
    """
    fila = cx.execute("SELECT estado, activa FROM evidencia WHERE id=?",
                      (ev["id"],)).fetchone()
    if fila is None or fila["estado"] != "incluida" or not fila["activa"]:
        estado = "inexistente" if fila is None else fila["estado"]
        raise EvidenciaNoIncluida(
            f"la evidencia {ev['id']} llegó al generador con estado «{estado}» "
            f"(activa={fila['activa'] if fila else '—'}). Se abortó la generación.")
    heredado = _origen_excluido(cx, ev["id"])
    if heredado:
        raise EvidenciaNoIncluida(
            f"la evidencia {ev['id']} salió de "
            f"{', '.join(str(i) for i in heredado)}, que está excluida, así que arrastra "
            f"su texto. Se abortó la generación.")


# ────────────────────────────────────────────────────────── chequeo previo ──
def verificar(cx: sqlite3.Connection) -> dict:
    """
    Qué hay que mirar antes de generar. No bloquea: informa.

    Devuelve los números que hacen falta para decidir si el punteo está listo o si
    conviene confirmar fojas y asignar testigos primero.
    """
    tipo_proceso = cx.execute("SELECT tipo_proceso FROM caso WHERE id=1").fetchone()
    tipo_proceso = tipo_proceso["tipo_proceso"] if tipo_proceso else "remision"
    incluidas = _incluidas(cx)
    sin_foja = [e for e in incluidas if not e.get("foja_inicio")]
    # Con foja de inicio pero sin la del final, y de varias páginas: la cita saldría
    # recortada a una sola foja, que es un dato falso y no un dato faltante.
    sin_foja_final = [e for e in incluidas
                      if e.get("foja_inicio") and not e.get("foja_fin")
                      and (e.get("pagina_fin") or 0) > (e.get("pagina_inicio") or 0)]
    foja_floja = [e for e in incluidas if e.get("foja_inicio") and not e.get("foja_firme")]
    # Confirmadas, pero con un número que se dedujo de la serie en lugar de leerse en el
    # papel. No bloquea: se dice, que es lo que corresponde con una conjetura probada.
    foja_interpolada = [e for e in incluidas if e.get("foja_firme") and e.get("foja_interpolada")]
    # Extremos que no son la misma serie: adentro del rango arranca otra foliatura.
    discontinuas = [e for e in incluidas if rango_discontinuo(cx, e)]
    sin_testigo = [e for e in incluidas if not e.get("testigo")]
    contadores = dict(cx.execute("SELECT * FROM v_contadores").fetchone())
    return {
        "tipo_proceso": tipo_proceso,
        "incluidas": len(incluidas),
        "pendientes": contadores["pendientes"],
        "sin_foja": [{"id": e["id"], "descripcion": e["descripcion"]} for e in sin_foja],
        "sin_foja_final": [{"id": e["id"], "descripcion": e["descripcion"],
                            "foja": e["foja_inicio"]} for e in sin_foja_final],
        "foja_sin_confirmar": [{"id": e["id"], "descripcion": e["descripcion"],
                                "foja": e["foja_inicio"]} for e in foja_floja],
        "foja_interpolada": [{"id": e["id"], "descripcion": e["descripcion"],
                              "foja": e["foja_inicio"]} for e in foja_interpolada],
        "fojas_discontinuas": [{"id": e["id"], "descripcion": e["descripcion"],
                                "foja": e["foja_inicio"]} for e in discontinuas],
        # En abreviado el testigo introductor no es obligatorio, así que no se informa
        # como faltante: sería ruido en la mitad de los casos.
        "sin_testigo": ([{"id": e["id"], "descripcion": e["descripcion"]}
                         for e in sin_testigo] if tipo_proceso == "remision" else []),
        "listo": bool(incluidas) and not sin_foja and not sin_foja_final
                 and not (tipo_proceso == "remision" and sin_testigo),
    }


# ───────────────────────────────────────────────────────────── el armado ──
def rango_discontinuo(cx: sqlite3.Connection, ev: dict) -> bool:
    """
    ¿Las fojas de las páginas de esta pieza forman una serie?

    Entre dos páginas foliadas el número puede repetirse —«411» y «411 vta.»— o crecer,
    pero nunca hacia atrás ni más de lo que hay páginas en el medio. Si crece de más,
    adentro del rango empieza otro tramo de foliatura, y una cita «fs. 400/402» escrita
    con los extremos confirmados tapa que en el medio hay una foja 900.

    Si los dos extremos los escribió una persona, no se controla: ahí el rango lo afirmó
    ella y el sistema no tiene nada mejor que aportar.
    """
    if ev.get("foja_origen") == "manual" and ev.get("foja_fin_origen") == "manual":
        return False
    ini = ev.get("pagina_inicio")
    fin = ev.get("pagina_fin") or ini
    if not ini or fin <= ini:
        return False
    filas = cx.execute("""SELECT numero_global, foja_num FROM pagina
                           WHERE numero_global BETWEEN ? AND ? AND foja_num IS NOT NULL
                           ORDER BY numero_global""", (ini, fin)).fetchall()
    for anterior, siguiente in zip(filas, filas[1:]):
        salto = siguiente["foja_num"] - anterior["foja_num"]
        paginas = siguiente["numero_global"] - anterior["numero_global"]
        if salto < 0 or salto > paginas:
            return True
    return False


def _fojas_de(ev: dict, exigir_confirmada: bool, discontinuo: bool = False) -> str:
    cita = cita_fojas(ev)
    if not ev.get("foja_inicio"):
        return f"fs. {FALTA_FOJA}"
    if discontinuo:
        # Los extremos pueden estar confirmados y el medio no ser la misma serie. La cita
        # se escribe igual —los dos números son los que son— con la marca que avisa que
        # entre uno y otro hay foliatura que no sigue.
        cita = f"{cita} {FOJAS_DISCONTINUAS}"
    if exigir_confirmada and not ev.get("foja_firme"):
        # Alguno de los dos extremos lo puso la máquina. Se escribe con la marca al lado
        # para que no llegue a un escrito como si alguien lo hubiera verificado: confirmar
        # la foja donde la pieza empieza no dice nada sobre la foja donde termina.
        return f"{cita} {FOJA_A_CONFIRMAR}"
    return cita


def _frase_testigo(ev: dict, tipo_proceso: str) -> str:
    if tipo_proceso != "remision":
        return ""
    testigo = ev.get("testigo") or FALTA_TESTIGO
    return f", que será introducida al debate mediante la declaración testimonial de {testigo}"


def _parrafo(ev: dict, tipo_proceso: str, plantilla: str, exigir_confirmada: bool,
             discontinuo: bool = False) -> str:
    fecha = fecha_en_letras(ev.get("fecha_documento"))
    # La familia manda sobre la plantilla general, salvo que el usuario haya escrito una
    # plantilla propia: si la eligió a mano, es la que vale para todo.
    if plantilla in PLANTILLAS.values():
        plantilla = PLANTILLAS_POR_FAMILIA.get(catalogo.familia(ev.get("tipo")), plantilla)
    return plantilla.format(
        descripcion=(ev.get("descripcion") or "").strip().rstrip("."),
        fecha=f", de fecha {fecha}" if fecha else "",
        fojas=_fojas_de(ev, exigir_confirmada, discontinuo),
        testigo=_frase_testigo(ev, tipo_proceso),
        tipo=catalogo.etiqueta(ev.get("tipo")),
    ).replace("  ", " ")


def _clave_grupo(ev: dict, criterio: str) -> tuple:
    """
    Por qué se agrupa cada pieza, según el criterio elegido. Devuelve (orden, clave,
    encabezado). El orden es lo que decide la posición del bloque en la salida.
    """
    if criterio == "grupos":
        return (ev.get("grupo_orden") if ev.get("grupo_id") else 9999,
                ev.get("grupo_id") or 0,
                (ev.get("grupo_nombre") or "Sin agrupar"))
    if criterio == "tipo":
        fam = catalogo.familia(ev.get("tipo"))
        return (0, fam, catalogo.FAMILIAS.get(fam, "Otra"))
    if criterio == "testigo":
        return (1 if not ev.get("testigo") else 0, ev.get("testigo") or "",
                ev.get("testigo") or "Sin testigo asignado")
    return (0, "", "")


def _ordenar(evidencias: list[dict], criterio: str) -> list[dict]:
    """
    El orden que pidió la persona. Nada más que eso.

    El generador NO reordena por su cuenta: esta función aplica el criterio que el
    usuario eligió en la pantalla, y `manual` respeta tal cual el `orden_salida` que
    quedó del arrastre.
    """
    if criterio == "cronologico":
        # Sin fecha va al final. No se le inventa una para poder ordenar: en la salida
        # esa pieza aparece igual, y la falta de fecha se ve.
        return sorted(evidencias, key=lambda e: (e.get("fecha_documento") is None,
                                                 e.get("fecha_documento") or "",
                                                 e.get("pagina_inicio") or 0))
    if criterio in ("grupos", "tipo", "testigo"):
        return sorted(evidencias, key=lambda e: (_clave_grupo(e, criterio)[:2],
                                                 e.get("orden_en_grupo") or 0,
                                                 e.get("orden_salida") or 0,
                                                 e.get("pagina_inicio") or 0))
    return sorted(evidencias, key=lambda e: (e.get("orden_salida") or 0,
                                             e.get("pagina_inicio") or 0))


def generar(cx: sqlite3.Connection, *, criterio: str = "manual",
            con_encabezados: bool = True, numeracion: str = "continua",
            plantilla: str | None = None,
            exigir_foja_confirmada: bool = True) -> dict:
    """
    Arma el punteo y lo guarda como lista de párrafos.

    No se guarda como una cadena: cada párrafo conserva de qué evidencia salió, que es
    lo que sostiene poder editar el texto final sin perder la trazabilidad
    `párrafo ↔ evidencia`. Aplanar todo a un TEXTAREA la rompe en el primer guardado.
    """
    # El armado —que es donde está la segunda barrera— y el guardado van adentro del
    # mismo candado. Separados, otra pestaña podía excluir una pieza después de que la
    # barrera la diera por buena y antes de escribirla, y el punteo salía con ella.
    db.candado_de_escritura(cx)
    try:
        parrafos, ajustes = _armar(cx, criterio=criterio, con_encabezados=con_encabezados,
                                   numeracion=numeracion, plantilla=plantilla,
                                   exigir_foja_confirmada=exigir_foja_confirmada)
        punteo_id, ediciones = _escribir(cx, parrafos, ajustes)
    except Exception:
        # Si una barrera corta en la mitad del armado, no puede quedar un punteo con la
        # mitad de las piezas: eso se exporta igual y nadie ve que le falta un renglón.
        cx.rollback()
        raise
    cx.commit()
    return {**leer(cx, punteo_id), **ediciones}


def _armar(cx: sqlite3.Connection, *, criterio: str, con_encabezados: bool,
           numeracion: str, plantilla: str | None,
           exigir_foja_confirmada: bool) -> tuple[list[dict], dict]:
    """
    El punteo, como lista de párrafos, SIN escribir nada.

    Está separado del guardado para que `revalidar` pueda volver a armarlo con los mismos
    parámetros y compararlo con lo guardado. Ahí está la única forma honesta de contestar
    «¿este texto sigue diciendo lo que dicen las piezas hoy?»: rearmarlo y mirar. Una
    lista de campos a comparar se queda vieja el día que alguien agrega uno.
    """
    if criterio not in CRITERIOS:
        raise ValueError(f"criterio desconocido: {criterio!r}")
    caso = cx.execute("SELECT tipo_proceso FROM caso WHERE id=1").fetchone()
    tipo_proceso = caso["tipo_proceso"] if caso else "remision"
    # La plantilla ELEGIDA se guarda como vino, y `None` significa «la que corresponda al
    # tipo de proceso». Guardar la ya resuelta escondía un cambio real: pasar el caso de
    # abreviado a remisión no cambiaba el texto rearmado —la plantilla vieja ni siquiera
    # tiene lugar para el testigo— y el punteo del proceso anterior pasaba por actual.
    efectiva = plantilla or PLANTILLAS.get(tipo_proceso, PLANTILLAS["remision"])

    evidencias = _ordenar(_incluidas(cx), criterio)
    if not evidencias:
        raise NadaQueGenerar("no hay ninguna evidencia marcada para incluir")

    agrupa = con_encabezados and criterio in ("grupos", "tipo", "testigo")
    parrafos: list[dict] = []
    numero_pieza = numero_grupo = 0
    grupo_actual = None

    for ev in evidencias:
        # SEGUNDA BARRERA, por pieza y justo antes de escribirla.
        _verificar_incluida(cx, ev)

        if agrupa:
            clave = _clave_grupo(ev, criterio)[1]
            if clave != grupo_actual:
                grupo_actual = clave
                numero_grupo += 1
                if numeracion == "por_grupo":
                    numero_pieza = 0
                parrafos.append({"clase": "encabezado", "evidencia_id": None,
                                 "clave_grupo": str(clave),
                                 "numero": f"{romano(numero_grupo)}.-",
                                 "texto_generado": _encabezado_de(cx, ev, criterio).upper()})

        numero_pieza += 1
        parrafos.append({"clase": "pieza", "evidencia_id": ev["id"], "clave_grupo": None,
                         "numero": f"{numero_pieza}.-",
                         "texto_generado": _parrafo(ev, tipo_proceso, efectiva,
                                                    exigir_foja_confirmada,
                                                    rango_discontinuo(cx, ev))})

    ajustes = {"criterio": criterio, "con_encabezados": 1 if con_encabezados else 0,
               "numeracion": numeracion, "plantilla": plantilla,
               "exigir_foja_confirmada": 1 if exigir_foja_confirmada else 0,
               "total_piezas": len(evidencias)}
    return parrafos, ajustes


def _escribir(cx: sqlite3.Connection, parrafos: list[dict], ajustes: dict) -> tuple[int, dict]:
    """
    Guarda el punteo armado y arrastra las ediciones a mano que siguen valiendo.

    Un párrafo editado se traslada al punteo nuevo sólo si su texto generado es idéntico,
    o sea si la pieza no cambió en nada que salga al escrito. Si cambió, la edición se
    queda en el punteo anterior —que no se borra— y no se copia: arrastrarla sería
    reescribir el dato viejo arriba del corregido, que es justamente lo que se está
    arreglando. Se informa cuántas quedaron atrás para que nadie las dé por perdidas.
    """
    # La identidad de un párrafo es la pieza de la que salió; la de un encabezado, el
    # sector. Sin la segunda, dos sectores con el mismo encabezado se llevaban la edición
    # del otro: los encabezados no tienen `evidencia_id` y la clave quedaba sólo en su
    # texto. Un encabezado viejo sin clave guardada no arrastra nada, que es lo correcto
    # cuando no se puede saber de cuál era.
    previas = {}
    anterior = cx.execute(
        "SELECT id FROM punteo_generado ORDER BY id DESC LIMIT 1").fetchone()
    if anterior:
        for p in cx.execute("""SELECT clase, evidencia_id, clave_grupo, texto_generado,
                                      texto_final
                                 FROM punteo_parrafo
                                WHERE punteo_id=? AND texto_final IS NOT NULL""",
                            (anterior["id"],)):
            if p["clase"] == "encabezado" and p["clave_grupo"] is None:
                continue
            previas[(p["clase"], p["evidencia_id"], p["clave_grupo"],
                     p["texto_generado"])] = p["texto_final"]

    punteo_id = cx.execute(
        """INSERT INTO punteo_generado (criterio, con_encabezados, numeracion, plantilla,
                                        exigir_foja_confirmada, total_piezas, generado_en)
           VALUES (?,?,?,?,?,?,?)""",
        (ajustes["criterio"], ajustes["con_encabezados"], ajustes["numeracion"],
         ajustes["plantilla"], ajustes["exigir_foja_confirmada"],
         ajustes["total_piezas"], db.ahora())).lastrowid

    trasladadas = 0
    for orden, p in enumerate(parrafos, start=1):
        clave = (p["clase"], p["evidencia_id"], p.get("clave_grupo"), p["texto_generado"])
        texto_final = previas.pop(clave, None)
        trasladadas += 1 if texto_final is not None else 0
        cx.execute("""INSERT INTO punteo_parrafo (punteo_id, orden, clase, evidencia_id,
                                                  clave_grupo, numero, texto_generado,
                                                  texto_final)
                      VALUES (?,?,?,?,?,?,?,?)""",
                   (punteo_id, orden, p["clase"], p["evidencia_id"], p.get("clave_grupo"),
                    p["numero"], p["texto_generado"], texto_final))

    return punteo_id, {"ediciones_trasladadas": trasladadas,
                       "ediciones_no_trasladadas": len(previas)}


def _encabezado_de(cx: sqlite3.Connection, ev: dict, criterio: str) -> str:
    """
    El texto del encabezado del bloque. El del grupo manda sobre el nombre.

    Son dos campos distintos porque el nombre que sirve para trabajar —«Banco ERíos»—
    no es el que va en el escrito —«EVIDENCIA REMITIDA POR EL NUEVO BANCO DE ENTRE
    RÍOS S.A.»—, y obligar a elegir uno solo termina en una de las dos pantallas mal.
    """
    if criterio == "grupos" and ev.get("grupo_id"):
        fila = cx.execute("SELECT nombre, encabezado FROM grupo_evidencia WHERE id=?",
                          (ev["grupo_id"],)).fetchone()
        if fila:
            return (fila["encabezado"] or fila["nombre"]).strip()
    return _clave_grupo(ev, criterio)[2]


# ──────────────────────────────────────────────────── leer, editar, exportar ──
def leer(cx: sqlite3.Connection, punteo_id: int | None = None) -> dict:
    """El último punteo generado, o uno en particular."""
    if punteo_id is None:
        fila = cx.execute("SELECT id FROM punteo_generado ORDER BY id DESC LIMIT 1").fetchone()
        if not fila:
            raise KeyError("todavía no se generó ningún punteo")
        punteo_id = fila["id"]
    cab = cx.execute("SELECT * FROM punteo_generado WHERE id=?", (punteo_id,)).fetchone()
    if not cab:
        raise KeyError(punteo_id)
    parrafos = [dict(r) for r in cx.execute("""
        SELECT p.*, COALESCE(p.texto_final, p.texto_generado) AS texto,
               (p.texto_final IS NOT NULL) AS editado,
               e.descripcion, e.foja_inicio, e.foja_fin, e.estado AS evidencia_estado
          FROM punteo_parrafo p
          LEFT JOIN v_evidencia e ON e.id = p.evidencia_id
         WHERE p.punteo_id=? ORDER BY p.orden""", (punteo_id,))]
    return {**dict(cab), "criterio_etiqueta": CRITERIOS.get(cab["criterio"], cab["criterio"]),
            "parrafos": parrafos}


def editar_parrafo(cx: sqlite3.Connection, parrafo_id: int, texto: str | None) -> dict:
    """
    Cambia el texto de un párrafo del punteo, sin perder de qué evidencia salió.

    Con `texto` vacío vuelve al generado, que es lo que hace falta cuando alguien editó
    de más y quiere el original: el texto generado no se pisa nunca.
    """
    fila = cx.execute("SELECT punteo_id, evidencia_id FROM punteo_parrafo WHERE id=?",
                      (parrafo_id,)).fetchone()
    if not fila:
        raise KeyError(parrafo_id)
    texto = (texto or "").strip() or None
    cx.execute("UPDATE punteo_parrafo SET texto_final=? WHERE id=?", (texto, parrafo_id))
    if fila["evidencia_id"]:
        cx.execute("""INSERT INTO revision (evidencia_id, campo, valor_anterior,
                                            valor_nuevo, detalle, cuando)
                      VALUES (?, 'texto_punteo', NULL, ?, ?, ?)""",
                   (fila["evidencia_id"], texto, f"párrafo {parrafo_id}", db.ahora()))
    cx.commit()
    return leer(cx, fila["punteo_id"])


def como_texto(cx: sqlite3.Connection, punteo_id: int | None = None) -> str:
    """El punteo en texto plano, listo para copiar al portapapeles."""
    punteo = leer(cx, punteo_id)
    lineas: list[str] = []
    for p in punteo["parrafos"]:
        if p["clase"] == "encabezado":
            if lineas:
                lineas.append("")
            lineas.append(f"{p['numero']} {p['texto']}")
            lineas.append("")
        else:
            lineas.append(f"{p['numero']} {p['texto']}")
    return "\n".join(lineas).strip() + "\n"


def revalidar(cx: sqlite3.Connection, punteo_id: int | None = None) -> dict:
    """
    ¿El punteo guardado sigue diciendo lo que dicen las piezas hoy?

    Existe por un agujero concreto: se genera el punteo, después alguien cambia algo, y
    el texto guardado sigue siendo el de antes. Excluir una pieza era el caso conocido,
    pero corregir una descripción, confirmar una foja, asignar un testigo o cambiar el
    orden tienen exactamente el mismo efecto y no se veían: el archivo salía con el dato
    viejo y con cara de estar al día.

    La comprobación es rearmar el punteo con los mismos parámetros y comparar. Enumerar
    qué campos mirar sería empezar una lista que se queda vieja el día que alguien
    agregue uno.

    El texto no se actualiza solo —sería pisarle la edición a quien lo esté
    corrigiendo—: se avisa, y la exportación se niega.
    """
    punteo = leer(cx, punteo_id)
    desactualizados = []
    for p in punteo["parrafos"]:
        if p["clase"] != "pieza" or not p["evidencia_id"]:
            continue
        fila = cx.execute("SELECT estado, activa FROM evidencia WHERE id=?",
                          (p["evidencia_id"],)).fetchone()
        if fila is None or fila["estado"] != "incluida" or not fila["activa"]:
            desactualizados.append({
                "parrafo_id": p["id"], "evidencia_id": p["evidencia_id"],
                "numero": p["numero"], "texto": p["texto"][:90],
                "estado_actual": fila["estado"] if fila else "borrada"})
        elif _origen_excluido(cx, p["evidencia_id"]):
            desactualizados.append({
                "parrafo_id": p["id"], "evidencia_id": p["evidencia_id"],
                "numero": p["numero"], "texto": p["texto"][:90],
                "estado_actual": "arrastra material excluido"})
    nuevas = cx.execute("""SELECT COUNT(*) FROM v_evidencia_incluida
                            WHERE id NOT IN (SELECT COALESCE(evidencia_id, -1)
                                               FROM punteo_parrafo WHERE punteo_id=?)""",
                        (punteo["id"],)).fetchone()[0]

    try:
        ahora, _ = _armar(cx, criterio=punteo["criterio"],
                          con_encabezados=bool(punteo["con_encabezados"]),
                          numeracion=punteo["numeracion"], plantilla=punteo["plantilla"],
                          exigir_foja_confirmada=bool(punteo["exigir_foja_confirmada"]))
    except (NadaQueGenerar, EvidenciaNoIncluida):
        # Rearmar puede ser imposible: no quedó nada incluido, o una pieza arrastra
        # material excluido. Las dos cosas significan que el punteo guardado no está al
        # día, que es lo que esta función contesta; el detalle ya está en
        # `desactualizados`. Acá se informa, no se aborta: abortar dejaría la pantalla
        # del punteo sin poder abrirse justo cuando hay algo que arreglar.
        ahora = []

    clave = lambda p: (p["clase"], p["evidencia_id"], p["numero"], p["texto_generado"])
    guardado = [clave(p) for p in punteo["parrafos"]]
    rearmado = [clave(p) for p in ahora]

    # Qué cambió, párrafo por párrafo, para poder decirlo con el texto a la vista.
    nuevo_por_evidencia = {p["evidencia_id"]: p for p in ahora if p["clase"] == "pieza"}
    cambiados = []
    for p in punteo["parrafos"]:
        if p["clase"] != "pieza" or not p["evidencia_id"]:
            continue
        equivalente = nuevo_por_evidencia.get(p["evidencia_id"])
        if equivalente and equivalente["texto_generado"] != p["texto_generado"]:
            cambiados.append({"parrafo_id": p["id"], "evidencia_id": p["evidencia_id"],
                              "numero": p["numero"],
                              "texto": p["texto_generado"][:90],
                              "ahora": equivalente["texto_generado"][:90],
                              "editado": bool(p["editado"])})
    reordenado = (not desactualizados and not cambiados and not nuevas
                  and guardado != rearmado)
    return {"punteo_id": punteo["id"],
            "al_dia": guardado == rearmado and not desactualizados and not nuevas,
            "desactualizados": desactualizados, "cambiados": cambiados,
            "reordenado": reordenado, "incluidas_nuevas": nuevas}
