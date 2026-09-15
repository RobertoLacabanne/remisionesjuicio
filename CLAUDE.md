# Punteo de Evidencia — reglas del proyecto

Aplicación para armar el punteo de prueba de un requerimiento de remisión a juicio o de
un procedimiento abreviado, a partir de un legajo penal escaneado. UFIL Paraná, MPF
Entre Ríos.

Antes de tocar nada leé [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).

## Las invariantes

No son preferencias. Si un cambio las rompe, el cambio está mal.

1. **`EXCLUIDO` = imposible que aparezca en la salida.** El generador lee de
   `v_evidencia_incluida` y de ningún otro lado, y además revalida el estado de cada
   pieza antes de escribirla. Las dos barreras se mantienen: son redundantes a propósito.
2. **La foja no es la página del PDF.** Nunca convertir una en la otra. Guardar y
   mostrar siempre las dos. El texto final cita la foja.
3. **No decidir sin ver.** Los botones `INCLUIR` / `EXCLUIR` / `PENDIENTE` sólo existen
   en pantallas con el documento a la vista. Si la imagen no cargó, se dice y no se
   deja decidir.
4. **Lo detectado no se pisa.** `descripcion_detectada` y las demás columnas `_detectada`
   son de sólo escritura una vez. Lo que corrige una persona va a la columna `_final`.
   Leer siempre por la vista `v_evidencia`, nunca las columnas crudas.
5. **No inventar.** Si un dato no está determinado, queda vacío, o `desconocido`, o
   `pendiente`. Nunca se completa en silencio. Vale para fojas, fechas, nombres y tipos.
6. **El original no se toca.** Se guarda bajo su SHA-256, en `0444`, y no se reescribe.
7. **Nada sale de la máquina.** Sin red, sin CDN, sin fuentes remotas, sin telemetría,
   sin OCR en la nube. `pruebas/test_privacidad.py` lo verifica.
8. **No se borra evidencia.** Dividir, unir y descartar marcan `activa = 0` y dejan el
   rastro. `revision` es append-only.

## Cómo se trabaja acá

```bash
python3 -m punteo.cli diagnostico      # ¿está todo lo que hace falta en esta máquina?
python3 -m punteo.cli servir           # http://127.0.0.1:8714
python3 -m pruebas.correr              # toda la suite
python3 -m pruebas.correr test_invariante
```

Las pruebas son `unittest` de la biblioteca estándar. No agregar pytest ni ninguna
dependencia de test: la máquina de producción no tiene internet.

Dependencias permitidas: PyMuPDF, Pillow, pytesseract. Ninguna más sin una razón
escrita. Nada de Node en producción, nada de framework web, nada de paso de compilación.

## Trabajo conjunto con Codex

Este proyecto está diseñado para trabajar con Claude Code como coordinador principal y
Codex como segundo ingeniero. Las instrucciones de Codex están en [`AGENTS.md`](AGENTS.md)
y la instalación local está documentada en [`docs/CODEX-SETUP.md`](docs/CODEX-SETUP.md).

Al comenzar una sesión de desarrollo importante, si el plugin está disponible, comprobar
`/codex:status`. Para cambios relevantes, no dar por terminado un hito sin una segunda
mirada independiente de Codex.

Usar, según corresponda:

```text
/codex:review --background
/codex:adversarial-review --background
/codex:rescue --background <tarea>
/codex:status
/codex:result
```

Claude y Codex pueden investigar o revisar en paralelo, pero no deben modificar al mismo
tiempo los mismos archivos. Para arquitectura, persistencia, detección de evidencia,
foliatura, generación final, privacidad y rendimiento, preferir una revisión independiente
antes de consolidar el cambio.

Si Codex no está disponible, no fingir que se ejecutó la revisión: indicarlo claramente y
seguir las instrucciones de `docs/CODEX-SETUP.md` para recuperar la integración.

## Estilo

Castellano en todo: nombres de módulos, funciones, columnas, rutas de API y comentarios.
Es un sistema que va a mantener gente de la casa.

Los comentarios explican **por qué**, no qué. Si un comentario se puede borrar sin
perder información, sobra. Si una decisión costó descubrirla, se escribe con el caso que
la hizo evidente.

Una función hace una cosa. Un módulo tiene un tema. Si un archivo pasa de unas 500
líneas, probablemente son dos.

## Estructura

```
punteo/                               el paquete
  config.py  db.py  esquema.sql       base y configuración
  casos.py   almacen.py  ingesta.py   alta de casos y entrada de PDF
  ocr.py     foliatura.py             lectura de página y fojas
  evidencia/                          catálogo, detección, modelo
  personas.py  grupos.py              testigos y sectores
  generacion.py  exportacion.py       el punteo y su salida
  busqueda.py  trabajo.py  servidor.py
  web/                                interfaz
assets/fuentes/                       las tres tipografías, OFL, servidas de disco
pruebas/                              unittest, fixtures sintéticos
herramientas/                         generador de legajos de prueba
docs/                                 arquitectura, identidad, reutilización, hitos
```

Este repositorio es **sólo Punteo**. AppUFIL es otra aplicación, de otro dominio —
documentación administrativa de contratos— y no se importa desde acá ni se toca desde
acá. Lo que se tomó de su diseño está anotado en `docs/REUTILIZACION-APPUFIL.md`.

## Datos de prueba

Nunca datos reales de investigaciones. Los fixtures se generan por código con
`herramientas/generar_legajo.py`, que arma PDF sintéticos con marca en los metadatos.
