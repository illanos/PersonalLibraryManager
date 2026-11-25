# Notas

Una de las utilidades de [PersonalLibraryManager](../../README.md): tu libreta personal, con notas de
**texto**, **imágenes** y **notas de voz**, en una página web que funciona en tu equipo y no sube
nada a ningún sitio.

- **Apunta** escribiendo, pegando o soltando imágenes, o **grabando tu voz** desde la propia página.
  Una nota puede llevar las tres cosas.
- **Categorías**: ponle una o varias a cada nota, filtra por ellas o agrupa la vista por categoría.
- **Busca** en títulos, textos, categorías y nombres de archivo, sin distinguir mayúsculas ni acentos;
  con `"frase exacta"` y `-palabra` para excluir.
- **Organiza**: fija arriba lo importante, ponle color, archiva lo que ya no usas, y elige varias notas
  a la vez para moverlas de golpe.
- **Listas con casillas**: las líneas que empiezan por ☐ o ☑ se marcan pulsándolas.
- **Trae tus notas de Google Keep**, con sus listas, etiquetas, colores, fechas, imágenes y audios.
- **Se guarda solo** mientras escribes. Si tienes la misma nota abierta en dos ventanas, no se pisan.
- **Papelera**: nada se borra sin querer; todo se puede deshacer o restaurar.
- **Copia de seguridad** en un ZIP, desde la página o la terminal.
- También **desde la terminal**: crear, buscar, editar y ordenar notas.

## Instalación

Solo necesitas **Python 3.10 o superior**; no hay dependencias obligatorias.

| Paquete | Para qué | ¿Obligatorio? |
|---|---|---|
| `Pillow` | Miniaturas, para que la página vaya ligera con muchas fotos, y reducir las imágenes al importar | No: sin él se usa la imagen original |
| [ffmpeg](https://ffmpeg.org) | Pasar a M4A las notas de voz de Google Keep al importarlas | No: sin él, esas notas no se importan |

```powershell
pip install Pillow                    # opcional
pip install -e utilidades/notas       # opcional: el comando `notas` en la terminal
```

## Primeros pasos

Doble clic en **`notas.bat`**, en la raíz del repositorio (Windows), o

```powershell
cd utilidades/notas/src
python -m notas abrir
```

Se abre `http://127.0.0.1:8790/` en el navegador. La primera vez que grabes, el navegador te pedirá
permiso para usar el micrófono. Cierra la ventana de la consola para apagarlo.

| Tecla | Qué hace |
|---|---|
| `n` | Nota nueva |
| `/` | Buscar |
| `Esc` | Cerrar la nota (se guarda sola) o quitar la selección |
| `Mayús` + clic en ✓ | Elegir todas desde la última elegida |

## Dónde se guardan

En la carpeta `Notas` de tu usuario (`C:\Users\Tú\Notas`), **fuera del repositorio**:

```
Notas/
├── notas.sqlite     los textos, categorías, colores…
├── adjuntos/        imágenes y notas de voz, por año y mes, tal cual las añadiste (al importar, reducidas)
└── copias/          copias de seguridad
```

Para usar otra carpeta (por ejemplo, una que se sincronice o en otro disco): `--cuaderno CARPETA` o la
variable de entorno `NOTAS_CUADERNO`. No abras el mismo cuaderno desde dos equipos a la vez.

## Desde la terminal

Con el paquete instalado, `notas` equivale a `python -m notas`.

```powershell
# Crear
notas nueva "Llamar al dentista" --categoria Salud --fijar
notas nueva "Plano del garaje" --titulo "Garaje" --adjunto C:\fotos\plano.jpg --categoria Casa

# Buscar y ver
notas listar --buscar "instalador cocina"
notas listar --categoria Casa --tipo voz
notas ver 12

# Cambiar
notas editar 12 --anadir "Presupuesto: 300 €" --color menta
notas editar 12 --poner-categoria Cocina --archivar
notas borrar 12              # a la papelera
notas restaurar 12

# Categorías y copia de seguridad
notas categorias --renombrar Cocina Reformas
notas copia D:\copias
```

`notas <comando> -h` enseña todas las opciones.

## Importar de Google Keep

1. Pide tus datos en [takeout.google.com](https://takeout.google.com) marcando solo **Keep** (Conservar) y
   descomprime el ZIP.
2. Mira qué se importaría, sin escribir nada: `notas importar "D:\Takeout" --simular`
3. Impórtalas: `notas importar "D:\Takeout"` (en otra carpeta, `--cuaderno CARPETA`).

Se conservan el título, el texto, las listas con lo que está marcado, las etiquetas (como categorías), el
color, si estaba fijada, archivada o en la papelera, las fechas, las imágenes y las notas de voz. Además,
en los detalles de cada nota: los enlaces con el título de su página, con quién se compartió y si tenía
recordatorio. El formato del texto (negrita, subrayado…) no se conserva.

Las imágenes se guardan a 1920 píxeles y calidad 80, de sobra para verlas en pantalla: `--lado` y
`--calidad` lo cambian, y `--lado 0` las deja como están. Puedes repetir la importación con un Takeout más
nuevo: solo añade las notas que falten. El Takeout no se toca.

## Copia de seguridad

**Descargar copia** (abajo a la izquierda en la página) o `notas copia`. El ZIP lleva todo, incluido
un `notas.json` legible sin el programa. Para restaurarla, descomprímela en una carpeta vacía y ábrela
con `notas abrir --cuaderno "<esa carpeta>"`.

## Límites

- Es para **este equipo**: no se puede abrir desde el móvil ni se sincroniza entre ordenadores.
- La búsqueda **no entra en lo que se dice** en las notas de voz (no las transcribe): ponles un título.
- Las imágenes **HEIC** del iPhone no se ven en los navegadores: guárdalas antes como JPEG.

## Pruebas

```powershell
cd utilidades/notas
python -m unittest discover -s tests -t .
```

## Más información

[doc/ARQUITECTURA.md](doc/ARQUITECTURA.md) explica cómo está hecho y por qué, y [MAPA.md](MAPA.md), dónde
está cada cosa en el código.

## Licencia

[MIT](../../LICENSE)
