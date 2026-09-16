-- Esquema de Punteo de Evidencia — UFIL Paraná
--
-- Tres reglas están puestas ACÁ y no en el código de la aplicación, porque una regla
-- que sólo vive en la pantalla se saltea sola la próxima vez que alguien escriba un
-- SELECT:
--
--   1. lo que una persona excluyó no puede salir por `v_evidencia_incluida`;
--   2. lo que una persona corrigió tapa a lo que detectó la máquina, y lo detectado
--      no se pierde;
--   3. la foja y la página del PDF son dos columnas distintas y ninguna consulta
--      convierte una en la otra.

PRAGMA foreign_keys = ON;

-- ══════════════════════════════════════════════════════════════════ EL CASO ══
-- Una fila. Siempre una. Cada caso vive en su propio archivo SQLite (ver
-- punteo/casos.py), así que no hay `caso_id` desparramado por el esquema y no hay
-- forma de que una consulta traiga evidencia de otra causa: esa evidencia no está en
-- esta base. El CHECK deja constancia de que la tabla es de una fila a propósito.
CREATE TABLE IF NOT EXISTS caso (
  id             INTEGER PRIMARY KEY CHECK (id = 1),
  numero_legajo  TEXT NOT NULL,
  caratula       TEXT NOT NULL,
  -- remision | abreviado. En `abreviado` el testigo introductor no es obligatorio y
  -- el generador usa otra plantilla. Es lo único que cambia entre los dos modos: el
  -- motor documental es el mismo.
  tipo_proceso   TEXT NOT NULL CHECK (tipo_proceso IN ('remision', 'abreviado')),
  observaciones  TEXT,
  creado_en      TEXT NOT NULL,
  actualizado_en TEXT
);

CREATE TABLE IF NOT EXISTS ajuste (
  clave TEXT PRIMARY KEY,
  valor TEXT
);

-- ══════════════════════════════════════════════════════════ EL DOCUMENTO ══
-- Un legajo puede venir en varios PDF. El orden entre ellos lo fija quien los carga y
-- determina la numeración global de páginas, que es la referencia técnica cuando no
-- hay foliatura.
CREATE TABLE IF NOT EXISTS documento (
  id             INTEGER PRIMARY KEY,
  sha256         TEXT NOT NULL UNIQUE,
  nombre_archivo TEXT NOT NULL,        -- el nombre con el que llegó
  ruta           TEXT NOT NULL,        -- dónde quedó guardado, en 0444
  bytes          INTEGER NOT NULL,
  paginas        INTEGER NOT NULL,
  orden          INTEGER NOT NULL,     -- 1º, 2º… PDF del legajo
  -- Dónde arranca este documento en la numeración global del caso. Se calcula al
  -- ingerir y se recalcula si se reordenan los documentos.
  offset_global  INTEGER NOT NULL DEFAULT 0,
  estado         TEXT NOT NULL DEFAULT 'sin_leer',  -- sin_leer | leido | con_fallas
  ingerido_en    TEXT NOT NULL
);

-- Copias exactas del mismo contenido subidas de nuevo. No se borra ninguna: el
-- original es inmutable, así que se registra el hecho y se sigue.
CREATE TABLE IF NOT EXISTS documento_duplicado (
  sha256   TEXT NOT NULL REFERENCES documento(sha256),
  nombre   TEXT NOT NULL,
  visto_en TEXT NOT NULL,
  PRIMARY KEY (sha256, nombre, visto_en)
);

-- ══════════════════════════════════════════════════════════════ LA PÁGINA ══
-- Acá viven las dos numeraciones, y la razón por la que son dos columnas y no una
-- cuenta: en el escrito se cita «fs. 342/346». Si ese número sale de la página del
-- PDF, la cita es falsa y el error llega a un tribunal.
CREATE TABLE IF NOT EXISTS pagina (
  id             INTEGER PRIMARY KEY,
  documento_id   INTEGER NOT NULL REFERENCES documento(id) ON DELETE CASCADE,
  numero_pdf     INTEGER NOT NULL,     -- dentro de SU PDF, 1-based
  numero_global  INTEGER NOT NULL,     -- dentro del caso, en orden de documento
  ancho_pt       REAL, alto_pt REAL,
  rotacion       INTEGER NOT NULL DEFAULT 0,
  tiene_texto_nativo INTEGER NOT NULL DEFAULT 0,

  -- ── La foja ──────────────────────────────────────────────────────────────
  -- No es un entero. En un expediente argentino es «411», y también «411 vta.» —el
  -- reverso de la misma hoja, que se folia como continuación— y también «411 bis»,
  -- una hoja intercalada después de foliar. Guardarla como INTEGER pierde información
  -- el primer día, así que se guardan las tres cosas: la etiqueta tal como se lee, y
  -- el número y el sufijo por separado para poder ordenar y armar rangos.
  foja_etiqueta  TEXT,                 -- «411», «411 vta.», «411 bis»
  foja_num       INTEGER,
  foja_sufijo    TEXT NOT NULL DEFAULT '',   -- '' | 'vta' | 'bis'
  -- Quién puso ese valor. Es el campo que impide el error que este sistema existe
  -- para que no pase: una foja `detectada` es una conjetura de la máquina y la
  -- interfaz la muestra como tal. El generador exige `confirmada` o `manual`.
  foja_origen    TEXT NOT NULL DEFAULT 'desconocida'
                 CHECK (foja_origen IN ('desconocida','detectada','confirmada','manual')),
  -- Si el número se LEYÓ en esta página o se dedujo del tramo. Son dos cosas distintas y
  -- confirmarlas no las iguala: quien confirma un tramo de cuarenta fojas mira algunas,
  -- y las interpoladas son justamente donde una hoja intercalada corre la numeración.
  -- 'leida' | 'interpolada' | NULL cuando no corresponde (sin foja, o cargada a mano).
  foja_lectura   TEXT,
  foja_confianza REAL,
  tramo_id       INTEGER REFERENCES tramo_foliatura(id),

  -- ── La lectura ───────────────────────────────────────────────────────────
  -- El texto completo de la página, junto. Duplica lo que está en `palabra`, y se
  -- paga a propósito: la detección de piezas y la pantalla lo piden entero cientos de
  -- veces, y rearmarlo con un JOIN y un ORDER BY cada vez cuesta más que el disco.
  texto          TEXT,
  ruta_lectura   TEXT,                 -- nativo | ocr
  confianza      REAL,
  leida_en       TEXT,
  UNIQUE (documento_id, numero_pdf),
  UNIQUE (numero_global)
);
CREATE INDEX IF NOT EXISTS ix_pagina_global ON pagina(numero_global);
CREATE INDEX IF NOT EXISTS ix_pagina_foja   ON pagina(foja_num, foja_sufijo);

-- Palabras con su recuadro en PUNTOS PDF, origen arriba-izquierda. Esta unidad común
-- es lo que hace posible resaltar en la imagen el fragmento que sustenta una pieza.
CREATE TABLE IF NOT EXISTS palabra (
  id        INTEGER PRIMARY KEY,
  pagina_id INTEGER NOT NULL REFERENCES pagina(id) ON DELETE CASCADE,
  orden     INTEGER NOT NULL,
  texto     TEXT NOT NULL,
  x0 REAL, y0 REAL, x1 REAL, y1 REAL,
  conf      REAL
);
CREATE INDEX IF NOT EXISTS ix_palabra_pagina ON palabra(pagina_id, orden);

-- Todo lo que salió mal y alguien tiene que ver. Un documento que se pierde en
-- silencio es lo peor que puede hacer un sistema que existe para no perder documentos.
CREATE TABLE IF NOT EXISTS excepcion (
  id        INTEGER PRIMARY KEY,
  clase     TEXT NOT NULL,
  detalle   TEXT,
  documento_id INTEGER REFERENCES documento(id),
  pagina_id INTEGER REFERENCES pagina(id),
  estado    TEXT NOT NULL DEFAULT 'abierta',
  creado_en TEXT NOT NULL
);

-- Tramos de foliatura. Un legajo real casi nunca tiene un único desplazamiento entre
-- página y foja: se intercala documentación, se folia en dos etapas, empieza un cuerpo
-- nuevo. Modelarlo como varios tramos con su propio desplazamiento es la diferencia
-- entre acertar en todo el legajo y acertar en la primera mitad.
CREATE TABLE IF NOT EXISTS tramo_foliatura (
  id             INTEGER PRIMARY KEY,
  desde_global   INTEGER NOT NULL,
  hasta_global   INTEGER NOT NULL,
  desplazamiento INTEGER NOT NULL,     -- foja_num = numero_global + desplazamiento
  zona           TEXT NOT NULL,        -- sup_der | sup_cen | inf_der | inf_cen
  confianza      REAL NOT NULL,
  paginas_leidas INTEGER NOT NULL,     -- dónde se leyó el número de verdad
  paginas_interpoladas INTEGER NOT NULL,
  creado_en      TEXT NOT NULL
);

-- Índice de texto de las páginas. `remove_diacritics 2` para que buscar «peritacion»
-- encuentre «peritación»: el que busca no tiene por qué acordarse de dónde iba la
-- tilde, y el OCR tampoco es confiable con ellas.
CREATE VIRTUAL TABLE IF NOT EXISTS pagina_texto USING fts5(
  texto,
  pagina_id UNINDEXED,
  numero_global UNINDEXED,
  tokenize = "unicode61 remove_diacritics 2"
);

-- ══════════════════════════════════════════════════ SECTORES Y ETIQUETAS ══
-- El usuario organiza la evidencia como le sirve para el escrito. Un grupo es un
-- bloque del punteo —«Banco de Entre Ríos», «Gabinete Informático Forense»—; una
-- etiqueta es transversal y no arma bloque. No son lo mismo y por eso son dos tablas.
CREATE TABLE IF NOT EXISTS grupo_evidencia (
  id          INTEGER PRIMARY KEY,
  nombre      TEXT NOT NULL,
  descripcion TEXT,
  orden       INTEGER NOT NULL DEFAULT 0,
  color       TEXT,
  -- El encabezado con el que este grupo sale en el punteo. Si está vacío, el
  -- generador usa el nombre. Es editable porque el nombre que sirve para trabajar
  -- («Banco ERíos») no es el que va en el escrito («EVIDENCIA REMITIDA POR EL NUEVO
  -- BANCO DE ENTRE RÍOS S.A.»).
  encabezado  TEXT,
  tipo        TEXT NOT NULL DEFAULT 'personalizado',
  creado_en   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS etiqueta (
  id     INTEGER PRIMARY KEY,
  nombre TEXT NOT NULL UNIQUE,
  color  TEXT
);

-- ═══════════════════════════════════════════════════════════ LA EVIDENCIA ══
CREATE TABLE IF NOT EXISTS evidencia (
  id            INTEGER PRIMARY KEY,
  documento_id  INTEGER REFERENCES documento(id),

  -- ── Dónde está ───────────────────────────────────────────────────────────
  -- En numeración GLOBAL del caso. La foja se deriva de estas páginas por la vista
  -- `v_evidencia`, salvo que una persona la haya escrito a mano.
  pagina_inicio INTEGER,
  pagina_fin    INTEGER,
  -- Recuadro del fragmento que sustenta la pieza, en puntos PDF de `pagina_inicio`.
  x0 REAL, y0 REAL, x1 REAL, y1 REAL,
  -- El texto leído que respalda la propuesta. Es lo que se despliega en el panel
  -- derecho cuando alguien quiere ver de dónde salió esto sin irse a la imagen.
  texto_origen  TEXT,

  -- ── Lo que detectó la máquina. Se escribe una vez y no se toca más ───────
  tipo_detectado         TEXT,
  subtipo_detectado      TEXT,
  descripcion_detectada  TEXT,
  foja_inicio_detectada  TEXT,
  foja_fin_detectada     TEXT,

  -- ── Lo que decidió una persona. NULL = nadie lo tocó, vale lo detectado ──
  -- La lectura correcta es siempre COALESCE(final, detectado), y para eso existe
  -- `v_evidencia`. Ninguna consulta de pantalla ni de exportación lee estas columnas
  -- crudas: si lo hiciera, mostraría el valor viejo después de que alguien lo corrigió.
  tipo_final         TEXT,
  subtipo_final      TEXT,
  descripcion_final  TEXT,
  foja_inicio_final  TEXT,
  foja_fin_final     TEXT,

  -- ── La decisión ──────────────────────────────────────────────────────────
  -- Tres estados y no cuatro. Se consideró un cuarto, `sugerida`, para lo que el
  -- sistema propone con confianza alta, y se descartó: sería un estado que se parece
  -- a «incluida» sin que nadie lo haya decidido, y la primera vez que alguien genere
  -- un punteo sin llegar al final de la revisión, esa semejanza se convierte en
  -- prueba ofrecida que nadie leyó. Todo nace `pendiente`.
  estado        TEXT NOT NULL DEFAULT 'pendiente'
                CHECK (estado IN ('pendiente','incluida','excluida')),
  decidido_en   TEXT,

  -- ── Procedencia del registro ─────────────────────────────────────────────
  origen        TEXT NOT NULL DEFAULT 'automatica'
                CHECK (origen IN ('automatica','manual','division','union')),
  -- De qué evidencia salió ésta, cuando salió de una división o de una unión.
  origen_id     INTEGER REFERENCES evidencia(id),
  -- No se borra nunca. Dividir, unir y descartar apagan la fila y dejan el rastro,
  -- para poder contestar «¿de dónde salió esta pieza?» y para poder deshacer.
  activa        INTEGER NOT NULL DEFAULT 1,

  confianza     REAL,                  -- NULL en la evidencia manual: no hay qué medir
  advertencias  TEXT,                  -- JSON: ["foja_sin_confirmar", "ocr_pobre"]
  observaciones TEXT,

  -- ── Organización ─────────────────────────────────────────────────────────
  grupo_id       INTEGER REFERENCES grupo_evidencia(id) ON DELETE SET NULL,
  orden_en_grupo INTEGER NOT NULL DEFAULT 0,
  orden_salida   INTEGER NOT NULL DEFAULT 0,
  -- Fecha del documento, cuando se pudo determinar. ISO o NULL. Nunca se inventa
  -- una para poder ordenar: sin fecha, la pieza sale al final y dice SIN FECHA.
  fecha_documento TEXT,

  creado_en     TEXT NOT NULL,
  actualizado_en TEXT
);
CREATE INDEX IF NOT EXISTS ix_evidencia_estado ON evidencia(estado, activa);
CREATE INDEX IF NOT EXISTS ix_evidencia_grupo  ON evidencia(grupo_id, orden_en_grupo);
CREATE INDEX IF NOT EXISTS ix_evidencia_pagina ON evidencia(pagina_inicio);

-- Las partes de una unión. Una pieza unida conserva a sus partes acá, apagadas pero
-- enteras, para poder deshacer sin reprocesar.
CREATE TABLE IF NOT EXISTS evidencia_parte (
  union_id  INTEGER NOT NULL REFERENCES evidencia(id) ON DELETE CASCADE,
  parte_id  INTEGER NOT NULL REFERENCES evidencia(id),
  orden     INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (union_id, parte_id)
);

CREATE TABLE IF NOT EXISTS evidencia_etiqueta (
  evidencia_id INTEGER NOT NULL REFERENCES evidencia(id) ON DELETE CASCADE,
  etiqueta_id  INTEGER NOT NULL REFERENCES etiqueta(id) ON DELETE CASCADE,
  PRIMARY KEY (evidencia_id, etiqueta_id)
);

-- Posibles duplicados. Se detectan y se muestran; NO se eliminan ni se fusionan solos.
CREATE TABLE IF NOT EXISTS duplicado_posible (
  id        INTEGER PRIMARY KEY,
  evidencia_a INTEGER NOT NULL REFERENCES evidencia(id) ON DELETE CASCADE,
  evidencia_b INTEGER NOT NULL REFERENCES evidencia(id) ON DELETE CASCADE,
  score     REAL NOT NULL,
  motivo    TEXT,
  estado    TEXT NOT NULL DEFAULT 'abierto',  -- abierto | descartado | resuelto
  creado_en TEXT NOT NULL,
  UNIQUE (evidencia_a, evidencia_b)
);

-- ═══════════════════════════════════════════════════════════════ PERSONAS ══
-- Una persona puede aparecer con varios roles en el mismo legajo. El rol no es de la
-- persona: es de su relación con una pieza. Por eso vive en `evidencia_persona` y no
-- acá. Lo que sí vive acá es el rol principal, que es el que ordena la vista TESTIGOS.
CREATE TABLE IF NOT EXISTS persona (
  id           INTEGER PRIMARY KEY,
  nombre       TEXT NOT NULL,
  nombre_norm  TEXT NOT NULL,          -- sin tildes, mayúsculas, para comparar
  rol          TEXT,                   -- testigo | perito | funcionario | denunciante | ...
  documento    TEXT,                   -- DNI, si consta
  detalle      TEXT,                   -- «Sgto. 1º, Comisaría 5ª»: lo que va en el escrito
  origen       TEXT NOT NULL DEFAULT 'manual',   -- manual | detectada
  creado_en    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_persona_norm ON persona(nombre_norm);

CREATE TABLE IF NOT EXISTS evidencia_persona (
  evidencia_id INTEGER NOT NULL REFERENCES evidencia(id) ON DELETE CASCADE,
  persona_id   INTEGER NOT NULL REFERENCES persona(id) ON DELETE CASCADE,
  -- introductor | autor | interviniente | mencionado. `introductor` es el que importa
  -- para la remisión a juicio: quién mete esta pieza al debate.
  funcion      TEXT NOT NULL DEFAULT 'introductor',
  PRIMARY KEY (evidencia_id, persona_id, funcion)
);

-- Dos personas que podrían ser la misma. Se PROPONE; fusionar es una decisión humana.
CREATE TABLE IF NOT EXISTS fusion_propuesta (
  id        INTEGER PRIMARY KEY,
  persona_a INTEGER NOT NULL REFERENCES persona(id) ON DELETE CASCADE,
  persona_b INTEGER NOT NULL REFERENCES persona(id) ON DELETE CASCADE,
  score     REAL NOT NULL,
  motivo    TEXT,
  estado    TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente | aceptada | rechazada
  creado_en TEXT NOT NULL,
  UNIQUE (persona_a, persona_b)
);

-- ══════════════════════════════════════════════════════════════ HISTORIAL ══
-- Append-only. No se pisa nunca: corregir dos veces no puede borrar la explicación de
-- la primera corrección.
CREATE TABLE IF NOT EXISTS revision (
  id             INTEGER PRIMARY KEY,
  evidencia_id   INTEGER REFERENCES evidencia(id) ON DELETE SET NULL,
  campo          TEXT NOT NULL,        -- estado | descripcion | tipo | foja | testigo | ...
  valor_anterior TEXT,
  valor_nuevo    TEXT,
  detalle        TEXT,                 -- para división, unión y lo que necesite contexto
  cuando         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_revision_evidencia ON revision(evidencia_id, id);
CREATE INDEX IF NOT EXISTS ix_revision_fecha     ON revision(cuando);

-- ════════════════════════════════════════════════════ EL PUNTEO GENERADO ══
-- El punteo no se guarda como una cadena. Se guarda como una lista de párrafos, cada
-- uno con la evidencia de la que salió —o NULL si es un encabezado de grupo—. Es lo
-- que sostiene el requisito de poder editar el texto final sin perder la relación
-- `párrafo ↔ evidencia`: aplanar todo a un TEXTAREA la rompe en el primer guardado.
CREATE TABLE IF NOT EXISTS punteo_generado (
  id            INTEGER PRIMARY KEY,
  criterio      TEXT NOT NULL,   -- manual | grupos | cronologico | tipo | testigo
  con_encabezados INTEGER NOT NULL DEFAULT 1,
  numeracion    TEXT NOT NULL DEFAULT 'continua',   -- continua | por_grupo
  plantilla     TEXT,
  total_piezas  INTEGER NOT NULL DEFAULT 0,
  generado_en   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS punteo_parrafo (
  id           INTEGER PRIMARY KEY,
  punteo_id    INTEGER NOT NULL REFERENCES punteo_generado(id) ON DELETE CASCADE,
  orden        INTEGER NOT NULL,
  clase        TEXT NOT NULL,   -- encabezado | pieza
  evidencia_id INTEGER REFERENCES evidencia(id),
  numero       TEXT,            -- «1.-», «I.-»
  texto_generado TEXT NOT NULL, -- lo que armó el generador. No se pisa.
  texto_final    TEXT           -- lo que editó la persona. NULL = vale el generado.
);
CREATE INDEX IF NOT EXISTS ix_parrafo_punteo ON punteo_parrafo(punteo_id, orden);

-- ═══════════════════════════════════════════════════════════════════ VISTAS ══

-- LA VISTA DE TRABAJO. Todas las pantallas leen de acá, y ninguna lee las columnas
-- `_detectada` / `_final` directamente. Resuelve dos cosas de una vez: qué valor vale
-- —el corregido si lo hay, el detectado si no— y de dónde sale la foja.
--
-- La foja NO está guardada en la evidencia: se deriva de las páginas que la pieza
-- cubre, salvo que una persona la haya escrito a mano. Es a propósito y es importante:
-- cuando alguien corrige la foliatura de una página, la foja de todas las piezas que
-- pasan por ahí se corrige sola. Con la foja congelada adentro de la evidencia, habría
-- que acordarse de recalcularla, y nadie se acuerda.
DROP VIEW IF EXISTS v_evidencia;
CREATE VIEW v_evidencia AS
SELECT
  e.id,
  e.documento_id,
  e.estado,
  e.activa,
  e.origen,
  e.origen_id,
  e.confianza,
  e.advertencias,
  e.observaciones,
  e.grupo_id,
  g.nombre         AS grupo_nombre,
  g.orden          AS grupo_orden,
  e.orden_en_grupo,
  e.orden_salida,
  e.fecha_documento,
  e.pagina_inicio,
  e.pagina_fin,
  e.x0, e.y0, e.x1, e.y1,
  e.texto_origen,
  e.creado_en,
  e.actualizado_en,
  e.decidido_en,

  COALESCE(e.tipo_final,        e.tipo_detectado)        AS tipo,
  COALESCE(e.subtipo_final,     e.subtipo_detectado)     AS subtipo,
  COALESCE(e.descripcion_final, e.descripcion_detectada) AS descripcion,

  -- La foja que vale: lo escrito a mano, y si no, la etiqueta de la página.
  COALESCE(e.foja_inicio_final, pi.foja_etiqueta)        AS foja_inicio,
  COALESCE(e.foja_fin_final,    pf.foja_etiqueta)        AS foja_fin,
  -- De dónde sale esa foja. El generador la exige distinta de `desconocida` y de
  -- `detectada`: escribir en un escrito un número que nadie verificó es exactamente
  -- lo que este sistema existe para que no pase.
  --
  -- Y son DOS extremos, cada uno con su origen. Con un solo campo —el del inicio—
  -- confirmar la primera foja de una pieza de cinco hojas hacía pasar por verificado
  -- todo el rango, y «fs. 409/413» salía sin marca con el 413 puesto por la máquina.
  CASE WHEN e.foja_inicio_final IS NOT NULL THEN 'manual'
       ELSE COALESCE(pi.foja_origen, 'desconocida') END  AS foja_origen,
  CASE WHEN e.foja_fin_final IS NOT NULL THEN 'manual'
       WHEN e.pagina_fin IS NULL THEN
            CASE WHEN e.foja_inicio_final IS NOT NULL THEN 'manual'
                 ELSE COALESCE(pi.foja_origen, 'desconocida') END
       ELSE COALESCE(pf.foja_origen, 'desconocida') END  AS foja_fin_origen,
  -- Los dos extremos mirados por una persona. Es lo que el generador exige y lo que
  -- cuenta el checklist: una sola respuesta para «¿esta cita se puede firmar?».
  (CASE WHEN e.foja_inicio_final IS NOT NULL THEN 'manual'
        ELSE COALESCE(pi.foja_origen, 'desconocida') END IN ('confirmada','manual')
   AND CASE WHEN e.foja_fin_final IS NOT NULL THEN 'manual'
            WHEN e.pagina_fin IS NULL THEN
                 CASE WHEN e.foja_inicio_final IS NOT NULL THEN 'manual'
                      ELSE COALESCE(pi.foja_origen, 'desconocida') END
            ELSE COALESCE(pf.foja_origen, 'desconocida') END IN ('confirmada','manual')
  )                                                      AS foja_firme,
  -- Alguno de los dos extremos tiene un número que no se leyó en el papel: se dedujo de
  -- la serie, o viene de una base anterior a esta columna y no se sabe de dónde salió.
  -- Se muestra, porque confirmarlo no lo convierte en leído. No aplica al extremo que
  -- una persona escribió a mano: ahí el número es suyo y su procedencia es otra.
  ((e.foja_inicio_final IS NULL
    AND COALESCE(pi.foja_lectura,'') IN ('interpolada','desconocida'))
   OR (e.foja_fin_final IS NULL
       AND COALESCE(pf.foja_lectura,'') IN ('interpolada','desconocida')))
                                                         AS foja_interpolada,

  e.tipo_detectado, e.descripcion_detectada,
  e.foja_inicio_detectada, e.foja_fin_detectada,
  -- Para la columna «modificadas manualmente» del checklist. Es una consulta y no una
  -- heurística justamente porque lo detectado no se pisa.
  (e.tipo_final IS NOT NULL OR e.descripcion_final IS NOT NULL
   OR e.foja_inicio_final IS NOT NULL OR e.foja_fin_final IS NOT NULL) AS modificada,

  pi.numero_pdf    AS pagina_pdf_inicio,
  pf.numero_pdf    AS pagina_pdf_fin,
  d.nombre_archivo AS archivo,
  (SELECT p.id     FROM evidencia_persona ep JOIN persona p ON p.id = ep.persona_id
    WHERE ep.evidencia_id = e.id AND ep.funcion = 'introductor' LIMIT 1) AS testigo_id,
  (SELECT p.nombre FROM evidencia_persona ep JOIN persona p ON p.id = ep.persona_id
    WHERE ep.evidencia_id = e.id AND ep.funcion = 'introductor' LIMIT 1) AS testigo
FROM evidencia e
LEFT JOIN grupo_evidencia g ON g.id = e.grupo_id
LEFT JOIN documento d       ON d.id = e.documento_id
LEFT JOIN pagina pi         ON pi.numero_global = e.pagina_inicio
LEFT JOIN pagina pf         ON pf.numero_global = e.pagina_fin;


-- ═══════════════════════════════════════════════════════════════════════════
-- LA PUERTA. El generador lee de acá y de ningún otro lado.
--
-- Se llama con el nombre obvio a propósito: un SELECT futuro que se escriba apurado
-- tiene que salir seguro, no peligroso. Las dos condiciones son lo único que separa
-- «lo que una persona decidió ofrecer» de «todo lo que el sistema encontró»:
--
--   estado = 'incluida'  — nadie más que una persona pone ese estado;
--   activa = 1           — lo que se dividió, se unió o se descartó está apagado.
--
-- Esto NO es la única barrera. `generacion.py` revalida el estado de cada pieza antes
-- de escribirla, aunque ya venga filtrada de acá. La redundancia se paga sola: las dos
-- barreras las escriben caminos distintos, y si una queda mal la otra sigue en pie.
-- ═══════════════════════════════════════════════════════════════════════════
DROP VIEW IF EXISTS v_evidencia_incluida;
CREATE VIEW v_evidencia_incluida AS
SELECT * FROM v_evidencia
 WHERE estado = 'incluida' AND activa = 1;


-- Contadores del checklist, en una sola consulta.
DROP VIEW IF EXISTS v_contadores;
CREATE VIEW v_contadores AS
SELECT
  COUNT(*)                                                    AS detectadas,
  -- COALESCE en todos: SUM sobre cero filas devuelve NULL, no cero, y un caso recién
  -- creado mostraría «null incluidas» en la pantalla. Es feo y además se propaga: un
  -- NULL que llega al JavaScript se imprime como «null» o rompe una comparación.
  COALESCE(SUM(CASE WHEN estado = 'incluida'  THEN 1 ELSE 0 END), 0) AS incluidas,
  COALESCE(SUM(CASE WHEN estado = 'excluida'  THEN 1 ELSE 0 END), 0) AS excluidas,
  COALESCE(SUM(CASE WHEN estado = 'pendiente' THEN 1 ELSE 0 END), 0) AS pendientes,
  COALESCE(SUM(CASE WHEN testigo IS NULL      THEN 1 ELSE 0 END), 0) AS sin_testigo,
  COALESCE(SUM(CASE WHEN foja_inicio IS NULL  THEN 1 ELSE 0 END), 0) AS sin_foja,
  COALESCE(SUM(CASE WHEN NOT foja_firme THEN 1 ELSE 0 END), 0)       AS foja_sin_confirmar,
  COALESCE(SUM(CASE WHEN foja_interpolada THEN 1 ELSE 0 END), 0)     AS foja_interpolada,
  COALESCE(SUM(CASE WHEN confianza IS NOT NULL AND confianza < 0.55 THEN 1 ELSE 0 END), 0)
                                                                     AS baja_confianza,
  COALESCE(SUM(CASE WHEN modificada THEN 1 ELSE 0 END), 0)           AS modificadas,
  COALESCE(SUM(CASE WHEN estado = 'incluida' AND testigo IS NULL THEN 1 ELSE 0 END), 0)
                                                                     AS incluidas_sin_testigo,
  COALESCE(SUM(CASE WHEN estado = 'incluida' AND NOT foja_firme THEN 1 ELSE 0 END), 0)
                                                                     AS incluidas_sin_foja_firme
FROM v_evidencia WHERE activa = 1;
