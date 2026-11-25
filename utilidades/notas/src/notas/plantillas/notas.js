'use strict';
/* Página de Notas. Sin dependencias. Secciones:
   utilidades · API · avisos · estado y vistas · menú · rejilla · tarjeta · selección ·
   notas de voz (reproductor y grabadora) · editor · adjuntos · visor · categorías · arranque */

/* ---------- Utilidades ---------- */

const $ = (selector, raiz = document) => raiz.querySelector(selector);

const ICONOS = {
  menu: 'M4 6h16M4 12h16M4 18h16',
  lupa: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM16 16l4.5 4.5',
  agrupar: 'M3.500 18.500v-13h6l2 2.500h9v10.500z',
  lista: 'M4 6h16v4H4zM4 14h16v4H4z',
  tema: 'M12 4a8 8 0 1 0 8 8 6 6 0 0 1-8-8z',
  cerrar: 'M6 6l12 12M18 6L6 18',
  lapiz: 'M4 20l1-4L16 5l3 3L8 19zM14 7l3 3',
  descargar: 'M12 4v11M7.5 11l4.5 4.5 4.5-4.5M5 20h14',
  imagen: 'M4 5h16v14H4zM4 16l5-5 4 4 2.5-2.5L20 17M15.5 9.2h.01',
  micro: 'M12 3.5a2.8 2.8 0 0 1 2.8 2.8v5a2.8 2.8 0 0 1-5.6 0v-5A2.8 2.8 0 0 1 12 3.5zM6 11a6 6 0 0 0 12 0M12 17v3.5M9 20.5h6',
  chincheta: 'M9 4h6l-.7 6 2.7 3H7l2.7-3zM12 13v7',
  paleta: 'M12 4a8 8 0 1 0 0 16c1.6 0 1.8-1.2 1.2-2.2-.7-1.2.1-2.3 1.5-2.3H17a3 3 0 0 0 3-3C20 7.600 16.400 4 12 4zM8 11h.01M10.500 7.800h.01M14.500 8h.01',
  archivo: 'M4 5h16v4H4zM5.500 9v10h13V9M10 13h4',
  desarchivar: 'M4 5h16v4H4zM5.500 9v10h13V9M12 17v-5M9.500 14l2.500-2.500 2.500 2.500',
  papelera: 'M5 7h14M9 7V4.500h6V7M7 7l1 12.500h8L17 7M10.500 10.500v5.500M13.500 10.500v5.500',
  restaurar: 'M5 12a7 7 0 1 0 2.200-5.100M5 4v4.500h4.500',
  eliminar: 'M5 7h14M9 7V4.500h6V7M7 7l1 12.500h8L17 7M10 11l4 5M14 11l-4 5',
  etiqueta: 'M4 4h8l8 8-8 8-8-8zM8 8h.01',
  nota: 'M5 4h14v11l-5 5H5zM14 20v-5h5',
  texto: 'M5 6h14M5 11h14M5 16h9',
  casillas: 'M4 4.500h5v5H4zM4 14.500l2 2 3.500-4M13 7h7M13 16h7',
  enlace: 'M10 14a4 4 0 0 0 5.700 0l3-3a4 4 0 0 0-5.700-5.700l-1 1M14 10a4 4 0 0 0-5.700 0l-3 3a4 4 0 0 0 5.700 5.700l1-1',
  marcar: 'M5 12.500l4.500 4.500L19 7.500',
  tocar: 'M8 5.500v13l10.500-6.500z',
  pausa: 'M8 5.500v13M16 5.500v13',
  pausaLlena: 'M7 5.500h3.600v13H7zM13.400 5.500H17v13h-3.600z',
  izquierda: 'M14.500 5.500L8 12l6.500 6.500',
  derecha: 'M9.500 5.500L16 12l-6.500 6.500',
};

function icono(nombre) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  const trazo = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  trazo.setAttribute('d', ICONOS[nombre]);
  svg.append(trazo);
  return svg;
}

/** Elemento con atributos (`texto`, `class`, `onclick`…) e hijos. Nunca interpreta HTML. */
function el(etiqueta, atributos = {}, ...hijos) {
  const e = document.createElement(etiqueta);
  for (const [clave, valor] of Object.entries(atributos)) {
    if (valor == null || valor === false) continue;
    if (clave.startsWith('on')) e.addEventListener(clave.slice(2), valor);
    else if (clave === 'texto') e.textContent = valor;
    else e.setAttribute(clave, valor === true ? '' : valor);
  }
  e.append(...hijos.flat().filter(h => h != null && h !== false));
  return e;
}

const boton = (nombre, titulo, alPulsar, clase = '') =>
  el('button', { class: `ico ${clase}`, type: 'button', title: titulo, 'aria-label': titulo, onclick: alPulsar }, icono(nombre));

const memoria = {                       // preferencias de este navegador
  leer(clave, defecto) { try { return localStorage.getItem('notas.' + clave) ?? defecto; } catch { return defecto; } },
  guardar(clave, valor) { try { localStorage.setItem('notas.' + clave, valor); } catch { /* sin almacenamiento */ } },
};

/** Para comparar nombres como el servidor: sin mayúsculas ni acentos. */
const sinAcentos = texto => texto.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().trim();
const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
const tiempo = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const peso = b => b >= 1e6 ? `${(b / 1e6).toFixed(1).replace('.', ',')} MB` : `${Math.max(1, Math.round(b / 1e3))} KB`;
const fechaLarga = iso => new Date(iso).toLocaleString('es-ES', { dateStyle: 'long', timeStyle: 'short' });

function fechaCorta(iso) {
  const f = new Date(iso), hoy = new Date();
  if (f.toDateString() === hoy.toDateString()) return f.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
  return f.toLocaleDateString('es-ES', { day: 'numeric', month: 'short', year: f.getFullYear() === hoy.getFullYear() ? undefined : 'numeric' });
}

/** Texto con los enlaces pulsables, sin interpretar nada más. */
function conEnlaces(texto) {
  const trozos = [];
  let fin = 0;
  for (const m of texto.matchAll(/\bhttps?:\/\/[^\s<>"«»]+/g)) {
    const url = m[0].replace(/[.,;:!?)\]}'…]+$/, '');
    trozos.push(texto.slice(fin, m.index),
      el('a', { href: url, target: '_blank', rel: 'noopener noreferrer', texto: url, onclick: e => e.stopPropagation() }));
    fin = m.index + url.length;
  }
  trozos.push(texto.slice(fin));
  return trozos;
}

/** Como `conEnlaces`, con las casillas hechas (☑) tachadas. */
function conCasillas(texto) {
  if (!/^[☐☑]/m.test(texto)) return conEnlaces(texto);
  return texto.split('\n').flatMap((linea, i) => [i ? '\n' : '',
    el('span', { class: linea.startsWith('☑') ? 'hecha' : null }, conEnlaces(linea))]);
}

/** Los enlaces que traía una nota importada, con el título de la página. */
function enlacesDe(nota, maximo = Infinity) {
  return (nota.detalles.enlaces || []).filter(e => /^https?:\/\//.test(e.url)).slice(0, maximo).map(e =>
    el('a', { class: 'enlace', href: e.url, target: '_blank', rel: 'noopener noreferrer',
              title: [e.descripcion, e.url].filter(Boolean).join('\n'), onclick: x => x.stopPropagation() },
      icono('enlace'), el('span', {}, el('b', { texto: e.titulo || e.url }),
        el('small', { texto: e.url.replace(/^https?:\/\/(www\.)?/, '').split(/[/?#]/)[0] }))));
}

/* ---------- API ---------- */

class ErrorApi extends Error {
  constructor(mensaje, estado, datos = {}) { super(mensaje); this.estado = estado; this.datos = datos; }
}

let token = '';

async function pedir(metodo, ruta, cuerpo, cabeceras = {}) {
  for (let intento = 0; ; intento++) {
    const opciones = { method: metodo, headers: { ...cabeceras } };
    if (metodo !== 'GET') opciones.headers['X-Notas-Token'] = token;
    if (cuerpo instanceof Blob) opciones.body = cuerpo;
    else if (metodo === 'POST' || metodo === 'PATCH') {
      opciones.headers['Content-Type'] = 'application/json';
      opciones.body = JSON.stringify(cuerpo ?? {});
    }
    let respuesta;
    try {
      respuesta = await fetch(ruta, opciones);
    } catch {
      throw new ErrorApi('No hay conexión con Notas. ¿Sigue abierto el programa?', 0);
    }
    const datos = await respuesta.json().catch(() => ({}));
    if (respuesta.ok) return datos;
    if (datos.codigo === 'token' && intento === 0) {   // se ha reiniciado el programa
      token = (await pedir('GET', '/api/estado')).token;
      continue;
    }
    throw new ErrorApi(datos.error || `Error ${respuesta.status}`, respuesta.status, datos);
  }
}

/** Ejecuta una acción y enseña su error, si lo hay. Devuelve true si ha ido bien. */
async function intentar(accion) {
  try { await accion(); return true; } catch (error) { aviso(error.message, { error: true }); return false; }
}

/* ---------- Avisos y preguntas ---------- */

/** El diálogo abierto más arriba: lo de fuera no se puede pulsar mientras está abierto. */
const dialogoAbierto = () => [...document.querySelectorAll('dialog[open]')].pop();

function aviso(texto, { error = false, accion = null, alPulsar = null } = {}) {
  const zona = $('#avisos');
  (dialogoAbierto() || document.body).append(zona);
  const caja = el('div', { class: error ? 'aviso error' : 'aviso' }, el('span', { texto }));
  if (accion) caja.append(el('button', { type: 'button', texto: accion, onclick: () => { caja.remove(); alPulsar(); } }));
  zona.append(caja);
  while (zona.children.length > 3) zona.firstChild.remove();
  setTimeout(() => caja.remove(), accion || error ? 8000 : 3500);
}

function preguntar({ titulo, texto = '', aceptar = 'Aceptar', peligro = false }) {
  const d = $('#d-pregunta');
  $('#pr-titulo').textContent = titulo;
  $('#pr-texto').textContent = texto;
  $('#pr-si').textContent = aceptar;
  $('#pr-si').className = `boton ${peligro ? 'peligro' : 'principal'}`;
  return new Promise(resolver => {
    const fin = valor => { resolver(valor); d.close(); };
    $('#pr-si').onclick = () => fin(true);
    $('#pr-no').onclick = () => fin(false);
    d.onclose = () => resolver(false);        // también con Escape
    d.showModal();
    $('#pr-no').focus();
  });
}

/* ---------- Estado y vistas ---------- */

const app = {
  notas: [], categorias: [], totales: {}, colores: [], maxAdjunto: Infinity,
  vista: { clave: 'notas' }, buscar: '', elegidas: new Set(),
  orden: memoria.leer('orden', 'modificada'),
  agrupar: memoria.leer('agrupar', '') === '1',
  lista: memoria.leer('lista', '') === '1',
};

const TIPOS = { texto: 'Solo texto', lista: 'Listas', imagen: 'Con imágenes', voz: 'Notas de voz' };

/** La vista va en la dirección (#categoria=3, #papelera…): se puede recargar o ir atrás. */
function leerVista() {
  const [clave, valor] = decodeURIComponent(location.hash.slice(1)).split('=');
  if (['archivo', 'papelera', 'sin-categoria'].includes(clave)) return { clave };
  if (clave === 'categoria' && /^\d+$/.test(valor)) return { clave, valor: Number(valor) };
  if (clave === 'tipo' && TIPOS[valor]) return { clave, valor };
  return { clave: 'notas' };
}

function nombreVista() {
  const { clave, valor } = app.vista;
  if (clave === 'archivo') return 'Archivo';
  if (clave === 'papelera') return 'Papelera';
  if (clave === 'sin-categoria') return 'Sin categoría';
  if (clave === 'tipo') return TIPOS[valor];
  if (clave === 'categoria') return app.categorias.find(c => c.id === valor)?.nombre || 'Categoría';
  return 'Todas las notas';
}

let turno = 0;
async function cargar() {
  const mio = ++turno;
  const { clave, valor } = app.vista;
  const consulta = new URLSearchParams({ orden: app.orden });
  // Al buscar se mira también en el archivo, salvo que ya se esté en él o en la papelera
  consulta.set('vista', clave === 'papelera' ? 'papelera' : clave === 'archivo' ? 'archivadas'
    : app.buscar ? 'todas' : 'activas');
  if (app.buscar) consulta.set('buscar', app.buscar);
  if (clave === 'categoria') consulta.set('categoria', valor);
  if (clave === 'sin-categoria') consulta.set('categoria', 0);
  if (clave === 'tipo') consulta.set('tipo', valor);
  try {
    const [lista, estado] = await Promise.all([pedir('GET', '/api/notas?' + consulta), pedir('GET', '/api/estado')]);
    if (mio !== turno) return;            // ya se ha pedido otra cosa
    token = estado.token;
    Object.assign(app, { notas: lista.notas, categorias: estado.categorias, totales: estado.totales,
                         colores: estado.colores, maxAdjunto: estado.max_adjunto });
    if (clave === 'categoria' && !app.categorias.some(c => c.id === valor)) { location.hash = ''; return; }
    $('#donde').textContent = `Se guardan en ${estado.cuaderno}`;
    const visibles = new Set(app.notas.map(n => n.id));
    app.elegidas.forEach(id => visibles.has(id) || app.elegidas.delete(id));
    pintarMenu();
    pintar();
  } catch (error) {
    if (mio === turno) aviso(error.message, { error: true });
  }
}

/** Acción sobre varias notas, con «Deshacer» si se da cómo. */
async function lote(ids, accion, valor = null, texto = '', deshacer = null) {
  if (!await intentar(() => pedir('POST', '/api/lote', { ids: [...ids], accion, valor }))) return;
  app.elegidas.clear();
  await cargar();
  if (texto) aviso(texto, deshacer ? { accion: 'Deshacer', alPulsar: deshacer } : {});
}

const aPapelera = ids => lote(ids, 'papelera', null,
  ids.length === 1 ? 'Nota en la papelera' : `${ids.length} notas en la papelera`, () => lote(ids, 'restaurar'));

const desarchivar = ids => lote(ids, 'desarchivar', null,
  ids.length === 1 ? 'Nota fuera del archivo' : `${ids.length} notas fuera del archivo`, () => lote(ids, 'archivar'));

const restaurar = ids => lote(ids, 'restaurar', null,
  ids.length === 1 ? 'Nota restaurada' : `${ids.length} notas restauradas`);

function archivar(ids) {
  // Archivar suelta las fijadas: al deshacer se vuelven a fijar (y eso ya las desarchiva)
  const fijadas = app.notas.filter(n => n.fijada && ids.includes(n.id)).map(n => n.id);
  return lote(ids, 'archivar', null, ids.length === 1 ? 'Nota archivada' : `${ids.length} notas archivadas`, async () => {
    await lote(ids, 'desarchivar');
    if (fijadas.length) await lote(fijadas, 'fijar');
  });
}

async function eliminar(ids) {
  const si = await preguntar({
    titulo: ids.length === 1 ? '¿Eliminar esta nota para siempre?' : `¿Eliminar ${ids.length} notas para siempre?`,
    texto: 'Se borran también sus imágenes y notas de voz. No se puede deshacer.', aceptar: 'Eliminar', peligro: true });
  if (si) await lote(ids, 'eliminar', null, ids.length === 1 ? 'Nota eliminada' : `${ids.length} notas eliminadas`);
  return si;
}

/* ---------- Menú ---------- */

function pintarMenu() {
  const t = app.totales, { clave, valor } = app.vista;
  const enlace = (href, ico, texto, n, actual) => el('a', { href, 'aria-current': actual ? 'page' : null },
    icono(ico), el('span', { texto }), n ? el('span', { class: 'n', texto: n }) : null);
  $('#menu-vistas').replaceChildren(
    enlace('#', 'nota', 'Todas', t.activas, clave === 'notas'),
    enlace('#tipo=texto', 'texto', TIPOS.texto, t.texto, valor === 'texto'),
    enlace('#tipo=lista', 'casillas', TIPOS.lista, t.lista, valor === 'lista'),
    enlace('#tipo=imagen', 'imagen', TIPOS.imagen, t.imagen, valor === 'imagen'),
    enlace('#tipo=voz', 'micro', TIPOS.voz, t.voz, valor === 'voz'),
    enlace('#archivo', 'archivo', 'Archivo', t.archivadas, clave === 'archivo'),
    enlace('#papelera', 'papelera', 'Papelera', t.papelera, clave === 'papelera'));
  const categorias = app.categorias.map(c =>
    enlace(`#categoria=${c.id}`, 'etiqueta', c.nombre, c.total, clave === 'categoria' && valor === c.id));
  if (categorias.length && t.sin_categoria)
    categorias.push(enlace('#sin-categoria', 'etiqueta', 'Sin categoría', t.sin_categoria, clave === 'sin-categoria'));
  $('#menu-categorias').replaceChildren(...(categorias.length ? categorias
    : [el('p', { class: 'menu-vacio', texto: 'Aún no hay ninguna. Se crean al ponérselas a una nota.' })]));
  $('#lista-categorias').replaceChildren(...app.categorias.map(c => el('option', { value: c.nombre })));
}

/* ---------- Rejilla ---------- */

const POR_TANDA = 60;
const rejilla = { cola: [], hechas: 0, seccion: null, columnas: [], nColumnas: 0 };

/** Pinta la siguiente tanda al acercarse al final de la página. */
const vigia = new IntersectionObserver(entradas => {
  if (entradas.some(x => x.isIntersecting) && rejilla.hechas < rejilla.cola.length) { pintarMas(); vigilar(); }
}, { rootMargin: '600px' });

/** Solo avisa de los cambios: se vuelve a observar por si el final sigue a la vista. */
function vigilar() {
  vigia.unobserve($('#centinela'));
  vigia.observe($('#centinela'));
}

/** [(título de sección, notas)] según la vista: categorías, fijadas/otras o archivadas al buscar. */
function secciones() {
  const { clave } = app.vista;
  if (clave === 'papelera' || clave === 'archivo') return [['', app.notas]];
  if (app.agrupar && clave !== 'categoria' && clave !== 'sin-categoria') {
    const grupos = app.categorias.map(c => [c.nombre, app.notas.filter(n => n.categorias.some(x => x.id === c.id))]);
    grupos.push(['Sin categoría', app.notas.filter(n => !n.categorias.length)]);
    return grupos.filter(([, notas]) => notas.length);
  }
  const fijadas = app.notas.filter(n => n.fijada);
  const otras = app.notas.filter(n => !n.fijada && !n.archivada);
  const archivadas = app.notas.filter(n => n.archivada);
  const varias = [fijadas, otras, archivadas].filter(x => x.length).length > 1;
  return [['Fijadas', fijadas], ['Otras', otras], ['Archivadas', archivadas]]
    .filter(([, notas]) => notas.length)
    .map(([titulo, notas]) => [varias || titulo !== 'Otras' ? titulo : '', notas]);
}

function columnasQueCaben() {
  return app.lista ? 1 : Math.max(1, Math.floor(($('#notas').clientWidth + 14) / 254));
}

function pintar() {
  const { clave } = app.vista;
  document.body.classList.toggle('en-lista', app.lista);
  $('#titulo-vista').textContent = app.buscar ? `${nombreVista()}: «${app.buscar}»` : nombreVista();
  $('#cuantas').textContent = plural(app.notas.length, 'nota', 'notas');
  document.title = clave === 'notas' ? 'Notas' : `${nombreVista()} · Notas`;
  $('#componer').hidden = clave === 'papelera' || clave === 'archivo';
  $('#b-vaciar').hidden = clave !== 'papelera' || !app.notas.length || Boolean(app.buscar);
  $('#vacio').hidden = app.notas.length > 0;
  $('#vacio').textContent = app.buscar ? 'Nada coincide con la búsqueda.'
    : clave === 'papelera' ? 'La papelera está vacía.'
    : clave === 'archivo' ? 'No hay notas archivadas.'
    : clave === 'notas' ? 'Todavía no hay notas.\nEscribe una, graba tu voz o suelta aquí una imagen.'
    : 'No hay notas aquí.';

  const altura = window.scrollY, antes = rejilla.hechas;
  rejilla.cola = secciones().flatMap(([titulo, notas], i) => notas.map(nota => ({ seccion: i, titulo, nota })));
  Object.assign(rejilla, { hechas: 0, seccion: null, columnas: [], nColumnas: columnasQueCaben() });
  $('#notas').replaceChildren();
  pintarMas(Math.max(POR_TANDA, antes));
  window.scrollTo(0, altura);
  vigilar();
  pintarSeleccion();
  if (sonando && !sonando.isConnected) sonando.pause();
}

function pintarMas(n = POR_TANDA) {
  const hasta = Math.min(rejilla.cola.length, rejilla.hechas + n);
  for (; rejilla.hechas < hasta; rejilla.hechas++) {
    const { seccion, titulo, nota } = rejilla.cola[rejilla.hechas];
    if (seccion !== rejilla.seccion) {
      rejilla.seccion = seccion;
      rejilla.columnas = Array.from({ length: rejilla.nColumnas }, () => el('div', { class: 'columna' }));
      $('#notas').append(el('section', { class: 'seccion' },
        titulo ? el('h2', { texto: titulo }) : null, el('div', { class: 'columnas' }, rejilla.columnas)));
    }
    const menor = rejilla.columnas.reduce((a, b) => (b.offsetHeight < a.offsetHeight ? b : a));
    menor.append(tarjeta(nota));
  }
}

/* ---------- Tarjeta ---------- */

function tarjeta(n) {
  const enPapelera = Boolean(n.papelera);
  const imagenes = n.adjuntos.filter(a => a.tipo === 'imagen');
  const voces = n.adjuntos.filter(a => a.tipo === 'voz');
  const dentro = el('div', { class: 'dentro' });
  if (n.titulo) dentro.append(el('h3', { texto: n.titulo }));
  if (n.texto.trim()) {
    const corta = !n.titulo && !n.adjuntos.length && n.texto.length < 60;
    dentro.append(el('p', { class: corta ? 'corta' : null }, conCasillas(n.texto.slice(0, 1500).trimEnd())));
  }
  dentro.append(...enlacesDe(n, 2));
  dentro.append(...voces.slice(0, 3).map(a => reproductor(a)));
  if (voces.length > 3) dentro.append(el('p', { texto: `y ${plural(voces.length - 3, 'nota', 'notas')} de voz más` }));
  if (!n.titulo && !n.texto.trim() && !n.adjuntos.length) dentro.append(el('p', { class: 'vacia', texto: 'Nota vacía' }));
  if (n.categorias.length) dentro.append(el('div', { class: 'chips' },
    n.categorias.map(c => el('a', { class: 'chip', href: `#categoria=${c.id}`, texto: c.nombre, onclick: e => e.stopPropagation() }))));

  const pie = el('div', { class: 'pie' },
    el('time', { datetime: n.modificada, title: `Modificada: ${fechaLarga(n.modificada)}\nCreada: ${fechaLarga(n.creada)}`,
                 texto: (n.archivada && app.buscar ? 'Archivada · ' : '') + fechaCorta(enPapelera ? n.papelera : n.modificada) }),
    boton('marcar', 'Elegir', sin(e => alternarEleccion(n.id, e)), 'elegir'),
    enPapelera ? [boton('restaurar', 'Restaurar', sin(() => restaurar([n.id]))),
                  boton('eliminar', 'Eliminar para siempre', sin(() => eliminar([n.id])))]
      : [n.archivada ? boton('desarchivar', 'Sacar del archivo', sin(() => desarchivar([n.id])))
                     : boton('archivo', 'Archivar', sin(() => archivar([n.id]))),
         boton('papelera', 'Mandar a la papelera', sin(() => aPapelera([n.id])))]);

  const fijar = enPapelera ? null : boton('chincheta', n.fijada ? 'Soltar' : 'Fijar arriba',
    sin(() => lote([n.id], n.fijada ? 'soltar' : 'fijar')), 'fijar');
  fijar?.setAttribute('aria-pressed', n.fijada);

  return el('article', {
    class: `tarjeta${n.color ? ` color-${n.color}` : ''}`, tabindex: 0, 'data-id': n.id,
    'aria-label': n.titulo || n.texto.slice(0, 80) || 'Nota',
    onclick: e => (app.elegidas.size ? alternarEleccion(n.id, e) : abrirEditor(n)),
    onkeydown: e => {
      if (e.target !== e.currentTarget) return;
      if (e.key === 'Enter') { e.preventDefault(); abrirEditor(n); }
      else if (e.key === ' ' || e.key === 'x') { e.preventDefault(); alternarEleccion(n.id, e); }
      else if (e.key === 'Delete' && !enPapelera) aPapelera([n.id]);
    },
  }, mosaico(imagenes, 4), fijar, dentro, pie);
}

/** Manejador que no deja que el clic abra la nota. */
const sin = funcion => e => { e.stopPropagation(); funcion(e); };

function mosaico(imagenes, maximo = Infinity) {
  if (!imagenes.length) return null;
  return el('div', { class: 'mosaico' }, imagenes.slice(0, maximo).map((a, i) =>
    el('button', { type: 'button', 'aria-label': `Ver ${a.nombre}`, onclick: sin(() => abrirVisor(imagenes, i)) },
      imagenDe(a),
      i === maximo - 1 && imagenes.length > maximo ? el('span', { class: 'mas', texto: `+${imagenes.length - maximo + 1}` }) : null)));
}

function imagenDe(a) {
  const img = el('img', { src: a.miniatura, alt: a.nombre, loading: 'lazy' });
  // Con las medidas, la tarjeta ya tiene su altura antes de que llegue la imagen
  if (a.ancho && a.alto) { img.width = a.ancho; img.height = a.alto; img.style.aspectRatio = `${a.ancho} / ${a.alto}`; }
  return img;
}

/* ---------- Selección ---------- */

let ultimaElegida = null;

function alternarEleccion(id, evento) {
  if (evento?.shiftKey && ultimaElegida !== null) {        // de la última a esta
    const ids = rejilla.cola.map(x => x.nota.id);
    const [a, b] = [ids.indexOf(ultimaElegida), ids.indexOf(id)].sort((x, y) => x - y);
    if (a >= 0) ids.slice(a, b + 1).forEach(x => app.elegidas.add(x));
  } else if (!app.elegidas.delete(id)) app.elegidas.add(id);
  ultimaElegida = id;
  pintarSeleccion();
}

function pintarSeleccion() {
  const n = app.elegidas.size, ids = () => [...app.elegidas], { clave } = app.vista;
  document.body.classList.toggle('eligiendo', n > 0);
  $('#seleccion').hidden = !n;
  document.querySelectorAll('.tarjeta').forEach(t => t.classList.toggle('elegida', app.elegidas.has(Number(t.dataset.id))));
  if (!n) return;
  $('#s-cuantas').textContent = plural(n, 'elegida', 'elegidas');
  const elegidas = app.notas.filter(x => app.elegidas.has(x.id));
  const todasFijadas = elegidas.every(x => x.fijada);
  $('#s-acciones').replaceChildren(...(clave === 'papelera' ? [
    boton('restaurar', 'Restaurar', () => restaurar(ids())),
    boton('eliminar', 'Eliminar para siempre', () => eliminar(ids())),
  ] : [
    boton('chincheta', todasFijadas ? 'Soltar' : 'Fijar arriba', () => lote(ids(), todasFijadas ? 'soltar' : 'fijar')),
    boton('etiqueta', 'Poner categoría', () => ponerCategoria(ids())),
    clave === 'categoria' ? boton('cerrar', `Quitar de «${nombreVista()}»`, () =>
      quitarCategoria(ids(), nombreVista())) : null,
    clave === 'archivo' ? boton('desarchivar', 'Sacar del archivo', () => desarchivar(ids()))
                        : boton('archivo', 'Archivar', () => archivar(ids())),
    boton('papelera', 'Mandar a la papelera', () => aPapelera(ids())),
  ]).filter(Boolean));
}

/* ---------- Notas de voz: reproductor ---------- */

let sonando = null;
const VELOCIDADES = [1, 1.5, 2];

/** Reproductor compacto. El audio no se descarga hasta que se pulsa. */
function reproductor(a) {
  const audio = el('audio', { preload: 'none', src: a.url });
  const barra = el('input', { type: 'range', min: 0, max: 1000, value: 0, 'aria-label': 'Posición', onclick: e => e.stopPropagation() });
  const reloj = el('span', { class: 'tiempo', texto: a.duracion ? tiempo(a.duracion) : '·:··' });
  const tocar = boton('tocar', 'Escuchar', sin(alternar), 'tocar');
  const velocidad = el('button', { class: 'vel', type: 'button', title: 'Velocidad', texto: '1×', onclick: sin(() => {
    audio.playbackRate = VELOCIDADES[(VELOCIDADES.indexOf(audio.playbackRate) + 1) % VELOCIDADES.length];
    velocidad.textContent = `${String(audio.playbackRate).replace('.', ',')}×`;
  }) });
  const caja = el('div', { class: 'voz', onclick: e => e.stopPropagation() }, tocar, barra, reloj, velocidad, audio);

  const duracion = () => (Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : a.duracion || 0);
  const pintarReloj = () => {
    const total = duracion();
    barra.value = total ? Math.round(audio.currentTime / total * 1000) : 0;
    reloj.textContent = audio.currentTime > 0 ? `${tiempo(audio.currentTime)} / ${tiempo(total)}` : tiempo(total);
  };
  async function alternar() {
    if (!audio.paused) return audio.pause();
    if (sonando && sonando !== audio) sonando.pause();
    sonando = audio;
    try { await audio.play(); } catch (error) {
      if (error.name !== 'AbortError') { caja.classList.add('rota'); reloj.textContent = 'no se puede reproducir'; }
    }
  }
  audio.addEventListener('play', () => { tocar.replaceChildren(icono('pausaLlena')); tocar.setAttribute('aria-label', 'Pausar'); });
  audio.addEventListener('pause', () => { tocar.replaceChildren(icono('tocar')); tocar.setAttribute('aria-label', 'Escuchar'); });
  audio.addEventListener('timeupdate', pintarReloj);
  audio.addEventListener('durationchange', pintarReloj);
  audio.addEventListener('ended', () => { audio.currentTime = 0; pintarReloj(); });
  barra.addEventListener('input', () => {
    const total = duracion();
    if (total) audio.currentTime = barra.value / 1000 * total;
  });
  return caja;
}

/** Duración de un audio elegido o soltado (0 si el navegador no la sabe). */
function medirDuracion(archivo) {
  return new Promise(resolver => {
    const url = URL.createObjectURL(archivo), audio = new Audio();
    const fin = valor => { URL.revokeObjectURL(url); resolver(Number.isFinite(valor) ? valor : 0); };
    setTimeout(() => fin(0), 3000);
    audio.onloadedmetadata = () => fin(audio.duration);
    audio.onerror = () => fin(0);
    audio.preload = 'metadata';
    audio.src = url;
  });
}

/* ---------- Notas de voz: grabadora ---------- */

const grabadora = { mr: null, flujo: null, contexto: null, trozos: [], acumulado: 0, desde: 0, cuadro: 0, fin: null };
const TIPOS_GRABACION = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'];
const ERRORES_MICRO = {
  NotAllowedError: 'El navegador no tiene permiso para usar el micrófono. Permítelo en el icono de la barra de direcciones.',
  NotFoundError: 'No se ha encontrado ningún micrófono en este equipo.',
  NotReadableError: 'Otro programa está usando el micrófono.',
};

const grabando = () => grabadora.mr !== null;
const segundosGrabados = () => (grabadora.acumulado + (grabadora.desde ? performance.now() - grabadora.desde : 0)) / 1000;

async function grabar() {
  if (grabando()) return;
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
    return aviso('Este navegador no puede grabar audio.', { error: true });
  let flujo;
  try {
    flujo = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  } catch (error) {
    return aviso(ERRORES_MICRO[error.name] || `No se puede grabar: ${error.message}`, { error: true });
  }
  if (!$('#editor').open) abrirEditor(null);
  sonando?.pause();
  const tipo = TIPOS_GRABACION.find(t => MediaRecorder.isTypeSupported(t));
  const mr = new MediaRecorder(flujo, tipo ? { mimeType: tipo, audioBitsPerSecond: 48000 } : undefined);
  Object.assign(grabadora, { mr, flujo, trozos: [], acumulado: 0, desde: performance.now() });
  mr.ondataavailable = e => { if (e.data.size) grabadora.trozos.push(e.data); };
  mr.onerror = () => terminarGrabacion();
  flujo.getAudioTracks()[0].onended = () => terminarGrabacion();      // micrófono desconectado
  mr.start(1000);
  $('#e-grabadora').hidden = false;
  $('#e-grabadora').classList.remove('pausada');
  $('#g-pausa').replaceChildren(icono('pausa'));
  $('#e-voz').setAttribute('aria-pressed', 'true');
  dibujarNivel(flujo);
  $('#g-listo').focus();
}

function dibujarNivel(flujo) {
  const lienzo = $('#g-nivel'), ctx = lienzo.getContext('2d');
  const contexto = grabadora.contexto = new AudioContext();
  const analizador = contexto.createAnalyser();
  analizador.fftSize = 512;
  contexto.createMediaStreamSource(flujo).connect(analizador);
  const muestras = new Uint8Array(analizador.fftSize), niveles = [];
  let ultimo = 0;
  const cuadro = ahora => {
    if (!grabando()) return;
    grabadora.cuadro = requestAnimationFrame(cuadro);
    $('#g-tiempo').textContent = tiempo(segundosGrabados());
    if (ahora - ultimo < 60 || grabadora.mr.state !== 'recording') return;
    ultimo = ahora;
    analizador.getByteTimeDomainData(muestras);
    niveles.push(Math.max(...muestras.map(m => Math.abs(m - 128))) / 128);
    const barras = Math.floor(lienzo.width / 6);
    if (niveles.length > barras) niveles.shift();
    ctx.clearRect(0, 0, lienzo.width, lienzo.height);
    ctx.fillStyle = getComputedStyle(lienzo).color;
    niveles.forEach((nivel, i) => {
      const alto = Math.max(3, Math.min(1, nivel * 1.6) * lienzo.height);
      ctx.fillRect(i * 6, (lienzo.height - alto) / 2, 3.5, alto);
    });
  };
  grabadora.cuadro = requestAnimationFrame(cuadro);
}

function pausarGrabacion() {
  const { mr } = grabadora;
  if (!mr) return;
  if (mr.state === 'recording') {
    mr.pause();
    grabadora.acumulado += performance.now() - grabadora.desde;
    grabadora.desde = 0;
  } else {
    mr.resume();
    grabadora.desde = performance.now();
  }
  const pausada = mr.state === 'paused';
  $('#e-grabadora').classList.toggle('pausada', pausada);
  $('#g-pausa').replaceChildren(icono(pausada ? 'micro' : 'pausa'));
  $('#g-pausa').title = pausada ? 'Seguir grabando' : 'Pausar';
}

/** Para de grabar y guarda la grabación en la nota (o la descarta). */
function terminarGrabacion({ descartar = false } = {}) {
  const { mr } = grabadora;
  if (!mr) return grabadora.fin || Promise.resolve();
  grabadora.fin = new Promise(resolver => {
    const segundos = segundosGrabados();
    mr.onstop = async () => {
      const audio = new Blob(grabadora.trozos, { type: mr.mimeType.split(';')[0] || 'audio/webm' });
      grabadora.trozos = [];
      if (!descartar && audio.size) await subirAdjunto(audio, nombreGrabacion(audio.type), segundos);
      resolver();
    };
    grabadora.mr = null;
    if (mr.state === 'inactive') mr.onstop(); else mr.stop();
    grabadora.flujo.getTracks().forEach(p => { p.onended = null; p.stop(); });
    grabadora.contexto?.close();
    cancelAnimationFrame(grabadora.cuadro);
    $('#e-grabadora').hidden = true;
    $('#e-voz').setAttribute('aria-pressed', 'false');
  });
  return grabadora.fin;
}

function nombreGrabacion(tipo) {
  const f = new Date(), dos = n => String(n).padStart(2, '0');
  const ext = { 'audio/ogg': 'ogg', 'audio/mp4': 'm4a' }[tipo] || 'webm';
  return `Nota de voz ${f.getFullYear()}-${dos(f.getMonth() + 1)}-${dos(f.getDate())} ${dos(f.getHours())}.${dos(f.getMinutes())}.${dos(f.getSeconds())}.${ext}`;
}

/* ---------- Editor ---------- */

const editor = { nota: null, sucio: false, reloj: 0, cadena: Promise.resolve(), nueva: false, tuvoAdjuntos: false, abierta: false, cerrando: false };
const NOTA_NUEVA = { id: null, titulo: '', texto: '', color: '', fijada: false, archivada: false, papelera: null, detalles: {}, categorias: [], adjuntos: [] };

function abrirEditor(nota) {
  const categoria = app.vista.clave === 'categoria' && app.categorias.find(c => c.id === app.vista.valor);
  Object.assign(editor, {
    nota: nota ? structuredClone(nota) : { ...NOTA_NUEVA, categorias: categoria ? [{ id: categoria.id, nombre: categoria.nombre }] : [], adjuntos: [] },
    sucio: false, nueva: !nota, tuvoAdjuntos: Boolean(nota?.adjuntos.length), abierta: true, cerrando: false,
  });
  clearTimeout(editor.reloj);
  $('#e-titulo').value = editor.nota.titulo;
  $('#e-texto').value = editor.nota.texto;
  $('#e-subidas').replaceChildren();
  $('#e-conflicto').hidden = $('#e-paleta').hidden = true;
  $('#e-color').setAttribute('aria-expanded', 'false');
  estadoGuardado('');
  pintarEditor();
  pintarAdjuntos();
  $('#editor').showModal();
  ajustarAltura();
  $('.desplazable', $('#editor')).scrollTop = 0;
  if (editor.nota.papelera) $('#e-restaurar').focus(); else $('#e-texto').focus();
}

/** Todo menos el título y el texto (que son lo que está escribiendo el usuario). */
function pintarEditor() {
  const n = editor.nota, enPapelera = Boolean(n.papelera);
  $('.hoja', $('#editor')).className = `hoja${n.color ? ` color-${n.color}` : ''}`;
  $('#e-titulo').readOnly = $('#e-texto').readOnly = enPapelera;
  $('#e-fijar').hidden = $('#e-categoria').hidden = enPapelera;
  $('.e-acciones:not(#e-acciones-papelera)', $('#editor')).hidden = enPapelera;
  $('#e-acciones-papelera').hidden = !enPapelera;
  $('#e-fijar').setAttribute('aria-pressed', n.fijada);
  $('#e-fijar').title = n.fijada ? 'Soltar' : 'Fijar arriba';
  $('#e-archivar').setAttribute('aria-pressed', n.archivada);
  $('#e-archivar').title = n.archivada ? 'Sacar del archivo' : 'Archivar';
  $('#e-chips').replaceChildren(...n.categorias.map(c => el('span', { class: 'chip' }, c.nombre,
    enPapelera ? null : el('button', { class: 'quitar', type: 'button', 'aria-label': `Quitar ${c.nombre}`, texto: '✕',
      onclick: () => cambiarCategorias(n.categorias.filter(x => x !== c)) }))));
  $('#e-paleta').replaceChildren(...app.colores.map(c => el('button', {
    type: 'button', class: c ? `color-${c}` : null, title: c || 'sin color', 'aria-label': c || 'sin color',
    'aria-pressed': String(c === n.color), onclick: () => cambiar({ color: c }) })));
  $('#e-detalles').replaceChildren(...enlacesDe(n), el('p', { texto: detallesDe(n.detalles) }));
  $('#e-detalles').hidden = !$('#e-detalles').textContent;
  $('#e-fechas').textContent = n.id ? (enPapelera ? `En la papelera desde el ${fechaLarga(n.papelera)}`
    : `Creada el ${fechaLarga(n.creada)} · Modificada el ${fechaLarga(n.modificada)}`) : '';
}

const detallesDe = d => [
  d.fuente && `Importada de ${d.fuente}`,
  d.compartida && `Compartida con ${d.compartida.map(x => (x === d.propietario ? `${x} (es suya)` : x)).join(', ')}`,
  d.recordatorio && 'Tenía un recordatorio',
  d.faltan && `Faltan archivos: ${d.faltan.join(', ')}`,
].filter(Boolean).join(' · ');

/** Dónde empieza la línea en la que está el cursor. */
const inicioLinea = t => (t.selectionStart ? t.value.lastIndexOf('\n', t.selectionStart - 1) + 1 : 0);

/** Pulsar una casilla del texto la marca o la desmarca. */
function pulsarCasilla() {
  const t = $('#e-texto'), inicio = inicioLinea(t), casilla = t.value[inicio];
  if (t.readOnly || t.selectionStart !== t.selectionEnd || t.selectionStart - inicio > 1) return;
  if (casilla !== '☐' && casilla !== '☑') return;
  t.setRangeText(casilla === '☐' ? '☑' : '☐', inicio, inicio + 1, 'end');
  t.oninput();
}

/** Enter en una casilla empieza la siguiente; en una vacía, termina la lista. */
function seguirLista(e) {
  const t = e.target, pos = t.selectionStart, inicio = inicioLinea(t);
  if (e.key !== 'Enter' || e.shiftKey || e.isComposing || t.readOnly || pos !== t.selectionEnd) return;
  const linea = t.value.slice(inicio).split('\n', 1)[0];
  if (pos === inicio || !/^[☐☑]/.test(linea)) return;
  e.preventDefault();
  if (/^.\s*$/.test(linea)) t.setRangeText('', inicio, inicio + linea.length, 'end');
  else t.setRangeText('\n☐ ', pos, pos, 'end');
  t.oninput();
}

function ajustarAltura() {
  const t = $('#e-texto'), zona = t.closest('.desplazable'), arriba = zona.scrollTop;
  t.style.height = 'auto';
  t.style.height = `${t.scrollHeight + 2}px`;
  zona.scrollTop = arriba;
}

function estadoGuardado(texto, error = false) {
  $('#e-estado').textContent = texto;
  $('#e-estado').classList.toggle('error', error);
}

function escribiendo() {
  editor.sucio = true;
  estadoGuardado('…');
  clearTimeout(editor.reloj);
  editor.reloj = setTimeout(guardar, 700);
}

/** Pone en fila lo que cambia la nota abierta: las respuestas del servidor llegan en orden. */
function encolar(accion) {
  const esta = editor.cadena.then(accion);
  editor.cadena = esta.catch(() => {});       // un fallo no bloquea a los siguientes
  return esta;
}

/** Guarda el texto si hay cambios. Resuelve a true si no queda nada pendiente. */
function guardar() {
  clearTimeout(editor.reloj);
  return encolar(guardarYa);
}

async function guardarYa() {
  const n = editor.nota;
  if (!editor.sucio) return true;
  if (!$('#e-conflicto').hidden) return false;         // primero hay que decidir qué versión vale
  const titulo = $('#e-titulo').value, texto = $('#e-texto').value;
  if (!n.id && !titulo.trim() && !texto.trim()) return true;
  editor.sucio = false;
  estadoGuardado('Guardando…');
  try {
    if (n.id) conservar(await pedir('PATCH', `/api/notas/${n.id}`, { titulo, texto, version: n.version }));
    else conservar(await crearDesdeEditor(titulo, texto));
    if (!editor.sucio) estadoGuardado('Guardado');
    return !editor.sucio;
  } catch (error) {
    editor.sucio = true;
    if (error.estado === 409) {
      editor.otra = error.datos.nota;
      $('#e-conflicto').hidden = false;
      estadoGuardado('Sin guardar', true);
    } else if (error.estado === 0) {
      estadoGuardado('Sin conexión con Notas: se reintentará', true);
      editor.reloj = setTimeout(guardar, 3000);
    } else {
      estadoGuardado(error.message, true);
    }
    return false;
  }
}

const crearDesdeEditor = (titulo, texto) => pedir('POST', '/api/notas', {
  titulo, texto, color: editor.nota.color, fijada: editor.nota.fijada, categorias: editor.nota.categorias.map(c => c.nombre) });

function conservar(nota) {
  editor.nota = nota;
  if (nota.adjuntos.length) editor.tuvoAdjuntos = true;
  pintarEditor();
}

/** Cambia algo que no es el texto; en una nota aún sin crear, se guarda al crearla. */
async function cambiar(cambios, enServidor = cambios) {
  Object.assign(editor.nota, cambios);
  if (cambios.archivada) editor.nota.fijada = false;
  if (cambios.fijada) editor.nota.archivada = false;
  pintarEditor();
  if (!editor.nota.id) return;
  await encolar(() => intentar(async () =>
    conservar(await pedir('PATCH', `/api/notas/${editor.nota.id}`, enServidor))));
}

const cambiarCategorias = categorias => cambiar({ categorias }, { categorias: categorias.map(c => c.nombre) });

async function ponerCategoriaEditor() {
  const campo = $('#e-categoria'), nombre = campo.value.trim().replace(/\s+/g, ' ');
  if (!nombre) return;
  campo.value = '';
  const actuales = editor.nota.categorias;
  if (actuales.some(c => sinAcentos(c.nombre) === sinAcentos(nombre))) return;
  await cambiarCategorias([...actuales, { id: null, nombre }]);
  const estado = await pedir('GET', '/api/estado').catch(() => null);
  if (estado) { app.categorias = estado.categorias; app.totales = estado.totales; pintarMenu(); }
}

/** Una nota nueva se crea ya (aunque esté vacía) para poder añadirle adjuntos. */
async function asegurarNota() {
  await guardar();
  await encolar(async () => {
    if (!editor.nota.id) conservar(await crearDesdeEditor($('#e-titulo').value, $('#e-texto').value));
  });
}

function ocultarEditor() {
  editor.abierta = false;
  $('#editor').close();
}

async function cerrarEditor() {
  if (editor.cerrando || !$('#editor').open) return;
  editor.cerrando = true;
  try {
    if (grabando()) await terminarGrabacion();
    await grabadora.fin;
    await subidasEnMarcha();
    if (!await guardar() && editor.sucio) {
      const salir = await preguntar({
        titulo: 'Hay cambios sin guardar', peligro: true, aceptar: 'Cerrar sin guardar',
        texto: $('#e-conflicto').hidden ? $('#e-estado').textContent : 'La nota ha cambiado en otra ventana: decide antes qué versión quieres guardar.' });
      if (!salir) return;
    }
    if ($('.subida.fallo')) {
      const salir = await preguntar({ titulo: 'Hay archivos sin guardar', peligro: true, aceptar: 'Cerrar sin guardarlos',
        texto: 'Alguna grabación o archivo no se ha podido guardar en la nota y se perderá.' });
      if (!salir) return;
    }
    clearTimeout(editor.reloj);
    editor.sucio = false;
    sonando?.pause();
    ocultarEditor();
    await descartarSiVacia();
    await cargar();
  } finally {
    editor.cerrando = false;
  }
}

/** Una nota que se queda sin nada no se guarda: si es nueva desaparece; si no, a la papelera. */
async function descartarSiVacia() {
  const n = editor.nota;
  if (!n.id || n.papelera || n.titulo.trim() || n.texto.trim() || n.adjuntos.length) return;
  await intentar(async () => {
    await pedir('POST', '/api/lote', { ids: [n.id], accion: 'papelera' });
    if (editor.nueva && !editor.tuvoAdjuntos) await pedir('POST', '/api/lote', { ids: [n.id], accion: 'eliminar' });
    aviso(editor.nueva && !editor.tuvoAdjuntos ? 'Nota vacía descartada' : 'La nota se ha quedado vacía: está en la papelera');
  });
}

async function resolverConflicto(que) {
  const otra = editor.otra, titulo = $('#e-titulo').value, texto = $('#e-texto').value;
  if (que === 'ambas' && !await intentar(() => crearDesdeEditor(titulo, texto))) return;
  $('#e-conflicto').hidden = true;
  editor.nota = otra;
  if (que === 'mia') {                    // se guarda sobre la versión de la otra ventana
    editor.sucio = true;
    await guardar();
  } else {
    editor.sucio = false;
    $('#e-titulo').value = otra.titulo;
    $('#e-texto').value = otra.texto;
    ajustarAltura();
    pintarEditor();
    pintarAdjuntos();
    estadoGuardado('Guardado');
    if (que === 'ambas') aviso('Tu texto está en otra nota; esta tiene lo de la otra ventana');
  }
}

async function desdeEditor(accion) {       // archivar, papelera…: guarda, cierra y lo hace
  const { id } = editor.nota;
  await cerrarEditor();
  if (id && !$('#editor').open) await accion([id]);
}

/* ---------- Adjuntos del editor ---------- */

function pintarAdjuntos() {
  const n = editor.nota, imagenes = n.adjuntos.filter(a => a.tipo === 'imagen');
  const quitar = a => (n.papelera ? null : boton('papelera', `Quitar ${a.nombre}`, sin(() => quitarAdjunto(a)), 'quitar-adj'));
  $('#e-imagenes').replaceChildren(...imagenes.map((a, i) =>
    el('div', { tabindex: 0, role: 'button', 'aria-label': `Ver ${a.nombre}`, onclick: () => abrirVisor(imagenes, i),
                onkeydown: e => { if (e.key === 'Enter' && e.target === e.currentTarget) abrirVisor(imagenes, i); } },
      imagenDe(a), quitar(a))));
  $('#e-voces').replaceChildren(...n.adjuntos.filter(a => a.tipo === 'voz').flatMap(a => {
    const caja = reproductor(a);
    caja.append(el('a', { class: 'ico peq', href: `${a.url}&descargar=1`, download: a.nombre, title: 'Descargar' }, icono('descargar')));
    const papelera = quitar(a);
    if (papelera) { papelera.className = 'ico peq'; caja.append(papelera); }
    return [caja, el('div', { class: 'nombre', texto: `${a.nombre} · ${peso(a.bytes)}` })];
  }));
}

async function quitarAdjunto(a) {
  const poner = quitar => encolar(() => intentar(async () => {
    const nota = await pedir('POST', `/api/adjuntos/${a.id}/${quitar ? 'quitar' : 'recuperar'}`);
    if (editor.nota.id === nota.id && $('#editor').open) { conservar(nota); pintarAdjuntos(); } else await cargar();
  }));
  sonando?.pause();
  if (await poner(true))
    aviso(a.tipo === 'imagen' ? 'Imagen quitada' : 'Nota de voz quitada', { accion: 'Deshacer', alPulsar: () => poner(false) });
}

const subidas = new Set();
const subidasEnMarcha = () => Promise.allSettled([...subidas]);

/** Sube un archivo a la nota abierta. Si falla, se queda ahí para reintentar: no se pierde. */
function subirAdjunto(archivo, nombre, segundos = 0) {
  const fila = el('div', { class: 'subida' }, el('span', { texto: `Guardando ${nombre}…` }));
  $('#e-subidas').append(fila);
  const subida = (async () => {
    try {
      if (archivo.size > app.maxAdjunto) throw new ErrorApi(`Pesa más de ${peso(app.maxAdjunto)}`, 413);
      await asegurarNota();
      const { id } = editor.nota;
      await pedir('POST', `/api/notas/${id}/adjuntos`, archivo, {
        'Content-Type': archivo.type || 'application/octet-stream',
        'X-Nombre': encodeURIComponent(nombre), 'X-Duracion': String(segundos || '') });
      fila.remove();
      // Mientras subía se ha podido guardar el texto: se pide la nota como ha quedado
      await encolar(() => intentar(async () => {
        const nota = await pedir('GET', `/api/notas/${id}`);
        if (editor.nota.id === id) { conservar(nota); pintarAdjuntos(); }
      }));
    } catch (error) {
      if ([400, 404, 413, 415].includes(error.estado)) {      // no se arregla reintentando
        fila.remove();
        aviso(error.message, { error: true });
        return;
      }
      fila.className = 'subida fallo';
      const url = URL.createObjectURL(archivo);
      fila.replaceChildren(el('span', { texto: `No se ha podido guardar «${nombre}»: ${error.message}` }),
        el('button', { class: 'boton', type: 'button', texto: 'Reintentar', onclick: () => { URL.revokeObjectURL(url); fila.remove(); subirAdjunto(archivo, nombre, segundos); } }),
        el('a', { class: 'boton', href: url, download: nombre, texto: 'Descargar' }));
    }
  })();
  subidas.add(subida);
  subida.finally(() => subidas.delete(subida));
  return subida;
}

async function adjuntarArchivos(archivos) {
  archivos = [...archivos];
  if (!archivos.length) return;
  if (!$('#editor').open) abrirEditor(null);
  if (editor.nota.papelera) return aviso('La nota está en la papelera: restáurala para cambiarla', { error: true });
  for (const archivo of archivos) {
    const esAudio = archivo.type.startsWith('audio/') || /\.(opus|m4a|mp3|ogg|wav|flac|aac)$/i.test(archivo.name);
    await subirAdjunto(archivo, archivo.name || 'Imagen pegada', esAudio ? await medirDuracion(archivo) : 0);
  }
}

/* ---------- Visor de imágenes ---------- */

const visor = { imagenes: [], i: 0 };

function abrirVisor(imagenes, i) {
  Object.assign(visor, { imagenes, i });
  pintarVisor();
  $('#visor').showModal();
}

function pintarVisor() {
  const a = visor.imagenes[visor.i], varias = visor.imagenes.length > 1;
  $('#v-imagen').src = a.url;
  $('#v-imagen').alt = a.nombre;
  $('#v-nombre').textContent = (varias ? `${visor.i + 1} de ${visor.imagenes.length} · ` : '') + `${a.nombre} · ${peso(a.bytes)}`;
  $('#v-descargar').href = `${a.url}&descargar=1`;
  $('#v-descargar').download = a.nombre;
  $('#v-anterior').hidden = $('#v-siguiente').hidden = !varias;
}

function moverVisor(paso) {
  visor.i = (visor.i + paso + visor.imagenes.length) % visor.imagenes.length;
  pintarVisor();
}

/* ---------- Categorías ---------- */

function pintarCategorias() {
  $('#dc-lista').replaceChildren(...app.categorias.map(c => {
    const campo = el('input', { type: 'text', value: c.nombre, maxlength: 60, 'aria-label': `Nombre de ${c.nombre}` });
    const renombrar = () => {
      const nombre = campo.value.trim();
      if (!nombre || nombre === c.nombre) { campo.value = c.nombre; return; }
      intentar(() => pedir('PATCH', `/api/categorias/${c.id}`, { nombre })).then(async () => { await cargar(); pintarCategorias(); });
    };
    campo.addEventListener('change', renombrar);
    return el('li', {}, campo, el('span', { class: 'tenue', texto: c.total || '' }),
      boton('papelera', `Quitar la categoría ${c.nombre}`, async () => {
        const si = await preguntar({ titulo: `¿Quitar la categoría «${c.nombre}»?`, aceptar: 'Quitar', peligro: true,
          texto: 'Sus notas no se borran: solo dejan de tener esta categoría.' });
        if (si && await intentar(() => pedir('DELETE', `/api/categorias/${c.id}`))) { await cargar(); pintarCategorias(); }
      }));
  }));
}

const quitarCategoria = (ids, nombre) => lote(ids, 'quitar_categoria', nombre,
  `Fuera de «${nombre}»: ${plural(ids.length, 'nota', 'notas')}`, () => lote(ids, 'poner_categoria', nombre));

function ponerCategoria(ids) {
  const d = $('#d-poner'), campo = $('input', d);
  const poner = nombre => {
    d.close();
    // «Deshacer» solo se la quita a las que no la tenían
    const sinElla = ids.filter(id => !app.notas.find(n => n.id === id)?.categorias.some(c => sinAcentos(c.nombre) === sinAcentos(nombre)));
    lote(ids, 'poner_categoria', nombre, `En «${nombre}»: ${plural(ids.length, 'nota', 'notas')}`,
      sinElla.length ? () => lote(sinElla, 'quitar_categoria', nombre) : null);
  };
  campo.value = '';
  $('#dp-existentes').replaceChildren(...app.categorias.map(c =>
    el('button', { class: 'chip', type: 'button', texto: c.nombre, onclick: () => poner(c.nombre) })));
  $('#dp-nueva').onsubmit = e => { e.preventDefault(); if (campo.value.trim()) poner(campo.value.trim()); };
  d.showModal();
}

/* ---------- Arranque ---------- */

function cambiarTema() {
  const oscuro = document.documentElement.dataset.tema
    ? document.documentElement.dataset.tema === 'oscuro' : matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.dataset.tema = oscuro ? 'claro' : 'oscuro';
  memoria.guardar('tema', document.documentElement.dataset.tema);
}

function alternador(boton, campo) {
  const poner = () => boton.setAttribute('aria-pressed', app[campo]);
  poner();
  boton.addEventListener('click', () => {
    app[campo] = !app[campo];
    memoria.guardar(campo, app[campo] ? '1' : '');
    poner();
    pintar();
  });
}

function cerrarAlPulsarFuera(dialogo, cerrar) {
  let dentro = false;        // no cerrar si se empezó a arrastrar (p. ej. seleccionando texto) dentro
  dialogo.addEventListener('pointerdown', e => { dentro = e.target !== dialogo; });
  dialogo.addEventListener('click', e => { if (e.target === dialogo && !dentro) cerrar(); });
}

function arrancar() {
  document.querySelectorAll('[data-icono]').forEach(e => {
    e.prepend(icono(e.dataset.icono));
    if (e.title && !e.textContent.trim() && !e.hasAttribute('aria-label')) e.setAttribute('aria-label', e.title);
  });
  const tema = memoria.leer('tema', '');
  if (tema) document.documentElement.dataset.tema = tema;

  // Cabecera y menú
  const estrecha = matchMedia('(max-width: 760px)');
  const menu = visible => {
    document.body.classList.toggle('menu-oculto', !visible);
    $('#b-menu').setAttribute('aria-expanded', visible);
  };
  menu(!estrecha.matches && memoria.leer('menu', '1') === '1');
  $('#b-menu').onclick = () => {
    const visible = document.body.classList.contains('menu-oculto');
    menu(visible);
    if (!estrecha.matches) memoria.guardar('menu', visible ? '1' : '');
  };
  $('#menu').addEventListener('click', e => { if (estrecha.matches && e.target.closest('a')) menu(false); });
  $('#b-tema').onclick = cambiarTema;
  $('#orden').value = app.orden;
  $('#orden').onchange = e => { app.orden = e.target.value; memoria.guardar('orden', app.orden); cargar(); };
  alternador($('#b-agrupar'), 'agrupar');
  alternador($('#b-lista'), 'lista');
  let espera;
  $('#buscar').addEventListener('input', e => {
    clearTimeout(espera);
    espera = setTimeout(() => { app.buscar = e.target.value.trim(); rejilla.hechas = 0; cargar(); }, 180);
  });
  $('#s-cerrar').onclick = () => { app.elegidas.clear(); pintarSeleccion(); };
  $('#b-vaciar').onclick = async () => {
    const si = await preguntar({ titulo: '¿Vaciar la papelera?', aceptar: 'Vaciar', peligro: true,
      texto: `Se borran para siempre ${plural(app.notas.length, 'nota', 'notas')}, con sus imágenes y notas de voz. No se puede deshacer.` });
    if (si && await intentar(() => pedir('POST', '/api/papelera/vaciar', { confirmar: 'VACIAR' }))) { await cargar(); aviso('Papelera vacía'); }
  };

  // Componer
  $('#c-texto').onclick = () => abrirEditor(null);
  $('#c-voz').onclick = $('#e-voz').onclick = () => (grabando() ? terminarGrabacion() : grabar());
  $('#c-imagen').onclick = $('#e-imagen').onclick = () => $('#elegir').click();
  $('#elegir').onchange = e => { adjuntarArchivos(e.target.files); e.target.value = ''; };

  // Editor
  $('#e-titulo').oninput = escribiendo;
  $('#e-titulo').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); $('#e-texto').focus(); } };
  $('#e-texto').oninput = () => { ajustarAltura(); escribiendo(); };
  $('#e-texto').onclick = pulsarCasilla;
  $('#e-texto').onkeydown = seguirLista;
  $('#e-fijar').onclick = () => cambiar({ fijada: !editor.nota.fijada });
  $('#e-archivar').onclick = () => desdeEditor(editor.nota.archivada ? desarchivar : archivar);
  $('#e-papelera').onclick = () => desdeEditor(aPapelera);
  $('#e-restaurar').onclick = () => desdeEditor(restaurar);
  $('#e-eliminar').onclick = async () => { const { id } = editor.nota; if (await eliminar([id])) ocultarEditor(); };
  $('#e-color').onclick = () => {
    $('#e-paleta').hidden = !$('#e-paleta').hidden;
    $('#e-color').setAttribute('aria-expanded', !$('#e-paleta').hidden);
  };
  $('#e-categoria').onkeydown = e => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); ponerCategoriaEditor(); } };
  $('#e-categoria').onchange = ponerCategoriaEditor;       // al elegir de la lista o salir del campo
  $('#e-cerrar').onclick = cerrarEditor;
  $('#editor').addEventListener('cancel', e => { if (e.target === $('#editor')) { e.preventDefault(); cerrarEditor(); } });
  // Con dos Escapes seguidos el navegador lo cierra sin preguntar: se reabre y se cierra bien
  $('#editor').addEventListener('close', () => { if (editor.abierta) { $('#editor').showModal(); cerrarEditor(); } });
  cerrarAlPulsarFuera($('#editor'), cerrarEditor);
  $('#g-pausa').onclick = pausarGrabacion;
  $('#g-listo').onclick = () => terminarGrabacion();
  $('#g-descartar').onclick = async () => {
    if (grabadora.mr?.state === 'recording') pausarGrabacion();
    if (await preguntar({ titulo: '¿Descartar la grabación?', aceptar: 'Descartar', peligro: true })) terminarGrabacion({ descartar: true });
  };
  $('#k-mia').onclick = () => resolverConflicto('mia');
  $('#k-otra').onclick = () => resolverConflicto('otra');
  $('#k-ambas').onclick = () => resolverConflicto('ambas');

  // Visor
  $('#v-cerrar').onclick = () => $('#visor').close();
  $('#v-anterior').onclick = () => moverVisor(-1);
  $('#v-siguiente').onclick = () => moverVisor(1);
  $('#visor').addEventListener('keydown', e => { if (e.key === 'ArrowLeft') moverVisor(-1); if (e.key === 'ArrowRight') moverVisor(1); });
  $('#visor').addEventListener('close', () => $('#v-imagen').removeAttribute('src'));
  cerrarAlPulsarFuera($('#visor'), () => $('#visor').close());

  // Categorías
  $('#b-categorias').onclick = () => { pintarCategorias(); $('#d-categorias').showModal(); };
  $('#dc-cerrar').onclick = () => $('#d-categorias').close();
  $('#dc-nueva').onsubmit = async e => {
    e.preventDefault();
    const campo = $('input', e.target);
    if (campo.value.trim() && await intentar(() => pedir('POST', '/api/categorias', { nombre: campo.value }))) {
      campo.value = '';
      await cargar();
      pintarCategorias();
    }
  };
  $('#dp-cerrar').onclick = () => $('#d-poner').close();
  for (const id of ['#d-categorias', '#d-poner']) cerrarAlPulsarFuera($(id), () => $(id).close());

  // Los avisos viven en el diálogo abierto; al cerrarse, vuelven a la página
  document.querySelectorAll('dialog').forEach(d => d.addEventListener('close', () => {
    if (d.contains($('#avisos'))) (dialogoAbierto() || document.body).append($('#avisos'));
  }));

  // Pegar, soltar, teclado
  document.addEventListener('paste', e => {
    const archivos = e.clipboardData?.files;
    if (archivos?.length) { e.preventDefault(); adjuntarArchivos(archivos); }
  });
  let arrastre = 0;
  const hayArchivos = e => e.dataTransfer?.types.includes('Files');
  document.addEventListener('dragenter', e => { if (hayArchivos(e)) { arrastre++; $('#soltar').hidden = false; } });
  document.addEventListener('dragleave', e => { if (hayArchivos(e) && --arrastre <= 0) { arrastre = 0; $('#soltar').hidden = true; } });
  document.addEventListener('dragover', e => { if (hayArchivos(e)) e.preventDefault(); });
  document.addEventListener('drop', e => {
    arrastre = 0;
    $('#soltar').hidden = true;
    if (hayArchivos(e)) { e.preventDefault(); adjuntarArchivos(e.dataTransfer.files); }
  });
  document.addEventListener('keydown', e => {
    if (dialogoAbierto() || e.ctrlKey || e.metaKey || e.altKey || e.target.closest('input, textarea, select')) return;
    if (e.key === '/') { e.preventDefault(); $('#buscar').focus(); $('#buscar').select(); }
    else if (e.key === 'n') { e.preventDefault(); abrirEditor(null); }
    else if (e.key === 'Escape' && app.elegidas.size) { app.elegidas.clear(); pintarSeleccion(); }
  });
  window.addEventListener('beforeunload', e => {
    if (editor.sucio) guardar();
    if (editor.sucio || grabando() || subidas.size || $('.subida.fallo')) e.preventDefault();
  });

  // Vistas, tamaño y más notas al bajar
  const cambioDeVista = () => {
    app.vista = leerVista();
    app.elegidas.clear();
    rejilla.hechas = 0;
    window.scrollTo(0, 0);
    cargar();
  };
  window.addEventListener('hashchange', cambioDeVista);
  new ResizeObserver(() => { if (rejilla.nColumnas && columnasQueCaben() !== rejilla.nColumnas) pintar(); }).observe($('#notas'));
  // Al volver a la pestaña, por si se ha añadido algo desde la terminal u otra ventana
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !dialogoAbierto() && !app.elegidas.size && (!sonando || sonando.paused)) cargar(); });
  cambioDeVista();
}

arrancar();
