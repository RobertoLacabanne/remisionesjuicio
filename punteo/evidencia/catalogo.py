"""
Catálogo de tipos de pieza probatoria.

Es una LISTA DE DATOS, no un enum, y la base no tiene un CHECK contra ella. Los dos
detalles son a propósito: agregar un tipo tiene que ser agregar una entrada acá, y un
tipo que alguien sumó ayer no puede hacer fallar la apertura de un caso viejo.

Cada entrada dice cómo se reconoce el tipo en el papel —los patrones se prueban contra
el encabezado de la página, normalizado sin tildes y en mayúsculas, porque así es como
sobrevive al OCR— y cómo se lo nombra en el escrito.

El `peso` es cuánta confianza aporta el patrón cuando pega. Un título inequívoco como
«ACTA DE ALLANAMIENTO» pesa más que «INFORME», que puede ser cualquier cosa.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Las familias ordenan la vista «por tipo de prueba» y los encabezados del punteo
# agrupado. Son pocas a propósito: una taxonomía de veinte ramas no la usa nadie.
FAMILIAS = {
    "testimonial": "Testimonial",
    "documental": "Documental",
    "pericial": "Pericial",
    "informativa": "Informativa",
    "digital": "Evidencia digital",
    "audiovisual": "Audiovisual",
    "material": "Efectos y secuestros",
    "otra": "Otra",
}


@dataclass
class Tipo:
    clave: str
    etiqueta: str
    familia: str
    patrones: list[str]
    peso: float = 0.8
    # Cómo se nombra la pieza en el punteo cuando no hay una descripción mejor. El
    # generador la usa como base y la persona la corrige: nunca es la última palabra.
    plantilla: str = ""
    compilados: list[re.Pattern] = field(default_factory=list, repr=False)

    def __post_init__(self):
        # MULTILINE, y no es un detalle. El encabezado que se prueba contra estos
        # patrones son varias líneas unidas por saltos, y arriba de todo suele estar el
        # número de foja sellado y el membrete del organismo. Sin MULTILINE, `^` es el
        # principio de TODO el encabezado, así que `^\s*OFICIO` no pegaba nunca: el
        # título es la tercera línea, no la primera. Medido sobre el legajo escaneado de
        # prueba, eso escondía el oficio adentro de la declaración testimonial anterior.
        self.compilados = [re.compile(p, re.MULTILINE) for p in self.patrones]
        if not self.plantilla:
            self.plantilla = self.etiqueta


# El orden importa: se prueba de arriba abajo y gana el primero que pega con más peso.
# Los específicos van antes que los genéricos —«ACTA DE SECUESTRO» antes que «ACTA»—
# porque si no, todo cae en el cajón de los genéricos y la clasificación no sirve.
TIPOS: list[Tipo] = [
    # ── Testimonial ────────────────────────────────────────────────────────
    Tipo("declaracion_testimonial", "Declaración testimonial", "testimonial",
         [r"\bDECLARACI[OÓ]N\s+TESTIMONIAL\b", r"\bACTA\s+DE\s+DECLARACI[OÓ]N\b",
          r"\bTESTIMONIAL\s+DE\b"], 0.95,
         "Declaración testimonial"),
    Tipo("entrevista", "Entrevista", "testimonial",
         [r"\bACTA\s+DE\s+ENTREVISTA\b", r"\bENTREVISTA\s+A\b"], 0.85),
    Tipo("declaracion_imputado", "Declaración del imputado", "testimonial",
         [r"\bDECLARACI[OÓ]N\s+DEL?\s+IMPUTADO\b",
          r"\bACTA\s+DE\s+DECLARACI[OÓ]N\s+DE\s+IMPUTADO\b"], 0.95),
    Tipo("careo", "Careo", "testimonial", [r"\bACTA\s+DE\s+CAREO\b", r"\bCAREO\b"], 0.8),
    Tipo("reconocimiento", "Reconocimiento en rueda de personas", "testimonial",
         [r"\bRECONOCIMIENTO\s+EN\s+RUEDA\b", r"\bRUEDA\s+DE\s+PERSONAS\b"], 0.9),
    Tipo("camara_gesell", "Entrevista en Cámara Gesell", "testimonial",
         [r"\bC[AÁ]MARA\s+GESELL\b"], 0.9),

    # ── Actas y procedimiento ──────────────────────────────────────────────
    Tipo("denuncia", "Denuncia", "documental",
         [r"\bACTA\s+DE\s+DENUNCIA\b", r"\bDENUNCIA\s+PENAL\b",
          r"^\s*DENUNCIA\b"], 0.9),
    Tipo("acta_allanamiento", "Acta de allanamiento", "documental",
         [r"\bACTA\s+DE\s+ALLANAMIENTO\b", r"\bORDEN\s+DE\s+ALLANAMIENTO\b"], 0.95),
    Tipo("acta_secuestro", "Acta de secuestro", "material",
         [r"\bACTA\s+DE\s+SECUESTRO\b"], 0.95),
    Tipo("acta_apertura", "Acta de apertura", "documental",
         [r"\bACTA\s+DE\s+APERTURA\b"], 0.9),
    Tipo("cadena_custodia", "Cadena de custodia", "material",
         [r"\bCADENA\s+DE\s+CUSTODIA\b", r"\bPLANILLA\s+DE\s+CUSTODIA\b"], 0.95),
    Tipo("acta_procedimiento", "Acta de procedimiento", "documental",
         [r"\bACTA\s+DE\s+PROCEDIMIENTO\b"], 0.9),
    Tipo("acta_inspeccion", "Acta de inspección ocular", "documental",
         [r"\bINSPECCI[OÓ]N\s+OCULAR\b", r"\bACTA\s+DE\s+INSPECCI[OÓ]N\b"], 0.9),
    Tipo("croquis", "Croquis", "documental", [r"\bCROQUIS\b"], 0.8),
    Tipo("acta", "Acta", "documental", [r"^\s*ACTA\b"], 0.55),

    # ── Pericial ───────────────────────────────────────────────────────────
    Tipo("pericia_informatica", "Pericia informática", "digital",
         [r"\bGABINETE\s+INFORM[AÁ]TICO\b", r"\bPERICIA\s+INFORM[AÁ]TICA\b",
          r"\bINFORME\s+T[EÉ]CNICO\s+INFORM[AÁ]TICO\b"], 0.95),
    Tipo("extraccion_forense", "Extracción forense", "digital",
         [r"\bEXTRACCI[OÓ]N\s+FORENSE\b", r"\bADQUISICI[OÓ]N\s+(L[OÓ]GICA|F[IÍ]SICA)\b",
          r"\bVOLCADO\s+DE\s+DISPOSITIVO\b"], 0.95),
    Tipo("informe_contable", "Informe pericial contable", "pericial",
         [r"\bPERICIA(L)?\s+CONTABLE\b", r"\bINFORME\s+CONTABLE\b"], 0.95),
    Tipo("pericia_caligrafica", "Pericia caligráfica", "pericial",
         [r"\bPERICIA\s+CALIGR[AÁ]FICA\b", r"\bCALIGR[AÁ]FIC[OA]\b"], 0.9),
    Tipo("informe_medico", "Informe médico", "pericial",
         [r"\bINFORME\s+M[EÉ]DICO\b", r"\bEXAMEN\s+M[EÉ]DICO\b",
          r"\bINFORME\s+M[EÉ]DICO\s+LEGAL\b"], 0.9),
    Tipo("autopsia", "Informe de autopsia", "pericial",
         [r"\bAUTOPSIA\b", r"\bINFORME\s+NECROPSIA\b"], 0.95),
    Tipo("informe_pericial", "Informe pericial", "pericial",
         [r"\bINFORME\s+PERICIAL\b", r"\bDICTAMEN\s+PERICIAL\b", r"\bPERICIA\b"], 0.8),

    # ── Informativa ────────────────────────────────────────────────────────
    Tipo("oficio", "Oficio", "informativa",
         [r"^\s*OFICIO\b", r"\bOFICIO\s+N[ºO°]?\s*\d+"], 0.85),
    Tipo("respuesta_oficio", "Respuesta a oficio", "informativa",
         [r"\bRESPUESTA\s+A(L)?\s+OFICIO\b", r"\bCONTESTA\s+OFICIO\b",
          r"\bEN\s+RESPUESTA\s+AL\s+OFICIO\b"], 0.9),
    Tipo("informe_bancario", "Informe bancario", "informativa",
         [r"\bINFORME\s+BANCARIO\b", r"\bMOVIMIENTOS\s+BANCARIOS\b",
          r"\bEXTRACTO\s+BANCARIO\b", r"\bRESUMEN\s+DE\s+CUENTA\b",
          r"\bTITULARIDAD\s+DE\s+(LA\s+)?CUENTAS?\b"], 0.9),
    Tipo("informe_telefonico", "Informe de telefonía", "informativa",
         [r"\bINFORME\s+DE\s+TELEFON[IÍ]A\b", r"\bREGISTRO\s+DE\s+LLAMADAS\b",
          r"\bTR[AÁ]FICO\s+TELEF[OÓ]NICO\b", r"\bANTENAS?\b"], 0.85),
    Tipo("informe_policial", "Informe policial", "informativa",
         [r"\bINFORME\s+POLICIAL\b", r"\bSUMARIO\s+DE\s+PREVENCI[OÓ]N\b",
          r"\bPARTE\s+POLICIAL\b"], 0.85),
    Tipo("informe_organismo", "Informe de organismo público", "informativa",
         [r"\bTRIBUNAL\s+DE\s+CUENTAS\b", r"\bINFORME\s+DE\s+AUDITOR[IÍ]A\b",
          r"\bMUNICIPALIDAD\s+DE\b", r"\bSECRETAR[IÍ]A\s+DE\b"], 0.8),
    Tipo("informe_empresa", "Informe de empresa", "informativa",
         [r"\bINFORME\s+DE\s+LA\s+EMPRESA\b", r"\bS\.?A\.?\s+INFORMA\b"], 0.75),
    Tipo("informe_administrativo", "Expediente administrativo", "documental",
         [r"\bEXPEDIENTE\s+ADMINISTRATIVO\b", r"\bACTUACIONES\s+ADMINISTRATIVAS\b"], 0.85),
    Tipo("informe", "Informe", "informativa", [r"^\s*INFORME\b"], 0.5),

    # ── Documental ─────────────────────────────────────────────────────────
    Tipo("contrato", "Contrato", "documental",
         [r"\bCONTRATO\s+DE\b", r"^\s*CONTRATO\b"], 0.8),
    Tipo("factura", "Factura", "documental",
         [r"^\s*FACTURA\b", r"\bFACTURA\s+[ABC]\b"], 0.8),
    Tipo("recibo", "Recibo", "documental", [r"^\s*RECIBO\b"], 0.75),
    Tipo("certificado", "Certificado", "documental",
         [r"^\s*CERTIFICADO\b", r"\bCERTIFICA\s+QUE\b"], 0.75),
    Tipo("planilla", "Planilla", "documental", [r"^\s*PLANILLA\b", r"\bPLANILLA\s+DE\b"], 0.7),
    Tipo("resolucion", "Resolución administrativa", "documental",
         [r"^\s*RESOLUCI[OÓ]N\b", r"^\s*DECRETO\b", r"^\s*DISPOSICI[OÓ]N\b"], 0.8),
    Tipo("documentacion", "Documentación", "documental",
         [r"\bDOCUMENTACI[OÓ]N\s+(ACOMPA[NÑ]ADA|APORTADA|RESERVADA)\b"], 0.7),

    # ── Digital y audiovisual ──────────────────────────────────────────────
    Tipo("conversaciones", "Conversaciones", "digital",
         [r"\bTRANSCRIPCI[OÓ]N\s+DE\s+CONVERSACIONES\b", r"\bCONVERSACIONES\b",
          r"\bCHAT(S)?\s+DE\b", r"\bWHATSAPP\b", r"\bMENSAJER[IÍ]A\b"], 0.85),
    Tipo("correos", "Correos electrónicos", "digital",
         [r"\bCORREOS?\s+ELECTR[OÓ]NICOS?\b", r"\bCASILLA\s+DE\s+CORREO\b"], 0.85),
    Tipo("capturas", "Capturas de pantalla", "digital",
         [r"\bCAPTURAS?\s+DE\s+PANTALLA\b", r"\bSCREENSHOT", r"\bIMPRESI[OÓ]N\s+DE\s+PANTALLA\b"], 0.85),
    Tipo("fotografias", "Registro fotográfico", "audiovisual",
         [r"\bREGISTRO\s+FOTOGR[AÁ]FICO\b", r"\bFOTOGRAF[IÍ]AS?\b",
          r"\bTOMAS?\s+FOTOGR[AÁ]FICAS?\b"], 0.9),
    Tipo("video", "Registro audiovisual", "audiovisual",
         [r"\bREGISTRO\s+F[IÍ]LMICO\b", r"\bFILMACI[OÓ]N\b", r"\bC[AÁ]MARAS?\s+DE\s+SEGURIDAD\b",
          r"\bVIDEOVIGILANCIA\b"], 0.9),
    Tipo("audio", "Registro de audio", "audiovisual",
         [r"\bREGISTRO\s+DE\s+AUDIO\b", r"\bDESGRABACI[OÓ]N\b", r"\bESCUCHAS?\b"], 0.9),
    Tipo("efecto_secuestrado", "Efecto secuestrado", "material",
         [r"\bEFECTOS?\s+SECUESTRADOS?\b", r"\bELEMENTOS?\s+SECUESTRADOS?\b"], 0.85),

    # ── El cajón que no puede faltar ───────────────────────────────────────
    # Sin esto, una pieza que el catálogo no reconoce NO se propondría, y una pieza
    # que no se propone es una que nadie va a mirar. La regla es que toda pieza tenga
    # un tipo, aunque el tipo diga «no sé»: el sistema propone, la persona decide.
    Tipo("sin_clasificar", "Sin clasificar", "otra", [], 0.3),
]

POR_CLAVE = {t.clave: t for t in TIPOS}
SIN_CLASIFICAR = POR_CLAVE["sin_clasificar"]


def reconocer(encabezado: str) -> tuple[Tipo, float]:
    """
    Qué tipo de pieza parece ser, mirando el encabezado normalizado de una página.

    Devuelve (tipo, fuerza). `fuerza` es 0 cuando ningún patrón pegó, y en ese caso el
    tipo es `sin_clasificar`: la pieza existe igual, sin tipo, y aparece en la lista
    marcada para que alguien la mire.
    """
    mejor, fuerza = SIN_CLASIFICAR, 0.0
    for tipo in TIPOS:
        for patron in tipo.compilados:
            m = patron.search(encabezado)
            if not m:
                continue
            # Un título que aparece en los primeros caracteres del encabezado vale más
            # que uno mencionado de paso en el cuerpo. «…conforme el acta de secuestro
            # de fs. 120» no convierte esta página en un acta de secuestro.
            cerca = 1.0 if m.start() < 90 else 0.6
            puntaje = tipo.peso * cerca
            if puntaje > fuerza:
                mejor, fuerza = tipo, puntaje
            break
    return mejor, round(fuerza, 3)


def etiqueta(clave: str | None) -> str:
    t = POR_CLAVE.get(clave or "")
    return t.etiqueta if t else (clave or "Sin clasificar")


def familia(clave: str | None) -> str:
    t = POR_CLAVE.get(clave or "")
    return t.familia if t else "otra"


def como_lista() -> list[dict]:
    """El catálogo para la interfaz, agrupado por familia."""
    return [{"clave": t.clave, "etiqueta": t.etiqueta, "familia": t.familia,
             "familia_etiqueta": FAMILIAS.get(t.familia, t.familia)}
            for t in TIPOS]
