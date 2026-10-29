# GRIFFIN-ES · Girls' Frontline 2: Exilium en español

Parches de traducción al español, hechos por fans, para el **cliente CN** de Girls' Frontline 2: Exilium en **Android** y **PC (Windows)**.

Traducen la interfaz, la historia, los objetos, las misiones y el resto de textos que el juego guarda en sus tablas de idioma. Los ejecutables del juego no se modifican: solo se reemplazan las tablas de idioma y siempre se guarda un respaldo para volver al chino.

> Proyecto no oficial, sin relación con SunBorn ni MICA Team. Funciona con el cliente oficial y con servidores privados como [GRIFFIN](https://github.com/jhon1466/GRIFFIN).

## Descargas

Todo está en [**Releases**](../../releases/latest):

| Archivo | Para qué sirve |
|---|---|
| `GF2ExiliumES-<versión>-android.apk` | App instaladora para Android (usa Shizuku). Trae el parche dentro. |
| `gf2-es-android-<versión>.zip` | Paquete del parche para Android, por si quieres cargarlo a mano con **Usar otro ZIP**. |
| `GRIFFIN-ES-PC-<fecha>.zip` | Parche para PC (cambia entre chino, inglés y español). |

## Android

Requiere [Shizuku](https://github.com/RikkaApps/Shizuku/releases) para poder escribir en `Android/data`.

1. Abre el juego una vez y deja que termine de descargar.
2. Instala y arranca Shizuku.
3. Instala `GF2ExiliumES-<versión>-android.apk` y ábrelo.
4. Pulsa **Conectar** y concede el permiso de Shizuku.
5. Pulsa **Instalar en español**. La app cierra el juego antes de escribir.

**Volver al chino** restaura las tablas originales. Si una actualización del juego trae tablas nuevas, vuelve a instalar o carga un paquete nuevo con **Usar otro ZIP**.

## PC (Windows)

Requiere [Python 3.11](https://www.python.org/downloads/) o posterior (con Tkinter, incluido en el instalador de python.org).

1. Cierra el juego.
2. Descomprime `GRIFFIN-ES-PC-<fecha>.zip` y ejecuta `Iniciar parche de idioma.cmd`.
3. Pulsa **Español**. Para volver, pulsa **中文 · Restaurar**.

Si el juego está en `C:\Program Files`, Windows pedirá permiso de administrador. Más detalles en [`pc/README.md`](pc/README.md).

## Traducción

Cada fila china de las tablas se sustituye por el texto **oficial en español del cliente Global** cuando tiene una traducción única; si no, por una traducción automática local que pasa un filtro de calidad (mismas variables, etiquetas y saltos de línea). Lo que no pasa el filtro se queda en chino. Se conservan IDs, orden y el resto de columnas, y el índice de páginas se reconstruye y se valida.

Tablas 1195672 (cliente 4.0.5136 de PC y 4.0.5137 de Android): **516.104 de 518.230** filas en español (335.326 oficiales, 180.778 automáticas). El texto dibujado dentro de imágenes no está en las tablas y no se traduce.

## Estructura

| Carpeta | Contenido |
|---|---|
| `lib/`, `android/` | App instaladora de Android (Flutter + Shizuku) |
| `img/game/` | Imágenes del cliente (fondos de la pantalla de actualización, logo, iconos de los diálogos) |
| `pc/` | Parche de PC y el paquete de idiomas (`pc/data`) |
| `tools/build_patch_zip.py` | Genera el paquete de Android a partir de las tablas chinas originales |

## Compilar

```
python tools/build_patch_zip.py --tables <carpeta con LangPackageTableCn*Data.bytes originales> --stc 1195672
copy dist\gf2-es-android-1.0.0.zip patch\
flutter build apk --release
python pc/package_release.py
```

La firma de release se lee de `android/key.properties` (no está en el repositorio); sin ella el APK se firma con la clave de depuración.
