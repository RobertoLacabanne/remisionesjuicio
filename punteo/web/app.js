/* ════════════════════════════════════════════════════════════════════════════
   Punteo de Evidencia — interfaz

   Sin framework y sin paso de compilación: el archivo que se lee es el que corre.

   Dos reglas gobiernan todo lo de abajo:

     · «guardado» se muestra SÓLO cuando el servidor contestó que sí. No hay
       optimismo: si la escritura falla, la pantalla lo dice y el estado visual de
       la pieza no cambia;
     · los botones de decidir viven únicamente en la pantalla que tiene el
       documento a la vista, y si la imagen no cargó se dice con todas las letras.
   ════════════════════════════════════════════════════════════════════════════ */
'use strict';

const $  = (s, raiz = document) => raiz.querySelector(s);
const $$ = (s, raiz = document) => Array.from(raiz.querySelectorAll(s));

const E = {
  caso: null,            // el caso abierto
  catalogo: null,
  vista: 'casos',
  paginas: [],           // [{numero_global, foja_etiqueta, foja_origen, estado_ev}]
  totalPaginas: 0,
  pagina: 1,
  zoom: 1,
  giro: 0,
  evidencias: [],
  indice: -1,            // posición en E.evidencias de la pieza abierta
  contadores: {},
  grupos: [],
  seleccion: new Set(),
  modoCheck: 'lista',
  sondeo: null,
};

/* ───────────────────────────────────────────────────────────────── utilería ── */
const texto = (s) => (s === null || s === undefined) ? '' : String(s);

function esc(s) {
  return texto(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** Resalta los marcadores del generador para que el hueco se vea, no se lea por encima. */
function conMarcadores(s) {
  return esc(s)
    .replace(/\[FOJA PENDIENTE\]/g, '<span class="marcador duro">[FOJA PENDIENTE]</span>')
    .replace(/\[TESTIGO PENDIENTE\]/g, '<span class="marcador duro">[TESTIGO PENDIENTE]</span>')
    .replace(/\[FOJA A CONFIRMAR\]/g, '<span class="marcador">[FOJA A CONFIRMAR]</span>');
}

async function api(ruta, opciones = {}) {
  const cfg = { method: opciones.metodo || 'GET', headers: {} };
  if (opciones.cuerpo !== undefined) {
    cfg.body = JSON.stringify(opciones.cuerpo);
    cfg.headers['Content-Type'] = 'application/json';
  }
  if (opciones.binario) { cfg.body = opciones.binario; Object.assign(cfg.headers, opciones.cabeceras || {}); }
  const r = await fetch(ruta, cfg);
  const tipo = r.headers.get('Content-Type') || '';
  const datos = tipo.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error((datos && datos.error) || `error ${r.status}`);
  return datos;
}

let avisoTimer;
function avisar(mensaje, mal = false) {
  const n = $('#aviso');
  n.textContent = mensaje;
  n.classList.toggle('mal', !!mal);
  n.hidden = false;
  clearTimeout(avisoTimer);
  avisoTimer = setTimeout(() => { n.hidden = true; }, mal ? 6500 : 2600);
}

/** El indicador de guardado. Nunca dice «guardado» antes de que el servidor conteste. */
function guardando() {
  const n = $('#guardado'); n.hidden = false; n.classList.remove('error');
  n.textContent = 'guardando…';
}
function guardado() {
  const n = $('#guardado'); n.hidden = false; n.classList.remove('error');
  n.textContent = 'guardado';
  setTimeout(() => { if (n.textContent === 'guardado') n.hidden = true; }, 1800);
}
function fallo(e) {
  const n = $('#guardado'); n.hidden = false; n.classList.add('error');
  n.textContent = 'NO se guardó';
  avisar(e.message || String(e), true);
}

/** Envuelve una escritura para que el indicador diga la verdad siempre. */
async function escribir(fn) {
  guardando();
  try { const r = await fn(); guardado(); return r; }
  catch (e) { fallo(e); throw e; }
}

async function dialogo({ titulo, campos = [], aceptar = 'Aceptar', ayuda = '' }) {
  return new Promise(resolve => {
    const dlg = $('#dlg');
    dlg.innerHTML = `
      <form method="dialog">
        <div class="dlg-cuerpo">
          <h2>${esc(titulo)}</h2>
          ${ayuda ? `<p class="ayuda">${ayuda}</p>` : ''}
          <div class="dlg-campos">${campos.map(c => {
            if (c.tipo === 'select') return `<label>${esc(c.rotulo)}
              <select name="${c.nombre}">${c.opciones.map(o =>
                `<option value="${esc(o.valor)}" ${o.valor === c.valor ? 'selected' : ''}>${esc(o.texto)}</option>`).join('')}</select></label>`;
            if (c.tipo === 'textarea') return `<label>${esc(c.rotulo)}
              <textarea name="${c.nombre}" rows="3">${esc(c.valor || '')}</textarea></label>`;
            return `<label>${esc(c.rotulo)}
              <input type="text" name="${c.nombre}" value="${esc(c.valor || '')}"
                     placeholder="${esc(c.marcador || '')}" ${c.mono ? 'class="mono"' : ''}></label>`;
          }).join('')}</div>
        </div>
        <div class="dlg-pie">
          <button value="" class="boton">Cancelar</button>
          <button value="ok" class="boton principal">${esc(aceptar)}</button>
        </div>
      </form>`;
    dlg.addEventListener('close', () => {
      if (dlg.returnValue !== 'ok') return resolve(null);
      const datos = {};
      $$('input,select,textarea', dlg).forEach(i => { if (i.name) datos[i.name] = i.value.trim(); });
      resolve(datos);
    }, { once: true });
    dlg.showModal();
    const primero = $('input,select,textarea', dlg);
    if (primero) primero.focus();
  });
}

/* ──────────────────────────────────────────────────────────────── navegación ── */
function mostrar(vista) {
  E.vista = vista;
  $$('.vista').forEach(v => v.classList.toggle('activa', v.id === `vista-${vista}`));
  $$('#nav button').forEach(b => b.classList.toggle('activo', b.dataset.vista === vista));
  if (E.caso) location.hash = `#/${E.caso.slug}/${vista}`;
  const carga = { legajo: cargarLegajo, revision: cargarRevision, checklist: cargarChecklist,
                  testigos: cargarTestigos, punteo: cargarPunteo, casos: cargarCasos }[vista];
  if (carga) carga();
}

async function abrirCaso(slug, vista = 'legajo') {
  E.caso = await api(`/api/caso/${slug}`);
  E.contadores = E.caso.contadores || {};
  $('#nav').hidden = false;
  $('#barra-caso').hidden = false;
  $('#caso-legajo').textContent = E.caso.numero_legajo;
  $('#caso-caratula').textContent = E.caso.caratula;
  document.title = `${E.caso.numero_legajo} — Punteo`;
  // Grupos y personas se cargan al abrir el caso y no cuando los necesita cada pantalla:
  // la ficha de evidencia arma sus dos selectores con estas listas, y si llega antes que
  // ellas el selector sale vacío y parece que el caso no tiene sectores ni testigos.
  await Promise.all([cargarPaginas(), refrescarGrupos(), refrescarPersonas()]);
  mostrar(vista);
}

function cerrarCaso() {
  E.caso = null; E.evidencias = []; E.paginas = [];
  $('#nav').hidden = true; $('#barra-caso').hidden = true;
  document.title = 'Punteo de Evidencia — UFIL Paraná';
  location.hash = '';
  mostrar('casos');
}

/* ══════════════════════════════════════════════════════════════════ CASOS ══ */
async function cargarCasos() {
  const [{ casos }, estado] = await Promise.all([api('/api/casos'), api('/api/estado')]);
  const cont = $('#lista-casos');
  if (!casos.length) {
    cont.innerHTML = `<p class="vacio">Todavía no hay ningún caso. Creá el primero con
      el número de legajo y la carátula.</p>`;
  } else {
    cont.innerHTML = casos.map(c => `
      <button class="caso-ficha" data-slug="${esc(c.slug)}">
        <div class="cf-datos">
          <div class="cf-legajo">${esc(c.numero_legajo)}</div>
          <div class="cf-caratula">${esc(c.caratula)}</div>
          <div class="cf-meta">${esc(c.tipo_etiqueta)} · ${c.documentos} PDF · ${c.paginas} páginas</div>
        </div>
        <div class="cf-cuentas">
          <span style="color:var(--incluir)">${c.incluidas} incl.</span>
          <span style="color:var(--pendiente)">${c.pendientes} pend.</span>
        </div>
      </button>`).join('');
    $$('.caso-ficha', cont).forEach(b =>
      b.onclick = () => abrirCaso(b.dataset.slug).catch(e => avisar(e.message, true)));
  }
  const ocr = estado.ocr;
  $('#estado-maquina').textContent =
    `v${estado.version} · ${ocr.disponible ? ocr.detalle : 'SIN OCR'} · ` +
    `idioma ${ocr.idioma_configurado} ${ocr.idioma_presente ? 'presente' : 'AUSENTE'} · ` +
    `datos en ${estado.datos}`;
  if (!ocr.disponible || !ocr.idioma_presente) {
    $('#estado-maquina').style.color = 'var(--excluir)';
  }
}

$('#nuevo-caso').onclick = async () => {
  const d = await dialogo({
    titulo: 'Nuevo caso',
    ayuda: 'El tipo de proceso decide si el testigo introductor es obligatorio y qué ' +
           'plantilla usa el generador. Se puede cambiar después.',
    campos: [
      { nombre: 'numero_legajo', rotulo: 'Número de legajo', mono: true, marcador: 'OGA-0000/2026' },
      { nombre: 'caratula', rotulo: 'Carátula', marcador: 'APELLIDO, Nombre s/ Peculado' },
      { nombre: 'tipo_proceso', rotulo: 'Tipo de proceso', tipo: 'select', valor: 'remision',
        opciones: [{ valor: 'remision', texto: 'Remisión a juicio' },
                   { valor: 'abreviado', texto: 'Procedimiento abreviado' }] },
      { nombre: 'observaciones', rotulo: 'Observaciones (opcional)', tipo: 'textarea' },
    ], aceptar: 'Crear',
  });
  if (!d) return;
  try {
    const caso = await api('/api/casos', { metodo: 'POST', cuerpo: d });
    await abrirCaso(caso.slug);
  } catch (e) { avisar(e.message, true); }
};

/* ═════════════════════════════════════════════════════════════════ LEGAJO ══ */
async function cargarLegajo() {
  E.caso = await api(`/api/caso/${E.caso.slug}`);
  const docs = E.caso.documentos_detalle || [];
  $('#lista-documentos').innerHTML = docs.length ? docs.map(d => `
    <div class="doc-fila">
      <span class="mono tenue">${d.orden}</span>
      <span class="dnombre">${esc(d.nombre_archivo)}</span>
      <span class="mono tenue">${d.paginas_leidas}/${d.paginas} págs. leídas</span>
      <span class="dhash" title="SHA-256 del original">${esc(d.sha256.slice(0, 12))}…</span>
    </div>`).join('') : '';

  $('#tarjeta-procesar').hidden = !docs.length;
  const faltan = docs.reduce((a, d) => a + (d.paginas - d.paginas_leidas), 0);
  $('#procesar').textContent = faltan ? `Procesar ${faltan} páginas` : 'Volver a procesar';

  const fol = E.caso.foliatura || {};
  $('#tarjeta-foliatura').hidden = !fol.paginas;
  if (fol.paginas) {
    $('#resumen-foliatura').innerHTML = `
      <div class="contadores-tira">
        ${[['paginas', 'páginas', ''], ['confirmadas', 'confirmadas', 'incluidas'],
           ['detectadas', 'detectadas', 'pendientes'], ['manuales', 'a mano', ''],
           ['desconocidas', 'sin foja', 'avisa']]
          .map(([k, r, cl]) => `<div class="cuenta ${cl}"><b>${fol[k] ?? 0}</b><span>${r}</span></div>`).join('')}
      </div>`;
    $('#tramos-foliatura').innerHTML = (fol.tramos || []).map(t => `
      <div class="tramo">
        <span class="mono">págs. ${t.desde_global}–${t.hasta_global}</span>
        <span class="mono" style="color:var(--bronce)">fs. ${t.desde_global + t.desplazamiento}–${t.hasta_global + t.desplazamiento}</span>
        <span class="tenue">${esc(t.zona)} · ${t.paginas_leidas} leídas, ${t.paginas_interpoladas} calculadas</span>
        <span class="espaciador"></span>
        <span class="confianza ${t.confianza >= .75 ? 'alta' : t.confianza >= .55 ? 'media' : 'baja'}">${t.confianza}</span>
        <button class="mini" data-confirmar="${t.desde_global}:${t.hasta_global}">Confirmar tramo</button>
      </div>`).join('') || '<p class="vacio">No se detectó ningún tramo de foliatura.</p>';
    $$('[data-confirmar]').forEach(b => b.onclick = async () => {
      const [desde, hasta] = b.dataset.confirmar.split(':').map(Number);
      await escribir(() => api(`/api/caso/${E.caso.slug}/foliatura`,
        { metodo: 'POST', cuerpo: { desde, hasta } }));
      avisar('Tramo confirmado: esas fojas ya se pueden citar en el escrito.');
      cargarLegajo();
    });
  }
  $('#confirmar-borrado').value = '';
}

function conectarCarga() {
  const zona = $('#zona-carga'), campo = $('#archivo-pdf');
  $('#elegir-pdf').onclick = () => campo.click();
  campo.onchange = () => subir(Array.from(campo.files));
  ['dragenter', 'dragover'].forEach(ev => zona.addEventListener(ev, e => {
    e.preventDefault(); zona.classList.add('encima');
  }));
  ['dragleave', 'drop'].forEach(ev => zona.addEventListener(ev, e => {
    e.preventDefault(); zona.classList.remove('encima');
  }));
  zona.addEventListener('drop', e => subir(Array.from(e.dataTransfer.files)));
}

async function subir(archivos) {
  const pdfs = archivos.filter(f => /\.pdf$/i.test(f.name));
  if (!pdfs.length) return avisar('Sólo se cargan archivos PDF.', true);
  for (const f of pdfs) {
    guardando();
    try {
      const r = await api(`/api/caso/${E.caso.slug}/documentos`, {
        metodo: 'POST', binario: await f.arrayBuffer(),
        cabeceras: { 'Content-Type': 'application/pdf',
                     'X-Nombre-Archivo': encodeURIComponent(f.name) },
      });
      guardado();
      avisar(r.duplicado ? `«${f.name}» ya estaba cargado (mismo contenido).`
                         : `«${f.name}»: ${r.paginas} páginas.`);
    } catch (e) { fallo(e); }
  }
  await cargarLegajo();
  await cargarPaginas();
}

$('#procesar').onclick = async () => {
  try {
    const r = await api(`/api/caso/${E.caso.slug}/procesar`, { metodo: 'POST' });
    if (!r.ok) return avisar(r.motivo, true);
    sondearProgreso();
  } catch (e) { avisar(e.message, true); }
};
$('#detener').onclick = () => api(`/api/caso/${E.caso.slug}/procesar/detener`, { metodo: 'POST' });

function sondearProgreso() {
  clearInterval(E.sondeo);
  const paso = async () => {
    let p;
    try { p = await api(`/api/caso/${E.caso.slug}/progreso`); } catch { return; }
    const corriendo = p.estado === 'corriendo';
    $('#progreso').hidden = !corriendo;
    $('#detener').hidden = !corriendo;
    $('#procesar').disabled = corriendo;
    if (corriendo) {
      $('#progreso-etapa').textContent = p.etapa;
      $('#progreso-numeros').textContent = p.total ? `${p.hecho}/${p.total}` : '';
      $('#progreso-falta').textContent = p.faltan_segundos
        ? `faltan ~${Math.ceil(p.faltan_segundos / 60)} min` : '';
      $('#progreso-relleno').style.width = p.total ? `${100 * p.hecho / p.total}%` : '0%';
    }
    const msg = $('#procesar-mensaje');
    if (p.mensaje) {
      msg.hidden = false; msg.textContent = p.mensaje;
      msg.classList.toggle('error', p.estado === 'error');
    }
    if (!corriendo && p.estado !== 'inactivo') {
      clearInterval(E.sondeo); E.sondeo = null;
      await cargarLegajo(); await cargarPaginas();
    }
  };
  paso();
  E.sondeo = setInterval(paso, 2000);
}

$('#borrar-caso').onclick = async () => {
  const numero = $('#confirmar-borrado').value.trim();
  if (!numero) return avisar('Escribí el número de legajo para confirmar.', true);
  try {
    await api(`/api/caso/${E.caso.slug}`, { metodo: 'DELETE', cuerpo: { numero_legajo: numero } });
    avisar('Caso borrado.');
    cerrarCaso();
  } catch (e) { avisar(e.message, true); }
};

/* ═══════════════════════════════════════════════════════════════ REVISIÓN ══ */
async function cargarPaginas() {
  if (!E.caso) return;
  const r = await api(`/api/caso/${E.caso.slug}/paginas?desde=1&limite=500`);
  E.paginas = r.paginas; E.totalPaginas = r.total;
  $('#pagina-total').textContent = r.total ? `/ ${r.total}` : '';
}

async function cargarRevision() {
  if (!E.evidencias.length) await cargarEvidencias();
  if (E.indice < 0 && E.evidencias.length) E.indice = 0;
  pintarTira();
  if (E.evidencias.length) abrirEvidencia(E.indice);
  else { irAPagina(E.pagina); pintarPanelVacio(); }
}

function pintarPanelVacio() {
  $('#ev-cuerpo').innerHTML = `<p class="vacio">No hay piezas propuestas todavía.
    Cargá los PDF en <b>Legajo</b> y procesalos, o creá una pieza a mano desde la
    página que estés mirando.</p>`;
  $('#ev-decision').hidden = true; $('#ev-navegar').hidden = true;
  $('#ev-numero').textContent = ''; $('#ev-sello').className = 'sello'; $('#ev-sello').textContent = '';
}

/** La tira de fojas: una marca por página, pintada según el estado de su evidencia. */
function pintarTira() {
  const porPagina = new Map();
  for (const ev of E.evidencias) {
    for (let p = ev.pagina_inicio; p <= (ev.pagina_fin || ev.pagina_inicio); p++) {
      // Gana el estado más «fuerte»: si una página tiene una incluida y una pendiente,
      // lo que importa saber de un vistazo es que ahí ya hay algo que va al escrito.
      const previo = porPagina.get(p);
      if (previo === 'incluida') continue;
      porPagina.set(p, ev.estado);
    }
  }
  const tira = $('#tira');
  tira.innerHTML = '';
  const frag = document.createDocumentFragment();
  for (let p = 1; p <= E.totalPaginas; p++) {
    const b = document.createElement('button');
    b.className = `tira-marca ${porPagina.get(p) || ''} ${p === E.pagina ? 'actual' : ''}`;
    const pag = E.paginas.find(x => x.numero_global === p);
    b.title = `pág. ${p}${pag && pag.foja_etiqueta ? ` · foja ${pag.foja_etiqueta}` : ' · sin foja'}`;
    b.onclick = () => irAPagina(p);
    frag.appendChild(b);
  }
  tira.appendChild(frag);
  const actual = tira.querySelector('.actual');
  if (actual) actual.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

async function irAPagina(numero, resalte) {
  numero = Math.max(1, Math.min(E.totalPaginas || 1, numero));
  E.pagina = numero;
  $('#ir-pagina').value = numero;
  const marco = $('#doc-marco'), img = $('#doc-imagen');
  marco.classList.remove('sin-imagen');
  img.hidden = false;
  img.onerror = () => {
    // Que la imagen no cargue no puede pasar desapercibido: la regla del sistema es
    // que nadie decida sobre una pieza sin ver la foja que la sustenta.
    img.hidden = true; marco.classList.add('sin-imagen');
  };
  img.src = `/api/caso/${E.caso.slug}/pagina/${numero}/imagen`;
  img.style.width = `${Math.round(100 * E.zoom)}%`;
  marco.style.transform = E.giro ? `rotate(${E.giro}deg)` : '';

  const pag = E.paginas.find(x => x.numero_global === numero);
  $('#campo-foja').value = pag && pag.foja_etiqueta ? pag.foja_etiqueta : '';
  const sello = $('#sello-foja');
  const origen = pag ? pag.foja_origen : 'desconocida';
  sello.className = `sello-foja ${origen}`;
  sello.textContent = { desconocida: 'sin foja', detectada: 'detectada',
                        confirmada: 'confirmada', manual: 'a mano' }[origen] || origen;
  pintarResalte(resalte);
  pintarTira();
}

/**
 * Dibuja el recuadro del fragmento que sustenta la pieza, sobre la imagen de la página.
 *
 * El tamaño de la página sale de `pagina.ancho_pt`/`alto_pt` y NO de un A4 supuesto:
 * en un legajo entran oficios en tamaño oficio, planillas apaisadas y páginas que se
 * enderezaron al leerlas, y con un tamaño fijo el recuadro cae en cualquier lado.
 *
 * Y se dibuja cuando la imagen YA cargó. La primera versión chequeaba `naturalWidth`
 * arriba de todo y cortaba: como `img.src` se acababa de cambiar, ese valor siempre era
 * cero y el recuadro no se dibujaba nunca.
 */
function pintarResalte(ev) {
  const caja = $('#resalte'), img = $('#doc-imagen');
  E.resalte = null;
  caja.hidden = true;
  if (!ev || ev.x0 == null || ev.pagina_inicio !== E.pagina) return;

  const pag = E.paginas.find(x => x.numero_global === E.pagina) || {};
  const anchoPt = ev.ancho_pt || pag.ancho_pt, altoPt = ev.alto_pt || pag.alto_pt;
  if (!anchoPt || !altoPt) return;      // sin medida de la página no se inventa una
  E.resalte = { ...ev, ancho_pt: anchoPt, alto_pt: altoPt };

  const mostrar = () => {
    if (!img.naturalWidth || !img.clientWidth) return;
    const fx = img.clientWidth / anchoPt, fy = img.clientHeight / altoPt;
    caja.style.left = `${ev.x0 * fx}px`;   caja.style.top = `${ev.y0 * fy}px`;
    caja.style.width = `${(ev.x1 - ev.x0) * fx}px`;
    caja.style.height = `${(ev.y1 - ev.y0) * fy}px`;
    caja.hidden = false;
  };
  if (img.complete && img.naturalWidth) mostrar();
  else img.addEventListener('load', mostrar, { once: true });
}

// Al cambiar el zoom o el tamaño de la ventana, la imagen mide otra cosa y el recuadro
// queda apuntando a donde el texto ya no está.
addEventListener('resize', () => { if (E.resalte) pintarResalte(E.resalte); });

async function cargarEvidencias(filtro = 'todas', orden = 'manual', texto = null) {
  const q = new URLSearchParams({ filtro, orden, limite: '500' });
  if (texto) q.set('q', texto);
  const r = await api(`/api/caso/${E.caso.slug}/evidencias?${q}`);
  E.evidencias = r.evidencias;
  const c = await api(`/api/caso/${E.caso.slug}`);
  E.contadores = c.contadores || {};
  return r;
}

async function abrirEvidencia(indice) {
  if (indice < 0 || indice >= E.evidencias.length) return;
  E.indice = indice;
  const breve = E.evidencias[indice];
  const ev = await api(`/api/caso/${E.caso.slug}/evidencia/${breve.id}`);
  E.evidencias[indice] = { ...breve, ...ev };

  const pag = E.paginas.find(x => x.numero_global === ev.pagina_inicio) || {};
  await irAPagina(ev.pagina_inicio || 1, { ...ev, ancho_pt: pag.ancho_pt, alto_pt: pag.alto_pt });

  $('#ev-numero').textContent = `#${ev.id}`;
  const sello = $('#ev-sello');
  sello.className = `sello ${ev.estado}`;
  sello.textContent = ev.estado;
  $('#ev-posicion').textContent = `${indice + 1} de ${E.evidencias.length}`;
  $('#ev-decision').hidden = false; $('#ev-navegar').hidden = false;
  $$('.decidir').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.estado === ev.estado)));

  const c = E.contadores;
  $('#ev-contadores').innerHTML =
    `<span style="color:var(--incluir)">${c.incluidas || 0}</span> · ` +
    `<span style="color:var(--pendiente)">${c.pendientes || 0}</span> · ` +
    `<span style="color:var(--excluir)">${c.excluidas || 0}</span> de ${c.detectadas || 0}`;

  pintarFichaEvidencia(ev);
}

const ADVERTENCIAS = {
  foja_sin_confirmar: ['La foja no está confirmada', false],
  sin_foja: ['Sin foja: el escrito va a salir con un marcador', true],
  ocr_pobre: ['El OCR leyó mal estas páginas', true],
  sin_titulo: ['No se reconoció un título: revisá dónde empieza y dónde termina', false],
  pieza_larga: ['Pieza muy larga: puede que adentro haya más de un documento', false],
  union_con_excluida: ['Esta unión contiene material que habías excluido', true],
  union_de_tipos_distintos: ['Se unieron piezas de tipos distintos', false],
};

function pintarFichaEvidencia(ev) {
  const tipos = (E.catalogo.tipos || []);
  const cuerpo = $('#ev-cuerpo');
  const conf = ev.confianza == null ? 'cargada a mano'
             : `${ev.confianza_nivel} (${ev.confianza})`;
  cuerpo.innerHTML = `
    <div class="advertencias">
      ${(ev.advertencias || []).map(a => {
        const [t, dura] = ADVERTENCIAS[a] || [a, false];
        return `<span class="adv ${dura ? 'dura' : ''}">${esc(t)}</span>`;
      }).join('')}
    </div>

    <div class="campo-ev">
      <label for="ev-desc">Descripción</label>
      <textarea id="ev-desc" rows="3">${esc(ev.descripcion)}</textarea>
      ${ev.descripcion_final ? `<div class="detectado">detectado: <b>${esc(ev.descripcion_detectada)}</b>
        <button class="enlace" id="ev-desc-volver">volver a lo detectado</button></div>` : ''}
    </div>

    <div class="campo-ev">
      <label for="ev-tipo">Tipo de prueba</label>
      <select id="ev-tipo">
        ${tipos.map(t => `<option value="${esc(t.clave)}" ${t.clave === ev.tipo ? 'selected' : ''}
          >${esc(t.etiqueta)} — ${esc(t.familia_etiqueta)}</option>`).join('')}
      </select>
    </div>

    <div class="par-campos">
      <div class="campo-ev">
        <label for="ev-foja-i">Foja desde</label>
        <input type="text" id="ev-foja-i" class="mono" value="${esc(ev.foja_inicio)}" placeholder="—">
      </div>
      <div class="campo-ev">
        <label for="ev-foja-f">Foja hasta</label>
        <input type="text" id="ev-foja-f" class="mono" value="${esc(ev.foja_fin)}" placeholder="—">
      </div>
    </div>
    <div class="detectado" style="margin-top:-8px;margin-bottom:12px">
      páginas PDF <b class="mono">${ev.pagina_inicio}${ev.pagina_fin !== ev.pagina_inicio ? `–${ev.pagina_fin}` : ''}</b>
      · archivo <b>${esc(ev.archivo)}</b>
      · origen de la foja <b>${esc(ev.foja_origen)}</b>
    </div>

    <div class="campo-ev">
      <label for="ev-testigo">Testigo introductor${E.caso.tipo_proceso === 'abreviado' ? ' (opcional)' : ''}</label>
      <input type="text" id="ev-testigo" value="${esc(ev.testigo)}"
             placeholder="apellido, nombre" list="lista-personas">
    </div>

    <div class="campo-ev">
      <label for="ev-fecha">Fecha del documento</label>
      <input type="text" id="ev-fecha" class="mono" value="${esc(ev.fecha_documento)}"
             placeholder="AAAA-MM-DD, o vacío si no consta">
    </div>

    <div class="campo-ev">
      <label for="ev-grupo">Sector</label>
      <select id="ev-grupo">
        <option value="">— sin agrupar —</option>
        ${E.grupos.filter(g => g.id).map(g => `<option value="${g.id}"
          ${g.id === ev.grupo_id ? 'selected' : ''}>${esc(g.nombre)}</option>`).join('')}
      </select>
    </div>

    <div class="campo-ev">
      <label for="ev-obs">Observaciones</label>
      <textarea id="ev-obs" rows="2">${esc(ev.observaciones)}</textarea>
    </div>

    <div class="campo-ev">
      <label>Confianza de la detección</label>
      <span class="confianza ${ev.confianza_nivel}">${esc(conf)}</span>
      <span class="tenue" style="font-size:.76rem"> · origen: ${esc(ev.origen)}</span>
    </div>

    ${(ev.duplicados || []).length ? `<div class="campo-ev">
      <label>Posible duplicado</label>
      ${ev.duplicados.map(d => `<button class="mini" data-ver-dup="${d.otra_id}">
        ver la pieza #${d.otra_id} (${d.motivo})</button>`).join(' ')}
    </div>` : ''}

    <details>
      <summary>Texto de respaldo (lo que se leyó del papel)</summary>
      <div class="texto-origen">${esc(ev.texto_origen) || '<i>sin texto</i>'}</div>
    </details>

    <div class="campo-ev" style="margin-top:14px;display:flex;gap:6px;flex-wrap:wrap">
      <button class="mini" id="ev-dividir">Dividir</button>
      <button class="mini" id="ev-historial">Historial</button>
      ${ev.origen === 'division' || ev.origen === 'union'
        ? '<button class="mini" id="ev-deshacer">Deshacer</button>' : ''}
      <button class="mini" id="ev-descartar">No es una pieza</button>
    </div>`;

  // ── guardado de cada campo ──
  const guardarCampo = (campo, valor) => escribir(() =>
    api(`/api/caso/${E.caso.slug}/evidencia/${ev.id}`,
        { metodo: 'PATCH', cuerpo: { [campo]: valor } })
  ).then(nuevo => { E.evidencias[E.indice] = { ...E.evidencias[E.indice], ...nuevo }; });

  const alSalir = (sel, campo) => {
    const n = $(sel); if (!n) return;
    n.addEventListener('change', () => guardarCampo(campo, n.value).catch(() => {}));
  };
  alSalir('#ev-desc', 'descripcion');
  alSalir('#ev-tipo', 'tipo');
  alSalir('#ev-foja-i', 'foja_inicio');
  alSalir('#ev-foja-f', 'foja_fin');
  alSalir('#ev-obs', 'observaciones');
  alSalir('#ev-fecha', 'fecha_documento');

  const volver = $('#ev-desc-volver');
  if (volver) volver.onclick = async () => {
    await guardarCampo('descripcion', '');
    abrirEvidencia(E.indice);
  };

  $('#ev-grupo').addEventListener('change', async e => {
    const v = e.target.value;
    await escribir(() => api(`/api/caso/${E.caso.slug}/evidencia/${ev.id}/grupo`,
      { metodo: 'POST', cuerpo: { grupo_id: v ? Number(v) : null } }));
  });

  $('#ev-testigo').addEventListener('change', async e => {
    const nombre = e.target.value.trim();
    try {
      if (!nombre && ev.testigo_id) {
        await escribir(() => api(`/api/caso/${E.caso.slug}/evidencia/${ev.id}/testigo`,
          { metodo: 'DELETE', cuerpo: { persona_id: ev.testigo_id } }));
      } else if (nombre) {
        await escribir(() => api(`/api/caso/${E.caso.slug}/evidencia/${ev.id}/testigo`,
          { metodo: 'POST', cuerpo: { nombre } }));
      }
      await refrescarPersonas();
      abrirEvidencia(E.indice);
    } catch { /* ya avisó */ }
  });

  $('#ev-dividir').onclick = async () => {
    const d = await dialogo({
      titulo: 'Dividir la pieza',
      ayuda: `Indicá la <b>primera página de la segunda mitad</b>. Esta pieza va de la
        ${ev.pagina_inicio} a la ${ev.pagina_fin}. Las dos mitades quedan
        <b>pendientes</b>: dividir cambia qué es cada pieza, así que la decisión
        anterior no se aplica a ninguna de las dos.`,
      campos: [{ nombre: 'pagina_corte', rotulo: 'Página de corte', mono: true,
                 valor: String(Math.min(ev.pagina_fin, ev.pagina_inicio + 1)) }],
      aceptar: 'Dividir',
    });
    if (!d) return;
    try {
      await escribir(() => api(`/api/caso/${E.caso.slug}/evidencia/${ev.id}/dividir`,
        { metodo: 'POST', cuerpo: { pagina_corte: Number(d.pagina_corte) } }));
      await cargarEvidencias(); pintarTira(); abrirEvidencia(Math.min(E.indice, E.evidencias.length - 1));
    } catch { /* ya avisó */ }
  };

  $('#ev-descartar').onclick = async () => {
    await escribir(() => api(`/api/caso/${E.caso.slug}/evidencia/${ev.id}/descartar`,
      { metodo: 'POST', cuerpo: {} }));
    avisar('Descartada. No se borró: queda en el historial y se puede restaurar.');
    await cargarEvidencias(); pintarTira();
    abrirEvidencia(Math.min(E.indice, E.evidencias.length - 1));
  };

  const deshacer = $('#ev-deshacer');
  if (deshacer) deshacer.onclick = async () => {
    await escribir(() => api(`/api/caso/${E.caso.slug}/evidencia/${ev.id}/deshacer`,
      { metodo: 'POST', cuerpo: {} }));
    await cargarEvidencias(); pintarTira(); abrirEvidencia(0);
  };

  $('#ev-historial').onclick = async () => {
    const { historial } = await api(`/api/caso/${E.caso.slug}/evidencia/${ev.id}/historial`,
      { metodo: 'POST', cuerpo: {} });
    const dlg = $('#dlg');
    dlg.innerHTML = `<form method="dialog"><div class="dlg-cuerpo">
      <h2>Historial de la pieza #${ev.id}</h2>
      ${historial.length ? `<table class="check"><tbody>${historial.map(h => `
        <tr><td class="c-num">${esc((h.cuando || '').slice(0, 16).replace('T', ' '))}</td>
            <td class="c-tipo">${esc(h.campo)}</td>
            <td>${esc(h.valor_anterior) || '<i>—</i>'} → <b>${esc(h.valor_nuevo) || '<i>—</i>'}</b>
                ${h.detalle ? `<div class="tenue" style="font-size:.74rem">${esc(h.detalle)}</div>` : ''}</td>
        </tr>`).join('')}</tbody></table>` : '<p class="vacio">Sin cambios registrados.</p>'}
      </div><div class="dlg-pie"><button value="ok" class="boton">Cerrar</button></div></form>`;
    dlg.showModal();
  };

  $$('[data-ver-dup]').forEach(b => b.onclick = () => {
    const i = E.evidencias.findIndex(x => x.id === Number(b.dataset.verDup));
    if (i >= 0) abrirEvidencia(i); else avisar('Esa pieza no está en la lista cargada.');
  });
}

async function decidir(estado) {
  const ev = E.evidencias[E.indice];
  if (!ev) return;
  try {
    const nuevo = await escribir(() => api(`/api/caso/${E.caso.slug}/evidencia/${ev.id}/estado`,
      { metodo: 'POST', cuerpo: { estado } }));
    E.evidencias[E.indice] = { ...ev, ...nuevo };
    const c = await api(`/api/caso/${E.caso.slug}`);
    E.contadores = c.contadores || {};
    pintarTira();
    // Avanzar sola después de decidir es lo que hace que revisar cuatrocientas piezas
    // sea posible. Si es la última, se queda y lo dice.
    if (E.indice < E.evidencias.length - 1) abrirEvidencia(E.indice + 1);
    else { abrirEvidencia(E.indice); avisar('Era la última pieza de la lista.'); }
  } catch { /* ya avisó */ }
}

$$('.decidir').forEach(b => b.onclick = () => decidir(b.dataset.estado));
$('#ev-anterior').onclick = () => abrirEvidencia(E.indice - 1);
$('#ev-siguiente').onclick = () => abrirEvidencia(E.indice + 1);
$('#pag-anterior').onclick = () => irAPagina(E.pagina - 1);
$('#pag-siguiente').onclick = () => irAPagina(E.pagina + 1);
$('#ir-pagina').addEventListener('change', e => irAPagina(Number(e.target.value) || 1));
function cambiarZoom(delta) {
  E.zoom = Math.max(.3, Math.min(3, E.zoom + delta));
  actualizarZoom();
  $('#doc-imagen').style.width = `${Math.round(100 * E.zoom)}%`;
  // El recuadro se recalcula contra el ancho nuevo. Sin esto queda pegado al tamaño
  // anterior y señala un renglón que ya no es el que corresponde.
  if (E.resalte) pintarResalte(E.resalte);
}
$('#zoom-mas').onclick = () => cambiarZoom(.15);
$('#zoom-menos').onclick = () => cambiarZoom(-.15);
$('#rotar').onclick = () => { E.giro = (E.giro + 90) % 360; irAPagina(E.pagina); };
function actualizarZoom() { $('#zoom-valor').textContent = `${Math.round(E.zoom * 100)}%`; }

$('#campo-foja').addEventListener('change', async e => {
  try {
    await escribir(() => api(`/api/caso/${E.caso.slug}/pagina/${E.pagina}/foja`,
      { metodo: 'POST', cuerpo: { foja: e.target.value } }));
    await cargarPaginas();
    await irAPagina(E.pagina);
    if (E.evidencias.length) { await cargarEvidencias(); abrirEvidencia(E.indice); }
  } catch { /* ya avisó */ }
});

$('#nueva-evidencia').onclick = async () => {
  const pag = E.paginas.find(x => x.numero_global === E.pagina) || {};
  const d = await dialogo({
    titulo: `Nueva pieza desde la página ${E.pagina}`,
    ayuda: 'La evidencia cargada a mano se integra igual que la automática: mismo ' +
           'checklist, mismo orden, mismo generador. Lo único que no tiene es confianza, ' +
           'porque no hay nada que medir en algo que escribió una persona.',
    campos: [
      { nombre: 'descripcion', rotulo: 'Descripción', tipo: 'textarea' },
      { nombre: 'tipo', rotulo: 'Tipo', tipo: 'select', valor: 'sin_clasificar',
        opciones: (E.catalogo.tipos || []).map(t => ({ valor: t.clave, texto: t.etiqueta })) },
      { nombre: 'pagina_inicio', rotulo: 'Página desde', mono: true, valor: String(E.pagina) },
      { nombre: 'pagina_fin', rotulo: 'Página hasta', mono: true, valor: String(E.pagina) },
      { nombre: 'foja_inicio', rotulo: 'Foja desde', mono: true, valor: pag.foja_etiqueta || '' },
      { nombre: 'foja_fin', rotulo: 'Foja hasta', mono: true, valor: pag.foja_etiqueta || '' },
    ], aceptar: 'Crear',
  });
  if (!d) return;
  try {
    const nueva = await escribir(() => api(`/api/caso/${E.caso.slug}/evidencias`,
      { metodo: 'POST', cuerpo: { ...d, pagina_inicio: Number(d.pagina_inicio),
                                  pagina_fin: Number(d.pagina_fin) } }));
    await cargarEvidencias();
    const i = E.evidencias.findIndex(x => x.id === nueva.id);
    pintarTira();
    if (i >= 0) abrirEvidencia(i);
  } catch { /* ya avisó */ }
};

/* ══════════════════════════════════════════════════════════════ CHECKLIST ══ */
async function cargarChecklist() {
  await refrescarGrupos();
  const filtro = $('#filtro-estado').value;
  const orden = $('#filtro-orden').value;
  const texto = $('#filtro-texto').value.trim() || null;
  const r = await cargarEvidencias(filtro, orden, texto);
  pintarContadores();
  if (E.modoCheck === 'grupos') pintarChecklistGrupos();
  else pintarChecklistLista(r.total);
}

function pintarContadores() {
  const c = E.contadores;
  const cuentas = [
    ['detectadas', 'detectadas', ''],
    ['incluidas', 'incluidas', 'incluidas'],
    ['excluidas', 'excluidas', 'excluidas'],
    ['pendientes', 'pendientes', 'pendientes'],
    ['sin_testigo', 'sin testigo', c.sin_testigo ? 'avisa' : ''],
    ['foja_sin_confirmar', 'foja sin confirmar', c.foja_sin_confirmar ? 'avisa' : ''],
    ['modificadas', 'modificadas', ''],
  ];
  $('#contadores-tira').innerHTML = cuentas.map(([k, r, cl]) =>
    `<button class="cuenta ${cl}" data-filtro="${k}"><b>${c[k] ?? 0}</b><span>${r}</span></button>`).join('');
  $$('#contadores-tira .cuenta').forEach(b => b.onclick = () => {
    const mapa = { detectadas: 'todas', incluidas: 'incluidas', excluidas: 'excluidas',
                   pendientes: 'pendientes', sin_testigo: 'sin_testigo',
                   foja_sin_confirmar: 'foja_sin_confirmar', modificadas: 'modificadas' };
    $('#filtro-estado').value = mapa[b.dataset.filtro] || 'todas';
    cargarChecklist();
  });
}

const MARCA_ESTADO = { incluida: '✓', excluida: '✕', pendiente: '○' };

function pintarChecklistLista(total) {
  const filas = E.evidencias.map(e => `
    <tr class="fila ${E.seleccion.has(e.id) ? 'elegida' : ''}" data-id="${e.id}">
      <td class="c-sel"><input type="checkbox" ${E.seleccion.has(e.id) ? 'checked' : ''}></td>
      <td class="c-estado ${e.estado}" title="${e.estado}">${MARCA_ESTADO[e.estado]}</td>
      <td class="c-num">#${e.id}</td>
      <td class="c-tipo">${esc(e.tipo_etiqueta)}</td>
      <td class="c-desc">${esc(e.descripcion)}
        ${e.modificada ? '<span class="marca-mod" title="corregida a mano">◆</span>' : ''}
        ${(e.advertencias || []).length ? `<span class="aviso-adv" title="${esc((e.advertencias || []).join(', '))}">⚠</span>` : ''}</td>
      <td class="c-foja">${e.foja_inicio ? esc(e.foja_inicio) + (e.foja_fin && e.foja_fin !== e.foja_inicio ? '/' + esc(e.foja_fin) : '') : '—'}</td>
      <td class="c-pag">${e.pagina_inicio}${e.pagina_fin !== e.pagina_inicio ? '–' + e.pagina_fin : ''}</td>
      <td class="c-testigo ${e.testigo ? '' : 'falta'}">${esc(e.testigo) || 'sin asignar'}</td>
      <td class="c-conf"><span class="confianza ${e.confianza_nivel}">${e.confianza ?? 'mano'}</span></td>
    </tr>`).join('');

  $('#cuerpo-checklist').innerHTML = `
    <table class="check">
      <thead><tr>
        <th class="c-sel"><input type="checkbox" id="sel-todas"></th>
        <th></th><th>Nº</th><th>Tipo</th><th>Descripción</th><th>Foja</th>
        <th>Pág. PDF</th><th>Testigo</th><th>Conf.</th>
      </tr></thead>
      <tbody>${filas}</tbody>
    </table>
    <div class="solo-angosto">${E.evidencias.map(e => `
      <button class="ficha-ev" data-id="${e.id}">
        <div class="fe-cab"><span class="sello ${e.estado}">${e.estado}</span>
          <b>${esc(e.tipo_etiqueta)}</b></div>
        <div>${esc(e.descripcion)}</div>
        <div class="fe-meta"><span>fs. ${esc(e.foja_inicio) || '—'}</span>
          <span>pág. ${e.pagina_inicio}</span>
          <span>${esc(e.testigo) || 'sin testigo'}</span></div>
      </button>`).join('')}</div>
    <p class="pie-estado">${E.evidencias.length} de ${total} piezas mostradas</p>`;

  $$('#cuerpo-checklist tr.fila').forEach(tr => {
    tr.onclick = ev => {
      if (ev.target.type === 'checkbox') return;
      irARevision(Number(tr.dataset.id));
    };
    $('input', tr).onchange = e => {
      const id = Number(tr.dataset.id);
      e.target.checked ? E.seleccion.add(id) : E.seleccion.delete(id);
      tr.classList.toggle('elegida', e.target.checked);
      pintarLote();
    };
  });
  $$('#cuerpo-checklist .ficha-ev').forEach(b =>
    b.onclick = () => irARevision(Number(b.dataset.id)));
  const todas = $('#sel-todas');
  if (todas) todas.onchange = e => {
    E.seleccion = e.target.checked ? new Set(E.evidencias.map(x => x.id)) : new Set();
    pintarChecklistLista(total); pintarLote();
  };
  pintarLote();
}

function pintarChecklistGrupos() {
  const porGrupo = new Map();
  for (const e of E.evidencias) {
    const clave = e.grupo_id || 0;
    if (!porGrupo.has(clave)) porGrupo.set(clave, []);
    porGrupo.get(clave).push(e);
  }
  const bloques = E.grupos.map(g => {
    const piezas = porGrupo.get(g.id || 0) || [];
    return `<div class="grupo-bloque" data-grupo="${g.id ?? ''}">
      <div class="grupo-cab">
        <h3>${esc(g.nombre)}</h3>
        <div class="grupo-cuentas">
          <span style="color:var(--incluir)">${g.incluidas} ✓</span>
          <span style="color:var(--pendiente)">${g.pendientes} ○</span>
          <span style="color:var(--excluir)">${g.excluidas} ✕</span>
          <span class="tenue">${g.total} total</span>
        </div>
        ${g.id ? `<button class="mini" data-editar-grupo="${g.id}">Editar</button>` : ''}
      </div>
      <div class="grupo-cuerpo">${piezas.map(e => `
        <button class="ficha-ev" data-id="${e.id}">
          <div class="fe-cab"><span class="c-estado ${e.estado}">${MARCA_ESTADO[e.estado]}</span>
            <b>${esc(e.descripcion)}</b></div>
          <div class="fe-meta"><span>fs. ${esc(e.foja_inicio) || '—'}</span>
            <span>${esc(e.tipo_etiqueta)}</span>
            <span>${esc(e.testigo) || 'sin testigo'}</span></div>
        </button>`).join('') || '<p class="vacio" style="padding:8px">Sin piezas.</p>'}</div>
    </div>`;
  }).join('');

  $('#cuerpo-checklist').innerHTML = bloques +
    `<button class="boton" id="nuevo-grupo">+ Nuevo sector</button>`;
  $$('#cuerpo-checklist .ficha-ev').forEach(b =>
    b.onclick = () => irARevision(Number(b.dataset.id)));
  $('#nuevo-grupo').onclick = async () => {
    const d = await dialogo({
      titulo: 'Nuevo sector',
      ayuda: 'Un sector es un bloque del punteo. El <b>encabezado</b> es el texto que va ' +
             'en el escrito, que casi nunca es el nombre corto con el que se trabaja.',
      campos: [{ nombre: 'nombre', rotulo: 'Nombre', marcador: 'Banco de Entre Ríos' },
               { nombre: 'encabezado', rotulo: 'Encabezado en el escrito (opcional)',
                 marcador: 'EVIDENCIA REMITIDA POR EL NUEVO BANCO DE ENTRE RÍOS S.A.' }],
      aceptar: 'Crear',
    });
    if (!d) return;
    await escribir(() => api(`/api/caso/${E.caso.slug}/grupos`, { metodo: 'POST', cuerpo: d }));
    cargarChecklist();
  };
  $$('[data-editar-grupo]').forEach(b => b.onclick = async ev => {
    ev.stopPropagation();
    const g = E.grupos.find(x => x.id === Number(b.dataset.editarGrupo));
    const d = await dialogo({
      titulo: 'Editar sector',
      campos: [{ nombre: 'nombre', rotulo: 'Nombre', valor: g.nombre },
               { nombre: 'encabezado', rotulo: 'Encabezado en el escrito', valor: g.encabezado || '' }],
      aceptar: 'Guardar',
    });
    if (!d) return;
    await escribir(() => api(`/api/caso/${E.caso.slug}/grupo/${g.id}`, { metodo: 'PATCH', cuerpo: d }));
    cargarChecklist();
  });
}

function pintarLote() {
  const n = E.seleccion.size;
  $('#acciones-lote').hidden = !n;
  $('#lote-cuenta').textContent = `${n} elegidas`;
}

async function irARevision(id) {
  const i = E.evidencias.findIndex(x => x.id === id);
  mostrar('revision');
  await cargarPaginas();
  if (i >= 0) { E.indice = i; await abrirEvidencia(i); }
}

$$('#acciones-lote [data-lote]').forEach(b => b.onclick = async () => {
  await escribir(() => api(`/api/caso/${E.caso.slug}/evidencias/estado`,
    { metodo: 'POST', cuerpo: { ids: [...E.seleccion], estado: b.dataset.lote } }));
  E.seleccion.clear(); cargarChecklist();
});
$('#lote-unir').onclick = async () => {
  if (E.seleccion.size < 2) return avisar('Elegí al menos dos piezas para unir.', true);
  try {
    await escribir(() => api(`/api/caso/${E.caso.slug}/evidencias/unir`,
      { metodo: 'POST', cuerpo: { ids: [...E.seleccion] } }));
    avisar('Unidas. La pieza nueva queda pendiente y las partes se conservan.');
    E.seleccion.clear(); cargarChecklist();
  } catch { /* ya avisó */ }
};
$('#lote-grupo').onclick = async () => {
  const d = await dialogo({
    titulo: `Mover ${E.seleccion.size} piezas`,
    campos: [{ nombre: 'grupo_id', rotulo: 'Sector', tipo: 'select',
               opciones: [{ valor: '', texto: '— sin agrupar —' },
                          ...E.grupos.filter(g => g.id).map(g => ({ valor: String(g.id), texto: g.nombre }))] }],
    aceptar: 'Mover',
  });
  if (!d) return;
  await escribir(() => api(`/api/caso/${E.caso.slug}/evidencias/grupo`,
    { metodo: 'POST', cuerpo: { ids: [...E.seleccion], grupo_id: d.grupo_id ? Number(d.grupo_id) : null } }));
  E.seleccion.clear(); cargarChecklist();
};
$('#lote-testigo').onclick = async () => {
  const d = await dialogo({
    titulo: `Asignar testigo a ${E.seleccion.size} piezas`,
    ayuda: 'El policía que firmó el acta de procedimiento suele introducir también el ' +
           'acta de secuestro, las fotos y el croquis del mismo operativo.',
    campos: [{ nombre: 'nombre', rotulo: 'Nombre', marcador: 'APELLIDO, Nombre' }],
    aceptar: 'Asignar',
  });
  if (!d || !d.nombre) return;
  await escribir(() => api(`/api/caso/${E.caso.slug}/evidencias/testigo`,
    { metodo: 'POST', cuerpo: { ids: [...E.seleccion], nombre: d.nombre } }));
  E.seleccion.clear(); await refrescarPersonas(); cargarChecklist();
};

['#filtro-estado', '#filtro-orden'].forEach(s => $(s).addEventListener('change', cargarChecklist));
let filtroTimer;
$('#filtro-texto').addEventListener('input', () => {
  clearTimeout(filtroTimer); filtroTimer = setTimeout(cargarChecklist, 260);
});
$$('#vistas-check button').forEach(b => b.onclick = () => {
  E.modoCheck = b.dataset.modo;
  $$('#vistas-check button').forEach(x => x.classList.toggle('activo', x === b));
  if (E.modoCheck === 'cronologia') $('#filtro-orden').value = 'cronologico';
  cargarChecklist();
});

/* ═══════════════════════════════════════════════════════════════ TESTIGOS ══ */
async function cargarTestigos() {
  const solo = $('#testigos-solo-incluidas').checked ? '1' : '0';
  const { testigos } = await api(`/api/caso/${E.caso.slug}/testigos?solo_incluidas=${solo}`);
  $('#cuerpo-testigos').innerHTML = testigos.length ? testigos.map(t => `
    <div class="testigo-bloque ${t.id ? '' : 'sin-testigo'}">
      <div class="testigo-cab">
        <strong>${esc(t.nombre)}</strong>
        <span class="rol">${esc(t.detalle || (E.catalogo.roles || {})[t.rol] || '')}</span>
        <span class="espaciador"></span>
        <span class="mono tenue">${t.evidencias.length} piezas</span>
      </div>
      <ul class="testigo-lista">${t.evidencias.map(e => `
        <li><span class="c-estado ${e.estado}">${MARCA_ESTADO[e.estado]}</span>
            <button class="enlace" data-ev="${e.evidencia_id}">${esc(e.descripcion)}</button>
            <span class="tl-foja">fs. ${esc(e.foja_inicio) || '—'}${e.foja_fin && e.foja_fin !== e.foja_inicio ? '/' + esc(e.foja_fin) : ''}</span>
        </li>`).join('')}</ul>
    </div>`).join('') : '<p class="vacio">Todavía no hay testigos asignados.</p>';
  $$('#cuerpo-testigos [data-ev]').forEach(b =>
    b.onclick = () => irARevision(Number(b.dataset.ev)));

  const { fusiones } = await api(`/api/caso/${E.caso.slug}/personas`);
  $('#fusiones').innerHTML = fusiones.length ? `
    <div class="tarjeta">
      <h2>¿Son la misma persona?</h2>
      <p class="ayuda">El sistema propone; no fusiona solo. En un legajo penal decir que
        dos nombres son la misma persona es una afirmación, no una comodidad.</p>
      ${fusiones.map(f => `<div class="tramo">
        <b>${esc(f.a_nombre)}</b> <span class="tenue">y</span> <b>${esc(f.b_nombre)}</b>
        <span class="tenue">${esc(f.motivo)}</span>
        <span class="espaciador"></span>
        <button class="mini" data-fus="${f.id}" data-queda="${f.a_id}">Dejar «${esc(f.a_nombre)}»</button>
        <button class="mini" data-fus="${f.id}" data-queda="${f.b_id}">Dejar «${esc(f.b_nombre)}»</button>
        <button class="mini" data-no-fus="${f.id}">No son</button>
      </div>`).join('')}
    </div>` : '';
  $$('[data-fus]').forEach(b => b.onclick = async () => {
    await escribir(() => api(`/api/caso/${E.caso.slug}/fusiones`, { metodo: 'POST',
      cuerpo: { accion: 'aceptar', id: Number(b.dataset.fus), quedarse_con: Number(b.dataset.queda) } }));
    cargarTestigos();
  });
  $$('[data-no-fus]').forEach(b => b.onclick = async () => {
    await escribir(() => api(`/api/caso/${E.caso.slug}/fusiones`,
      { metodo: 'POST', cuerpo: { accion: 'rechazar', id: Number(b.dataset.noFus) } }));
    cargarTestigos();
  });
}
$('#testigos-solo-incluidas').addEventListener('change', cargarTestigos);

async function refrescarPersonas() {
  if (!E.caso) return;
  const { personas } = await api(`/api/caso/${E.caso.slug}/personas`);
  let lista = $('#lista-personas');
  if (!lista) {
    lista = document.createElement('datalist'); lista.id = 'lista-personas';
    document.body.appendChild(lista);
  }
  lista.innerHTML = personas.map(p => `<option value="${esc(p.nombre)}">`).join('');
}

async function refrescarGrupos() {
  const { grupos } = await api(`/api/caso/${E.caso.slug}/grupos`);
  E.grupos = grupos;
}

/* ═════════════════════════════════════════════════════════════════ PUNTEO ══ */
async function cargarPunteo() {
  const v = await api(`/api/caso/${E.caso.slug}/punteo/verificar`);
  const linea = (clase, n, texto) =>
    `<div class="chequeo-linea ${clase}"><span class="pastilla">${n}</span><span>${texto}</span></div>`;
  $('#tarjeta-verificar').innerHTML = `
    <h2>Antes de generar</h2>
    <div class="chequeo">
      ${linea(v.incluidas ? 'ok' : 'mal', v.incluidas, 'piezas marcadas para incluir')}
      ${v.pendientes ? linea('avisa', v.pendientes, 'piezas todavía pendientes de decisión') : ''}
      ${v.sin_foja.length ? linea('mal', v.sin_foja.length,
        'piezas incluidas <b>sin foja</b>: el escrito va a salir con un marcador visible') : ''}
      ${v.foja_sin_confirmar.length ? linea('avisa', v.foja_sin_confirmar.length,
        'piezas con foja detectada pero <b>sin confirmar</b>. Confirmá los tramos en <b>Legajo</b>.') : ''}
      ${v.sin_testigo.length ? linea('avisa', v.sin_testigo.length,
        'piezas incluidas <b>sin testigo introductor</b>') : ''}
      ${v.listo ? linea('ok', '✓', 'todo en orden') : ''}
    </div>`;
  $('#generar-punteo').disabled = !v.incluidas;
  try { pintarPunteo(await api(`/api/caso/${E.caso.slug}/punteo`)); }
  catch { $('#tarjeta-salida').hidden = true; }
}

$('#generar-punteo').onclick = async () => {
  try {
    const p = await escribir(() => api(`/api/caso/${E.caso.slug}/punteo`, {
      metodo: 'POST',
      cuerpo: { criterio: $('#punteo-criterio').value,
                con_encabezados: $('#punteo-encabezados').checked,
                numeracion: $('#punteo-numeracion').value,
                exigir_foja_confirmada: $('#punteo-exigir-foja').checked },
    }));
    pintarPunteo(p);
    avisar(`Punteo generado con ${p.total_piezas} piezas.`);
  } catch { /* ya avisó */ }
};

function pintarPunteo(p) {
  $('#tarjeta-salida').hidden = false;
  if (p.revalidacion && !p.revalidacion.al_dia) {
    avisar('El punteo quedó desactualizado: cambió alguna pieza desde que se generó. ' +
           'Volvé a generarlo antes de exportar.', true);
  }
  $('#punteo-salida').innerHTML = p.parrafos.map(pa => pa.clase === 'encabezado'
    ? `<div class="p-encabezado">${esc(pa.numero)} ${esc(pa.texto)}</div>`
    : `<div class="p-parrafo">
         <span class="p-numero">${esc(pa.numero)}</span>
         <div class="p-texto" contenteditable="plaintext-only" data-parrafo="${pa.id}"
              >${conMarcadores(pa.texto)}</div>
         ${pa.editado ? '<span class="p-editado" title="editado a mano">◆</span>' : ''}
       </div>`).join('');

  $$('#punteo-salida .p-texto').forEach(n => {
    n.addEventListener('blur', async () => {
      const nuevo = n.textContent.trim();
      const pa = p.parrafos.find(x => String(x.id) === n.dataset.parrafo);
      if (!pa || nuevo === (pa.texto || '').trim()) return;
      try {
        pintarPunteo(await escribir(() => api(
          `/api/caso/${E.caso.slug}/punteo/parrafo/${n.dataset.parrafo}`,
          { metodo: 'PATCH', cuerpo: { texto: nuevo } })));
      } catch { /* ya avisó */ }
    });
  });
}

$('#copiar').onclick = async () => {
  try {
    const r = await fetch(`/api/caso/${E.caso.slug}/punteo/exportar?formato=txt`);
    if (!r.ok) throw new Error((await r.json()).error);
    await navigator.clipboard.writeText(await r.text());
    avisar('Copiado al portapapeles.');
  } catch (e) { avisar(e.message || 'No se pudo copiar.', true); }
};
$$('[data-exportar]').forEach(b => b.onclick = async () => {
  const url = `/api/caso/${E.caso.slug}/punteo/exportar?formato=${b.dataset.exportar}`;
  const r = await fetch(url);
  if (!r.ok) return avisar((await r.json()).error, true);
  const blob = await r.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = (r.headers.get('Content-Disposition') || '').match(/filename="(.+?)"/)?.[1]
               || `punteo.${b.dataset.exportar}`;
  a.click();
  URL.revokeObjectURL(a.href);
});

/* ════════════════════════════════════════════════════════════════ BUSCADOR ══ */
function abrirBuscador() {
  $('#buscador').hidden = false;
  $('#buscador-campo').value = '';
  $('#buscador-resultados').innerHTML = '';
  $('#buscador-campo').focus();
}
$('#buscar-abrir').onclick = abrirBuscador;
$('#buscador-cerrar').onclick = () => { $('#buscador').hidden = true; };
let buscarTimer;
$('#buscador-campo').addEventListener('input', e => {
  clearTimeout(buscarTimer);
  const q = e.target.value.trim();
  if (q.length < 3) return;
  buscarTimer = setTimeout(async () => {
    const r = await api(`/api/caso/${E.caso.slug}/buscar?q=${encodeURIComponent(q)}`);
    $('#buscador-resultados').innerHTML = `
      ${r.evidencias.length ? `<h3>Piezas de evidencia</h3>${r.evidencias.map(e => `
        <button class="res" data-ev="${e.id}">
          <div class="res-ubi">#${e.id} · ${e.estado} · fs. ${esc(e.foja_inicio) || '—'}</div>
          <div>${esc(e.descripcion)}</div></button>`).join('')}` : ''}
      ${r.paginas.length ? `<h3>Dónde dice eso</h3>${r.paginas.map(p => `
        <button class="res" data-pag="${p.numero_global}">
          <div class="res-ubi">pág. ${p.numero_global}${p.foja ? ` · foja ${esc(p.foja)}` : ''}</div>
          <div class="res-frag">${esc(p.fragmento)}</div></button>`).join('')}` : ''}
      ${!r.paginas.length && !r.evidencias.length ? '<p class="vacio">Nada.</p>' : ''}`;
    $$('#buscador-resultados [data-ev]').forEach(b => b.onclick = () => {
      $('#buscador').hidden = true; irARevision(Number(b.dataset.ev));
    });
    $$('#buscador-resultados [data-pag]').forEach(b => b.onclick = () => {
      $('#buscador').hidden = true; mostrar('revision');
      setTimeout(() => irAPagina(Number(b.dataset.pag)), 60);
    });
  }, 280);
});

/* ═══════════════════════════════════════════════════════════════ TECLADO ══ */
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !$('#buscador').hidden) { $('#buscador').hidden = true; return; }
  // Nunca robar una tecla mientras alguien escribe: perder media descripción por
  // apretar la E es el tipo de cosa que hace abandonar una herramienta.
  const escribiendo = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)
                      || document.activeElement.isContentEditable;
  if (escribiendo || e.ctrlKey || e.metaKey || e.altKey) return;
  if (!E.caso) return;

  if (e.key.toLowerCase() === 'b') { e.preventDefault(); return abrirBuscador(); }
  if (E.vista !== 'revision') return;

  const teclas = { i: 'incluida', e: 'excluida', p: 'pendiente' };
  const estado = teclas[e.key.toLowerCase()];
  if (estado) { e.preventDefault(); return decidir(estado); }
  if (e.key === 'ArrowRight') { e.preventDefault(); return abrirEvidencia(E.indice + 1); }
  if (e.key === 'ArrowLeft')  { e.preventDefault(); return abrirEvidencia(E.indice - 1); }
  if (e.key === 'PageDown')   { e.preventDefault(); return irAPagina(E.pagina + 1); }
  if (e.key === 'PageUp')     { e.preventDefault(); return irAPagina(E.pagina - 1); }
  if (e.key.toLowerCase() === 'm') { e.preventDefault(); return $('#nueva-evidencia').click(); }
  if (e.key.toLowerCase() === 'f') { e.preventDefault(); return $('#campo-foja').select(); }
});

/* ═══════════════════════════════════════════════════════════════ ARRANQUE ══ */
$('#tema').onclick = () => {
  const actual = document.documentElement.dataset.tema;
  const nuevo = actual === 'oscuro' ? 'claro' : actual === 'claro' ? '' : 'oscuro';
  document.documentElement.dataset.tema = nuevo;
  try { localStorage.setItem('punteo-tema', nuevo); } catch { /* modo privado */ }
};
$('#ir-inicio').onclick = cerrarCaso;
$$('#nav button').forEach(b => b.onclick = () => mostrar(b.dataset.vista));

(async function arrancar() {
  try { document.documentElement.dataset.tema = localStorage.getItem('punteo-tema') || ''; }
  catch { /* sin localStorage se usa la preferencia del sistema */ }
  actualizarZoom();
  conectarCarga();
  E.catalogo = await api('/api/catalogo');
  const [, slug, vista] = (location.hash || '').split('/');
  if (slug) {
    try { await abrirCaso(slug, vista || 'legajo'); await refrescarPersonas(); return; }
    catch { /* el caso ya no existe: se cae al listado */ }
  }
  mostrar('casos');
})();
