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

# «411», «411 vta.», «411 vlta», «fs. 411», «f° 411», «-411-»
_CANDIDATO = re.compile(
    r"^[\-–—.·\(\[]*(?:f?s?\.?º?°?\s*)?(\d{1,4})\s*(vta\.?|vlta\.?|bis)?[\-–—.·\)\]]*$",
    re.IGNORECASE)

_SUFIJOS = {"vta": "vta", "vta.": "vta", "vlta": "vta", "vlta.": "vta", "bis": "bis"}


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

    escritas = 0
    for t in sorted(elegidos, key=lambda t: t.desde_global):
        tramo_id = cx.execute(
            """INSERT INTO tramo_foliatura (desde_global, hasta_global, desplazamiento,
                                            zona, confianza, paginas_leidas,
                                            paginas_interpoladas, creado_en)
               VALUES (?,?,?,?,?,?,?,?)""",
            (t.desde_global, t.hasta_global, t.desplazamiento, t.zona, t.confianza,
             t.lecturas, t.interpoladas, db.ahora())).lastrowid
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

    cx.commit()
    total = cx.execute("SELECT COUNT(*) FROM pagina").fetchone()[0]
    return {"tramos": len(elegidos), "paginas_con_foja": escritas, "paginas": total,
            "sin_foja": total - escritas - len(protegidas & set(range(1, total + 1)))}


# ────────────────────────────────────────────────────── corrección a mano ──
def fijar(cx: sqlite3.Connection, numero_global: int, etiqueta: str | None, *,
          confirmada: bool = True) -> dict:
    """
    Carga o corrige la foja de una página. Es una decisión humana: queda `manual`.

    Con `etiqueta` vacía la foja vuelve a desconocida, que es distinto de cero y hay que
    poder decirlo: una página puede no estar foliada.
    """
    if etiqueta is None or not str(etiqueta).strip():
        cx.execute("""UPDATE pagina SET foja_etiqueta=NULL, foja_num=NULL, foja_sufijo='',
                             foja_origen='desconocida', foja_confianza=NULL, foja_lectura=NULL
                       WHERE numero_global=?""", (numero_global,))
        cx.commit()
        return {"numero_global": numero_global, "foja": None, "origen": "desconocida"}

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
               COALESCE(SUM(foja_lectura='interpolada'),0) AS interpoladas
          FROM pagina""").fetchone()
    tramos = [dict(r) for r in cx.execute(
        "SELECT * FROM tramo_foliatura ORDER BY desde_global")]
    return {**dict(fila), "tramos": tramos}
