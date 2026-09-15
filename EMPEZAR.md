# Empezar

Tres pasos. Está escrito para alguien que no participó del desarrollo y sólo quiere
usar la aplicación.

---

## 1. Lo que hace falta en la máquina

Dos cosas, y se instalan una sola vez:

**Python 3.11 o posterior** — [python.org/downloads](https://www.python.org/downloads/).
En Windows, en la primera pantalla del instalador, **tildar «Add python.exe to PATH»**.

**Tesseract, con castellano** — es el motor que lee los escaneos.

| | |
|---|---|
| Windows | [github.com/UB-Mannheim/tesseract/wiki](https://github.com/UB-Mannheim/tesseract/wiki) — en «Additional language data» tildar **Spanish** y **Orientation and script detection** |
| Ubuntu / Debian | `sudo apt install tesseract-ocr tesseract-ocr-spa tesseract-ocr-osd` |
| macOS | `brew install tesseract tesseract-lang` |

---

## 2. Instalar

**Windows** — clic derecho en `scripts\instalar.ps1` → *Ejecutar con PowerShell*.

**Linux / macOS** — en una terminal, dentro de la carpeta del proyecto:

```bash
./scripts/instalar.sh
```

El instalador chequea todo y, si falta algo, dice exactamente qué instalar y se
detiene. No sigue a medias.

---

## 3. Usar

**Windows** — doble clic en `scripts\arrancar.bat`.

**Linux / macOS**:

```bash
./scripts/arrancar.sh
```

Se abre solo en el navegador. Si no, entrá a **http://127.0.0.1:8714**.

Para cerrar, `Ctrl-C` en esa ventana.

---

## Y ahora, el recorrido

1. **Nuevo caso** — número de legajo, carátula y tipo: remisión a juicio o abreviado.
2. **Legajo** — arrastrá los PDF. El original no se modifica nunca.
3. **Procesar el legajo** — lee cada página, busca la foliatura y propone las piezas.
   Tarda: como referencia, un cuarto de segundo por página escaneada. Se puede parar
   y retoma donde iba.
4. **Confirmá los tramos de foliatura**, en la misma pantalla. Hasta que no lo hagas,
   las fojas son una conjetura de la máquina y el escrito las va a marcar como tales.
5. **Revisión** — el documento a la izquierda, la pieza a la derecha. `I` incluir,
   `E` excluir, `P` pendiente, flechas para moverte. Corregí la descripción y asigná
   el testigo introductor sobre la marcha.
6. **Checklist** — la vista general, con filtros y contadores. Desde acá se agrupa en
   sectores y se ordena.
7. **Punteo** — generar, revisar la vista previa, exportar a `.rtf` y pegarlo en el
   requerimiento.

Si algo no cierra, `python3 -m punteo.cli diagnostico` dice qué le falta a la máquina.

---

## Preguntas que van a aparecer

**¿Se puede usar desde el celular?**
Sí, pero hay que levantarlo escuchando en la red y **ahí pide clave**, que se genera en
cada arranque y se muestra una sola vez en la terminal:

```bash
./scripts/arrancar.sh --host 0.0.0.0
```

El tráfico va en HTTP plano: sirve para la red de la fiscalía, no para internet.

**¿Anda sin internet?**
Sí, y es el modo para el que está hecho. Ni una llamada de red: ni tipografías, ni
OCR en la nube, ni telemetría. Para instalar en una máquina desconectada, se bajan las
librerías una vez en otra máquina:

```bash
pip download -r requisitos.txt -d ruedas/
pip install --no-index --find-links ruedas/ -r requisitos.txt
```

**¿Dónde queda el trabajo?**
En la carpeta `datos/` del proyecto, una subcarpeta por caso. Respaldar es copiar esa
carpeta; entregarla es mandarla. Dentro de cada caso están los PDF originales, la base
del caso y lo exportado.

**¿Y si quiero que lo vea el fiscal desde otro lado?**
Hay un `Dockerfile` y un `render.yaml` para publicarlo en un servidor. **Leer los
comentarios de `render.yaml` antes**: ahí el material vive en un servidor de un tercero,
que es lo contrario de para lo que está diseñada esta aplicación. Para mostrarlo con
documentación sintética es la herramienta correcta; para un legajo real hay que decidirlo
antes, y esa decisión no es técnica.
