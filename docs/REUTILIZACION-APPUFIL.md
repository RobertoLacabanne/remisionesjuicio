# Matriz de reutilización de AppUFIL

Qué se tomó del proyecto anterior, en qué forma y por qué. «Adaptar» significa que se
tomó el diseño y la lección aprendida, y se reescribió el código para el dominio nuevo;
casi nada se copió textual, porque casi nada de AppUFIL habla de evidencia.

| Componente AppUFIL | Reutilizar | Adaptar | Reescribir | Motivo |
|---|:--:|:--:|:--:|---|
| `capa0_ingesta.py` — SHA-256, duplicado exacto, metadatos PDF | | ✅ | | El diseño es correcto y está probado: abrir en `rb` y nada más, registrar la copia exacta en lugar de borrarla. Se adapta porque la unidad acá es el caso, no el lote, y porque la procedencia de un legajo no tiene `dispositivo` ni `fecha_secuestro`. |
| `almacen.py` — original bajo su hash, `chmod 0444` | | ✅ | | Se conserva entero el criterio, incluido guardar bajo el SHA y no bajo el nombre, y conservar el nombre original en la base. |
| `capa1_texto.py` — palabras con coordenadas en puntos PDF | | ✅ | | La unidad común `Palabra(texto, x0,y0,x1,y1, conf)` es lo que hace posible anclar cualquier dato a su lugar en la imagen. Se adapta: acá no hace falta doble lectura de rutina —no se extraen campos críticos— y sí hace falta no guardar el PNG de cada página. |
| `enderezar_si_mejora` — girar sólo si al releer mejora | ✅ | | | Se toma la lección completa, que es buena y cara de descubrir: el detector de orientación sugiere, el resultado decide. |
| `busqueda.py` — FTS5 con `remove_diacritics 2` | | ✅ | | Buscar «peritacion» tiene que encontrar «peritación». Se adapta el esquema de la tabla virtual y se tira todo lo de campos de contrato. |
| `trabajo.py` — trabajador único, progreso por página, corte limpio | | ✅ | | Progreso por unidad real de trabajo y bandera de parada consultada entre páginas. Las etapas son otras. |
| `db.py` — WAL, esquema versionado, columnas agregadas | | ✅ | | Incluida la lección de chequear columnas faltantes en cada arranque y no sólo cuando sube la versión. |
| Separación por legajo (`config.py` por hilo, `legajos.py`) | | ✅ | | La idea central —un caso, un archivo, resolución por hilo— se toma completa. `legajos.py` son 502 líneas de las cuales la mayoría es gestión de plantillas y respaldos del dominio viejo. |
| `servidor.py` — `http.server`, sin framework | | ✅ | | Se toma el criterio y la forma de despachar. 1.568 líneas de rutas de contratos no sirven. |
| `confianza.py` — ocho estados, `FIRMES` explícito | ✅ | | | No los estados, que son de otro problema, sino la regla: la línea entre lo que se puede afirmar y lo que no vive en la base y en las consultas, no en la pantalla. |
| Vista `v_contrato` filtrando por estado firme | ✅ | | | El patrón exacto se reusa como `v_evidencia_incluida`, con el mismo argumento: el `SELECT` obvio tiene que ser el seguro. |
| `auditoria` / `revision_humana` — historial append-only | | ✅ | | Se fusionan en una sola tabla `revision`: acá no hay reproceso que pueda huerfanar decisiones, porque la evidencia no se regenera pisando la existente. |
| `DESIGN_SYSTEM.md` — la tipografía dice la procedencia | ✅ | | | Es la mejor idea de diseño del proyecto anterior y se toma entera. La paleta no: ver abajo. |
| `assets/fuentes/` — Archivo, Source Serif 4, IBM Plex Mono | ✅ | | | OFL 1.1, con sus licencias. **Están copiadas adentro de este repositorio**, no referenciadas: el proyecto tiene que andar solo, sin AppUFIL al lado en el disco. |
| Paleta azul tribunal / oro | | | ✅ | Punteo necesita verde, punzó y ámbar para los tres estados de decisión, que es su distinción principal. Un cromo azul institucional dejaría la pantalla con cinco colores peleando. Ver `docs/IDENTIDAD.md`. |
| `capa2_extraccion.py`, `capa2_campos.py`, `perfiles/` | | | ✅ | Extracción de campos de contratos y facturas. No aplica. |
| `capa3_identidad.py` — fusión de personas | | ✅ | | Sólo el criterio: proponer fusiones, nunca fusionar en silencio, guardar la decisión humana. El algoritmo de AppUFIL se apoya en CUIL/CUIT como clave fuerte, que en un legajo de testigos casi nunca está. |
| `capa4_analisis.py` — superposiciones, acumulados | | | ✅ | Análisis económico del dominio viejo. |
| `capa5_interpretacion.py` — carril de interpretación | | | ✅ | Responde a un problema que este sistema no tiene: acá no hay conjeturas del sistema sobre el contenido, hay propuestas de corte y de tipo, que se revisan una por una. |
| `capa7_export.py` — XLSX y RTF | | ✅ | | El generador de RTF a mano, sin dependencia, se aprovecha como referencia. XLSX no hace falta. |
| `consultas/*.sql` — las diez consultas del pliego | | | ✅ | Dominio viejo, entero. |
| `acceso.py` — clave de acceso | | ✅ | | Queda para después del MVP. El criterio —que la clave no sea obligatoria en `127.0.0.1` y sí al exponer en red— se conserva. |
| `lector_manuscrito.py`, `capa1_vlm.py` | | | ✅ | Fuera del MVP. Y `capa1_vlm` manda recortes a un servicio: incompatible con el requisito de procesamiento local mientras no haya modelo en la máquina. |
| `respaldo.py` | | ✅ | | Respaldar un caso es copiar su carpeta. Mucho más simple acá que allá. |
| `pruebas/` — 22 archivos | | ✅ | | Se toma la forma: `unittest`, sin dependencias, fixtures sintéticos generados por código, y una prueba por invariante con el nombre de la invariante. Los casos son otros. |

## Lo que explícitamente no se arrastra

Contratos, facturas, contratados, montos, cámaras, superposición de períodos, Tribunal
de Cuentas como entidad del modelo, y cualquier consulta del pliego anterior. El prompt
maestro lo pide y además es correcto: arrastrar ese vocabulario al modelo de datos
habría producido una aplicación que parece dos aplicaciones.
