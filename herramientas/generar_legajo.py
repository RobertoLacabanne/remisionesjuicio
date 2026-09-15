"""
Generador de legajos sintéticos de prueba.

Todo lo que produce es inventado. Los nombres, los números de legajo, los organismos y
los hechos no corresponden a ninguna causa: son cadenas armadas para que el sistema
tenga algo con qué trabajar. Cada PDF lleva una marca en sus metadatos para que no
pueda confundirse con documentación real ni en una demostración.

    python3 herramientas/generar_legajo.py /tmp/legajo --fojas-desde 400

Produce dos PDF: uno con capa de texto nativa y otro «escaneado» —el mismo contenido
rasterizado, sin capa de texto—, para poder probar las dos rutas de lectura.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pymupdf

MARCA = "PUNTEO-LEGAJO-SINTETICO-DE-PRUEBA"

ANCHO, ALTO = 595, 842            # A4 en puntos
MARGEN = 56

# Cada pieza es (tipo, título, cuerpo, páginas). El cuerpo se repite hasta llenar las
# páginas que pide la pieza, que es lo que hace falta para probar evidencia multipágina.
PIEZAS = [
    ("denuncia", "ACTA DE DENUNCIA",
     "En la ciudad de Paraná, a los doce días del mes de marzo, comparece ante esta "
     "Unidad Fiscal la señora MARTINA QUIROGA, DNI 28.445.190, quien manifiesta que "
     "desea formular denuncia contra quien resulte responsable por el desvío de fondos "
     "de la partida de obra pública correspondiente al ejercicio anterior. Refiere que "
     "tomó conocimiento de los hechos en razón de su función administrativa.", 2),

    ("acta_procedimiento", "ACTA DE PROCEDIMIENTO",
     "Siendo las nueve horas del día quince de marzo, el suscripto Sargento Primero "
     "RUBÉN OSVALDO ANDRADE, de la Comisaría Quinta de Paraná, se constituye en el "
     "domicilio de calle Gualeguaychú 1240 a fin de dar cumplimiento a lo ordenado. "
     "Se deja constancia de que el procedimiento se desarrolló sin novedad.", 2),

    ("acta_allanamiento", "ACTA DE ALLANAMIENTO",
     "En cumplimiento de la orden librada, se procede al registro del inmueble sito en "
     "calle Gualeguaychú 1240 de esta ciudad, con la presencia de dos testigos hábiles. "
     "Se recorren las dependencias y se procede conforme se detalla seguidamente.", 3),

    ("acta_secuestro", "ACTA DE SECUESTRO",
     "Se procede al secuestro de un (1) equipo de telefonía celular marca Samsung, un "
     "(1) cuaderno tapa dura con anotaciones manuscritas y doce (12) fojas de "
     "documentación administrativa, todo lo cual se detalla y se lacra en presencia de "
     "los testigos.", 2),

    ("cadena_custodia", "PLANILLA DE CADENA DE CUSTODIA",
     "Registro de traslados y entregas del efecto identificado bajo el número de orden "
     "que se consigna. Se deja constancia de cada transferencia con firma del receptor.", 1),

    ("declaracion_testimonial", "DECLARACIÓN TESTIMONIAL",
     "Comparece ante esta Unidad Fiscal el señor RUBÉN OSVALDO ANDRADE, quien previo "
     "juramento de decir verdad manifiesta que se desempeña como personal policial y "
     "que participó del procedimiento que se le exhibe, reconociendo su firma inserta "
     "al pie del acta respectiva.", 3),

    ("declaracion_testimonial", "DECLARACIÓN TESTIMONIAL",
     "Comparece la señora MARTINA QUIROGA, quien previo juramento de decir verdad "
     "manifiesta que ratifica en todos sus términos la denuncia oportunamente "
     "formulada y agrega que puede aportar documentación respaldatoria.", 2),

    ("oficio", "OFICIO Nº 1174",
     "Tengo el agrado de dirigirme a usted en el marco del legajo de referencia, a fin "
     "de solicitarle tenga a bien informar la titularidad de las cuentas radicadas en "
     "esa entidad a nombre de la persona cuyos datos se consignan al pie.", 1),

    ("respuesta_oficio", "RESPUESTA A OFICIO Nº 1174",
     "En atención a lo requerido, se informa que la persona indicada registra una "
     "cuenta corriente y una caja de ahorro en esta entidad, adjuntándose los extractos "
     "correspondientes al período solicitado.", 2),

    ("informe_bancario", "INFORME DE MOVIMIENTOS BANCARIOS",
     "Detalle de acreditaciones y débitos registrados en la cuenta que se indica, "
     "correspondiente al período comprendido entre el primero de enero y el treinta y "
     "uno de diciembre del ejercicio consultado.", 4),

    # El catálogo lo reconoce como `informe_contable`, que es más específico que
    # `informe_pericial` y es la respuesta correcta para este título.
    ("informe_contable", "INFORME PERICIAL CONTABLE",
     "El perito que suscribe, contador público designado en autos, informa que del "
     "análisis de la documentación puesta a disposición surgen las inconsistencias que "
     "se detallan, sin que ello importe pronunciamiento sobre responsabilidades.", 3),

    ("pericia_informatica", "INFORME DEL GABINETE INFORMÁTICO FORENSE Nº C6223",
     "Se practicó la extracción forense del dispositivo remitido mediante herramienta "
     "de adquisición lógica, obteniéndose la información que se detalla en el anexo. Se "
     "deja constancia del valor hash del contenedor generado.", 4),

    ("conversaciones", "TRANSCRIPCIÓN DE CONVERSACIONES",
     "Se transcriben a continuación los intercambios seleccionados de la aplicación de "
     "mensajería instalada en el dispositivo, con indicación de fecha, hora y "
     "participantes según surge de la extracción.", 3),

    ("fotografias", "REGISTRO FOTOGRÁFICO",
     "Se incorporan las tomas fotográficas obtenidas durante el procedimiento, con "
     "indicación de la dependencia registrada en cada una.", 2),

    ("informe_administrativo", "EXPEDIENTE ADMINISTRATIVO Nº 4412",
     "Copia certificada de las actuaciones administrativas labradas con motivo de la "
     "contratación que se investiga, remitidas por el organismo requerido.", 3),

    ("informe_organismo", "INFORME DEL TRIBUNAL DE CUENTAS",
     "Se remite copia del informe de auditoría practicado sobre la rendición del "
     "período consultado, con las observaciones formuladas oportunamente.", 2),
]


def _texto_pagina(pag, titulo: str, cuerpo: str, n_parte: int, total_partes: int,
                  foja: int | None) -> None:
    y = MARGEN
    pag.insert_text((MARGEN, y), "MINISTERIO PÚBLICO FISCAL — ENTRE RÍOS",
                    fontname="helv", fontsize=8)
    y += 28
    if n_parte == 1:
        pag.insert_text((MARGEN, y), titulo, fontname="hebo", fontsize=13)
        y += 26
    else:
        pag.insert_text((MARGEN, y), f"{titulo} (continuación {n_parte}/{total_partes})",
                        fontname="helv", fontsize=9)
        y += 22

    caja = pymupdf.Rect(MARGEN, y, ANCHO - MARGEN, ALTO - MARGEN - 40)
    texto = (cuerpo + " ") * 6
    pag.insert_textbox(caja, texto, fontname="tiro", fontsize=10.5, align=3)

    if n_parte == total_partes:
        pag.insert_text((MARGEN, ALTO - MARGEN - 24), "Es todo cuanto tengo para informar.",
                        fontname="tiit", fontsize=9.5)

    if foja is not None:
        # El número de foja va arriba a la derecha, que es donde se sella en la práctica.
        pag.insert_text((ANCHO - MARGEN - 34, MARGEN - 18), str(foja),
                        fontname="helv", fontsize=11)


def generar(destino: Path, *, fojas_desde: int | None = 400,
            sin_foliar_desde: int | None = None) -> dict:
    """
    Arma el legajo. Devuelve un mapa de lo que produjo, para que las pruebas puedan
    verificar contra la verdad conocida en vez de contra lo que el sistema detecte.
    """
    destino.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    doc.set_metadata({"title": "Legajo sintético de prueba", "keywords": MARCA,
                      "producer": MARCA})

    verdad, pagina_global, foja = [], 0, fojas_desde
    for tipo, titulo, cuerpo, paginas in PIEZAS:
        inicio_pag, inicio_foja = pagina_global + 1, foja
        for parte in range(1, paginas + 1):
            pagina_global += 1
            sin_foliar = (sin_foliar_desde is not None and pagina_global >= sin_foliar_desde)
            pag = doc.new_page(width=ANCHO, height=ALTO)
            _texto_pagina(pag, titulo, cuerpo, parte, paginas,
                          None if (foja is None or sin_foliar) else foja)
            if foja is not None and not sin_foliar:
                foja += 1
        verdad.append({"tipo": tipo, "titulo": titulo,
                       "pagina_inicio": inicio_pag, "pagina_fin": pagina_global,
                       "foja_inicio": inicio_foja, "foja_fin": foja - 1 if foja else None})

    con_texto = destino / "legajo-con-texto.pdf"
    doc.save(con_texto, garbage=4, deflate=True)

    # El mismo legajo, rasterizado: sin capa de texto, como sale de un escáner. Es lo
    # que obliga a pasar por OCR, que es la ruta que de verdad hay que probar.
    escaneado = pymupdf.open()
    escaneado.set_metadata({"title": "Legajo escaneado sintético", "keywords": MARCA})
    for pag in doc:
        pix = pag.get_pixmap(matrix=pymupdf.Matrix(200 / 72, 200 / 72))
        nueva = escaneado.new_page(width=ANCHO, height=ALTO)
        nueva.insert_image(pymupdf.Rect(0, 0, ANCHO, ALTO), stream=pix.tobytes("png"))
    ruta_escaneado = destino / "legajo-escaneado.pdf"
    escaneado.save(ruta_escaneado, garbage=4, deflate=True)

    doc.close(); escaneado.close()
    return {"con_texto": con_texto, "escaneado": ruta_escaneado,
            "paginas": pagina_global, "piezas": verdad}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Genera un legajo sintético de prueba.")
    ap.add_argument("destino", type=Path)
    ap.add_argument("--fojas-desde", type=int, default=400,
                    help="número de la primera foja; 0 para un legajo sin foliar")
    ap.add_argument("--sin-foliar-desde", type=int, default=None,
                    help="a partir de esta página global, deja de imprimir la foja")
    a = ap.parse_args(argv)
    r = generar(a.destino, fojas_desde=a.fojas_desde or None,
                sin_foliar_desde=a.sin_foliar_desde)
    print(f"{r['paginas']} páginas · {len(r['piezas'])} piezas")
    print(f"  {r['con_texto']}")
    print(f"  {r['escaneado']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
