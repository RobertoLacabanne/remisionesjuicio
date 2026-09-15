# Imagen de Punteo de Evidencia — UFIL Paraná.
#
# Se construye UNA vez en una máquina con internet, se exporta con `docker save` y
# viaja en un disco externo. En la fiscalía no se descarga nada.
FROM python:3.12-slim-bookworm

# Tesseract con castellano y con el detector de orientación. `osd` no es opcional: sin
# él, una hoja apoyada de costado en el escáner no se endereza, el OCR no reconoce una
# palabra, y la pieza de evidencia que estaba en esa foja desaparece sin dejar rastro.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-spa tesseract-ocr-osd \
    && rm -rf /var/lib/apt/lists/*

# Usuario sin privilegios. Importa de verdad: los originales se guardan en modo 0444 y
# root ignora ese permiso. Corriendo como `punteo`, un intento de sobrescribir un
# original falla de entrada en vez de depender de que alguien lo note después.
RUN useradd --create-home --uid 10001 punteo

WORKDIR /app
COPY requisitos.txt .
RUN pip install --no-cache-dir -r requisitos.txt

COPY punteo/ ./punteo/
COPY assets/ ./assets/
COPY pruebas/ ./pruebas/
COPY herramientas/ ./herramientas/

RUN mkdir -p /app/datos && chown -R punteo:punteo /app
USER punteo

ENV PUNTEO_DATOS=/app/datos

# `/app/datos` NO se declara con VOLUME, y es a propósito: `VOLUME` hace que el motor de
# contenedores cree un **volumen anónimo** ahí, que se ve como un punto de montaje de
# verdad y se destruye junto con el contenedor. O sea, en cada despliegue — y con él,
# todo el trabajo de revisión, que es lo único de este sistema que no se regenera.
#
# Dónde vive `/app/datos` lo declara quien corre la imagen: docker-compose lo mapea a
# `./datos` del host, y en Render se monta un disco. Si nadie lo declara, es
# almacenamiento efímero, y más vale que eso se note.

EXPOSE 8714

# El proceso escucha en 0.0.0.0 porque adentro de un contenedor no hay otra opción: en
# loopback no lo alcanzaría ni el propio Docker. Quién llega de verdad lo decide la
# publicación del puerto, afuera. Por eso `PUNTEO_ACCESO` no se fija acá: lo pone quien
# corre la imagen, sabiendo a qué la expone. Ver docker-compose.yml y render.yaml.
CMD ["sh", "-c", "python -m punteo.cli servir --host 0.0.0.0 --puerto ${PORT:-8714}"]
