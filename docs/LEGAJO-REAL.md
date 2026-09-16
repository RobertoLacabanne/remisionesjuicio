# La primera medición sobre un legajo real

Hasta acá el sistema se había medido contra el legajo sintético que arma
`herramientas/generar_legajo.py`: 39 de 39 fojas correctas, 16 de 16 piezas con el rango
exacto. Era un buen piso y no era una prueba: los fixtures los escribe el mismo código
que después los lee, y lo que no aparece en ellos no se puede descubrir.

Este documento es lo que pasó la primera vez que entró un legajo penal escaneado de
verdad —84 páginas, la primera parte de un legajo de corrupción, sin capa de texto,
íntegramente rasterizado— y qué se cambió como consecuencia.

**Del legajo no queda nada acá.** Ni número, ni carátula, ni nombres, ni una línea de su
texto. Lo que se documenta son los mecanismos que fallaron, con los datos mínimos para
entender por qué. El legajo vivió en `datos/`, que no está versionado, en la máquina
donde se corrió la prueba.

---

## Lo que ya andaba

- **La lectura.** 84 de 84 páginas leídas, 0 fallidas, en 1 minuto con OCR real sobre
  escaneo puro. Confianza media por página alta salvo en las que son foto o captura.
- **La ingesta.** SHA-256, original en `0444`, numeración global. Sin una observación.
- **El visor y la revisión.** La pieza, su imagen, el resalte del fragmento que la
  sustenta y sus avisos, todo en la misma pantalla. Funcionó tal como estaba diseñado.
- **La carga en partes.** El legajo venía cortado en dos archivos. Cargar el segundo
  procesó sólo sus páginas, propuso sólo sobre las nuevas y dejó intactas las decisiones,
  la descripción corregida y la exclusión hechas sobre el primero.
- **La invariante.** Lo excluido no apareció en la salida; lo corregido salió corregido.

## Lo que falló

Cuatro cosas, y las cuatro fallaban **en silencio y hacia el lado caro**: el sistema no
avisaba nada, y el resultado era plausible.

### 1. La foliatura detectada era falsa, con alta confianza

El detector encontró dos tramos en el pie derecho y les creyó: uno daba fojas 3 a 6, otro
daba fojas 2 a 11. Catorce páginas quedaron con foja `detectada` y confianza 0,80 y 0,89.

No era foliatura. Era la paginación interna de dos documentos que numeran sus propias
hojas desde 1, como hacen todos los informes. La foliatura real del legajo es un sello
redondo con el número escrito **a mano**, muy por encima de la foja mil, que Tesseract no
lee.

El sistema exige confirmar la foja antes de escribirla en un escrito, así que la barrera
final aguantaba. Pero lo que ofrecía para confirmar era falso, y confirmar un tramo es un
botón.

**Lo que se agregó:** un control de coherencia entre tramos. Una foliatura de legajo no
puede repetir una foja ni retroceder cuando avanza la página; dos tramos que se
contradicen no pueden ser los dos foliatura. Caen **los dos**, no gana el más creíble: la
contradicción prueba que la señal no sirve, no cuál de los dos era buena. Un tramo que no
contradice a nadie sobrevive, así que un legajo foliado en dos etapas sigue funcionando.

Sobre este legajo: de 14 fojas falsas a ninguna.

### 2. El sello de folio no se distinguía de una hoja sin foliar

Las hojas selladas quedaban en `desconocida`, junto a las que nadie folió. Son dos cosas
muy distintas: en una hay un número para copiar del papel, en la otra no hay nada.

**Lo que se agregó:** cuando se lee la palabra del sello en zona de margen y no se lee
ninguna cifra, la página queda marcada como `sello_ilegible`. No se le pone foja —el
número no se leyó y no se inventa—, pero el visor dice «hay sello de folio: copiá el
número» y la tarjeta de foliatura las cuenta aparte.

### 3. Siete actas escondidas adentro de una sola pieza

El legajo trae siete actas de declaración testimonial, cada una de un testigo distinto,
cada una con «ACTA DE DECLARACIÓN TESTIMONIAL» centrado y en negrita. El detector no
reconoció ninguna, y las siete quedaron adentro de una sola pieza de treinta y ocho
páginas. Es exactamente el error que la arquitectura declara como el caro: una pieza
escondida adentro de otra no la ve nadie.

La causa no era el catálogo. Era que en un escaneo de verdad, arriba de todo no está el
título: están el borde negro de la hoja, el sello, una firma al margen y las marcas del
abrochado. De eso el OCR saca renglones como `A! ES GN`, `| /` o `2, SÍ`, y las seis
líneas del encabezado se gastaban ahí.

**Lo que se agregó:** una línea que no aporta al menos seis letras no cuenta como
encabezado. No se mira ni una línea más abajo que antes; se miran seis líneas que dicen
algo. Entre cuatro y diez letras el resultado sobre este legajo no cambia, así que se
tomó el extremo conservador del tramo estable.

De 6 piezas a 15, con las siete actas separadas y su tipo reconocido.

### 4. Las siete actas salían con la misma fecha, y era falsa

Las siete fueron labradas entre el 27 de agosto y el 4 de septiembre. Las siete salían
con fecha 7 de agosto: la de la resolución que ordenó las actuaciones, que las siete citan
en su primer párrafo. El detector tomaba la primera fecha del texto.

Esa fecha se escribe en el punteo —«Acta de declaración testimonial, de fecha …»— y se
usa para ordenar cronológicamente.

**Lo que se cambió:** ya no se busca «una fecha». Se buscan las dos fórmulas con las que
un instrumento declara la suya: la de otorgamiento («a los 28 días del mes de agosto del
año 2025») y la de encabezamiento («Paraná, 14 de julio del 2025»), donde el lugar y la
coma son lo que la atan a este documento. Una fecha suelta en el cuerpo no se afirma,
aunque sea la única del texto: en un expediente suele ser la del oficio que se contesta o
la de la resolución que se cita.

Las siete actas pasaron a tener su fecha real, distinta cada una. Tres piezas donde antes
se afirmaba una fecha equivocada quedaron sin fecha, que es lo correcto: el campo vacío lo
completa quien revisa, que tiene el documento a la vista.

### 5. Veintiún duplicados propuestos, ninguno verdadero

Este apareció **como consecuencia** del arreglo 3: separadas las siete actas, el detector
de duplicados las comparó entre sí y propuso los veintiún pares. Se parecen al noventa por
ciento porque comparten el formulario entero —membrete, fórmula de juramento, el artículo
275 del Código Penal transcripto— y son siete testigos distintos.

El propio módulo dice que el ruido es peor que no tener las propuestas.

**Lo que se agregó:** dos documentos con fecha cierta y distinta no son el mismo
documento. Es un descarte duro y no toca el duplicado verdadero, que trae la misma fecha
en las dos copias; si a una de las dos le falta la fecha, no hay contradicción y el par se
propone igual.

De 21 propuestas falsas a ninguna.

---

## El patrón

Los cinco son el mismo error de fondo: **el sistema afirmaba a partir de una señal
compatible con lo que buscaba, en lugar de exigir una señal que sólo pudiera significar
eso**. Un número que crece en el margen es compatible con una foliatura, y también con la
paginación de un informe. Una fecha en el texto es compatible con la fecha del documento,
y también con la de cualquier documento que el documento cite.

Los cinco arreglos tienen la misma forma, y conviene tenerla a mano para el próximo: se
buscó una **contradicción dura** —la foja no retrocede, dos fechas ciertas no son la misma
pieza— o una **marca de atribución** —la fórmula de otorgamiento, el sello en el margen—,
en lugar de subir un umbral. Un umbral más alto hubiera tapado estos casos y dejado pasar
los siguientes.

Y los cinco se descubrieron porque un legajo real trae cosas que un fixture sintético no
tiene: el borde de la hoja escaneada, el sello manuscrito, el formulario repetido, la
resolución citada en el primer párrafo.

## Lo que sigue estando sin resolver

- **El número del sello no se lee.** Es manuscrito y Tesseract no lee manuscrita. Hoy se
  marca la hoja para que alguien copie el número; leerlo sería otro problema, y uno que no
  se resuelve sin un modelo, que es una dependencia que este sistema no tiene.
- **La descripción propuesta sigue siendo pobre** cuando el título no se reconoce: sale un
  fragmento del cuerpo. Es material de corrección humana y el sistema lo marca como tal,
  pero es lo próximo que conviene mejorar.
- **Sigue sin medirse un legajo grande de verdad.** Ochenta y cuatro páginas no dicen nada
  de mil.
