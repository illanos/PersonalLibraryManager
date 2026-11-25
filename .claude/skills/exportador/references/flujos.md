# Recetas de uso

Todas siguen la regla de oro: primero `--simular`, resumir, confirmar, y luego de verdad.
Los ejemplos usan rutas de Windows; entre comillas siempre.

## Índice

1. Primera importación desde el móvil o una tarjeta
2. Volcados periódicos (cada mes, la misma carpeta)
3. Ajustar calidad, peso y tiempo
4. WhatsApp
5. iPhone: HEIC y Live Photos
6. Google Fotos (Takeout)
7. Fusionar dos colecciones
8. Limpiar repetidas
9. Galería: caras, lugares, favoritos
10. Reorganizar una biblioteca antigua
11. Conservar los originales
12. El panel web
13. Responder «¿por qué…?»

## 1. Primera importación desde el móvil o una tarjeta

```powershell
python -m exportador todo "E:\DCIM" --destino "D:\Biblioteca" --simular
python -m exportador todo "E:\DCIM" --destino "D:\Biblioteca" --servir
```

- `todo` = fotos + vídeos + audio + galería. `--servir` abre la galería al terminar (el
  proceso se queda sirviéndola hasta Ctrl+C; si lo lanzas tú en segundo plano, díselo).
- En la simulación fíjate en: archivos encontrados por tipo, cuántos con fecha de
  `archivo` (fecha dudosa: no traían EXIF ni fecha en el nombre), dañados, y que el destino
  sea el que el usuario espera.
- Si el móvil está conectado por MTP (no tiene letra de unidad), primero hay que copiar la
  carpeta DCIM al disco: el programa necesita una ruta de carpeta normal.

## 2. Volcados periódicos

Repetir **el mismo comando** con la misma biblioteca: solo se procesa lo nuevo (lo ya
importado se reconoce por ruta, tamaño y fecha, o por su MD5 si se movió). Lo descartado
a propósito (dañados, peor copia de parecidas) tampoco se vuelve a leer. Si en una versión
anterior se importaron cosas con nombre `AAAAMMDD_000000`, añade `--renombrar-aproximadas`.

## 3. Ajustar calidad, peso y tiempo

Fotos (por defecto JPEG, lado largo 3200 px, calidad 88, nunca más calidad que la del
original):

| Quiere… | Opciones |
|---|---|
| Menos peso, misma resolución | `--formato webp` (~30 % menos; WebP no guarda IPTC, se avisa) |
| Aún menos | `--max-lado 2560` o `--calidad 82` |
| Conservar la resolución completa | `--max-lado 0` |
| No traer la peor copia de cada grupo de casi idénticas | `--omitir-parecidas` |
| Ir más rápido / dejar CPU libre | `--hilos N` (por defecto según núcleos) |

Vídeos (por defecto H.264, 1920 px, CRF del perfil, preset `medium`, software):

| Quiere… | Opciones |
|---|---|
| Menos peso con calidad parecida | `--codec h265` (MP4 más ligero; algún reproductor antiguo no lo abre) |
| Ir mucho más rápido | `--hw auto` (GPU NVIDIA/Intel/AMD; archivos algo mayores; si falla, repite por software) y/o `--hilos-video 2` |
| Más calidad | `--crf` menor (p. ej. 20 en h264, 24 en h265) o `--preset slow` |
| Mantener 4K | `--max-lado-video 0` (o 3840) |
| Formato libre | `--codec vp9` (WebM; lento) |

Si recomprimir no compensa (saldría más pesado), se conserva el original tal cual: es
normal ver archivos con acción `SIN_CAMBIOS` en el informe.

## 4. WhatsApp

- Se detecta solo (nombres `IMG-AAAAMMDD-WA…`, `VID-…`, `PTT-…`, `STK-…` o carpetas de
  WhatsApp) y va a `WhatsApp/AAAA/MM-Mes/`; las notas de voz a `WhatsApp/Audio/`.
- En la galería solo aparece en la vista *WhatsApp* (botón), no en la línea de tiempo ni
  en la búsqueda: si el usuario «no ve» fotos de WhatsApp, es por eso.
- `--pegatinas-aparte` manda las pegatinas a `WhatsApp/Pegatinas/`.
- Las fotos de WhatsApp traen solo el día en el nombre: si la fecha del archivo es del
  mismo día se usa su hora (*Hora aproximada*); si no, el nombre queda `AAAAMMDD_WA0011`.
- Para las copias repetidas (Sent/ e Images/, reenvíos): `--omitir-parecidas` al importar o,
  mejor para revisarlas una a una, *Limpiar repetidas* (receta 8).

## 5. iPhone: HEIC y Live Photos

- Hace falta `pip install pillow-heif` (o `pip install -e ".[heic]"`); sin él las HEIC se
  omiten con un aviso y se importan en cuanto se instale y se repita el comando.
- Las HEIC se convierten a JPEG (o WebP) conservando EXIF, GPS y perfil de color.
- Los vídeos del iPhone usan la fecha local de Apple (`creationdate`) y se giran bien.
- Live Photos: la foto y su clip se importan como foto y vídeo por separado. En un Takeout,
  el clip usa el JSON de su foto y ambos quedan con el mismo nombre final.

## 6. Google Fotos (Takeout)

Recomendación: importar el Takeout a **una biblioteca propia** y después fusionarla con la
principal (receta 7). Así la principal no se toca hasta revisar el plan de la fusión.

```powershell
python -m exportador google "G:\Takeout\Google Fotos" --destino "D:\Google" --simular
python -m exportador google "G:\Takeout\Google Fotos" --destino "D:\Google"
```

- Se le pasa la carpeta `Google Fotos` del Takeout descomprimido (si hay varios ZIP,
  descomprimirlos todos en la misma carpeta).
- Lee todos los JSON primero y dice cuántos archivos tienen JSON y cuántos no.
- Graba en cada archivo lo que dice su JSON: fecha y GPS solo si el archivo no los trae;
  personas, descripción y álbumes (como etiquetas) siempre; favorita → 5 estrellas.
- Los JSON no se copian. De `foto-editada.jpg` se importa solo el original. El clip de las
  fotos con movimiento (`.MP`) se importa como vídeo con el mismo nombre que su foto.
- La misma foto en «Fotos del AAAA» y en álbumes se importa una vez con todos sus álbumes.
  Las copias de álbum recomprimidas: `--omitir-parecidas` (sus álbumes pasan a la que queda).
- Si se mueve el Takeout, relanzar con la ruta nueva: se reconoce lo ya importado por MD5.
- Admite las opciones de `todo` (calidad, códec, `--sin-galeria`…).

## 7. Fusionar dos colecciones

```powershell
python -m exportador fusionar "D:\Google" --destino "D:\Biblioteca" --simular
python -m exportador fusionar "D:\Google" --destino "D:\Biblioteca"
```

- La colección (primer argumento) solo se lee; la biblioteca (`--destino`) debe existir.
  Ninguna puede estar dentro de la otra. Los audios no se fusionan.
- La simulación deja el plan en un CSV de la carpeta temporal del sistema (la ruta sale al
  final): ábrelo o resúmelo por la columna `accion` — `ANADIDA` (nueva), `SUSTITUYE` (la de
  la colección es mejor; la de la biblioteca irá a la papelera), `YA_ESTA`, `REPETIDA`
  (repetida dentro de la colección), `QUITADA_ANTES` (se quitó antes con Limpiar
  repetidas), `PARECIDA` (con `--omitir-parecidas`), `METADATOS` (la de la biblioteca gana
  metadatos de la otra), `ERROR`.
- Compara por días (±`--margen-dias`, 1). Dos fotos son la misma si su dHash difiere
  ≤ `--umbral` bits (5), con la misma fecha EXIF si ambas la tienen, o si vienen del mismo
  original (mismo nombre y hora, o mismo MD5). Ráfagas: no son copias, se añaden (salen como
  *parecidas* para revisarlas luego).
- Se queda la de más calidad (resolución, EXIF de cámara, no WhatsApp, peso); a igualdad,
  la de la biblioteca. La que se queda **gana los metadatos** de la otra sin recomprimir
  (fecha, GPS, cámara, descripción, álbumes, personas, valoración); `--sin-metadatos` lo
  desactiva.
- Lo que entra y pasa del límite (`--max-lado` 3200 en fotos, `--max-lado-video` 1920 en
  vídeos) se exporta reducido, como al importar; lo demás se copia tal cual.
- Comprueba el espacio antes de copiar (deja 2 GB libres); si no cabe, no empieza.
- Subir `--umbral` (máx. 12) es más agresivo: más pares iguales, más riesgo de tomar dos
  fotos distintas por la misma. Solo si la simulación deja copias obvias sin emparejar.
- **Una carpeta llena de copias de lo que ya hay** (un disco viejo, una copia del móvil):
  `--sin-sustituir` no cambia nada de la biblioteca aunque llegue una copia mejor (solo
  gana sus metadatos) y `--omitir-parecidas` no añade lo que se parece a una foto de la
  biblioteca sin ser igual (ráfagas, editadas; acción `PARECIDA` en el informe). Así solo
  entra lo que de verdad no está. Úsalas cuando el usuario diga que no quiere repetidas
  ni parecidas, o que no se toque lo que ya tiene.
- Una segunda fusión solo mira lo nuevo. Al terminar actualiza la galería (salvo
  `--sin-galeria`) y el informe queda en `.exportador/informes/fusion_*.csv`.

## 8. Limpiar repetidas

```powershell
python -m exportador galeria "D:\Biblioteca" --servir
```

En la galería, botón **Limpiar repetidas** (o `http://127.0.0.1:<puerto>/limpiar.html`).

- Muestra grupos de fotos casi idénticas (umbral ajustable 0-24 bits; 12 por defecto),
  propone conservar la mejor (más píxeles, EXIF de cámara, no WhatsApp, no `Sent/`, más
  peso) y quitar las demás, con el motivo.
- Teclas: `←` `→` elegir, `Espacio` conservar/quitar, `Enter` confirmar y siguiente,
  `S` saltar, `N` no son repetidas, `A` o doble clic tamaño real, `Z` deshacer.
- Lo quitado va a `.exportador/papelera/` (restaurable desde *Papelera*) y no se vuelve a
  importar. Las decisiones se guardan al momento: se puede seguir otro día.
- Solo el usuario debe vaciar la papelera (escribiendo `VACIAR`): es irreversible.
- Necesita el servidor (`--servir`); no funciona con el HTML abierto con doble clic.

## 9. Galería: caras, lugares, favoritos

```powershell
python -m exportador galeria "D:\Biblioteca" --descargar-lugares --descargar-modelos-caras --caras --servir
```

- Las descargas (ciudades GeoNames ~3 MB, modelos de caras ~38 MB) se hacen **una vez** a la
  carpeta de datos; después todo funciona sin conexión. Sin conexión, la galería se genera
  igualmente y se reintenta la próxima vez.
- `--caras` requiere `opencv-python`; analiza solo lo nuevo. Los nombres se ponen en la
  ficha de cada foto (`I`) y se aplican a todo su grupo.
- `--regenerar` rehace metadatos y miniaturas de todo (lento); úsalo si cambiaron etiquetas
  en las fotos o algo se ve mal. Sin él, regenerar es incremental.
- `--puerto N` si el 8080 está ocupado (de todas formas prueba los siguientes);
  `--sin-navegador` para no abrirlo.
- Visor: flechas, `P` presentación, `F` pantalla completa, `S` favorito, `I` ficha.
  Favoritos en `_galeria/favoritos.json`.

## 10. Reorganizar una biblioteca antigua

Para bibliotecas importadas con versiones anteriores del programa:

```powershell
python -m exportador reorganizar "D:\Biblioteca" --whatsapp --fechas-aproximadas --simular
```

- `--whatsapp` mueve a `WhatsApp/` lo de WhatsApp que quedó mezclado (`--pegatinas-aparte`
  para las pegatinas). `--fechas-aproximadas` renombra los `AAAAMMDD_000000`.
- Solo mueve dentro de la biblioteca y actualiza catálogo, galería, caras y favoritos.
- Exige al menos una de las dos opciones.

## 11. Conservar los originales

`--con-originales` guarda además una copia intacta de cada original en `originales/`
(duplica el espacio). Por defecto no se hace porque el origen nunca se toca; recomiéndalo
solo si el usuario va a borrar el origen (p. ej. vaciar la tarjeta) y quiere los originales.

## 12. El panel web

`panel.bat` o `python -m exportador panel` → `http://127.0.0.1:8765/`. Formulario con todas
las opciones (sale del mismo `argparse`), comprobación en vivo de carpetas, botones
**Simular** e **Importar**/**Fusionar**, progreso en directo, registro descargable,
*Detener* (como Ctrl+C) y el comando equivalente para copiar. En el panel la galería sale
con caras y lugares activados por defecto. Una ejecución a la vez.

## 13. Responder «¿por qué…?»

| Pregunta | Dónde mirar |
|---|---|
| ¿Por qué tiene *Fecha dudosa*? | La fecha salió de la fecha del archivo (`fuente_fecha = archivo`): no traía EXIF ni fecha en el nombre. `estado_biblioteca.py --buscar`. Si es de Google, quizá el JSON lo arregla (`google`/`fusionar`). |
| ¿Por qué no se importó? | `--buscar` con su nombre: `DESCARTADO (danado …)`, `(parecida)` con la copia buena, o `QUITADA`; también el informe (`DUPLICADO`, `OMITIDA` = versión editada, `ERROR`). |
| ¿Dónde está la foto X? | `--buscar X` (nombre original o final) da el destino. |
| ¿Por qué no la veo en la galería? | ¿Es de WhatsApp (vista aparte)? ¿Capturas ocultas? ¿Está en la papelera? ¿Galería sin regenerar tras importar con `fotos`/`videos`? |
| ¿Por qué pesa más/menos? | Columnas `bytes_antes`/`bytes_despues` del informe; `SIN_CAMBIOS` = se copió tal cual. |
