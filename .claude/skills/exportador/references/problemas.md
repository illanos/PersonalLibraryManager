# Problemas frecuentes

| Mensaje o síntoma | Causa | Qué hacer |
|---|---|---|
| `No module named exportador` | El paquete no está instalado y no se ejecuta desde `src/` | `PYTHONPATH=utilidades/fotos/src` desde la raíz del monorepo, o, con permiso del usuario, `pip install -e "utilidades/fotos[todo]"` |
| `Falta la librería Pillow` | Sin Pillow | `pip install Pillow` (o `pip install -e utilidades/fotos`) |
| `FFmpeg no está disponible en la terminal` | Sin FFmpeg (o terminal abierta antes de instalarlo) | `winget install Gyan.FFmpeg` y abrir una terminal nueva. En `todo`/`google` los vídeos se omiten con un aviso; `videos` no arranca |
| `AVISO: se omiten N foto(s) HEIC/HEIF` | Falta `pillow-heif` | `pip install pillow-heif` y repetir el mismo comando: solo importará esas |
| `AVISO: se omiten las caras porque falta OpenCV` | `--caras` sin `opencv-python` | `pip install opencv-python` |
| `AVISO: caras con el detector básico (agrupa poco)` | Faltan los modelos YuNet/SFace | `galeria <biblioteca> --descargar-modelos-caras --caras` (una vez, ~38 MB) |
| `AVISO: sin lugares …` | No se han descargado las ciudades | `galeria <biblioteca> --descargar-lugares` (una vez, ~3 MB) |
| `no se han podido descargar …` | Sin conexión | La galería se genera igual; se reintenta la próxima vez |
| `La carpeta de origen no existe` / `La carpeta no existe` | Ruta mal escrita o unidad desconectada | Revisar la ruta (comillas, letra de unidad). Móvil por MTP: copiar antes DCIM al disco |
| `El destino no puede estar dentro del origen ni coincidir con él` | `--destino` dentro de la carpeta que se importa | Elegir una biblioteca fuera del origen |
| `La colección y la biblioteca deben ser carpetas distintas y ninguna dentro de la otra` | `fusionar` con carpetas anidadas | Carpetas hermanas |
| `La biblioteca no existe` (fusionar) | `--destino` aún no creada | Fusionar es para añadir a una biblioteca existente; para una nueva, importar (`todo`) |
| `ERROR: No hay espacio suficiente en el disco de …` (fusionar) | Lo que entra no cabe dejando 2 GB libres; no se copia nada | Liberar espacio o fusionar en otro disco; la simulación ya lo avisa con el espacio necesario |
| `Indica qué reorganizar: --whatsapp y/o --fechas-aproximadas` | `reorganizar` sin opciones | Añadir una de las dos |
| `AVISO: se omiten N vídeo(s): para compararlos hace falta FFmpeg` (fusionar) | Sin FFmpeg | Instalarlo; las fotos se fusionan igual |
| La galería sale en blanco o pide servirla | Se abrió `galeria.html` con doble clic (`file://`) | `galeria <biblioteca> --servir` |
| El puerto está ocupado | Otro servidor en 8080/8765 | Prueba solo los siguientes; o `--puerto N` |
| No aparecen las fotos de WhatsApp en la galería | Van en su vista aparte | Botón *WhatsApp* de la galería |
| Una foto borrada a mano ha vuelto | La importación incremental trae lo que falta | Quitarla con *Limpiar repetidas* (papelera + no reimportar) |
| Fotos con *Fecha dudosa* | Sin EXIF ni fecha en el nombre: se usó la del archivo | Normal en fotos reenviadas o descargadas. Si vienen de Google, el JSON del Takeout o una fusión con la copia buena lo arreglan |
| Vídeos `SIN_CAMBIOS` o fotos que pesan igual | Recomprimir no compensaba | Correcto: se conserva el original tal cual |
| La GPU falla (`--hw`) | Codificador no disponible o driver | Se repite por software solo; o `--hw no` |
| Se cortó la luz / Ctrl+C a mitad | — | Volver a lanzar el mismo comando: no quedan archivos a medias y sigue donde iba |
| «database is locked» o va lento al empezar | Otra ejecución (o el panel) usando la misma biblioteca | Una ejecución a la vez por biblioteca |
| Movió el Takeout o la carpeta de origen | — | Relanzar con la ruta nueva: lo ya importado se reconoce por MD5 (la primera vez relee los archivos) |
| Muchas `parecidas` tras fusionar | Ráfagas o fotos muy similares que no son copias | Revisarlas en *Limpiar repetidas* |

Si el problema no está aquí: lee la salida completa (los avisos dicen qué falta), el
informe CSV de la ejecución (`ERROR` con su detalle) y, para dudas de diseño,
`utilidades/fotos/doc/ARQUITECTURA.md`.
