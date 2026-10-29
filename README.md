# GRIFFIN-ES-EN · Girls' Frontline 2: Exilium en español e inglés

[Español](#español) · [English](#english)

---

## Español

Parches de traducción, hechos por fans, para el **cliente CN** de Girls' Frontline 2: Exilium en **Android** y **PC (Windows)**. Ponen el juego en **español** o en **inglés**.

Traducen la interfaz, la historia, los objetos, las misiones y el resto de textos que el juego guarda en sus tablas de idioma. Los ejecutables del juego no se modifican: solo se reemplazan las tablas de idioma y siempre se guarda un respaldo para volver al chino.

> Proyecto no oficial, sin relación con SunBorn ni MICA Team. Funciona con el cliente oficial y con servidores privados como [GRIFFIN](https://github.com/jhon1466/GRIFFIN).

### Descargas

Todo está en [**Releases**](../../releases/latest):

| Archivo | Para qué sirve |
|---|---|
| `GRIFFIN-ES-EN-<versión>-android.apk` | App instaladora para Android (usa Shizuku). Trae los dos idiomas dentro. |
| `gf2-es-android-<versión>.zip` / `gf2-en-android-<versión>.zip` | Paquetes sueltos para Android, por si quieres cargarlos a mano con **Usar otro ZIP**. |
| `GRIFFIN-ES-EN-PC-<fecha>.zip` | Parche para PC (cambia entre chino, inglés y español). |

### Android

Requiere [Shizuku](https://github.com/RikkaApps/Shizuku/releases) para poder escribir en `Android/data`.

1. Abre el juego una vez y deja que termine de descargar.
2. Instala y arranca Shizuku.
3. Instala el APK y ábrelo.
4. Elige **Español** o **English**.
5. Pulsa **Conectar** y concede el permiso de Shizuku.
6. Pulsa **Instalar**. La app cierra el juego antes de escribir.

Puedes cambiar de idioma cuando quieras. **Volver al chino** restaura las tablas originales. Si una actualización del juego trae tablas nuevas, vuelve a instalar o carga un paquete nuevo con **Usar otro ZIP**.

### PC (Windows)

Requiere [Python 3.11](https://www.python.org/downloads/) o posterior (con Tkinter, incluido en el instalador de python.org).

1. Cierra el juego.
2. Descomprime `GRIFFIN-ES-EN-PC-<fecha>.zip` y ejecuta `Iniciar parche de idioma.cmd` (o `Start language patcher.cmd`).
3. Pulsa **Español** o **English**. Para volver, pulsa **中文 · Restaurar**.

Si el juego está en `C:\Program Files`, Windows pedirá permiso de administrador. Más detalles en [`pc/README.md`](pc/README.md).

### Traducción

Cada fila china de las tablas se sustituye por el texto **oficial del cliente Global** cuando tiene una traducción única; si no, por una traducción automática local que pasa un filtro de calidad (mismas variables, etiquetas y saltos de línea). Lo que no pasa el filtro se queda en chino. Se conservan IDs, orden y el resto de columnas, y el índice de páginas se reconstruye y se valida.

Tablas 1195672 (cliente 4.0.5136 de PC y 4.0.5137 de Android), de 518.230 filas:

| Idioma | Traducidas | Oficiales | Automáticas |
|---|---|---|---|
| Español | 516.104 | 335.326 | 180.778 |
| English | 516.192 | 351.904 | 164.288 |

El texto dibujado dentro de imágenes no está en las tablas y no se traduce.

### Estructura

| Carpeta | Contenido |
|---|---|
| `lib/`, `android/` | App instaladora de Android (Flutter + Shizuku) |
| `img/` | Icono de la app e imágenes del cliente (fondos de la pantalla de actualización, logo, iconos de los diálogos) |
| `pc/` | Parche de PC y el paquete de idiomas (`pc/data`) |
| `tools/build_patch_zip.py` | Genera los paquetes de Android a partir de las tablas chinas originales |

### Compilar

```
python tools/build_patch_zip.py --tables <carpeta con LangPackageTableCn*Data.bytes originales> --stc 1195672 --locale es
python tools/build_patch_zip.py --tables <la misma carpeta> --stc 1195672 --locale en
copy dist\gf2-*-android-1.0.0.zip patch\
flutter build apk --release
python pc/package_release.py
```

La firma de release se lee de `android/key.properties` (no está en el repositorio); sin ella el APK se firma con la clave de depuración.

---

## English

Fan-made translation patches for the **CN client** of Girls' Frontline 2: Exilium on **Android** and **PC (Windows)**. They switch the game to **Spanish** or **English**.

They translate the UI, story, items, missions and the rest of the text the game keeps in its language tables. The game executables are not modified: only the language tables are replaced, and a backup is always kept to go back to Chinese.

> Unofficial project, not affiliated with SunBorn or MICA Team. Works with the official client and with private servers such as [GRIFFIN](https://github.com/jhon1466/GRIFFIN).

### Downloads

Everything is in [**Releases**](../../releases/latest): the Android installer app (`GRIFFIN-ES-EN-<version>-android.apk`, both languages bundled), the loose Android packages (`gf2-es/en-android-<version>.zip`) and the PC patcher (`GRIFFIN-ES-EN-PC-<date>.zip`).

### Android

Requires [Shizuku](https://github.com/RikkaApps/Shizuku/releases) to write to `Android/data`.

1. Open the game once and let it finish downloading.
2. Install and start Shizuku.
3. Install the APK and open it.
4. Pick **English** or **Español**.
5. Tap **Connect** and grant the Shizuku permission.
6. Tap **Install**. The app closes the game before writing.

You can switch language at any time. **Back to Chinese** restores the original tables. If a game update ships new tables, install again or load a newer package with **Use another ZIP**.

### PC (Windows)

Requires [Python 3.11](https://www.python.org/downloads/) or later (with Tkinter, included in the python.org installer). Close the game, unzip `GRIFFIN-ES-EN-PC-<date>.zip`, run `Start language patcher.cmd` and pick **English** or **Español**; **中文 · Restaurar** goes back. If the game is under `C:\Program Files`, Windows asks for administrator permission. See [`pc/README.md`](pc/README.md).

### Translation

Each Chinese row is replaced by the **official Global client text** when it has a single translation; otherwise by a local machine translation that passes a quality filter. Anything else stays Chinese. IDs, order and every other column are kept, and the page index is rebuilt and validated. Coverage for tables 1195672 is in the table above (English: 516,192 of 518,230 rows; 351,904 official).
