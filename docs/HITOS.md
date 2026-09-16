# Plan por hitos

Dónde está el proyecto y qué falta. Se actualiza al cerrar cada hito.

Convención: **hecho** es que está implementado, probado y usable de punta a punta;
**parcial** es que anda pero le falta algo declarado; **falta** es que no está.

---

## Hito 1 — Arquitectura · **hecho**

Análisis de AppUFIL, matriz de reutilización componente por componente, modelo de datos,
estrategia de OCR y de foliatura, riesgos. En
[`ARQUITECTURA.md`](ARQUITECTURA.md), [`REUTILIZACION-APPUFIL.md`](REUTILIZACION-APPUFIL.md)
y [`IDENTIDAD.md`](IDENTIDAD.md).

El protocolo pedía que este hito fuera Claude y Codex por separado y después síntesis.
**Codex no está disponible en el entorno** —verificado, no supuesto— así que es un
análisis de un solo agente y el documento lo dice. Lo que sí se hizo es la revisión
adversarial contra las propias decisiones, en
[`REVISION-ADVERSARIAL.md`](REVISION-ADVERSARIAL.md), con los puntos marcados
**[PARA CODEX]** que conviene someterle primero cuando la integración esté operativa.

## Hito 2 — Ingesta, OCR y fojas · **hecho**

SHA-256, original en `0444`, numeración global encadenada entre varios PDF, lectura por
texto nativo o por Tesseract local con palabras y coordenadas en puntos, enderezado que
decide por el resultado, y detección de foliatura por tramos validados por serie.

Medido sobre el legajo sintético rasterizado: 39 de 39 fojas correctas, 0,28 s por
página, confianza media 0,958.

## Hito 3 — Modelo de evidencia · **hecho**

Catálogo extensible, detección por título de encabezado, el par `_detectada` / `_final`
para que lo corregido no pise lo detectado, dividir y unir con rastro, evidencia
manual, duplicados propuestos y nunca eliminados.

16 de 16 piezas con el rango de páginas exacto, por las dos rutas de lectura.

## Hito 4 — Visor y checklist · **hecho**

Dos paneles con la foja siempre a la vista, resalte del fragmento que sustenta la pieza,
tira de fojas, atajos de teclado, checklist con filtros y contadores, vista por sectores,
acciones en lote.

**Falta** el arrastre para reordenar: hoy se reordena con selectores y botones, que es la
alternativa accesible y es la que tenía que existir igual.

## Hito 5 — Testigos y personas · **hecho**

Registro normalizado, vista por testigo introductor con su bloque de piezas sin asignar,
propuestas de fusión que reconocen el nombre incompleto y la inicial, y que nunca se
aplican solas.

## Hito 6 — Generación del punteo · **hecho**

Lee únicamente de `v_evidencia_incluida`, revalida pieza por pieza, respeta el orden
aprobado sin reordenar, arma bloques con encabezados editables, plantillas por familia de
prueba, y marcadores visibles donde falta un dato.

Revisión adversarial obligatoria: hecha, en [`REVISION-ADVERSARIAL.md`](REVISION-ADVERSARIAL.md) §1.

## Hito 7 — Persistencia y recuperación · **parcial**

Escritura en la misma petición, «guardado» sólo cuando el servidor contestó, historial
append-only, reproceso que no pisa el trabajo hecho, reordenamiento de documentos que
remapea la evidencia. Todo con prueba.

**Falta**: dos pestañas sobre el mismo caso no se coordinan, y una descripción a medio
escribir se pierde si se cierra la pestaña sin salir del campo.

## Hito 8 — Legajos grandes · **parcial**

Las decisiones están tomadas: el OCR no guarda una imagen por página, el visor rasteriza
bajo demanda a una caché con tope, el checklist se sirve paginado, la tira agrupa páginas
por encima de 300 marcas.

**Falta lo principal: medirlo.** No se probó con 500, 2.000 ni 5.000 páginas. Los números
que hay son una extrapolación de un legajo de 39 páginas, y están dichos como tales.
También falta paginar la navegación de la pantalla de revisión, que hoy carga hasta 500
piezas.

## Hito 9 — MVP completo · **hecho para el recorrido declarado**

El recorrido del criterio de éxito funciona de punta a punta: crear caso, cargar,
procesar, revisar con la foja al lado, corregir, asignar testigo, incluir y excluir,
agregar a mano, ordenar, generar y exportar.

245 pruebas. Sin `--lentas` se saltean las 12 que invocan Tesseract; con `--lentas` se
saltea una sola, por condición, cuando el segundo PDF de prueba entra como copia exacta
del primero. Todas en verde por las dos rutas.

---

## Hito 10 — Repositorio propio · **hecho**

El proyecto salió de la carpeta de AppUFIL y pasó a su propio repositorio, con la
historia de los tres commits conservada (`git subtree split`). Las tipografías se
copiaron adentro con sus licencias OFL, así que no queda ninguna dependencia de que
AppUFIL esté al lado en el disco.

---

## Hito 11 — Primer legajo real · **hecho**

Entró el primer legajo penal escaneado de verdad: 84 páginas sin capa de texto, la
primera parte de un legajo de corrupción. Leído entero, 0 páginas fallidas, un minuto de
OCR. La ingesta, el visor, la revisión, la carga en partes y la invariante de exclusión
funcionaron sin una observación.

Falló otra cosa, y cinco veces: el sistema **afirmaba a partir de señales compatibles con
lo que buscaba en lugar de exigir señales que sólo pudieran significar eso**. Foliatura
falsa con confianza 0,89 —era la paginación interna de dos informes—, hojas selladas a
mano indistinguibles de hojas sin foliar, siete actas de declaración testimonial
escondidas adentro de una sola pieza porque el encabezado se gastaba en el ruido del
escaneo, las siete con la misma fecha y falsa —la de la resolución que citan—, y después
veintiún duplicados propuestos y ninguno verdadero.

Los cinco arreglados, cada uno con su prueba, buscando una contradicción dura o una marca
de atribución en lugar de subir umbrales. Sobre ese legajo: de 14 fojas falsas a ninguna,
de 6 piezas a 15 con las siete actas separadas y cada una con su fecha real, de 21
propuestas de duplicado a ninguna.

El detalle, con el método y lo que quedó sin resolver, en
[`LEGAJO-REAL.md`](LEGAJO-REAL.md). Del legajo no queda nada en el repositorio.

---

## Lo que sigue, por orden de valor

1. **Medir con un legajo real GRANDE.** El primero fueron 84 páginas y despejó lo que
   despejó; de mil páginas no dice nada.
2. **Mejorar la descripción propuesta cuando el título no se reconoce**, que hoy sale como
   un fragmento del cuerpo del documento.
3. **Señales de corte que no dependan del título** —membrete, bloque de firma, página en
   blanco—: es el agujero por donde hoy se puede esconder una pieza sin título.
4. **Clave de acceso**, adaptando el criterio de `acceso.py` de AppUFIL: no obligatoria
   en `127.0.0.1`, obligatoria al exponer en red.
5. **Arrastre para reordenar**, conservando siempre la alternativa por botones.
6. **Agrupación propuesta por organismo y membrete**, como sugerencia que el usuario
   acepta, rechaza o corrige; nunca aplicada sola.
7. **Exportación a DOCX**, que entra sin tocar el generador.
8. **Coordinación entre pestañas** y guardado del texto a medio escribir.
