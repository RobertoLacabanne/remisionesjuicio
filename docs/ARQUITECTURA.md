# Arquitectura — Punteo de Evidencia

Cómo está construido el sistema y por qué. Escrito para que alguien que no participó
del desarrollo pueda agregar una función sin romper las invariantes que sostienen todo
lo demás.

El sistema existe para una sola cosa: que una persona de la fiscalía revise un legajo
escaneado y salga de ahí con un punteo de prueba que contenga **exactamente** las
piezas que esa persona decidió incluir, ninguna más y ninguna menos, cada una con su
foja verificable. Todo lo que sigue es subordinado a eso.

---

## 0. Qué se decidió antes de escribir código

### 0.1 Un proyecto aparte, y por qué

Punteo es una aplicación distinta de AppUFIL y vive en su propio repositorio. No
comparte paquete de Python, ni base de datos, ni configuración, ni una sola línea de
código de contratos, facturas o contratados.

La separación no es de prolijidad: es de dominio. AppUFIL contesta «¿qué dice este
volumen de documentación administrativa?» sobre contratos y comprobantes de la
Legislatura. Punteo contesta «¿qué prueba ofrece Fiscalía en este legajo, y en qué
foja está cada pieza?». Arrastrar el vocabulario de contratos al modelo de datos de
la evidencia habría producido una aplicación que parece dos aplicaciones.

Lo que sí se tomó de AppUFIL —el diseño, no el árbol de archivos— está en
[`REUTILIZACION-APPUFIL.md`](REUTILIZACION-APPUFIL.md), componente por componente.

**El proyecto es autosuficiente.** Las tres tipografías viven en `assets/fuentes/` con
sus licencias OFL: nada se pide a un servidor y nada depende de que AppUFIL esté al
lado en el disco.

### 0.2 El segundo agente

El protocolo de trabajo pide que Claude y Codex analicen en paralelo y que cada
decisión importante pase por dos análisis independientes. En el entorno donde se
construyó esta primera etapa **Codex no está disponible**: no hay plugin instalado, no
hay marketplace configurado, no hay binario `codex` en el PATH y no hay credenciales de
OpenAI. Está verificado, no supuesto.

Por lo tanto: el análisis de arquitectura que sigue es de un solo agente, y este
documento lo dice en lugar de presentarlo como una síntesis de dos. Lo que sí se hizo,
porque no depende de Codex, es el trabajo adversarial explícito contra las propias
decisiones, que está en [`REVISION-ADVERSARIAL.md`](REVISION-ADVERSARIAL.md). No es lo
mismo y no pretende serlo: es el mismo modelo revisándose, con los sesgos que eso
implica. Cuando Codex esté conectado, los puntos marcados **[PARA CODEX]** en ese
documento son los que conviene someterle primero.

---

## 1. La forma general

Un proceso de Python que sirve una interfaz web en `127.0.0.1`. Nada sale de la
máquina. El trabajo pesado —leer los PDF, hacer OCR, proponer evidencia— corre en un
hilo de fondo con progreso real; la interfaz consulta ese progreso y no se cuelga.

```
                    ┌──────────────────────────────────────┐
   PDF del legajo ─►│ ingesta   SHA-256 · original 0444    │
                    │           páginas · sin reescribir    │
                    └───────────────┬──────────────────────┘
                                    ▼
                    ┌──────────────────────────────────────┐
                    │ ocr       texto nativo o Tesseract    │
                    │           palabras con coordenadas    │
                    └───────────────┬──────────────────────┘
                                    ▼
                    ┌──────────────────────────────────────┐
                    │ foliatura  número impreso en el       │
                    │            margen, validado por serie │
                    └───────────────┬──────────────────────┘
                                    ▼
                    ┌──────────────────────────────────────┐
                    │ evidencia  corte en piezas + tipo     │
                    │            PROPONE, no decide         │
                    └───────────────┬──────────────────────┘
                                    ▼
        ╔═══════════════════════════════════════════════════════╗
        ║  REVISIÓN HUMANA — incluir · excluir · pendiente       ║
        ║  con la foja a la vista, siempre                       ║
        ╚═══════════════════════════┬═══════════════════════════╝
                                    ▼
                    ┌──────────────────────────────────────┐
                    │ v_evidencia_incluida   ◄── la puerta  │
                    └───────────────┬──────────────────────┘
                                    ▼
                    ┌──────────────────────────────────────┐
                    │ generacion  arma el texto del punteo  │
                    │ exportacion RTF · JSON · portapapeles │
                    └──────────────────────────────────────┘
```

La línea gruesa del dibujo está en el medio a propósito. Arriba de ella el sistema
propone; abajo de ella solamente se ejecuta lo que una persona decidió. El generador no
tiene acceso a nada que esté arriba de esa línea, y la sección 6 explica cómo se
garantiza eso.

---

## 2. Stack, y por qué este

Python 3.11, SQLite, servidor de la biblioteca estándar, HTML/CSS/JavaScript sin
framework ni paso de compilación. Tres dependencias externas y ninguna más:
**PyMuPDF** para abrir PDF y rasterizar páginas, **Pillow** para manipular imágenes,
**pytesseract** como puente a un **Tesseract** local.

Es el stack de AppUFIL, y se mantiene por las mismas razones, que siguen siendo buenas:
la máquina de producción no necesita Node ni compilar nada; la restricción de que el
sistema ande desconectado se cumple sola porque no hay un recurso que no salga del
disco; y el día que el que lo instaló no está, alguien puede leer los archivos y
entender qué hacen.

Se evaluó y se descartó FastAPI. El servidor de `http.server` con `ThreadingHTTPServer`
alcanza de sobra para dos o tres personas en una red de oficina, y lo que se ganaría en
comodidad de escritura se pagaría en una dependencia más que hay que llevar a una
máquina sin internet.

---

## 3. Un caso, un archivo

Cada caso vive en su propia carpeta con su propia base:

```
datos/
  casos/
    <slug>/
      punteo.sqlite        la base del caso
      originales/<sha>.pdf los PDF, en 0444
      derivados/           imágenes de página, regenerables
      export/              lo que se generó
```

Es la decisión de AppUFIL y se reutiliza con convicción. Separar por archivo y no por
una columna `caso_id` convierte «ningún cálculo cruza casos» en un hecho físico en
lugar de un `WHERE` que alguien puede olvidarse de escribir. Respaldar un caso es
copiar una carpeta; borrarlo es borrarla; entregarlo es mandarla. Y una consulta mal
escrita no puede traer evidencia de otra causa, porque esa evidencia no está en la base
que la consulta abrió.

El costo es que no hay vista global entre casos. Para este sistema eso no es un costo:
no hay una sola pregunta legítima que cruce dos legajos penales distintos.

La resolución de cuál es el caso activo es **por hilo**, como en AppUFIL. El servidor
atiende en varios hilos y el procesamiento corre en otro; una variable global
significaría que abrir un caso en una pestaña le cambia el caso al trabajo que está
corriendo en otra.

---

## 4. Foja y página son dos cosas

Esta es la distinción de la que depende que el escrito sirva. En el texto final se cita
`fs. 342/346`; si ese número sale de la página del PDF, la cita es falsa y el error
llega a un tribunal.

Por eso no hay en ninguna parte del sistema una conversión implícita entre una cosa y
la otra. Son columnas distintas, se muestran las dos siempre, y el generador usa
**solamente la foja**.

### El modelo

En un expediente argentino la foja no es un entero. Es `411`, y también `411 vta.`
—el reverso de la misma hoja, que se folia como continuación— y también `411 bis`
—una hoja intercalada después de foliar—. Guardar eso como `INTEGER` pierde
información el primer día.

| columna | qué guarda |
|---|---|
| `numero_pdf` | página dentro de su PDF, 1-based |
| `numero_global` | página dentro del caso, en orden de documento |
| `foja_etiqueta` | lo que se lee en el papel: `411`, `411 vta.`, `411 bis` |
| `foja_num` | la parte entera, para ordenar y para los rangos |
| `foja_sufijo` | `''`, `vta`, `bis` |
| `foja_origen` | `detectada` · `confirmada` · `manual` · `desconocida` |
| `foja_confianza` | 0..1, cuánto se le cree a la detección |

`foja_origen` es el campo que impide el error que este sistema existe para que no pase.
Una foja `detectada` es una conjetura de la máquina y la interfaz la muestra como tal,
con su marca; una `confirmada` la miró una persona. **El generador exige que la foja de
toda evidencia incluida esté confirmada o cargada a mano, y si no lo está avisa antes de
generar en lugar de escribir un número que nadie verificó.**

Una cita tiene **dos** fojas, y cada extremo tiene su origen: `v_evidencia` expone
`foja_origen` (inicio), `foja_fin_origen` y `foja_firme`, que es verdadero sólo si los
dos están confirmados o cargados a mano. Con un único origen, confirmar la foja donde
empieza una pieza hacía pasar por verificada la foja donde termina. Si a una pieza de
varias páginas le falta la foja final, la cita sale `fs. 409/[FOJA PENDIENTE]` y no
`fs. 409`; si adentro del rango la foliatura salta —otro tramo en el medio—, sale con
`[RANGO DE FOJAS A REVISAR]`.

`pagina.foja_lectura` distingue además cómo se obtuvo el número: `leida` en el papel,
`interpolada` desde el tramo, o `desconocida` en las bases anteriores a esa columna.
Confirmar un tramo no convierte en leído lo interpolado, y el chequeo previo lo cuenta.

Un legajo sin foliar es un caso normal, no un error: todas las páginas quedan en
`desconocida`, el sistema funciona igual usando `numero_global` como referencia técnica,
y las fojas se completan después, cuando el legajo se folie o cuando la persona las
cargue.

### Cómo se detecta la foliatura

Un número suelto en una esquina no prueba nada: puede ser un número de expediente, un
año, o basura de OCR. Lo que prueba una foliatura es la **serie**.

El detector busca candidatos a número de foja en las cuatro zonas de margen donde se
folia —arriba a la derecha, arriba al centro, abajo a la derecha, abajo al centro— y
después busca **tramos de páginas consecutivas donde el candidato de la misma zona
crece de a uno**. Un tramo de veinte páginas donde el número del margen superior
derecho va 402, 403, 404… es foliatura y no puede ser otra cosa. Un número que aparece
una sola vez no entra.

Dentro de un tramo, la relación queda como un desplazamiento: `foja = numero_global +
desplazamiento`. Eso permite dos cosas que hacen falta de verdad. La primera es
completar las páginas del tramo donde el OCR no leyó el número, por interpolación, que
es correcto porque la serie ya está probada. La segunda es que **el desplazamiento
cambia entre tramos** —pasa siempre: se intercala documentación, se folia en dos
etapas, hay un cuerpo nuevo— y el sistema modela eso como lo que es, varios tramos con
su propio desplazamiento, en lugar de forzar un único número global que estaría mal en
medio legajo.

La confianza sale del largo del tramo y de la proporción de páginas donde el número se
leyó de verdad contra las interpoladas.

---

## 5. El modelo de evidencia

### 5.1 Lo detectado no se pisa nunca

Cada campo revisable existe dos veces: lo que leyó la máquina y lo que dejó la persona.

```
descripcion_detectada   TEXT   -- lo que propuso el sistema. No se escribe más.
descripcion_final       TEXT   -- lo que decidió la persona. NULL = vale la detectada.
```

Lo mismo para el tipo y para las fojas. `NULL` en el campo final significa «nadie lo
tocó, vale lo detectado», y no «vacío». Esto da tres cosas gratis: se puede mostrar qué
cambió una persona y qué no, se puede volver atrás sin reprocesar, y la columna
`modificadas manualmente` del checklist es una consulta y no una heurística.

La lectura correcta es siempre `COALESCE(final, detectada)`, y para eso existe la vista
`v_evidencia`, que es la que usan todas las pantallas. Ninguna consulta de interfaz lee
las columnas crudas.

### 5.2 Los estados, y por qué son tres y no cuatro

`pendiente`, `incluida`, `excluida`. No hay un cuarto.

Se consideró un estado `sugerida` para lo que el sistema propone con confianza alta y
se descartó: sería un estado que se parece a «incluida» sin que nadie lo haya decidido,
y la primera vez que alguien genere un punteo sin revisar hasta el final, esa
semejanza se convierte en prueba ofrecida que nadie leyó. Toda evidencia nace
`pendiente`. La confianza de la detección se muestra al lado, en su propia columna,
donde no se puede confundir con una decisión.

### 5.3 Dividir y unir sin perder el rastro

La detección se equivoca, y de las dos maneras: parte en dos lo que es una pieza, y
junta en una lo que son dos. Las dos operaciones tienen que existir y ninguna de las
dos puede borrar nada.

No se borra: se marca `activa = 0` y se deja el rastro. Una evidencia que salió de una
división guarda en `origen_id` de cuál salió; una unión guarda todas sus partes en
`evidencia_parte`. Así se puede contestar «¿de dónde salió esta pieza?» y, sobre todo,
deshacer.

**Una pieza excluida no se une ni se divide.** La pieza nueva copia la descripción de
su origen, así que excluir A, unirla con B e incluir la unión sacaba al escrito la
descripción de A con A todavía excluida. Hay que volverla a pendiente primero, y esa
decisión queda en el historial. Por la misma razón, incluir una pieza controla su linaje
completo —partes de uniones y origen de divisiones, recursivamente—, y `restaurar` sólo
enciende lo que se apagó por un **descarte**: lo absorbido por una unión se recupera
deshaciendo la unión, desde arriba hacia abajo.

`origen` distingue cómo nació cada una: `automatica`, `manual`, `division`, `union`. La
evidencia manual es ciudadana de primera y no lleva ninguna marca de segunda categoría;
lo único que la distingue es que su confianza no existe, porque no hay nada que medir en
algo que escribió una persona.

### 5.4 Los tipos son un catálogo, no un enum

Los tipos de pieza probatoria viven en `evidencia/catalogo.py` como datos: clave,
etiqueta, familia, patrones de título, peso. Agregar un tipo es agregar una entrada, no
tocar el motor. La base guarda la clave como texto libre y **no** tiene una
restricción `CHECK` contra la lista: un tipo que alguien agregó ayer no puede hacer
fallar la carga de un caso viejo.

La familia (`testimonial`, `documental`, `pericial`, `informativa`, `digital`,
`material`, `audiovisual`) es lo que alimenta la vista «por tipo de prueba» y el
encabezado del punteo agrupado.

---

## 6. La invariante: EXCLUIDO = IMPOSIBLE

Es el error que el sistema no puede cometer: que alguien marque una pieza como excluida
y el punteo la traiga igual.

No se resuelve con un `if` en el generador. Un `if` en el generador es exactamente lo
que falla el día que alguien agregue un segundo camino de generación y se olvide de
copiarlo. Se resuelve con tres barreras que fallan por separado:

**Primera, en la base.** Existe la vista `v_evidencia_incluida`, que filtra por
`estado = 'incluida' AND activa = 1`. El generador lee de ahí y de ningún otro lado. Se
llama con el nombre obvio a propósito: un `SELECT` futuro que se escriba apurado tiene
que salir seguro.

**Segunda, en el código.** La función que arma el punteo recibe una lista de piezas y
**verifica el estado de cada una antes de escribirla**, aunque ya vengan filtradas, y
verifica también que no haya salido de una pieza excluida. La redundancia se paga sola:
las dos barreras las escriben caminos distintos y si una queda mal, la otra sigue. El
armado y el guardado van adentro de un mismo `BEGIN IMMEDIATE`: si la barrera controla
y otra pestaña excluye antes de que se escriba, el control no dice nada.

**Y al exportar.** El punteo se guarda como texto, así que todo lo que cambie después
—una exclusión, pero también una descripción corregida, una foja confirmada, un testigo,
el orden, el tipo de proceso— lo deja viejo. `revalidar` vuelve a armar el punteo en
memoria con los mismos parámetros y lo compara con el guardado; si difiere en algo, la
exportación se niega. Al regenerar, las ediciones a mano pasan al punteo nuevo sólo si
el texto generado de su párrafo es idéntico, y se informa cuántas quedaron atrás.

**Tercera, en las pruebas.** `pruebas/test_invariante.py` arma un caso con piezas en
los tres estados, cambia estados de ida y de vuelta, genera, y verifica que en la
salida no aparezca ni el identificador ni el texto de ninguna excluida. Es la prueba
que no se puede borrar.

La segunda mitad de la invariante es igual de importante y tiene su propia prueba: si
una persona corrigió la descripción, la foja o el testigo, **la salida usa el valor
corregido y no el detectado**. Un sistema que respeta la exclusión pero imprime la
descripción vieja falla por el otro lado.

---

## 7. No decidir sin ver

Tomado de AppUFIL y convertido en invariante: cuando alguien decide sobre una pieza,
tiene la foja que la sustenta a la vista en la misma pantalla.

En la práctica eso significa que los botones de incluir, excluir y pendiente **no
existen en ninguna pantalla donde no haya visor**, y que si la imagen de la página no
pudo cargarse, la interfaz lo dice con todas las letras y no deja decidir a ciegas. El
checklist general permite cambiar de estado en lote, pero solamente sobre piezas que ya
tienen un estado decidido: sirve para rectificar, no para decidir por primera vez.

---

## 8. Rendimiento con legajos grandes

El objetivo declarado son legajos de miles de páginas. Dos decisiones lo hacen posible
y las dos se apartan de AppUFIL.

**Las imágenes no se guardan todas.** AppUFIL rasteriza cada página a PNG durante el
procesamiento. A 200 DPI eso son unos 500 KB por página: un legajo de 5.000 páginas
ocupa dos gigas y medio en imágenes que en su mayoría nadie va a mirar. Acá el OCR
trabaja sobre un pixmap **en memoria** y lo descarta; el visor pide la imagen de la
página que está mirando y esa se rasteriza en el momento y se guarda en una caché con
tope de tamaño, en JPEG de calidad alta, que para un escaneo pesa entre un quinto y un
décimo de lo que pesa el PNG. La caché se puede borrar entera sin perder nada.

**La interfaz no dibuja la lista entera.** El servidor entrega las piezas de a
quinientas y la interfaz las pide todas, tanda por tanda: revisar tiene que poder llegar
a la última, y la primera versión se quedaba en la quinientos. Lo que se dosifica es el
DOM: el checklist dibuja quinientas filas y ofrece las siguientes, sin perder la
selección. La tira de páginas agrupa marcas por encima de trescientas. No hay
virtualización propiamente dicha.

**La imagen se identifica por el documento, no por el número de página.** La caché y la
etiqueta que revalida el navegador usan el SHA-256 del PDF, la página dentro de él, la
rotación y el DPI. El número global se mueve al reordenar los PDF, y con esa clave el
visor mostraba la hoja de otro documento al lado de los datos del correcto.

El OCR reparte las páginas entre los núcleos disponibles, como en AppUFIL, y confirma a
la base cada pocas páginas: un corte de luz a los ochenta minutos no puede costar los
ochenta minutos.

---

## 9. Persistencia y guardado

Toda decisión de revisión se escribe a la base en el momento, en la misma petición que
la origina, y la interfaz **muestra «guardado» recién cuando el servidor contestó que
sí**. No hay optimismo: si la escritura falla, la pantalla dice que falló y no cambia el
estado visual de la pieza.

No hay autosave por temporizador porque no hay nada que guardar más tarde. El único
lugar donde hay texto libre que se escribe de a poco —la descripción final y las
observaciones— guarda con `debounce` corto y muestra su propio estado.

Cada cambio relevante deja una fila en `revision`: qué evidencia, qué campo, valor
anterior, valor nuevo, cuándo. Es append-only y nunca se pisa, porque corregir dos veces
no puede borrar la explicación de la primera corrección. El orden manual también se
anota: lo que no deja rastro, la redetección lo trata como descartable.

**Volver a detectar no pisa nada.** La detección propone sólo sobre páginas que ninguna
pieza vigente cubre —activa, descartada a propósito, o representada por lo que salió de
ella—, y cada pieza cubre sólo páginas de su propio documento. Así, cargar otro PDF
propone su evidencia sin tocar lo revisado. «Rehacer» reemplaza únicamente las
propuestas que nadie tocó —sin decisión, corrección, testigo, sector, etiqueta,
duplicado resuelto ni historial— y deja constancia en `revision`. Las dos operaciones
toman el candado de escritura antes de leer la cobertura.

**Una base más nueva no se abre.** Si `user_version` es mayor que la que entiende el
programa, `db.inicializar` corta antes de tocar nada: el esquema viejo pisaría las
vistas nuevas y se llevaría sus controles.

---

## 10. Privacidad

El sistema no hace una sola llamada de red. No hay CDN, no hay fuentes remotas, no hay
analytics, no hay telemetría, no hay OCR en la nube, no hay modelo remoto. El servidor
escucha en `127.0.0.1` por omisión.

Los archivos temporales de Tesseract se escriben en el directorio temporal del proceso
y se borran; los originales quedan en modo solo lectura. Los logs del servidor no
registran contenido de documentos ni texto OCR: registran método, ruta, código y
duración.

Hay una prueba que verifica que en el código del paquete no aparezcan `http://`,
`https://` ni llamadas a `urllib`/`socket` fuera del servidor local. La única excepción
es `acceso.py`, que abre un socket UDP sin mandar nada para averiguar la IP de la
máquina, y está listada por nombre en la prueba.

Escuchar en `127.0.0.1` no alcanza contra el navegador de quien usa el sistema. Por eso:
ninguna ruta que cambie algo se atiende por `GET`; las escrituras con `Origin` ajeno o
`Sec-Fetch-Site: cross-site` se rechazan; y sin clave, la cabecera `Host` tiene que ser
local —o estar en `PUNTEO_HOSTS`—, que es la defensa contra el rebinding de DNS.

Los originales se guardan en `0444` y se comprueba que hayan quedado así: si el sistema
de archivos no respeta el permiso, la carga se corta. Para una carpeta que no puede
respetarlo existe `PUNTEO_ORIGINALES_SIN_PROTECCION=aceptar`, una decisión explícita
de quien instala; con ella la carga sigue, pero queda anotada y la pantalla lo avisa.
Un archivo que existe con el nombre de un hash y no hashea eso no se acepta ni se
reemplaza. Ese control ocurre al cargar: que el archivo siga intacto después lo
contesta `almacen.verificar`, que rehashea.

---

## 11. Modelo de datos

Esquema completo en [`punteo/esquema.sql`](../punteo/esquema.sql). El resumen:

```
caso ──┬── documento ──── pagina ──── palabra
       │                     │
       │                     └─ (foja_etiqueta, foja_num, foja_sufijo, foja_origen)
       │
       ├── grupo_evidencia ─┐
       │                    │
       ├── evidencia ◄──────┘        estado · origen · activa
       │      ├── evidencia_persona ──── persona
       │      ├── evidencia_etiqueta ─── etiqueta
       │      ├── evidencia_parte  (uniones)
       │      └── revision          (historial, append-only)
       │
       └── punteo_generado ──── punteo_parrafo ──► evidencia
```

`punteo_parrafo` es lo que sostiene el requisito de que el texto final se pueda editar
sin perder la relación `párrafo ↔ evidencia`. El punteo generado no es una cadena: es
una lista de párrafos, cada uno con su `evidencia_id` —o `NULL` si es un encabezado— y
su texto, que la persona puede editar. Exportar recorre esa lista. Así editar el texto
final no rompe la trazabilidad, que es lo que pasa cuando se aplana todo a un `TEXTAREA`.

---

## 12. Qué se reutilizó de AppUFIL

Se leyó el código, no se copió el árbol. La matriz completa, componente por componente,
está en [`REUTILIZACION-APPUFIL.md`](REUTILIZACION-APPUFIL.md). El resumen:

Se **adaptaron** —mismo diseño, código reescrito para el dominio nuevo— la ingesta con
SHA-256 y original inmutable, la lectura de página con palabras y coordenadas en puntos
PDF, el enderezado por resultado en lugar de por confianza del detector, el trabajador
de fondo con progreso y corte limpio, la conexión SQLite en WAL con esquema versionado,
la búsqueda FTS5 con `remove_diacritics`, el servidor de biblioteca estándar y la
separación por caso.

Se **reutilizó tal cual** el principio de «no decidir sin ver», la regla de que la
tipografía dice la procedencia del dato, la disciplina de no completar en silencio, y
los archivos de fuentes, que son OFL y ya están en disco.

Se **descartó** todo el dominio anterior: perfiles de contrato, extracción de campos de
factura, identidad de contratados, análisis económico, cruces de superposición,
consultas SQL del pliego, y el carril de interpretación de la Capa 5, que responde a un
problema que este sistema no tiene.

---

## 13. Riesgos

**El corte en piezas es el riesgo número uno.** Es lo que más valor agrega y lo que
más caro sale cuando falla. Un corte de más produce piezas partidas que la persona tiene
que unir a mano; un corte de menos esconde una pieza adentro de otra y ahí sí se puede
perder prueba. La mitigación es que el sistema está sesgado a **cortar de más**: es
mucho más barato unir dos piezas que descubrir que faltaba una. Y que la confianza baja
se ve y se puede filtrar.

**La calidad del OCR manda sobre todo lo demás.** Un escaneo a 150 DPI en gris, o una
fotocopia de fotocopia, produce texto que no alcanza para detectar ni títulos ni fojas.
El sistema no puede arreglar eso y no debe fingir que sí: las páginas cuya lectura sale
por debajo del umbral se marcan, se cuentan y se muestran juntas, para que la persona
sepa qué parte del legajo el sistema básicamente no leyó.

**La foliatura puede estar mal detectada en los bordes de cada tramo.** Es donde la
serie arranca y termina, y donde una interpolación puede pisar una hoja intercalada. Por
eso el generador exige confirmación de la foja antes de escribirla.

**El trabajo de revisión es lo único irreemplazable.** Todo lo demás se regenera
reprocesando. Por eso `revision` es append-only, por eso las decisiones se escriben en
el momento, y por eso el respaldo de un caso es copiar una carpeta.

**Un legajo de varios miles de páginas todavía no se midió.** Las decisiones de la
sección 8 están tomadas para que escale, pero medido de verdad está solamente hasta lo
que permiten los fixtures sintéticos. Está anotado como lo que es: una expectativa, no
un número.

---

El plan por etapas, con el estado de cada una, está en [`HITOS.md`](HITOS.md).

---

## 14. Lo que el MVP no hace

Y conviene decirlo para que nadie lo espere: no lee manuscrito, no clasifica por
similitud semántica, no propone agrupaciones automáticas por membrete todavía, no
exporta DOCX —exporta RTF, que abre en Word y en LibreOffice, y la arquitectura de
exportación ya está partida para que DOCX entre después sin tocar el generador—, y no
tiene control de usuarios.
