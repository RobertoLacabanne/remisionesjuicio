# Punteo de Evidencia

Unidad Fiscal de Investigación y Litigación de Paraná · Ministerio Público Fiscal de
Entre Ríos.

Herramienta para armar el punteo de prueba de un **requerimiento de remisión a juicio**
o de un **acuerdo de juicio abreviado**, a partir de un legajo penal escaneado.

Se carga el legajo, el sistema lo lee y **propone** una lista de posibles piezas de
evidencia. La persona revisa cada una con la foja a la vista y decide expresamente si la
incluye, la excluye o la deja pendiente. Al final, el generador arma el punteo **con
exactamente lo que se marcó para incluir, y nada más**.

La aplicación ayuda a encontrar, ordenar y describir evidencia. **Nunca decide qué
prueba ofrece Fiscalía.**

> Es una aplicación distinta de [AppUFIL](https://github.com/RobertoLacabanne/AppUFIL),
> que analiza documentación administrativa de contratos. Comparten oficina y algunas
> soluciones técnicas, y nada más: ver
> [`docs/REUTILIZACION-APPUFIL.md`](docs/REUTILIZACION-APPUFIL.md).

---

## Lo que hace hoy

Corre de punta a punta. El recorrido completo:

1. crear el caso con número de legajo, carátula y tipo de proceso;
2. arrastrar uno o más PDF del legajo;
3. procesar: lee cada página —texto nativo u OCR local—, busca la foliatura y propone
   las piezas, con barra de progreso y botón de parar;
4. revisar de a una, con el documento al lado y el fragmento resaltado: `I` incluir,
   `E` excluir, `P` pendiente, flechas para navegar;
5. corregir la descripción, el tipo, la foja y el testigo introductor;
6. agregar a mano la pieza que el sistema no encontró;
7. dividir lo que quedó junto, unir lo que quedó partido;
8. organizar en sectores y ordenar;
9. generar el punteo y exportarlo a `.rtf`, `.txt` o `.json`.

### Lo que todavía no hace

Agrupación automática por membrete u organismo, arrastre para reordenar, exportación a
DOCX, lectura de manuscrito y control de usuarios. El detalle honesto, con lo que puede
fallar y por qué, está en [`docs/REVISION-ADVERSARIAL.md`](docs/REVISION-ADVERSARIAL.md).

---

## Las reglas que no se negocian

| | |
|---|---|
| **Excluido es imposible** | Lo que una persona marcó para excluir no puede aparecer en la salida. Tres barreras distintas lo garantizan y una prueba lo verifica por los cuatro caminos que llegan al escrito. |
| **La foja no es la página del PDF** | Se guardan y se muestran siempre las dos. El escrito cita la foja. Una foja que detectó la máquina es una conjetura hasta que alguien la confirma, y hasta entonces sale marcada. |
| **No decidir sin ver** | Los botones de decidir sólo existen donde está el documento a la vista. Si la imagen no cargó, se dice con todas las letras. |
| **No inventar** | Si un dato no está determinado, queda vacío o con un marcador visible. Nunca se completa en silencio: ni una foja, ni una fecha, ni un nombre. |
| **No se pisa lo detectado** | Lo que corrige una persona va a una columna aparte. Se puede ver qué cambió y volver atrás sin reprocesar. |
| **No se borra nada** | Dividir, unir y descartar apagan la fila y dejan el rastro. El historial es sólo agregar. |
| **Nada sale de la máquina** | Sin red, sin CDN, sin telemetría, sin OCR en la nube. Hay una prueba que lo verifica sobre el código. |

---

## Instalar

Hace falta Python 3.11 o más, y **Tesseract con el paquete de castellano**, que no se
instala por pip:

```bash
sudo apt install tesseract-ocr tesseract-ocr-spa tesseract-ocr-osd   # Debian / Ubuntu
pip install -r requisitos.txt
python3 -m punteo.cli diagnostico     # ¿está todo lo que hace falta en esta máquina?
```

`diagnostico` es lo primero que conviene correr en una máquina nueva: chequea las tres
bibliotecas, Tesseract, el idioma, el detector de orientación, FTS5 y los permisos de
escritura, y si falta algo dice qué instalar.

Para una máquina **sin internet**, se bajan las ruedas una vez en otra máquina y se
llevan:

```bash
pip download -r requisitos.txt -d ruedas/
pip install --no-index --find-links ruedas/ -r requisitos.txt
```

## Usar

```bash
python3 -m punteo.cli servir          # http://127.0.0.1:8714
```

Escucha en `127.0.0.1` por omisión: no se expone a la red ni por accidente. Con `--host`
se puede exponer, y avisa por consola cuando lo hace; **no hay clave de acceso todavía**,
así que exponerlo deja el legajo disponible para cualquiera en esa red.

También se puede trabajar sin interfaz:

```bash
python3 -m punteo.cli crear "OGA-1234/2026" "APELLIDO, Nombre s/ Peculado" --tipo remision
python3 -m punteo.cli cargar <caso> /ruta/a/los/pdf/
python3 -m punteo.cli procesar <caso>
python3 -m punteo.cli evidencias <caso> --filtro pendientes
python3 -m punteo.cli punteo <caso> --exportar rtf
```

## Pruebas

```bash
python3 -m pruebas.correr             # la suite normal
python3 -m pruebas.correr --lentas    # incluye el OCR de verdad
python3 -m pruebas.correr test_invariante
```

`unittest` de la biblioteca estándar, sin dependencias. Los datos son sintéticos y se
generan por código con `herramientas/generar_legajo.py`: **nunca datos reales de
investigaciones**.

---

## Dónde está cada cosa

```
punteo/                               el paquete
  config.py  db.py  esquema.sql       base y configuración
  casos.py  almacen.py  ingesta.py    alta de casos y entrada de PDF
  ocr.py  foliatura.py                lectura de página y fojas
  evidencia/                          catálogo, detección, modelo, duplicados
  personas.py  grupos.py              testigos y sectores
  generacion.py  exportacion.py       el punteo y su salida
  busqueda.py  trabajo.py  servidor.py
  web/                                interfaz
assets/fuentes/                       las tres tipografías, OFL, servidas de disco
pruebas/                              unittest, fixtures sintéticos
herramientas/                         generador de legajos de prueba
docs/                                 arquitectura, identidad, hitos
```

* [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) — cómo está construido y por qué
* [`docs/IDENTIDAD.md`](docs/IDENTIDAD.md) — cómo se ve y por qué
* [`docs/REUTILIZACION-APPUFIL.md`](docs/REUTILIZACION-APPUFIL.md) — qué se tomó del proyecto anterior
* [`docs/REVISION-ADVERSARIAL.md`](docs/REVISION-ADVERSARIAL.md) — dónde puede fallar
* [`docs/LEGAJO-REAL.md`](docs/LEGAJO-REAL.md) — qué falló la primera vez que entró un legajo de verdad
* [`docs/HITOS.md`](docs/HITOS.md) — qué está hecho, qué falta y en qué orden conviene seguir
* [`CLAUDE.md`](CLAUDE.md) y [`AGENTS.md`](AGENTS.md) — reglas para quien siga desarrollando

---

## Prioridades del diseño

```
fidelidad documental  >  automatización
trazabilidad          >  comodidad
decisión humana       >  decisión automática
exactitud             >  apariencia
```

La finalidad no es que la aplicación parezca inteligente. Es reducir el tiempo que lleva
revisar un legajo y preparar un punteo, sin soltar en ningún momento el control humano
sobre lo que finalmente se ofrece como prueba.
