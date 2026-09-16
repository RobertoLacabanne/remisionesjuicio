"""
Detección de foliatura.

El problema: en el escrito se cita «fs. 342/346». Ese número está impreso o sellado en
el margen de la hoja y no tiene por qué coincidir con la página del PDF. Hay que leerlo.

La idea central: **un número suelto en una esquina no prueba nada**. Puede ser un número
de expediente, un año, un número de artículo o basura de OCR. Lo que prueba una
foliatura es la SERIE. Un tramo de veinte páginas donde el número del margen superior
derecho va 402, 403, 404… es foliatura y no puede ser otra cosa.

Por eso el detector no clasifica páginas de a una: junta candidatos por zona de margen,
busca tramos donde el candidato crece de a uno junto con la página, y recién ahí acepta.
Adentro de un tramo probado puede completar las páginas donde el OCR no leyó el número,
porque la serie ya está demostrada.

Y por eso son TRAMOS y no un único desplazamiento global. Un legajo real casi nunca
tiene uno solo: se intercala documentación, se folia en dos etapas, empieza un cuerpo
nuevo. Forzar un número único es acertar en la primera mitad del legajo y errar en la
segunda, que es peor que no detectar nada porque no se nota.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from . import db

# Cuántas lecturas REALES —no interpoladas— exige un tramo para ser creíble. Con tres
# alcanzaba para que una numeración de artículos en tres páginas seguidas pasara por
# foliatura. Cuatro ya es una serie.
MIN_LECTURAS_TRAMO = 4
# Cuántas páginas seguidas sin leer el número tolera un tramo antes de cortarse. Un
# hueco largo puede ser una tanda de fotos o de planillas sin foliar, y estirar el
# tramo por encima de eso es inventar fojas para páginas que nadie folió.
MAX_HUECO = 12

ZONAS = ("sup_der", "sup_cen", "inf_der", "inf_cen")

# Por qué se descarta una serie. Se guarda con el tramo y se muestra tal cual, así que
# es corto: va en una fila, al lado del rango. Lo que significa —que casi siempre es la
# paginación interna de un informe— lo explica la pantalla una sola vez, arriba.
MOTIVO_CONTRADICCION = "se contradice con otra serie: la foja no puede retroceder ni repetirse"

# «411», «411 vta.», «411 vlta», «fs. 411», «f° 411», «-411-»
_CANDIDATO = re.compile(
    r"^[\-–—.·\(\[]*(?:f?s?\.?º?°?\s*)?(\d{1,4})\s*(vta\.?|vlta\.?|bis)?[\-–—.·\)\]]*$",
    re.IGNORECASE)

_SUFIJOS = {"vta": "vta", "vta.": "vta", "vlta": "vta", "vlta.": "vta", "bis": "bis"}

# El sello redondo de folio, que es como se folia de verdad en buena parte de los
# legajos: «FOLIO Nº ____» impreso, y el número ESCRITO A MANO adentro. Tesseract lee la
# palabra impresa y no lee la cifra manuscrita, así que la página termina sin foja y sin
# distinguirse de una hoja que nadie folió. Son dos cosas muy distintas para quien
# trabaja: una hay que cargarla mirando el sello, la otra no existe.
#
# Se reconoce la palabra sola y sólo en zona de margen. En el cuerpo, «obrante a folio
# 23» es una cita de otra pieza y no dice nada de esta hoja.
_SELLO_FOLIO = re.compile(r"^[\|\.\:\-]*f[o0]li[o0]s?[\|\.\:\-]*$", re.IGNORECASE)


@dataclass
class Candidato:
    numero_global: int
    zona: str
    num: int
    sufijo: str
    etiqueta: str
    conf: float


@dataclass
class Tramo:
    zona: str
    desde_global: int
    hasta_global: int
    desplazamiento: int          # foja_num = numero_global + desplazamiento
    lecturas: int
    interpoladas: int

    @property
    def confianza(self) -> float:
        """
        Cuánto se le cree. Sale de dos cosas: cuántas lecturas reales sostienen el tramo
        y qué proporción del tramo se leyó de verdad contra lo que se completó solo.
        Un tramo de cuarenta páginas con cuatro lecturas es una conjetura larga.
        """
        largo = self.hasta_global - self.desde_global + 1
        densidad = self.lecturas / largo if largo else 0
        volumen = min(1.0, self.lecturas / 12)
        return round(0.35 + 0.35 * densidad + 0.30 * volumen, 3)


def etiqueta_foja(num: int | None, sufijo: str = "") -> str | None:
    if num is None:
        return None
    return f"{num} vta." if sufijo == "vta" else f"{num} bis" if sufijo == "bis" else str(num)


def partir_etiqueta(texto: str) -> tuple[int, str] | None:
    """De «411 vta.» a (411, 'vta'). Devuelve None si no parece una foja."""
    m = _CANDIDATO.match((texto or "").strip())
    if not m:
        return None
    num = int(m.group(1))
    if not 1 <= num <= 9999:
        return None
    return num, _SUFIJOS.get((m.group(2) or "").lower(), "")


# ─────────────────────────────────────────────────────── candidatos por zona ──
def _zona_de(x0: float, y0: float, y1: float, ancho: float, alto: float) -> str | None:
    if not ancho or not alto:
        return None
    arriba = y1 < 0.13 * alto
    abajo = y0 > 0.87 * alto
    if not (arriba or abajo):
        return None
    if x0 > 0.62 * ancho:
        return "sup_der" if arriba else "inf_der"
    if 0.28 * ancho < x0 < 0.72 * ancho:
        return "sup_cen" if arriba else "inf_cen"
    return None


def candidatos(cx: sqlite3.Connection) -> list[Candidato]:
    """Todas las palabras de margen que podrían ser un número de foja."""
    fuera = []
    for p in cx.execute("""SELECT id, numero_global, ancho_pt, alto_pt FROM pagina
                            WHERE texto IS NOT NULL ORDER BY numero_global"""):
        ancho, alto = p["ancho_pt"] or 0, p["alto_pt"] or 0
        for w in cx.execute("""SELECT texto, x0, y0, y1, conf FROM palabra
                                WHERE pagina_id=? ORDER BY orden""", (p["id"],)):
            zona = _zona_de(w["x0"], w["y0"], w["y1"], ancho, alto)
            if not zona:
                continue
            partido = partir_etiqueta(w["texto"])
            if not partido:
                continue
            num, sufijo = partido
            fuera.append(Candidato(p["numero_global"], zona, num, sufijo,
                                   etiqueta_foja(num, sufijo), w["conf"] or 0.0))
    return fuera


# ───────────────────────────────────────────────────────────────── los tramos ──
def _tramos_de_zona(lecturas: dict[int, int]) -> list[Tramo]:
    """
    `lecturas` es {numero_global: num_foja} de UNA zona, sólo enteros sin sufijo.

    Un tramo es un conjunto de páginas consecutivas donde `num_foja - numero_global` se
    mantiene constante. Ese valor es el desplazamiento del tramo.
    """
    if not lecturas:
        return []
    paginas = sorted(lecturas)
    tramos: list[Tramo] = []
    inicio = paginas[0]
    desp = lecturas[inicio] - inicio
    ultima = inicio
    cuantas = 1

    def cerrar(fin_lectura: int):
        if cuantas >= MIN_LECTURAS_TRAMO:
            largo = fin_lectura - inicio + 1
            tramos.append(Tramo("", inicio, fin_lectura, desp, cuantas, largo - cuantas))

    for g in paginas[1:]:
        d = lecturas[g] - g
        if d == desp and (g - ultima) <= MAX_HUECO:
            ultima, cuantas = g, cuantas + 1
            continue
        cerrar(ultima)
        inicio, desp, ultima, cuantas = g, d, g, 1
    cerrar(ultima)
    return tramos


def _sello_en(cx: sqlite3.Connection, pagina_id: int, ancho: float, alto: float) -> bool:
    for w in cx.execute("""SELECT texto, x0, y0, y1 FROM palabra
                            WHERE pagina_id=? ORDER BY orden""", (pagina_id,)):
        if not _SELLO_FOLIO.match((w["texto"] or "").strip()):
            continue
        if _zona_de(w["x0"], w["y0"], w["y1"], ancho, alto):
            return True
    return False


def sellos_de_folio(cx: sqlite3.Connection) -> set[int]:
    """Páginas donde hay un sello de folio en el margen, se haya leído el número o no."""
    return {p["numero_global"] for p in cx.execute(
                """SELECT id, numero_global, ancho_pt, alto_pt FROM pagina
                    WHERE texto IS NOT NULL ORDER BY numero_global""")
            if _sello_en(cx, p["id"], p["ancho_pt"] or 0, p["alto_pt"] or 0)}


def hay_sello_de_folio(cx: sqlite3.Connection, numero_global: int) -> bool:
    """¿Esta hoja tiene el sello de folio en el margen?"""
    p = cx.execute("""SELECT id, ancho_pt, alto_pt FROM pagina
                       WHERE numero_global=? AND texto IS NOT NULL""",
                   (numero_global,)).fetchone()
    return bool(p) and _sello_en(cx, p["id"], p["ancho_pt"] or 0, p["alto_pt"] or 0)


def _fojas_del_tramo(t: Tramo) -> tuple[int, int]:
    return t.desde_global + t.desplazamiento, t.hasta_global + t.desplazamiento


def coherentes(tramos: list[Tramo]) -> tuple[list[Tramo], list[Tramo]]:
    """
    Saca los tramos que se contradicen entre sí. Devuelve (los que quedan, los que caen).

    Hay dos cosas que una foliatura de legajo no puede hacer, y no son heurísticas: una
    foja no se repite —dos hojas distintas no son la misma foja— y la foja no retrocede
    cuando avanza la página. Dos tramos que violan eso no pueden ser los dos foliatura.

    El caso real: el primer legajo escaneado de verdad que pasó por el sistema trajo dos
    tramos «buenos», los dos del pie derecho —uno que daba fojas 3 a 6 en las páginas 4 a
    7, y otro que daba fojas 2 a 11 en las páginas 30 a 39—, con confianzas de 0.8 y 0.89.
    No era foliatura: era la paginación interna de dos documentos distintos, cada uno
    numerando sus propias hojas desde el principio. La foliatura de ese legajo es un sello
    redondo con el número escrito a mano, y va por encima de la foja mil: el OCR no lo
    lee. Sin este control el sistema ofrecía «foja 3», con alta confianza, para una hoja
    que en el papel está foliada muy lejos de ahí, y alcanzaba con que alguien confirmara
    el tramo para que ese número entrara a un requerimiento.

    **Caen los dos, no gana el más creíble.** La contradicción prueba que esa señal no
    es foliatura; no dice cuál de los dos tramos era el bueno, y elegir uno sería quedarse
    con un número falso al que ya no contradice nadie. Un tramo que no contradice a
    ninguno sobrevive.

    El costo del falso negativo es que alguien cargue las fojas a mano. El del falso
    positivo es una cita falsa en un escrito. No es un empate.
    """
    orden = sorted(tramos, key=lambda t: t.desde_global)
    en_conflicto: set[int] = set()
    for i, a in enumerate(orden):
        _, a_fin = _fojas_del_tramo(a)
        for j in range(i + 1, len(orden)):
            b = orden[j]
            b_inicio, _ = _fojas_del_tramo(b)
            if b_inicio <= a_fin:
                en_conflicto.add(i)
                en_conflicto.add(j)
    return ([t for k, t in enumerate(orden) if k not in en_conflicto],
            [t for k, t in enumerate(orden) if k in en_conflicto])


def detectar(cx: sqlite3.Connection) -> dict:
    """
    Detecta la foliatura del caso y la escribe en `pagina`.

    NO pisa lo que una persona confirmó o cargó a mano: esas páginas se saltean. Es la
    regla que hace que reprocesar un legajo no le cueste al equipo el trabajo ya hecho.
    """
    por_zona: dict[str, dict[int, int]] = {z: {} for z in ZONAS}
    con_sufijo: dict[int, Candidato] = {}
    for c in candidatos(cx):
        if c.sufijo:
            # Una foja con «vta.» es una lectura directa y es de las más confiables que
            # hay, pero rompe la relación `foja = página + desplazamiento`: la vuelta de
            # una hoja no incrementa el número. No entra a los tramos; se usa tal cual.
            con_sufijo.setdefault(c.numero_global, c)
            continue
        # Si en la misma zona de la misma página hay dos candidatos, gana el primero:
        # el número de foja se sella una vez.
        por_zona[c.zona].setdefault(c.numero_global, c.num)

    candidatos_tramo: list[Tramo] = []
    for zona, lecturas in por_zona.items():
        for t in _tramos_de_zona(lecturas):
            t.zona = zona
            candidatos_tramo.append(t)

    # Dos zonas pueden producir tramos que se pisan —pasa cuando el membrete trae un
    # número que también crece—. Gana el que tenga más lecturas reales; el resto se
    # recorta o se descarta. Elegir por confianza y no por zona evita cablear una
    # preferencia que sería cierta en un juzgado y falsa en el de al lado.
    candidatos_tramo.sort(key=lambda t: (t.lecturas, t.confianza), reverse=True)
    tomadas: set[int] = set()
    elegidos: list[Tramo] = []
    for t in candidatos_tramo:
        rango = set(range(t.desde_global, t.hasta_global + 1))
        if rango & tomadas:
            continue
        tomadas |= rango
        elegidos.append(t)

    # Recién acá se controla que los tramos elegidos puedan ser foliatura los dos a la
    # vez. Antes no se puede: un tramo suelto siempre parece una serie razonable, y lo
    # que lo delata es lo que dice del de al lado.
    elegidos, descartados = coherentes(elegidos)

    protegidas = {r["numero_global"] for r in cx.execute(
        "SELECT numero_global FROM pagina WHERE foja_origen IN ('confirmada','manual')")}

    # El orden de estas dos importa y costó un error de clave foránea: las páginas que
    # una persona CONFIRMÓ conservan su `tramo_id`, así que borrar los tramos primero
    # dejaba filas apuntando a un tramo que ya no existe y SQLite abortaba la
    # redetección entera. Pasaba apenas alguien confirmaba un tramo y después cargaba
    # otro PDF, que es la secuencia normal de trabajo.
    #
    # Se suelta el vínculo en TODAS las páginas antes de borrar. Una foja confirmada no
    # necesita su tramo: el tramo es un rastro de cómo se detectó, y una vez que una
    # persona la miró, el valor se sostiene solo.
    cx.execute("UPDATE pagina SET tramo_id = NULL")
    cx.execute("DELETE FROM tramo_foliatura")
    cx.execute("""UPDATE pagina SET foja_etiqueta=NULL, foja_num=NULL, foja_sufijo='',
                         foja_origen='desconocida', foja_confianza=NULL, foja_lectura=NULL
                   WHERE foja_origen = 'detectada'""")

    def guardar_tramo(t: Tramo, motivo: str | None) -> int:
        return cx.execute(
            """INSERT INTO tramo_foliatura (desde_global, hasta_global, desplazamiento,
                                            zona, confianza, paginas_leidas,
                                            paginas_interpoladas, descartado, creado_en)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (t.desde_global, t.hasta_global, t.desplazamiento, t.zona, t.confianza,
             t.lecturas, t.interpoladas, motivo, db.ahora())).lastrowid

    # Las series que se cayeron se guardan igual, con el motivo. Es la respuesta a «en el
    # margen hay números, ¿por qué no los tomó?», y sin ella la pantalla dice «no se
    # detectó foliatura» y parece que el sistema ni miró.
    for t in sorted(descartados, key=lambda t: t.desde_global):
        guardar_tramo(t, MOTIVO_CONTRADICCION)

    escritas = 0
    for t in sorted(elegidos, key=lambda t: t.desde_global):
        tramo_id = guardar_tramo(t, None)
        for g in range(t.desde_global, t.hasta_global + 1):
            if g in protegidas:
                continue
            leida = por_zona[t.zona].get(g) is not None
            num = g + t.desplazamiento
            # Una página interpolada vale menos que una leída, y se nota en la pantalla:
            # la confianza del tramo se castiga cuando el número no se leyó ahí.
            conf = t.confianza if leida else round(t.confianza * 0.7, 3)
            cx.execute("""UPDATE pagina SET foja_etiqueta=?, foja_num=?, foja_sufijo='',
                                 foja_origen='detectada', foja_confianza=?, tramo_id=?,
                                 foja_lectura=?
                           WHERE numero_global=?""",
                       (etiqueta_foja(num), num, conf, tramo_id,
                        "leida" if leida else "interpolada", g))
            escritas += 1

    # Las fojas con sufijo se escriben después, y pisan lo interpolado: una lectura
    # directa siempre le gana a un número calculado.
    for g, c in con_sufijo.items():
        if g in protegidas:
            continue
        cx.execute("""UPDATE pagina SET foja_etiqueta=?, foja_num=?, foja_sufijo=?,
                             foja_origen='detectada', foja_confianza=?, foja_lectura='leida'
                       WHERE numero_global=?""",
                   (c.etiqueta, c.num, c.sufijo, round(0.5 + 0.4 * c.conf, 3), g))
        escritas += 1

    # Y por último, las hojas que tienen el sello de folio con el número a mano. No se
    # les pone foja —el número no se leyó y no se inventa—, pero dejan de confundirse con
    # una hoja sin foliar: quien revisa sabe que ahí hay un número para copiar del papel.
    cx.execute("""UPDATE pagina SET foja_lectura=NULL
                   WHERE foja_etiqueta IS NULL AND foja_lectura='sello_ilegible'""")
    sellos = sellos_de_folio(cx)
    sin_leer = 0
    for g in sorted(sellos):
        cur = cx.execute("""UPDATE pagina SET foja_lectura='sello_ilegible'
                             WHERE numero_global=? AND foja_etiqueta IS NULL""", (g,))
        sin_leer += cur.rowcount

    cx.commit()
    total = cx.execute("SELECT COUNT(*) FROM pagina").fetchone()[0]
    return {"sellos_sin_leer": sin_leer,
            "tramos": len(elegidos), "paginas_con_foja": escritas, "paginas": total,
            "sin_foja": total - escritas - len(protegidas & set(range(1, total + 1))),
            # Cuántas series se cayeron por contradecirse. No es un detalle de motor: es
            # lo que hay que decirle a quien procesa un legajo, porque significa «acá
            # había números en el margen y no son la foliatura». Se llama distinto de la
            # lista que devuelve `resumen` para que no se confundan un conteo y un detalle.
            "series_descartadas": len(descartados)}


# ────────────────────────────────────────────────────── corrección a mano ──
def fijar(cx: sqlite3.Connection, numero_global: int, etiqueta: str | None, *,
          confirmada: bool = True) -> dict:
    """
    Carga o corrige la foja de una página. Es una decisión humana: queda `manual`.

    Con `etiqueta` vacía la foja vuelve a desconocida, que es distinto de cero y hay que
    poder decirlo: una página puede no estar foliada.
    """
    if etiqueta is None or not str(etiqueta).strip():
        # Borrar la foja no borra el sello: si en el margen hay uno, la marca vuelve acá
        # mismo. Si no, la hoja se quedaba sin esa pista hasta el próximo reproceso, que
        # es cuando nadie la va a estar mirando.
        lectura = "sello_ilegible" if hay_sello_de_folio(cx, numero_global) else None
        cx.execute("""UPDATE pagina SET foja_etiqueta=NULL, foja_num=NULL, foja_sufijo='',
                             foja_origen='desconocida', foja_confianza=NULL, foja_lectura=?
                       WHERE numero_global=?""", (lectura, numero_global))
        cx.commit()
        return {"numero_global": numero_global, "foja": None, "origen": "desconocida",
                "sello_sin_leer": lectura is not None}

    partido = partir_etiqueta(str(etiqueta))
    if not partido:
        raise ValueError(f"«{etiqueta}» no parece una foja (se espera 411, 411 vta. o 411 bis)")
    num, sufijo = partido
    # `foja_lectura` vuelve a NULL: lo que escribió una persona no es ni una lectura del
    # OCR ni una interpolación del tramo, y decir que es «leída» sería mezclar dos cosas
    # que el sistema existe para distinguir.
    cx.execute("""UPDATE pagina SET foja_etiqueta=?, foja_num=?, foja_sufijo=?,
                         foja_origen='manual', foja_confianza=1.0, foja_lectura=NULL
                   WHERE numero_global=?""",
               (etiqueta_foja(num, sufijo), num, sufijo, numero_global))
    cx.commit()
    return {"numero_global": numero_global, "foja": etiqueta_foja(num, sufijo),
            "origen": "manual"}


def confirmar_tramo(cx: sqlite3.Connection, desde_global: int, hasta_global: int) -> int:
    """
    Una persona miró un tramo y dice que la foliatura detectada está bien.

    Es la operación que hace falta para que el generador pueda escribir esas fojas en un
    escrito: mientras estén en `detectada` son una conjetura de la máquina. Confirmar de
    a tramos y no de a una página es lo único que hace esto viable en un legajo de
    quinientas fojas.
    """
    cur = cx.execute("""UPDATE pagina SET foja_origen='confirmada', foja_confianza=1.0
                         WHERE numero_global BETWEEN ? AND ?
                           AND foja_origen = 'detectada'""", (desde_global, hasta_global))
    cx.commit()
    return cur.rowcount


def resumen(cx: sqlite3.Connection) -> dict:
    """Estado de la foliatura del caso, para la pantalla."""
    fila = cx.execute("""
        SELECT COUNT(*) AS paginas,
               COALESCE(SUM(foja_origen='desconocida'),0) AS desconocidas,
               COALESCE(SUM(foja_origen='detectada'),0)   AS detectadas,
               COALESCE(SUM(foja_origen='confirmada'),0)  AS confirmadas,
               COALESCE(SUM(foja_origen='manual'),0)      AS manuales,
               -- Cuántas fojas no se leyeron en el papel: se dedujeron de la serie.
               -- Confirmar un tramo no las convierte en leídas, así que se cuentan aparte.
               COALESCE(SUM(foja_lectura='interpolada'),0) AS interpoladas,
               -- Hojas con el sello de folio y el número escrito a mano, que el OCR no
               -- lee. No es lo mismo que una hoja sin foliar: ésta tiene foja y hay que
               -- copiarla del papel.
               COALESCE(SUM(foja_lectura='sello_ilegible'),0) AS sellos_sin_leer
          FROM pagina""").fetchone()
    tramos = [dict(r) for r in cx.execute(
        "SELECT * FROM tramo_foliatura WHERE descartado IS NULL ORDER BY desde_global")]
    descartados = [dict(r) for r in cx.execute(
        "SELECT * FROM tramo_foliatura WHERE descartado IS NOT NULL ORDER BY desde_global")]
    return {**dict(fila), "tramos": tramos, "tramos_descartados": descartados}
