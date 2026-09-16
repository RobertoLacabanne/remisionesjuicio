# Revisión adversarial

Este documento busca razones por las que la solución puede estar equivocada, no bugs
superficiales. Cada punto dice qué se hizo, qué queda expuesto y qué habría que probar.

**Advertencia sobre qué es esto y qué no.** El protocolo de trabajo pide que cada
decisión importante pase por dos análisis independientes, y nombra a Codex como el
segundo agente. En el entorno donde se construyó esta versión **Codex no está
disponible**: no hay plugin instalado, no hay marketplace configurado, no hay binario
`codex` en el `PATH` y no hay credenciales de OpenAI. Está verificado, no supuesto.

Lo que sigue es, entonces, el mismo modelo revisando su propio trabajo. Sirve —encontró
cosas, y están abajo— pero **no es diversidad de análisis**: comparte los sesgos que
produjeron el código. Los puntos marcados **[PARA CODEX]** son los que conviene
someterle primero cuando la integración esté operativa.

---

## 1. La invariante de exclusión

**Qué se hizo.** Tres barreras que fallan por separado: la vista `v_evidencia_incluida`
en la base, una revalidación por pieza en `generacion.py` justo antes de escribirla, y un
control en la exportación para el caso de que alguien excluya algo después de generar.
`pruebas/test_invariante.py` las prueba las tres, y prueba además que el texto de una
pieza excluida no aparezca en la salida ni por el identificador ni por la cadena.

**Lo que se encontró revisando.** El agujero real no era el generador: era el punteo
**ya guardado**. Se genera el escrito, alguien excluye una pieza media hora después, y
el archivo que se exporta sigue teniéndola. El texto no se puede actualizar solo —sería
pisarle la edición a quien lo esté corrigiendo— así que la exportación se niega y dice
qué párrafo es. Está cubierto por
`test_excluir_despues_de_generar_frena_la_exportacion`.

**Lo que queda expuesto.**

* Un párrafo que la persona editó a mano puede contener texto de una pieza excluida si
  lo escribió ahí. El sistema no puede distinguir eso de una redacción legítima, y no
  debería intentarlo: es texto de la persona.
* `punteo_parrafo.texto_final` no se revalida contra nada. Si alguien copia y pega una
  descripción excluida adentro de otro párrafo, sale.
* ~~**[PARA CODEX]** Falta buscar un camino por el que una unión arrastre contenido de
  una parte excluida.~~ **Resuelto después de la revisión de Codex:** existía, y ahora es
  una barrera. Una excluida no se une ni se divide; incluir una pieza y generar
  controlan su linaje completo. Ver `test_invariante.LoExcluidoNoVuelvePorOtraPuerta`.

---

## 2. Foja contra página

**Qué se hizo.** Columnas separadas, sin una sola conversión implícita en el código. La
foja de una evidencia se **deriva** de la página y no se congela, así que corregir la
foliatura corre la cita de todas las piezas que pasan por ahí. El generador exige que la
foja esté confirmada o cargada a mano; si no, escribe el número con `[FOJA A CONFIRMAR]`
al lado, y si no hay foja escribe `[FOJA PENDIENTE]`.

**Lo que queda expuesto, y es el riesgo más serio del sistema.**

* **La interpolación dentro de un tramo puede escribir una foja que el papel no tiene.**
  Si entre las páginas 40 y 60 el OCR leyó el número en doce y el detector completa las
  ocho restantes, una hoja intercalada sin foliar en el medio recibe un número que no le
  corresponde, y todas las siguientes quedan corridas en uno. El tramo igual se corta
  —el número leído de la página siguiente ya no coincide con el desplazamiento— pero las
  interpoladas del medio quedan mal. La mitigación es que el generador exige confirmar,
  y confirmar es mirar. **No es una mitigación completa: alguien puede confirmar un
  tramo de cuarenta fojas sin mirarlas una por una.**
* La foliatura con `vta.` no entra a los tramos porque rompe la relación
  `foja = página + desplazamiento`. Se usa el valor leído directamente, que es lo más
  confiable que hay, pero un legajo foliado sólo en el anverso —donde el reverso escaneado
  no lleva número— va a producir tramos cortados en cada vuelta.
* **[PARA CODEX]** Medir el detector contra foliatura real, no sintética: sellos
  desalineados, números manuscritos, foliatura a dos columnas, expedientes con dos
  numeraciones simultáneas (la del cuerpo y la del legajo). El fixture sintético imprime
  el número siempre en el mismo lugar y con la misma tipografía, que es el caso fácil.

---

## 3. El corte en piezas

**Qué se hizo.** Se corta donde el encabezado de la página pega contra un patrón del
catálogo. Está sesgado a cortar de más, y eso es deliberado: partir de más se arregla
con dos clics y esconder una pieza adentro de otra no lo ve nadie.

**Lo que se encontró revisando, y es el hallazgo más importante de todo el trabajo.**
La primera versión buscaba la palabra «continuación» suelta como marca de continuidad, y
se comía una pieza entera: la página decía `TRANSCRIPCIÓN DE CONVERSACIONES` en el
título y abajo, en el cuerpo, «Se transcriben **a continuación** los intercambios…».
Esa locución es de las más comunes en prosa jurídica. El sistema no cortaba y la
transcripción quedaba adentro del informe del gabinete informático. Se corrigió con
patrones que exigen paréntesis o contador de hojas, y con una regla nueva: una marca de
continuidad sólo tapa el corte cuando el título que pegó es del **mismo tipo** que la
pieza abierta.

El segundo hallazgo: los patrones anclados a principio de línea (`^OFICIO`, `^ACTA`) no
pegaban nunca, porque el título jamás es lo primero de la página —arriba está la foja
sellada y el membrete—. Faltaba `re.MULTILINE`. Escondía el oficio adentro de la
declaración testimonial anterior.

**Lo que queda expuesto.**

* Un documento **sin título** —una planilla, una tabla, un anexo de extractos
  bancarios— no produce corte y queda absorbido por la pieza anterior. Es exactamente el
  error caro, y el catálogo no puede cubrirlo con patrones porque no hay texto que
  reconocer. Hoy la única defensa es la advertencia `pieza_larga` y que la persona mire.
* El catálogo es de títulos en castellano rioplatense de expediente penal. Un oficio de
  un banco redactado como carta comercial no pega contra nada y sale
  `sin_clasificar` —lo cual está bien, la pieza existe igual— pero sin corte no existe.
* **[PARA CODEX]** Buscar señales de corte que no dependan del título: cambio de
  membrete entre páginas consecutivas, bloque de firma al pie, cambio brusco de densidad
  de texto o de márgenes, página en blanco como separador. Y medir cuánto suben los
  falsos positivos.

---

## 4. Persistencia y pérdida de trabajo

**Qué se hizo.** Cada decisión se escribe en la misma petición que la origina y la
interfaz dice «guardado» sólo cuando el servidor contestó que sí. `revision` es
append-only. Volver a detectar no pisa lo revisado; volver a foliar no pisa lo
confirmado; volver a leer no relee lo leído.

**Lo que queda expuesto.**

* **Dos pestañas sobre el mismo caso no se coordinan.** La segunda no se entera de lo
  que decidió la primera hasta que se recarga. No hay pérdida de datos —la última
  escritura gana y queda en el historial— pero sí hay confusión posible: dos personas
  revisando el mismo legajo se pisan las decisiones sin aviso.
* **Reordenar los PDF corre la numeración global debajo de la evidencia.** Se remapea
  por id de página, que es lo único estable, y hay prueba. Pero los tramos de foliatura
  se borran y hay que volver a detectar; las fojas **confirmadas** se conservan.
* Editar la descripción usa `change` del navegador, o sea que guarda al salir del campo.
  Si alguien escribe media descripción y cierra la pestaña sin salir del campo, esa
  media descripción se pierde. **No está resuelto.**
* **[PARA CODEX]** Escenarios de pérdida: corte de energía durante `leer_caso`, dos
  procesadores sobre el mismo caso, SQLite en una carpeta de red, disco lleno a mitad de
  un `INSERT` de palabras.

---

## 5. Rendimiento con legajos grandes

**Qué se hizo.** Las imágenes no se guardan todas: el OCR trabaja sobre un pixmap en
memoria y el visor rasteriza bajo demanda a una caché con tope. El OCR reparte páginas
entre núcleos y confirma cada diez. El checklist se sirve paginado.

**Lo que queda expuesto, y hay que decirlo con todas las letras.**

* **No se midió con un legajo grande.** Lo medido es un legajo sintético de 39 páginas:
  0,28 s por página de OCR, que extrapolado da unos 23 minutos para 5.000 páginas. Es
  una extrapolación, no un número.
* `duplicados.detectar` compara de a pares con una ventana de 400 páginas. Con 800
  piezas apretadas en pocas fojas, la ventana no acota nada y la comparación es
  cuadrática en Python.
* La tira de fojas dibuja **un botón por página**. Con 5.000 páginas son 5.000 nodos en
  el DOM, y eso sí es un problema medible. **No está virtualizada.** Es el defecto de
  rendimiento más concreto que tiene la interfaz hoy.
* ~~`cargarEvidencias` pide hasta 500 piezas de una.~~ **Resuelto:** pide todas, de a
  tandas, y el checklist dibuja de a quinientas filas conservando la selección.
  Verificado en un navegador con 620 piezas.
* **[PARA CODEX]** Medir de verdad con 500, 2.000 y 5.000 páginas, y con varios PDF.

---

## 6. Privacidad

**Qué se hizo.** Ninguna llamada de red. Fuentes desde disco. Servidor en `127.0.0.1`.
Log sin contenido de documentos. `pruebas/test_privacidad.py` verifica que no haya
importaciones de red, ni URL externas, ni `fetch` fuera de rutas propias, ni analytics.

**Lo que queda expuesto.**

* **No hay control de acceso.** Cualquiera con acceso a la máquina abre el navegador y
  ve el legajo. En `127.0.0.1` eso equivale a tener acceso al disco, así que no agrega
  exposición; pero si alguien levanta el servidor con `--host 0.0.0.0` —cosa que el
  programa permite y avisa por consola— el legajo queda en la red de la oficina sin
  clave. AppUFIL tiene `acceso.py` con clave; acá quedó para después del MVP.
* Los originales quedan en `0444` pero la carpeta de datos no tiene permisos especiales.
* **[PARA CODEX]** Temporales de Tesseract, contenido en los volcados de excepción de
  `excepcion.detalle`, y qué queda en el WAL de SQLite después de borrar un caso.

---

## 7. Lo que el sistema promete y no cumple del todo

Para que quede escrito y no se descubra en uso:

* La agrupación automática por membrete, organismo o similitud semántica **no está**.
  Los sectores existen y funcionan, pero se crean y se llenan a mano.
* El arrastre para reordenar **no está**: se reordena por API y desde la ficha, con
  selectores y botones. La alternativa accesible es lo único que hay.
* La vista de cronología usa el orden cronológico del checklist, pero no dibuja una
  línea de tiempo.
* No hay exportación a DOCX. Hay RTF, que abre en Word y en LibreOffice, y la
  arquitectura está partida para que DOCX entre sin tocar el generador.
* La detección de fecha del documento sólo reconoce formatos completos. «A los doce días
  del mes de marzo», que es como está escrito en la mitad de las actas, no produce
  fecha, y eso deja muchas piezas en `SIN FECHA`. Es a propósito —completar el año sería
  inventar— pero hace que el orden cronológico sirva menos de lo que promete.
