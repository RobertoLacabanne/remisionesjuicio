"""
Detección de piezas de evidencia.

El objetivo NO es resumir el expediente. Es identificar cada pieza probatoria
individualmente, con su rango de páginas, para que una persona la mire y decida.

Cómo corta
----------
Una página empieza una pieza nueva cuando su ENCABEZADO —las primeras líneas, que es
donde va el título de un documento— pega contra algún patrón del catálogo. Si no pega,
la página continúa la pieza anterior.

Está sesgado a CORTAR DE MÁS a propósito. Los dos errores no cuestan lo mismo: un corte
de más produce dos piezas que la persona une con dos clics, y un corte de menos esconde
una pieza adentro de otra, donde nadie la va a ver. En un punteo de prueba, lo segundo
es prueba que se pierde.

Lo que NO hace
--------------
No decide nada. Todo lo que sale de acá nace `pendiente`, con su confianza al lado, y
no entra a ninguna salida hasta que alguien lo marque para incluir.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

from .. import config, db
from ..castellano import sin_tildes
from . import catalogo, modelo

# Cuántas líneas del principio de la página se miran como encabezado. Con tres se
# escapaban los documentos que traen dos renglones de membrete antes del título; con
# ocho empezaba a pegar contra el primer párrafo del cuerpo, que menciona otras piezas.
LINEAS_ENCABEZADO = 6
# Fuerza mínima del patrón para aceptar que acá arranca algo nuevo.
UMBRAL_CORTE = 0.45
# Una pieza más larga que esto se marca. No se parte sola: partir en un número redondo
# sería inventar un límite que el papel no tiene.
PAGINAS_PIEZA_LARGA = 40

# Marcas de que la página sigue algo anterior y NO abre una pieza. Sin esto, la hoja 2
# de un acta que repite el título en el encabezado se convierte en un acta nueva, y una
# pieza de seis fojas sale partida en seis.
#
# Los patrones son DELIBERADAMENTE estrechos, y hay un caso concreto atrás. La primera
# versión buscaba la palabra «continuación» suelta y se comió una pieza entera: la
# página decía «TRANSCRIPCIÓN DE CONVERSACIONES» en el título —una pieza nueva, con
# todas las letras— y abajo, en el cuerpo, «Se transcriben A CONTINUACIÓN los
# intercambios…». Esa locución es de las más comunes en prosa jurídica. El sistema la
# tomó por marca de continuidad, no cortó, y la transcripción quedó adentro del informe
# del gabinete, donde nadie la habría visto.
#
# Por eso ninguno de estos patrones pega contra «a continuación»: todos exigen o un
# paréntesis, o un contador de hojas, o una locución que sólo aparece en un pie.
_CONTINUACION = re.compile(
    r"\(\s*CONTINUACI[OÓ]N"                            # «(continuación 2/3)»
    r"|\bCONTINUACI[OÓ]N\s+\d+\s*(/|DE)\s*\d+"         # «continuación 2 de 3»
    r"|\bCONTIN[UÚ]A\s+(EN|AL)\b"                      # «continúa al dorso»
    r"|\bVIENE\s+DE\s+(LA\s+VUELTA|FS)"
    r"|\bSIGUE\s+AL\s+DORSO\b"
    r"|\bHOJA\s+\d+\s+DE\s+\d+\b"
    r"|\bP[AÁ]G(INA)?\.?\s*\d+\s*(DE|/)\s*\d+\b")

# Tokens que no se pasan a minúsculas al armar la descripción.
_SIGLAS = {"DNI", "CUIT", "CUIL", "LE", "LC", "SA", "S.A.", "SRL", "S.R.L.", "MPF",
           "UFIL", "OGA", "PDF", "USB", "IMEI", "CBU", "IVA", "AFIP", "ARCA", "IAFAS",
           "Nº", "N°", "N.º"}


@dataclass
class Linea:
    texto: str
    x0: float; y0: float; x1: float; y1: float


def lineas_de(cx: sqlite3.Connection, pagina_id: int, limite: int | None = None) -> list[Linea]:
    """
    Rearma las líneas de una página a partir de sus palabras.

    Agrupa por proximidad vertical. La tolerancia sale del alto de la palabra y no de
    un número fijo porque un título en cuerpo 16 y un pie en cuerpo 7 no se agrupan con
    el mismo criterio, y un valor fijo parte el título o junta dos renglones del cuerpo.
    """
    palabras = cx.execute("""SELECT texto, x0, y0, x1, y1 FROM palabra
                              WHERE pagina_id=? ORDER BY orden""", (pagina_id,)).fetchall()
    if not palabras:
        return []
    # Se ordena por posición y no por el orden en que las devolvió el motor: el OCR en
    # modo disperso entrega columnas enteras antes de bajar, y con ese orden las líneas
    # salen mezcladas.
    ps = sorted(palabras, key=lambda p: (round(p["y0"], 1), p["x0"]))

    lineas: list[list] = []
    actual: list = []
    for p in ps:
        if not actual:
            actual = [p]
            continue
        alto = max(4.0, actual[-1]["y1"] - actual[-1]["y0"])
        if abs(p["y0"] - actual[0]["y0"]) <= alto * 0.7:
            actual.append(p)
        else:
            lineas.append(actual)
            actual = [p]
            if limite and len(lineas) >= limite:
                break
    if actual and (not limite or len(lineas) < limite):
        lineas.append(actual)

    fuera = []
    for grupo in lineas[:limite] if limite else lineas:
        grupo = sorted(grupo, key=lambda p: p["x0"])
        fuera.append(Linea(
            " ".join(p["texto"] for p in grupo),
            min(p["x0"] for p in grupo), min(p["y0"] for p in grupo),
            max(p["x1"] for p in grupo), max(p["y1"] for p in grupo)))
    return fuera


def normalizar_encabezado(lineas: list[Linea]) -> str:
    """Mayúsculas y sin tildes: así es como el texto sobrevive al OCR."""
    return sin_tildes(" \n".join(l.texto for l in lineas)).upper()


def _frase(texto: str) -> str:
    """
    De «ACTA DE SECUESTRO» a «Acta de secuestro».

    Los títulos vienen en mayúsculas y así no se pueden pegar en un escrito. Se bajan,
    salvo las siglas y todo lo que traiga un dígito, que en un expediente casi siempre
    es un número de oficio o de expediente y cambiarlo sería alterar el dato.
    """
    palabras = re.split(r"(\s+)", texto.strip())
    letras = [c for c in texto if c.isalpha()]
    if not letras:
        return texto.strip()
    if sum(1 for c in letras if c.isupper()) / len(letras) < 0.7:
        return texto.strip()             # ya viene en mayúsculas y minúsculas

    fuera = []
    for p in palabras:
        if not p.strip():
            fuera.append(p)
        elif p.upper() in _SIGLAS or any(c.isdigit() for c in p):
            fuera.append(p)
        else:
            fuera.append(p.lower())
    salida = "".join(fuera).strip(" .:-—·")
    return salida[:1].upper() + salida[1:] if salida else texto.strip()


def _linea_titulo(lineas: list[Linea], tipo: catalogo.Tipo) -> Linea | None:
    """Cuál de las líneas del encabezado es la que hizo pegar al patrón."""
    for l in lineas:
        norm = sin_tildes(l.texto).upper()
        for patron in tipo.compilados:
            if patron.search(norm):
                return l
    return None


# Fechas que se pueden afirmar sin interpretar. No se intenta leer «a los doce días del
# mes de marzo» sin año: una fecha incompleta que el sistema completa con el año del
# legajo es exactamente el tipo de invención que no puede hacer.
_FECHA_NUM = re.compile(r"\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})\b")
_MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
          "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
          "noviembre": 11, "diciembre": 12}
_FECHA_LETRAS = re.compile(
    r"\b(\d{1,2})\s+de\s+(" + "|".join(_MESES) + r")\s+de\s+(\d{4})\b", re.IGNORECASE)


def detectar_fecha(texto: str) -> str | None:
    """Fecha del documento en ISO, o None. Nunca se infiere ni se completa."""
    m = _FECHA_LETRAS.search(sin_tildes(texto or ""))
    if m:
        d, mes, a = int(m.group(1)), _MESES[m.group(2).lower()], int(m.group(3))
        if 1 <= d <= 31 and 1900 <= a <= 2100:
            return f"{a:04d}-{mes:02d}-{d:02d}"
    m = _FECHA_NUM.search(texto or "")
    if m:
        d, mes, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a = a + 2000 if a < 100 and a < 70 else a + 1900 if a < 100 else a
        if 1 <= d <= 31 and 1 <= mes <= 12 and 1900 <= a <= 2100:
            return f"{a:04d}-{mes:02d}-{d:02d}"
    return None


@dataclass
class Pieza:
    pagina_inicio: int
    pagina_fin: int
    documento_id: int
    tipo: str
    descripcion: str
    fuerza_titulo: float
    confianza_lectura: float
    texto_origen: str
    fecha: str | None = None
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None
    advertencias: list[str] = None

    @property
    def confianza(self) -> float:
        """
        Cuánto se le cree a esta propuesta.

        Dos cosas la sostienen y ninguna alcanza sola: qué tan inequívoco fue el título
        y qué tan bien se leyó la página. Un título perfecto sobre una página que el OCR
        leyó a la mitad no es una propuesta confiable, y al revés tampoco.
        """
        base = 0.55 * self.fuerza_titulo + 0.45 * min(1.0, self.confianza_lectura)
        if self.pagina_fin - self.pagina_inicio + 1 > PAGINAS_PIEZA_LARGA:
            base *= 0.75
        return round(min(1.0, base), 3)


def _paginas_del_caso(cx: sqlite3.Connection) -> list[sqlite3.Row]:
    return cx.execute("""SELECT id, documento_id, numero_global, texto, confianza
                           FROM pagina WHERE texto IS NOT NULL
                          ORDER BY numero_global""").fetchall()


def paginas_cubiertas(cx: sqlite3.Connection) -> set[int]:
    """
    Las páginas que ya tienen una pieza que las representa, y por lo tanto no se vuelven
    a proponer.

    Cuenta lo que está activo y también lo que una persona apagó a propósito: una
    carátula descartada no puede reaparecer como pieza nueva en cada procesamiento, y una
    parte absorbida por una unión ya está representada por esa unión.

    NO cuenta lo que apagó `rehacer`, que es justamente lo que se quiere volver a
    proponer.

    Una pieza que abarca páginas de dos PDF —una unión, o un rango cargado a mano— sólo
    cubre las de su propio documento. En la unión eso no se nota, porque sus partes
    cubren el resto; en un rango manual, las páginas del segundo PDF vuelven a
    proponerse una vez, y queda una pieza de más que se descarta con dos clics. Es el
    error barato: el caro es dar por cubierta una página que ninguna pieza representa.

    Se mira documento por documento y no por número de página global, porque el global
    se mueve al reordenar los PDF: el rango de una pieza vieja se remapea por sus
    extremos y puede terminar abarcando un documento cargado después, que nunca fue
    parte de ella.
    """
    paginas: dict[int, list[int]] = {}
    for r in cx.execute("SELECT numero_global, documento_id FROM pagina"):
        paginas.setdefault(r["documento_id"], []).append(r["numero_global"])

    cubiertas: set[int] = set()
    for e in cx.execute("""SELECT id, documento_id, pagina_inicio, pagina_fin, activa
                             FROM evidencia WHERE pagina_inicio IS NOT NULL"""):
        if not modelo.representa_sus_paginas(cx, e["id"], bool(e["activa"])):
            continue
        desde, hasta = e["pagina_inicio"], e["pagina_fin"] or e["pagina_inicio"]
        candidatas = (paginas.get(e["documento_id"], []) if e["documento_id"]
                      else [g for gs in paginas.values() for g in gs])
        cubiertas.update(g for g in candidatas if desde <= g <= hasta)
    return cubiertas


def proponer(cx: sqlite3.Connection) -> list[Pieza]:
    """
    Recorre el legajo y arma la lista de piezas. No escribe nada en la base.

    Sólo mira las páginas que ninguna pieza cubre todavía. Eso es lo que hace que agregar
    un PDF al legajo proponga la evidencia de ese PDF sin tocar lo ya revisado: antes, la
    detección se salteaba entera si el caso tenía una sola pieza, y las páginas nuevas
    quedaban sin proponer sin que nadie se enterara.

    Un hueco corta la pieza abierta, sea porque esas páginas ya están cubiertas o porque
    todavía no se leyeron. Estirar una pieza por encima de páginas que el sistema no
    miró sería afirmar que son parte del mismo documento sin haberlo visto.
    """
    cubiertas = paginas_cubiertas(cx)
    paginas = [p for p in _paginas_del_caso(cx) if p["numero_global"] not in cubiertas]
    if not paginas:
        return []

    piezas: list[Pieza] = []
    abierta: Pieza | None = None
    textos: list[str] = []

    def cerrar(hasta: int):
        if abierta is None:
            return
        abierta.pagina_fin = hasta
        abierta.texto_origen = " ".join(textos)[:1200]
        abierta.fecha = detectar_fecha(abierta.texto_origen)
        adv = list(abierta.advertencias or [])
        if abierta.confianza_lectura < config.CONFIANZA_PAGINA_POBRE:
            adv.append("ocr_pobre")
        if abierta.pagina_fin - abierta.pagina_inicio + 1 > PAGINAS_PIEZA_LARGA:
            adv.append("pieza_larga")
        abierta.advertencias = adv
        piezas.append(abierta)

    anterior: int | None = None
    for pag in paginas:
        lineas = lineas_de(cx, pag["id"], limite=LINEAS_ENCABEZADO)
        encabezado = normalizar_encabezado(lineas)
        tipo, fuerza = catalogo.reconocer(encabezado)
        continua = bool(_CONTINUACION.search(encabezado))
        # Un hueco, o el principio de otro PDF, cierran la pieza abierta. Lo segundo
        # porque una pieza que cruza dos archivos no se puede seguir representando con
        # `pagina_inicio`/`pagina_fin` en cuanto alguien reordena los documentos: entre
        # sus dos extremos aparecen páginas que nunca fueron de ella.
        hueco = anterior is not None and (pag["numero_global"] != anterior + 1
                                          or (abierta is not None
                                              and pag["documento_id"] != abierta.documento_id))

        # La marca de continuación sólo tapa el corte cuando el título que pegó es del
        # MISMO tipo que la pieza abierta. Si aparece un título fuerte de otro tipo, se
        # corta igual, y es a propósito: entre partir de más y esconder una pieza
        # adentro de otra, lo segundo es lo que hace perder prueba. Partir de más se
        # arregla con dos clics; lo que quedó adentro de otra pieza no lo ve nadie.
        sigue_lo_mismo = (continua and abierta is not None and not hueco
                          and tipo.clave == abierta.tipo)
        arranca = abierta is None or hueco or (fuerza >= UMBRAL_CORTE and not sigue_lo_mismo)
        if not arranca:
            anterior = pag["numero_global"]
            textos.append(pag["texto"] or "")
            # La confianza de la pieza es la de la PEOR página que la compone, no el
            # promedio: si una de las seis fojas salió ilegible, la pieza entera merece
            # que alguien la mire, y un promedio la esconde.
            abierta.confianza_lectura = min(abierta.confianza_lectura, pag["confianza"] or 0)
            continue

        # La pieza que estaba abierta termina en la última página que entró en ella, que
        # con huecos de por medio no es la anterior en la numeración.
        cerrar(anterior if anterior is not None else pag["numero_global"] - 1)
        anterior = pag["numero_global"]
        linea = _linea_titulo(lineas, tipo) if fuerza else (lineas[0] if lineas else None)
        descripcion = _frase(linea.texto) if linea else ""
        if not descripcion:
            descripcion = f"Pieza sin título legible (pág. {pag['numero_global']})"
        abierta = Pieza(
            pagina_inicio=pag["numero_global"], pagina_fin=pag["numero_global"],
            documento_id=pag["documento_id"],
            tipo=tipo.clave if fuerza else catalogo.SIN_CLASIFICAR.clave,
            descripcion=descripcion, fuerza_titulo=fuerza,
            confianza_lectura=pag["confianza"] or 0.0, texto_origen="",
            x0=linea.x0 if linea else None, y0=linea.y0 if linea else None,
            x1=linea.x1 if linea else None, y1=linea.y1 if linea else None,
            advertencias=[] if fuerza else ["sin_titulo"])
        textos = [pag["texto"] or ""]

    cerrar(anterior if anterior is not None else paginas[-1]["numero_global"])
    return piezas


def guardar(cx: sqlite3.Connection, piezas: list[Pieza]) -> dict:
    """
    Escribe las piezas propuestas como evidencia `pendiente`.

    NO toca lo que ya existe: `proponer` sólo mira páginas que ninguna pieza cubre, así
    que acá no hay nada que pisar. Lo que llega son piezas de páginas nuevas —un PDF que
    se sumó al legajo— o de páginas cuyas propuestas apagó `rehacer`.

    No confirma: la transacción la maneja quien llama, porque mirar la cobertura y
    escribir tienen que ser una sola operación. Si no, dos detecciones simultáneas
    —el trabajador de fondo y alguien apretando «detectar»— proponen las mismas páginas
    y el legajo termina con cada pieza por duplicado.
    """
    ya = cx.execute("""SELECT COUNT(*) FROM evidencia
                        WHERE origen='automatica' AND activa=1""").fetchone()[0]
    # La cobertura se vuelve a mirar ACÁ, con la transacción de escritura ya tomada: la
    # lista pudo haberse armado contra una foto vieja del caso. Una propuesta que pisa
    # aunque sea una página ya cubierta se descarta entera —recortarle el rango sería
    # cambiarle los límites a un documento que se leyó completo— y sus páginas libres las
    # vuelve a proponer el pase siguiente.
    cubiertas = paginas_cubiertas(cx)
    pisadas = [p for p in piezas
               if cubiertas & set(range(p.pagina_inicio, p.pagina_fin + 1))]
    piezas = [p for p in piezas if p not in pisadas]
    if not piezas:
        return {"creadas": 0, "ya_habia": ya, "descartadas": len(pisadas),
                "motivo": ("todas las páginas leídas ya tienen una pieza que las cubre"
                           if ya else None)}

    ahora = db.ahora()
    orden = cx.execute("SELECT COALESCE(MAX(orden_salida), 0) FROM evidencia").fetchone()[0]
    for p in piezas:
        orden += 1
        fi = cx.execute("SELECT foja_etiqueta FROM pagina WHERE numero_global=?",
                        (p.pagina_inicio,)).fetchone()
        ff = cx.execute("SELECT foja_etiqueta FROM pagina WHERE numero_global=?",
                        (p.pagina_fin,)).fetchone()
        cx.execute("""
            INSERT INTO evidencia (documento_id, pagina_inicio, pagina_fin,
                                   x0, y0, x1, y1, texto_origen,
                                   tipo_detectado, descripcion_detectada,
                                   foja_inicio_detectada, foja_fin_detectada,
                                   estado, origen, confianza, advertencias,
                                   fecha_documento, orden_salida, creado_en)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'pendiente','automatica',?,?,?,?,?)""",
            (p.documento_id, p.pagina_inicio, p.pagina_fin, p.x0, p.y0, p.x1, p.y1,
             p.texto_origen, p.tipo, p.descripcion,
             fi["foja_etiqueta"] if fi else None, ff["foja_etiqueta"] if ff else None,
             p.confianza, json.dumps(p.advertencias or [], ensure_ascii=False),
             p.fecha, orden, ahora))
    return {"creadas": len(piezas), "ya_habia": ya, "descartadas": len(pisadas),
            "motivo": None}


def detectar(cx: sqlite3.Connection) -> dict:
    """Proponer y guardar, de una, como una sola operación (ver `db.candado_de_escritura`)."""
    db.candado_de_escritura(cx)
    try:
        r = guardar(cx, proponer(cx))
        cx.commit()
    except Exception:
        cx.rollback()
        raise
    return r


# Una propuesta que nadie tocó: sin decisión, sin corrección, sin sector, sin testigo,
# sin etiqueta y sin una sola fila en el historial. Es lo único que `rehacer` puede
# reemplazar, porque es lo único donde no hay trabajo de nadie.
_INTACTA = """
      origen = 'automatica' AND activa = 1 AND estado = 'pendiente'
  AND tipo_final IS NULL AND subtipo_final IS NULL AND descripcion_final IS NULL
  AND foja_inicio_final IS NULL AND foja_fin_final IS NULL
  AND observaciones IS NULL AND grupo_id IS NULL
  AND NOT EXISTS (SELECT 1 FROM revision r         WHERE r.evidencia_id = evidencia.id)
  AND NOT EXISTS (SELECT 1 FROM evidencia_persona p WHERE p.evidencia_id = evidencia.id)
  AND NOT EXISTS (SELECT 1 FROM evidencia_etiqueta t WHERE t.evidencia_id = evidencia.id)
  -- Haber resuelto un posible duplicado también es trabajo: si la propuesta se
  -- reemplaza, el par vuelve a ofrecerse con identificadores nuevos y hay que decidirlo
  -- de nuevo.
  AND NOT EXISTS (SELECT 1 FROM duplicado_posible d
                   WHERE (d.evidencia_a = evidencia.id OR d.evidencia_b = evidencia.id)
                     AND d.estado <> 'abierto')"""


def rehacer(cx: sqlite3.Connection) -> dict:
    """
    Vuelve a proponer, tirando sólo las propuestas que nadie tocó.

    La versión anterior apagaba TODA la automática pendiente —descripciones corregidas y
    testigos asignados incluidos— sin dejar rastro, y después no creaba nada, porque la
    detección se salteaba si quedaba alguna automática activa. O sea: se llevaba trabajo
    hecho y encima no rehacía nada.

    Las que se apagan quedan anotadas en `revision`, que es append-only: se puede ver qué
    propuesta reemplazó a cuál.
    """
    db.candado_de_escritura(cx)
    try:
        ahora = db.ahora()
        reemplazadas = 0
        for fila in cx.execute(f"SELECT id FROM evidencia WHERE {_INTACTA}").fetchall():
            # La condición se repite en el UPDATE y no alcanza con el id: entre el SELECT
            # y la escritura, otra pestaña puede haber incluido esa misma propuesta, y
            # apagarla acá sería perder la decisión que alguien acaba de tomar.
            cur = cx.execute(
                f"UPDATE evidencia SET activa=0, actualizado_en=? WHERE id=? AND {_INTACTA}",
                (ahora, fila["id"]))
            if not cur.rowcount:
                continue
            cx.execute("""INSERT INTO revision (evidencia_id, campo, valor_anterior,
                                                valor_nuevo, detalle, cuando)
                          VALUES (?, 'rehacer_deteccion', 'activa', 'reemplazada',
                                  'se volvió a correr la detección', ?)""", (fila["id"], ahora))
            reemplazadas += 1
        # Las dos cosas se confirman juntas. Si la detección falla, las propuestas viejas
        # tienen que seguir donde estaban: media operación deja el caso sin piezas.
        resultado = guardar(cx, proponer(cx))
        cx.commit()
    except Exception:
        cx.rollback()
        raise
    return {**resultado, "reemplazadas": reemplazadas}
