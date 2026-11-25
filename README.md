# PersonalLibraryManager

Organiza, renombra y optimiza tu biblioteca personal de **fotos, vídeos y notas de voz**, y
la explora en una **galería web local** con búsqueda por fecha, etiquetas, personas, lugares
o cámara. Todo funciona en tu equipo, sin subir nada a ningún sitio.

- **Importa** desde el móvil, una tarjeta o cualquier carpeta: cada archivo se ordena en
  `Año/Mes`, se renombra con su fecha de captura (`20240810_190211.jpg`) y se optimiza
  (fotos a 3200 px, vídeos en H.264/H.265) conservando EXIF, GPS, etiquetas y perfil de color.
- **El origen solo se lee**: nunca se mueve, modifica ni borra nada de la carpeta de origen.
- **Incremental**: vuelve a importar la misma carpeta cuando quieras; solo se procesa lo nuevo.
- **Detecta** duplicados, fotos casi idénticas (copias de WhatsApp, reenvíos) y archivos dañados.
- **WhatsApp aparte**: lo de WhatsApp va a su propia carpeta y la galería no lo mezcla con el resto.
- **Galería web**: línea de tiempo, buscador, favoritos, caras, lugares sin conexión y una
  herramienta para **limpiar repetidas** con papelera restaurable.
- **Google Fotos (Takeout)**: importa la descarga de Google Fotos grabando en cada foto y
  vídeo lo que dicen sus JSON (fecha, GPS, personas, descripción y álbumes como etiquetas).
- **Fusiona colecciones**: añade otra biblioteca (p. ej. la de Google Fotos) sin repetir
  nada y quedándote siempre con la copia de más calidad.
- **Panel web** para elegir opciones, lanzar y seguir el progreso sin usar la terminal.

## Instalación

Necesitas **Python 3.10 o superior** y, para vídeos, **FFmpeg**.

### Windows

```powershell
# 1. Python 3.10+ desde https://www.python.org (marca "Add python.exe to PATH")
# 2. FFmpeg (vídeos, miniaturas de vídeo y duración de los audios)
winget install Gyan.FFmpeg

# 3. Descarga el proyecto y sus dependencias
git clone https://github.com/illanos/PersonalLibraryManager.git
cd PersonalLibraryManager
pip install -e ".[todo]"
```

Abre una terminal nueva después de instalar FFmpeg para que se reconozca el comando.

`pip install -e ".[todo]"` instala el paquete `exportador` con todas sus dependencias y el
comando `exportador` (equivale a `python -m exportador`). Con `pip install -e .` se instala
solo lo imprescindible (Pillow).

### macOS / Linux

```bash
brew install ffmpeg            # macOS (Homebrew)
sudo apt install ffmpeg        # Debian / Ubuntu

git clone https://github.com/illanos/PersonalLibraryManager.git
cd PersonalLibraryManager
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[todo]"
```

### Dependencias

| Paquete | Para qué | ¿Obligatorio? |
|---|---|---|
| `Pillow` | Fotos | Sí |
| `pillow-heif` | Fotos HEIC/HEIF del iPhone (extra `heic`) | No: sin él se omiten con un aviso |
| `opencv-python` | Agrupar caras en la galería, `--caras` (extra `caras`) | No |
| FFmpeg | Vídeos y miniaturas de vídeo | Solo para vídeos |

¿Sin instalar el paquete? También vale `pip install -r requirements.txt` y ejecutar los
comandos desde la carpeta `src` (`cd src`, luego `python -m exportador …`).

Datos opcionales que se descargan **una sola vez** a `datos/` (después todo funciona sin conexión):

```powershell
python -m exportador galeria "D:\Biblioteca" --descargar-lugares        # ciudades (GeoNames), ~3 MB
python -m exportador galeria "D:\Biblioteca" --descargar-modelos-caras  # modelos de caras, ~38 MB
```

## Primeros pasos: el panel web

La forma más cómoda: doble clic en **`panel.bat`** (Windows) o

```powershell
python -m exportador panel
```

Se abre `http://127.0.0.1:8765/` en el navegador. Elige qué hacer (importar todo, solo fotos,
vídeos o audio, generar la galería, reorganizar o **fusionar** otra colección), las carpetas y
las opciones, pulsa **Simular** para ver qué pasaría y después **Importar** (o **Fusionar**).
Debajo del formulario aparece el comando equivalente por si prefieres la terminal.

## Ejemplos de uso desde la terminal

Todos los comandos aceptan `--simular` (muestra qué haría sin tocar nada) y `-h` para ver
todas sus opciones: `python -m exportador fotos -h`. Con el paquete instalado, `exportador`
a secas es lo mismo que `python -m exportador`.

### Importar todo de una vez

```powershell
# Primero, en simulación: no crea ni modifica nada
python -m exportador todo "C:\Users\Tu\Pictures\Movil" --destino "D:\Biblioteca" --simular

# Fotos + vídeos + notas de voz + galería, y abre la galería al terminar
python -m exportador todo "C:\Users\Tu\Pictures\Movil" --destino "D:\Biblioteca" --servir
```

Sin `--destino`, la biblioteca se crea junto al origen como `<origen>_organizados`.

### Importar por partes

```powershell
# Solo fotos, en WebP (~30 % menos peso) y sin la peor copia de cada grupo de casi idénticas
python -m exportador fotos "C:\Users\Tu\Pictures\Movil" --destino "D:\Biblioteca" --formato webp --omitir-parecidas

# Solo vídeos, en H.265, con la GPU si la hay y dos a la vez
python -m exportador videos "C:\Users\Tu\Videos" --destino "D:\Biblioteca" --codec h265 --hw auto --hilos-video 2

# Notas de voz y audios (se copian sin recomprimir)
python -m exportador audio "C:\Users\Tu\Pictures\Movil" --destino "D:\Biblioteca"

# Guardar además una copia intacta de cada original en originales/
python -m exportador fotos "E:\DCIM" --destino "D:\Biblioteca" --con-originales
```

Repetir la importación más adelante (por ejemplo, cada vez que vacías el móvil en la misma
carpeta) solo procesa lo nuevo.

### Galería web

```powershell
# Generar la galería y abrirla en el navegador
python -m exportador galeria "D:\Biblioteca" --servir

# Con detección y agrupación de caras para ponerles nombre (requiere opencv-python)
python -m exportador galeria "D:\Biblioteca" --servir --caras
```

Abrir `galeria.html` con doble clic no funciona (el navegador bloquea la lectura de archivos
locales): usa siempre `--servir`. Desde la galería, el botón **Limpiar repetidas** muestra
los grupos de fotos casi idénticas, propone la mejor copia y mueve las demás a una papelera
de la biblioteca, desde la que se pueden restaurar.

Los vídeos de menos de 5 segundos (sobre todo, los clips de las fotos con movimiento del móvil)
tienen su propio botón, **Fotos en movimiento**, y no salen en *Vídeos*. Es solo cosa de la
galería: no cambian de carpeta ni de nombre, y los cortos de WhatsApp siguen en su vista.

### Importar un Takeout de Google Fotos

Igual que `todo`, para la carpeta `Google Fotos` de un Takeout: cada foto y vídeo recibe lo
que dice su JSON y no trae dentro (fecha, GPS), además de personas, descripción y los álbumes
como etiquetas. Los JSON no se copian, de las versiones `-editada` se importa solo el original
y el clip de cada foto con movimiento se importa como vídeo con el mismo nombre que su foto.

```powershell
python -m exportador google "G:\Takeout\Google Fotos" --destino "D:\Google" --simular
python -m exportador google "G:\Takeout\Google Fotos" --destino "D:\Google"
```

### Fusionar otra colección

Añade a una biblioteca lo que le falta de otra (por ejemplo, la exportación de Google
Fotos), comparando por días: lo que ya está no se añade y, de dos copias iguales, se queda la
de más calidad; la peor va a la papelera, desde donde se puede restaurar. La que se queda
gana los metadatos de la otra (fecha, ubicación, cámara, descripción, álbumes, personas,
valoración), quedándose en cada uno con el más completo y sin recomprimir nada. Lo que
pasa del límite de la exportación (3200 px en fotos, 1920 en vídeos) entra reducido, como
al importar. Antes de copiar comprueba que cabe en el disco (dejando 2 GB libres); si no,
no empieza.

```powershell
# Simular: el plan completo queda en un CSV para revisarlo en Excel
python -m exportador fusionar "D:\Google" --destino "D:\Biblioteca" --simular

# Fusionar de verdad (la colección "D:\Google" solo se lee)
python -m exportador fusionar "D:\Google" --destino "D:\Biblioteca"

# Sin tocar los metadatos de lo que ya está, y vídeos hasta 4K
python -m exportador fusionar "D:\Google" --destino "D:\Biblioteca" --sin-metadatos --max-lado-video 3840

# Una carpeta llena de copias de lo que ya hay: solo entra lo que no está, sin sustituir
# nada de la biblioteca y sin las fotos parecidas (otras tomas, editadas)
python -m exportador fusionar "E:\Fotos viejas" --destino "D:\Biblioteca" --sin-sustituir --omitir-parecidas
```

### Reorganizar una biblioteca ya importada

```powershell
# Separar en WhatsApp/ lo de WhatsApp importado con versiones antiguas y
# renombrar lo que se importó sin hora (solo mueve archivos dentro de la biblioteca)
python -m exportador reorganizar "D:\Biblioteca" --whatsapp --fechas-aproximadas --simular
python -m exportador reorganizar "D:\Biblioteca" --whatsapp --fechas-aproximadas
```

## Qué se obtiene

```
Biblioteca/
├── 2024/08-Agosto/20240810_190211.jpg        fotos y vídeos, por fecha de captura
├── WhatsApp/2024/08-Agosto/…                 lo de WhatsApp, separado del resto
├── Audio/2024/08-Agosto/…                    notas de voz y audios
├── galeria.html + galeria.json               la galería web
├── _galeria/                                 miniaturas, favoritos, caras
└── .exportador/                              catálogo, informes CSV y papelera
```

Cada ejecución deja un informe CSV en `.exportador/informes/` (se abre en Excel) con qué se
hizo con cada archivo.

## Ayuda con Claude Code

El proyecto incluye una *skill* para [Claude Code](https://claude.com/claude-code) en
`.claude/skills/exportador/`: abre Claude Code en esta carpeta y pídele, en tus palabras,
lo que quieras hacer («importa las fotos del móvil», «fusiona la biblioteca de Google con la
principal», «¿por qué esta foto tiene fecha dudosa?»). Conoce todos los comandos y opciones,
siempre simula primero y no ejecuta nada de verdad sin preguntarte.

## Estructura

```
src/exportador/   el código (paquete Python) y sus plantillas web
tests/            pruebas automáticas
doc/              documentación (ARQUITECTURA.md)
pyproject.toml    paquete, dependencias y comando `exportador`
panel.bat         abre el panel con doble clic
```

## Pruebas

```powershell
python -m unittest discover -s tests -t .
```

Desde la raíz del proyecto, sin necesidad de instalar nada más que las dependencias. No
necesitan FFmpeg ni OpenCV: los tests de vídeo y de caras los simulan (el único test con
FFmpeg real se salta si no está instalado).

## Más información

[doc/ARQUITECTURA.md](doc/ARQUITECTURA.md) explica en detalle cada comando y opción, las
decisiones de diseño (fechas, nombres, metadatos, duplicados, papelera, seguridad del servidor
local) y la organización del código.

## Licencia

[MIT](LICENSE)
