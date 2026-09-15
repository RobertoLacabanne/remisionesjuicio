# Identidad visual

Cómo se ve Punteo y por qué. Está escrito para que alguien que no participó del
desarrollo pueda agregar una pantalla sin desarmar el conjunto.

Es una herramienta que va a usar gente de una fiscalía muchas horas seguidas, en
oficinas con luz de tubo y monitores viejos, para producir un escrito que se firma y
entra a un legajo. Todas las decisiones de abajo salen de ahí.

---

## 1. La regla que manda: la tipografía dice de dónde salió el dato

Esto se toma entero de AppUFIL porque es la mejor idea de diseño de ese proyecto.

| Familia | Qué dice | Dónde |
|---|---|---|
| **Monoespaciada** — IBM Plex Mono | **Un dato leído del papel**, con su anclaje | fojas, páginas, SHA-256, confianza |
| **Serif** — Source Serif 4 | **Texto del documento** o del escrito | texto OCR de respaldo, vista previa del punteo |
| **Sans** — Archivo | **La aplicación hablando** | rótulos, botones, navegación, contadores |

Si un número de foja aparece en sans, la pantalla está mintiendo sobre de dónde salió.
Es el error más caro que se puede cometer en este sistema, y por eso lo dice la familia
tipográfica y no un ícono ni un color.

**Y al revés vale igual.** La descripción que escribió una persona no va en
monoespaciada: ahí la etiqueta miente para el otro lado.

Las tres se sirven desde disco. Ninguna llamada de red: el sistema tiene que andar
desconectado, y una tipografía que llega de un CDN también le cuenta a alguien que este
equipo está mirando este legajo.

Son las mismas fuentes que AppUFIL. Son OFL, ya están en el disco y bajarse otras no
agrega nada. **Lo que distingue a Punteo no es la letra: es el color y la densidad.**

---

## 2. Color

### Por qué el cromo no es azul

AppUFIL usa azul tribunal como cromo. Punteo no puede: su distinción principal son tres
estados de decisión —incluida, excluida, pendiente— que necesitan verde, punzó y ámbar,
y agregar un azul institucional encima deja la pantalla con cuatro colores peleando por
significar algo.

El cromo de Punteo es **grafito**. Es un color que no compite: no significa nada, y por
eso deja que los tres que sí significan se lean de lejos. El detalle institucional lo
pone el **bronce**, que es adorno y no lleva información nunca.

Y hay una lección heredada que conviene no repetir: en AppUFIL, el color del cromo y el
color de «firme» llegaron a ser el mismo hex, y un color que significa dos cosas no
significa ninguna. Acá el verde tiene un solo significado en toda la pantalla —**esta
pieza va al escrito**— y no se usa para nada más, ni para un botón, ni para un enlace,
ni para un «guardado».

### La paleta

| | Token | Claro | Oscuro |
|---|---|---|---|
| grafito (cromo) | `--grafito` | `#1E242C` | `#0C1014` |
| grafito elevado | `--grafito-2` | `#2A323C` | `#151B22` |
| bajo el puntero | `--grafito-3` | `#3A4552` | `#1F2831` |
| texto sobre grafito | `--grafito-txt` | `#F4F6F8` | `#E8EDF2` |
| rótulos sobre grafito | `--grafito-txt-2` | `#A8B4C0` | `#8D99A6` |
| bronce (institucional) | `--bronce` | `#B08442` | `#C89B55` |
| **incluida** | `--incluir` | `#2C6A4B` | `#74BC97` |
| **excluida** | `--excluir` | `#A81F26` | `#F08B8B` |
| **pendiente** | `--pendiente` | `#8A6714` | `#E5C57C` |
| papel | `--papel` | `#FBFAF7` | `#0E1216` |
| papel secundario | `--papel-2` | `#F1EFE9` | `#161C22` |
| superficie elevada | `--papel-3` | `#E7E4DC` | `#1D242B` |
| tinta | `--tinta` | `#141A21` | `#EEF2F6` |
| tinta secundaria | `--tinta-2` | `#4E5866` | `#A6B1BC` |
| marginalia | `--tinta-3` | `#6E7885` | `#7F8A96` |
| filete | `--filete` | `#DAD6CC` | `#2A333C` |
| borde de control | `--borde` | `#737D89` | `#59646F` |
| enlace / acción | `--accion` | `#2F5D82` | `#7FB0D8` |

### Qué puede decir cada color

* **Verde** — **incluida**, y nada más. Nunca un botón, nunca un enlace, nunca un
  «guardado». Es el color que dice que una pieza va a salir en el escrito, que es la
  afirmación más cara de la pantalla.
* **Punzó** — **excluida**, y las acciones destructivas. Son la misma idea: esto no va.
* **Ámbar** — **pendiente**, y las advertencias. También la misma idea: hay trabajo por
  hacer y se puede seguir trabajando igual.
* **Grafito** — quién sos y dónde estás parado. Es cromo: no informa nada sobre un dato.
* **Bronce** — el filete institucional y el ítem activo de la barra. Sobre papel da
  contraste insuficiente para texto, así que ahí es adorno y no puede llevar información.
* **Azul acción** — enlaces y el botón principal. Es el único azul y no toca el verde.

---

## 3. La tira de fojas

Es el motivo propio de Punteo y la cosa que se ve de lejos.

A la izquierda del visor corre una tira vertical con una marca por página del legajo,
pintada según el estado de la evidencia que la cubre: verde, punzó, ámbar, o gris si
ninguna pieza pasa por ahí. En un legajo de quinientas fojas, esa tira contesta de un
vistazo la pregunta que más se repite: **¿por dónde voy?**

La marca de la página abierta es la única que lleva el bronce. Se puede hacer clic en
cualquier parte de la tira para saltar.

---

## 4. Densidad

La pantalla de revisión está hecha para mirarla ocho horas. Eso manda tres cosas:

* **nada se esconde detrás de una animación.** El único movimiento es el de la rueda
  que dice «procesando», porque decir «esperá» con algo quieto no se distingue de
  decirlo con algo colgado;
* **el interlineado del checklist es apretado a propósito**, 30 px por fila, para que
  entren treinta piezas en pantalla y no doce;
* **los tres botones de decisión son enormes** y están siempre en el mismo lugar. Son
  el gesto que se repite cuatrocientas veces por legajo.

Atajos: `I` incluir, `E` excluir, `P` pendiente, `←` `→` anterior y siguiente, `B`
buscar, `M` crear evidencia desde esta foja, `F` editar la foja de la página.

---

## 5. Responsive

Escritorio es la prioridad y no se disimula: la revisión intensa se hace en un monitor.

Por debajo de 1100 px los dos paneles se apilan, con el documento arriba y la ficha
abajo, y los tres botones de decisión quedan fijos al pie de la pantalla, al alcance del
pulgar. La tira de fojas se acuesta y pasa a ser horizontal.

Por debajo de 700 px el checklist deja de ser tabla y pasa a ser una lista de fichas:
una tabla de nueve columnas en un teléfono no se lee, se adivina.

---

## 6. Modo oscuro

Se sigue la preferencia del sistema, y se puede forzar. Los tres colores de estado
suben de luminosidad en oscuro para mantener el contraste sobre fondo negro: el verde
`#2C6A4B` sobre papel claro y el `#74BC97` sobre fondo oscuro dicen lo mismo, y ninguno
de los dos se lee mal.
