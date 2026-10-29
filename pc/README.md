# Griffin Client Language Switcher

Parche local reversible para elegir **chino, inglés o español** en el cliente de GF2 (builds enumerados abajo). Funciona sin conexión: todo el texto sale del paquete de idiomas incluido en esta carpeta (`data/language-pack-v2.json.gz`); no descarga nada ni depende de ningún servidor o repositorio externo.

## Uso en Windows

Requisito: Python 3.11 o posterior con Tkinter (incluido en el instalador de python.org). No hay que instalar paquetes.

1. Cierra el juego.
2. Ejecuta `Iniciar parche de idioma.cmd` (o `Start language patcher.cmd`).
3. Pulsa `Español`, `English` o `中文 · Restaurar`.

**Administrador.** Si el juego está en una carpeta protegida (por ejemplo `C:\Program Files\GF2Exilium\GF2 Game`), el parcheador lo detecta y Windows pide permiso de administrador (UAC) antes de escribir; al aceptar, se abre una ventana nueva que termina la operación. Si lo rechazas no se cambia nada. En carpetas normales no hace falta.

Desde PowerShell:

```powershell
python pc\patcher.py status
python pc\patcher.py es          # también: en, cn
python pc\patcher.py --game-dir "D:\GF2_Exilium\Games" es
python pc\patcher.py es --dry-run   # construye y valida sin escribir
```

Las copias exactas de las tablas chinas y el diario de escritura están en `%LOCALAPPDATA%\Griffin\ClientPatcher\<perfil>\`. `cn` restaura byte por byte las dos tablas originales respaldadas. Una interrupción a mitad de escritura se deshace sola (restaura el chino) en el siguiente uso.

## Builds aceptados

- CN 4.0.5136, CodeRes `4.0.5136.0.14794`, CacheRes `4.0.5136.0.28495`, tablas 1189260.
- Bilibili 4.0.5142, CodeRes `4.0.5142.0.14870`, CacheRes `4.0.5142.0.28655`, tablas 1192505.
- Bilibili 4.0.5142, CodeRes `4.0.5142.0.14897`, CacheRes `4.0.5142.0.28655`, tablas 1193440.

Cualquier otro build 4.x cuyas tablas de idioma sigan siendo las chinas sin tocar (el juego saca actualizaciones en caliente con nuevos CodeRes/CacheRes) se acepta automáticamente con un perfil `dyn-…` que guarda sus hashes originales la primera vez. Para los builds enumerados, los hashes de las tablas chinas originales están fijados: el parcheador rechaza otra versión, otra tabla o una tabla editada fuera de él. No modifica ejecutables, proxy, certificados, el selector regional ni las tablas del servidor. Con el juego abierto no hace nada. El selector de idioma del propio juego seguirá mostrando chino; usa este programa para cambiar el contenido.

## Qué hay en el paquete de idiomas

`data/language-pack-v2.json.gz` (con su `.sha256`, que se comprueba al cargarlo) asocia el texto chino de cada fila con su traducción al inglés y al español, y marca cuáles son automáticas:

- **Traducción oficial** (la del juego Global) cuando un texto chino tiene una sola traducción oficial.
- **Traducción automática local** (modelos Argos Translate sin conexión) cuando no hay traducción oficial única. Pasa un filtro de calidad (sin letras de otros alfabetos, sin repeticiones, mismas variables `{0}`, etiquetas y saltos de línea). El español automático se hace desde el inglés. Lo que no pasa el filtro se deja en chino.

El resultado indica cuántas filas son oficiales, cuántas automáticas y cuántas siguen en chino (nombres propios, onomatopeyas y algunos fragmentos largos). El texto dibujado dentro de imágenes o fijo en el programa no está en estas tablas y no se traduce.

La tabla del cliente conserva filas, IDs y todas las columnas salvo el texto; el índice de páginas se reconstruye y se valida después de escribir. Si el cliente reserializa la tabla incorporada al arrancar, el parcheador lo reconoce solo cuando la tabla principal conserva el hash exacto del parche activo.

## Para quien mantiene el paquete

Solo hace falta para regenerar el paquete (no para usar el parche):

1. `python pc\generate-machine-fallback.py` traduce con Argos lo que no tiene traducción oficial y guarda la caché en `%LOCALAPPDATA%\Griffin\ClientPatcher\cache`. Usa la tarjeta NVIDIA si está disponible (`pip install nvidia-cublas-cu12`); `ARGOS_DEVICE_TYPE=cpu` fuerza el procesador. `GRIFFIN_REGEN_ES=1` rehace todo el español.
2. `python pc\build_language_pack.py` une las traducciones oficiales de las tablas Global (descarga una vez el archivo fijado por tamaño y SHA-256 en `patcher.py`) con la caché y escribe `data\language-pack-v2.json.gz` y su `.sha256`.
3. `python pc\package_release.py` crea `release\Griffin-ClientLanguagePatcher-<fecha>.zip` con lo que necesita un jugador, para subirlo a la release de GRIFFIN-ES.

Pruebas: `python -m unittest discover -s pc\tests -v`.

---

# English

Reversible local patch to switch the GF2 client between **Chinese, English and Spanish** (builds listed above). It works offline: all text comes from the language pack in this folder (`data/language-pack-v2.json.gz`); nothing is downloaded and nothing depends on an external server or repository.

On Windows close the game, run `Start language patcher.cmd` and pick a language. If the game lives in a protected folder (for example `C:\Program Files\GF2Exilium\GF2 Game`) the patcher detects it and Windows asks for administrator permission (UAC) before writing; if you decline, nothing is changed. CLI: `python pc\patcher.py status|en|es|cn [--game-dir DIR] [--dry-run]`.

Only the exact table fingerprints of the builds above are accepted. Original Chinese tables are backed up once in `%LOCALAPPDATA%\Griffin\ClientPatcher` and `cn` restores them byte for byte; an interrupted write is rolled back to Chinese on the next run. No executable, server table, proxy or certificate is touched, and the game's own language menu keeps showing Chinese.

The pack maps each Chinese line to its English and Spanish text: the official Global translation when a line has exactly one, otherwise an offline machine translation that passed a quality filter (Spanish is produced from English); anything else stays Chinese. Text drawn inside images or hard-coded in the client is not in these tables. Maintainers rebuild the pack with `generate-machine-fallback.py`, `build_language_pack.py` and `package_release.py` (the release zip contains only what a player needs).
