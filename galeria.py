"""Galería web local: genera una página para explorar fotos y vídeos exportados.

Crea en la carpeta indicada:
    - galeria.html    (interfaz con buscador y visor a pantalla completa)
    - galeria.json    (índice de los archivos encontrados)
    - _galeria/       (miniaturas para carga rápida)

Para servirla:  python main.py galeria <carpeta> --servir
(o manualmente: python -m http.server desde la carpeta)
"""

import json
import subprocess
import webbrowser
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from fotos import obtener_fecha as fecha_foto
from media_utils import NOMBRE_ORIGINALES
from videos import sondear

EXTENSIONES_FOTO = {".jpg", ".jpeg", ".png", ".webp"}
EXTENSIONES_VIDEO = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}

CARPETA_GALERIA = "_galeria"
ANCHO_MINIATURA = 400
PUERTO_DEFECTO = 8080


# ----------------------------- Índice y miniaturas -----------------------------

def _fecha_video(ruta: Path) -> datetime:
    info = sondear(ruta)
    if info and info["fecha"]:
        return info["fecha"]
    return datetime.fromtimestamp(ruta.stat().st_mtime)


def _miniatura_foto(ruta: Path, destino_thumb: Path):
    from PIL import Image, ImageOps
    with Image.open(ruta) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((ANCHO_MINIATURA, ANCHO_MINIATURA), Image.LANCZOS)
        if im.mode != "RGB":
            im = im.convert("RGB")
        im.save(destino_thumb, "JPEG", quality=72)


def _miniatura_video(ruta: Path, destino_thumb: Path):
    """Extrae un fotograma a los ~3 s con ffmpeg (requiere FFmpeg)."""
    cmd = ["ffmpeg", "-y", "-ss", "3", "-i", str(ruta),
           "-frames:v", "1", "-vf", f"scale={ANCHO_MINIATURA}:-2",
           "-loglevel", "error", str(destino_thumb)]
    subprocess.run(cmd, capture_output=True, timeout=60)


def generar_miniatura(ruta: Path, carpeta_thumbs: Path, clave: str) -> str:
    """Crea (si no existe) la miniatura y devuelve su ruta relativa."""
    destino = carpeta_thumbs / f"{clave}.jpg"
    if not destino.exists():
        try:
            if ruta.suffix.lower() in EXTENSIONES_FOTO:
                _miniatura_foto(ruta, destino)
            else:
                _miniatura_video(ruta, destino)
        except Exception as exc:
            print(f"  miniatura omitida para {ruta.name}: {exc}")
    if destino.exists():
        return f"{CARPETA_GALERIA}/thumbs/{destino.name}"
    return ""


def construir_indice(carpeta: Path) -> list:
    """Recorre la carpeta y construye la lista de elementos para la galería."""
    carpeta_thumbs = carpeta / CARPETA_GALERIA / "thumbs"
    carpeta_thumbs.mkdir(parents=True, exist_ok=True)

    elementos = []
    for ruta in sorted(carpeta.rglob("*")):
        if not ruta.is_file() or NOMBRE_ORIGINALES in ruta.parts:
            continue
        if CARPETA_GALERIA in ruta.parts:
            continue
        extension = ruta.suffix.lower()
        if extension in EXTENSIONES_FOTO:
            tipo = "foto"
            fecha = fecha_foto(ruta)
        elif extension in EXTENSIONES_VIDEO:
            tipo = "video"
            fecha = _fecha_video(ruta)
        else:
            continue

        rel = ruta.relative_to(carpeta).as_posix()
        clave = rel.replace("/", "_").rsplit(".", 1)[0][:80]
        elemento = {
            "tipo": tipo,
            "src": rel,
            "nombre": ruta.stem,
            "carpeta": str(ruta.parent.relative_to(carpeta)) if ruta.parent != carpeta else "",
            "fecha": fecha.strftime("%Y-%m-%d %H:%M"),
            "thumb": generar_miniatura(ruta, carpeta_thumbs, clave),
        }
        elementos.append(elemento)
    return elementos


# ----------------------------- Plantilla HTML -----------------------------

PLANTILLA_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Galería</title>
<style>
  :root { --bg:#111; --panel:#1c1c1e; --text:#f2f2f2; --muted:#999; --accent:#6d4aff; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif; }
  header { position:sticky; top:0; z-index:10; background:var(--panel);
           padding:.8rem 1.2rem; display:flex; gap:.8rem; flex-wrap:wrap; align-items:center;
           border-bottom:1px solid #333; }
  header h1 { font-size:1.1rem; margin-right:auto; }
  #busqueda { background:#2a2a2c; border:1px solid #444; color:var(--text);
              padding:.45rem .8rem; border-radius:8px; min-width:220px; }
  .filtro { background:none; border:1px solid #444; color:var(--muted); padding:.4rem .9rem;
            border-radius:20px; cursor:pointer; }
  .filtro.activo { border-color:var(--accent); color:var(--text); background:rgba(109,74,255,.15); }
  main { padding:1.2rem; columns:4 220px; column-gap:.9rem; }
  .tarjeta { break-inside:avoid; margin-bottom:.9rem; border-radius:10px; overflow:hidden;
             cursor:pointer; position:relative; background:var(--panel); }
  .tarjeta img { width:100%; display:block; }
  .tarjeta .info { position:absolute; bottom:0; left:0; right:0; padding:.4rem .6rem;
                   background:linear-gradient(transparent,rgba(0,0,0,.85));
                   font-size:.72rem; color:#ddd; white-space:nowrap;
                   overflow:hidden; text-overflow:ellipsis; }
  .tarjeta.video::after { content:"▶"; position:absolute; top:.5rem; right:.6rem;
                          font-size:.9rem; color:#fff; text-shadow:0 0 4px #000; }
  .tarjeta .info b { color:#fff; display:block; }
  #vacio { text-align:center; color:var(--muted); padding:3rem; }
  /* Visor */
  #visor { display:none; position:fixed; inset:0; background:rgba(0,0,0,.94); z-index:100;
           flex-direction:column; }
  #visor.abierto { display:flex; }
  #visor-contenido { flex:1; display:flex; align-items:center; justify-content:center;
                     min-height:0; padding:1rem; }
  #visor-contenido img, #visor-contenido video { max-width:100%; max-height:100%;
                     border-radius:4px; }
  #visor-pie { text-align:center; padding:.6rem; font-size:.85rem; color:var(--muted); }
  #visor-pie b { color:var(--text); }
  .flecha { position:fixed; top:50%; transform:translateY(-50%); font-size:2.4rem;
            background:none; border:none; color:#fff; cursor:pointer; padding:1rem;
            opacity:.5; }
  .flecha:hover { opacity:1; }
  #anterior { left:.4rem; } #siguiente { right:.4rem; }
  #cerrar { position:fixed; top:.6rem; right:1rem; font-size:1.8rem; background:none;
            border:none; color:#fff; cursor:pointer; opacity:.6; }
  #cerrar:hover { opacity:1; }
</style>
</head>
<body>
<header>
  <h1>📷 Galería</h1>
  <input id="busqueda" type="search" placeholder="Buscar por nombre, fecha o carpeta…">
  <button class="filtro activo" data-tipo="">Todas</button>
  <button class="filtro" data-tipo="foto">Fotos</button>
  <button class="filtro" data-tipo="video">Vídeos</button>
</header>
<main id="rejilla"></main>
<div id="vacio" hidden>No hay resultados para esta búsqueda.</div>

<div id="visor">
  <button id="cerrar" aria-label="Cerrar">✕</button>
  <button id="anterior" class="flecha" aria-label="Anterior">‹</button>
  <div id="visor-contenido"></div>
  <button id="siguiente" class="flecha" aria-label="Siguiente">›</button>
  <div id="visor-pie"></div>
</div>

<script>
let items = [], filtrados = [], indice = 0;
const rejilla = document.getElementById('rejilla');
const busqueda = document.getElementById('busqueda');
let tipoActual = '';

async function cargar() {
  const resp = await fetch('galeria.json');
  items = await resp.json();
  aplicar();
}

function aplicar() {
  const texto = busqueda.value.trim().toLowerCase();
  filtrados = items.filter(it => {
    if (tipoActual && it.tipo !== tipoActual) return false;
    if (!texto) return true;
    return (it.nombre + ' ' + it.fecha + ' ' + it.carpeta).toLowerCase().includes(texto);
  });
  pintar();
}

function pintar() {
  rejilla.innerHTML = '';
  document.getElementById('vacio').hidden = filtrados.length > 0;
  filtrados.forEach((it, i) => {
    const div = document.createElement('div');
    div.className = 'tarjeta' + (it.tipo === 'video' ? ' video' : '');
    const mini = it.thumb || '';
    div.innerHTML = `<img loading="lazy" src="${mini || it.src}" alt="">
      <div class="info"><b>${it.nombre}</b>${it.fecha}</div>`;
    div.onclick = () => abrirVisor(i);
    rejilla.appendChild(div);
  });
}

busqueda.addEventListener('input', aplicar);
document.querySelectorAll('.filtro').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.filtro').forEach(b => b.classList.remove('activo'));
    btn.classList.add('activo');
    tipoActual = btn.dataset.tipo;
    aplicar();
  };
});

/* ---- Visor a pantalla completa ---- */
const visor = document.getElementById('visor');
const visorContenido = document.getElementById('visor-contenido');
const visorPie = document.getElementById('visor-pie');

function abrirVisor(i) {
  indice = i;
  const it = filtrados[i];
  visorContenido.innerHTML = it.tipo === 'video'
    ? `<video src="${it.src}" controls autoplay></video>`
    : `<img src="${it.src}" alt="">`;
  visorPie.innerHTML = `<b>${it.nombre}</b> · ${it.fecha} · ${indice+1} de ${filtrados.length}`;
  visor.classList.add('abierto');
  document.body.style.overflow = 'hidden';
}
function cerrarVisor() {
  visor.classList.remove('abierto');
  visorContenido.innerHTML = '';
  document.body.style.overflow = '';
}
function mover(delta) {
  if (!filtrados.length) return;
  abrirVisor((indice + delta + filtrados.length) % filtrados.length);
}

document.getElementById('cerrar').onclick = cerrarVisor;
document.getElementById('anterior').onclick = () => mover(-1);
document.getElementById('siguiente').onclick = () => mover(1);
document.addEventListener('keydown', e => {
  if (!visor.classList.contains('abierto')) return;
  if (e.key === 'Escape') cerrarVisor();
  if (e.key === 'ArrowLeft') mover(-1);
  if (e.key === 'ArrowRight') mover(1);
});
visor.addEventListener('click', e => { if (e.target === visor) cerrarVisor(); });

cargar();
</script>
</body>
</html>
"""


# ----------------------------- Generación y servicio -----------------------------

def generar_galeria(carpeta: Path) -> bool:
    print(f"Explorando {carpeta} …")
    elementos = construir_indice(carpeta)

    if not elementos:
        print("No se encontraron fotos ni vídeos para la galería.")
        return False

    (carpeta / "galeria.json").write_text(
        json.dumps(elementos, ensure_ascii=False, indent=1), encoding="utf-8")
    (carpeta / "galeria.html").write_text(PLANTILLA_HTML, encoding="utf-8")

    fotos_n = sum(1 for e in elementos if e["tipo"] == "foto")
    videos_n = len(elementos) - fotos_n
    print(f"Galería generada: {fotos_n} foto(s) y {videos_n} vídeo(s).")
    print("Se sirve con: python main.py galeria <carpeta> --servir "
          "(no abrir el HTML con doble clic: el navegador bloquea file://).")
    return True


def servir(carpeta: Path, puerto: int):
    """Sirve la carpeta por HTTP local y abre el navegador."""
    import functools
    manejador = functools.partial(SimpleHTTPRequestHandler, directory=str(carpeta))
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), manejador)
    url = f"http://127.0.0.1:{puerto}/galeria.html"
    print(f"Galería disponible en {url}  (Ctrl+C para detener)")
    webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
