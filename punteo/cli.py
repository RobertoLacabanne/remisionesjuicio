"""
Línea de comandos.

Sirve para instalar, diagnosticar y para trabajar sin interfaz cuando hace falta. Lo
que se hace todos los días se hace desde la pantalla: `python3 -m punteo.cli servir`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import busqueda, casos, config, exportacion, foliatura, generacion, ingesta, ocr
from .evidencia import deteccion, duplicados, modelo


def _abrir(slug: str):
    try:
        return casos.abrir(slug)
    except casos.CasoNoEncontrado:
        sys.exit(f"no existe el caso «{slug}». Los que hay: "
                 + ", ".join(c.slug for c in casos.listar()) or "(ninguno)")


def cmd_diagnostico(a) -> int:
    """¿Esta máquina tiene todo lo que hace falta?"""
    print("Punteo de Evidencia — diagnóstico\n")
    ok = True

    print(f"  Python            {sys.version.split()[0]}")
    try:
        import pymupdf
        print(f"  PyMuPDF           {pymupdf.__version__ if hasattr(pymupdf,'__version__') else 'presente'}")
    except ImportError:
        print("  PyMuPDF           FALTA  ->  pip install PyMuPDF"); ok = False
    try:
        import PIL
        print(f"  Pillow            {PIL.__version__}")
    except ImportError:
        print("  Pillow            FALTA  ->  pip install pillow"); ok = False

    hay, detalle = ocr.hay_ocr()
    if hay:
        idiomas = ocr.idiomas_ocr()
        print(f"  {detalle}")
        if config.OCR_IDIOMA in idiomas:
            print(f"  idioma «{config.OCR_IDIOMA}»    presente")
        else:
            print(f"  idioma «{config.OCR_IDIOMA}»    FALTA  ->  "
                  f"apt install tesseract-ocr-{config.OCR_IDIOMA}")
            ok = False
        if "osd" not in idiomas:
            print("  detector de giro  FALTA  ->  apt install tesseract-ocr-osd "
                  "(las páginas de costado no se van a enderezar)")
    else:
        print(f"  Tesseract         FALTA  ->  apt install tesseract-ocr "
              f"tesseract-ocr-{config.OCR_IDIOMA}\n                    ({detalle})")
        ok = False

    import sqlite3
    cx = sqlite3.connect(":memory:")
    try:
        cx.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        print(f"  SQLite {sqlite3.sqlite_version:<10} con FTS5")
    except sqlite3.OperationalError:
        print(f"  SQLite {sqlite3.sqlite_version:<10} SIN FTS5  ->  la búsqueda no va a andar")
        ok = False
    finally:
        cx.close()

    print(f"\n  datos             {config.DATOS}")
    try:
        config.carpeta_casos().mkdir(parents=True, exist_ok=True)
        prueba = config.carpeta_casos() / ".escritura"
        prueba.write_text("ok"); prueba.unlink()
        print(f"  escritura         bien")
    except OSError as e:
        print(f"  escritura         FALLA: {e}"); ok = False
    print(f"  casos             {len(casos.listar())}")

    print("\n" + ("Todo listo." if ok else "Falta algo de lo de arriba."))
    return 0 if ok else 1


def cmd_casos(a) -> int:
    lista = casos.listar()
    if not lista:
        print("todavía no hay casos")
        return 0
    for c in lista:
        print(f"  {c.slug}")
        print(f"    {c.numero_legajo} · {c.caratula}")
        print(f"    {casos.ETIQUETA_TIPO[c.tipo_proceso]} · {c.documentos} PDF · "
              f"{c.paginas} páginas · {c.evidencias} piezas "
              f"({c.incluidas} incluidas, {c.pendientes} pendientes)")
    return 0


def cmd_crear(a) -> int:
    c = casos.crear(a.legajo, a.caratula, a.tipo, a.observaciones)
    print(f"creado: {c.slug}")
    return 0


def cmd_cargar(a) -> int:
    cx = _abrir(a.caso)
    rutas = []
    for p in a.pdf:
        p = Path(p)
        rutas.extend(sorted(p.rglob("*.pdf")) if p.is_dir() else [p])
    for ruta in rutas:
        r = ingesta.agregar(cx, ruta.read_bytes(), ruta.name)
        marca = "ya estaba" if r.duplicado else (r.error or f"{r.paginas} páginas")
        print(f"  {ruta.name:<44} {marca}")
    return 0


def cmd_procesar(a) -> int:
    cx = _abrir(a.caso)
    print("leyendo las páginas…")
    r = ocr.leer_caso(cx, avance=lambda h, t: print(f"  {h}/{t}", end="\r", flush=True))
    print(f"\n  {r['hechas']} páginas · {r['fallidas']} fallidas")
    print("foliatura:", foliatura.detectar(cx))
    print("evidencia:", deteccion.detectar(cx))
    print("duplicados:", duplicados.detectar(cx))
    print("índice:", busqueda.reindexar(cx), "páginas")
    print("contadores:", modelo.contadores(cx))
    return 0


def cmd_evidencias(a) -> int:
    cx = _abrir(a.caso)
    r = modelo.listar(cx, filtro=a.filtro, orden=a.orden, limite=a.limite)
    print(f"{r['total']} piezas ({a.filtro})\n")
    marca = {"incluida": "✓", "excluida": "✕", "pendiente": "○"}
    for e in r["evidencias"]:
        fojas = modelo.cita_fojas(e)
        print(f"  {marca.get(e['estado'],'?')} #{e['id']:<4} {(e['descripcion'] or '')[:52]:<52} "
              f"{fojas:<22} {e['confianza_nivel']}")
    return 0


def cmd_punteo(a) -> int:
    cx = _abrir(a.caso)
    v = generacion.verificar(cx)
    if not v["incluidas"]:
        print("no hay ninguna evidencia marcada para incluir")
        return 1
    for clave, rotulo in (("sin_foja", "sin foja"),
                          ("foja_sin_confirmar", "con foja sin confirmar"),
                          ("sin_testigo", "sin testigo introductor")):
        if v[clave]:
            print(f"  aviso: {len(v[clave])} piezas incluidas {rotulo}")
    generacion.generar(cx, criterio=a.criterio)
    print()
    print(exportacion.a_texto(cx))
    if a.exportar:
        print("guardado en", exportacion.guardar(cx, a.exportar))
    return 0


def cmd_servir(a) -> int:
    from . import servidor
    servidor.servir(a.puerto, a.host)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="punteo", description=__doc__)
    sub = ap.add_subparsers(dest="comando", required=True)

    sub.add_parser("diagnostico", help="¿está todo lo que hace falta?").set_defaults(fn=cmd_diagnostico)
    sub.add_parser("casos", help="lista los casos").set_defaults(fn=cmd_casos)

    p = sub.add_parser("crear", help="crea un caso")
    p.add_argument("legajo"); p.add_argument("caratula")
    p.add_argument("--tipo", choices=casos.TIPOS_PROCESO, default="remision")
    p.add_argument("--observaciones")
    p.set_defaults(fn=cmd_crear)

    p = sub.add_parser("cargar", help="carga PDF a un caso")
    p.add_argument("caso"); p.add_argument("pdf", nargs="+")
    p.set_defaults(fn=cmd_cargar)

    p = sub.add_parser("procesar", help="lee, folia y propone evidencia")
    p.add_argument("caso"); p.set_defaults(fn=cmd_procesar)

    p = sub.add_parser("evidencias", help="lista las piezas")
    p.add_argument("caso")
    p.add_argument("--filtro", default="todas")
    p.add_argument("--orden", default="manual")
    p.add_argument("--limite", type=int, default=200)
    p.set_defaults(fn=cmd_evidencias)

    p = sub.add_parser("punteo", help="genera el punteo con lo incluido")
    p.add_argument("caso")
    p.add_argument("--criterio", default="manual", choices=list(generacion.CRITERIOS))
    p.add_argument("--exportar", choices=list(exportacion.FORMATOS))
    p.set_defaults(fn=cmd_punteo)

    p = sub.add_parser("servir", help="levanta la interfaz web local")
    p.add_argument("--puerto", type=int, default=config.PUERTO)
    p.add_argument("--host", default=config.HOST)
    p.set_defaults(fn=cmd_servir)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
