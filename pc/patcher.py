#!/usr/bin/env python3
"""Reversible CN/EN/ES client language switcher for pinned Griffin builds."""
from __future__ import annotations

import argparse
import hashlib
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

import language_pack
from table_codec import extract_texts, replace_table_text, validate_structure, validate_subset_structure

ARCHIVE_URL = "https://gf2-us-cdn.sunborngame.com/prod/data/1151583/bk_stc_pb.zip"
ARCHIVE_SIZE = 183_858_679
ARCHIVE_SHA256 = "62f327e14caef69358836f15f823a71fb41abcf4c571dd80142c2e0352f97815"
LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
STATE_ROOT = LOCAL / "Griffin" / "ClientPatcher"
MACHINE_TRANSLATION_CACHE = STATE_ROOT / "cache" / "machine-translations-v1.json.gz"

PROFILES = {
    "cn-4.0.5136-1189260": {
        "code": "4.0.5136.0.14794", "cache": "4.0.5136.0.28495", "table": "1189260",
        "main": "2b1ca85aa5a8cc55efeaa8032ea768aa77d34f4a7f4e606d815b0435b60b43c5",
        "builtin": "8623d07ae1f628cbc193dd5b00fd6c9529d9a78b9365ef69c22a2c41385043f5",
    },
    "bilibili-4.0.5142-1192505": {
        "code": "4.0.5142.0.14870", "cache": "4.0.5142.0.28655", "table": "1192505",
        "main": "624ddcad3523f518060c4860a05c9129cd98ba32273540ce1226857c28b87071",
        "builtin": "8623d07ae1f628cbc193dd5b00fd6c9529d9a78b9365ef69c22a2c41385043f5",
    },
    "bilibili-4.0.5142-1193440": {
        "code": "4.0.5142.0.14897", "cache": "4.0.5142.0.28655", "table": "1193440",
        "main": "99fb3331b80b8bd8b209baf485fd2d2955a5324869821efde6590a96a14649fb",
        "builtin": "8623d07ae1f628cbc193dd5b00fd6c9529d9a78b9365ef69c22a2c41385043f5",
    },
}
TABLES = ("LangPackageTableCnData.bytes", "LangPackageTableCnBuiltinData.bytes")


class PatchError(RuntimeError):
    pass


class ElevationRequired(PatchError):
    """The game folder is protected (for example C:\\Program Files): the patcher has to run as administrator to write there."""


def is_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def relaunch_elevated(script: Path, arguments: list[str], keep_console: bool = False) -> bool:
    """Ask Windows (UAC) to run ``script`` again as administrator. True when the elevated copy was started, False when the user refused or it failed."""
    if os.name != "nt":
        return False
    import ctypes
    python = sys.executable
    if not keep_console and python.lower().endswith("python.exe"):
        windowed = python[:-len("python.exe")] + "pythonw.exe"
        if os.path.isfile(windowed):
            python = windowed
    if keep_console:
        parameters = subprocess.list2cmdline(["/k", python, str(script), *arguments])
        executable = os.environ.get("COMSPEC", "cmd.exe")
    else:
        parameters = subprocess.list2cmdline([str(script), *arguments])
        executable = python
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, parameters, str(script.parent), 1)
    return int(result) > 32


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_config(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def find_game_dirs() -> list[Path]:
    candidates = [Path(r"D:\GF2_Exilium\Games"), Path(r"C:\Program Files\GF2Exilium\GF2 Game")]
    return [p for p in candidates if (p / "GF2_Exilium_Data/LocalCache/Data/GameConfig.cfg").is_file()]


def managed_client_normalization(profile: str, table_dir: Path, hashes: dict[str, str]) -> bool:
    """Recognize the client's row-count normalization of the builtin language table."""
    active_path = STATE_ROOT / profile / "active.json"
    backup_dir, _ = state_paths(profile)
    try:
        active = json.loads(active_path.read_text(encoding="utf-8"))
        profile_info = PROFILES[profile]
        original_hashes = {TABLES[0]: profile_info["main"], TABLES[1]: profile_info["builtin"]}
        if active.get("profile") != profile or active.get("locale") not in ("en", "es"):
            return False
        if hashes[TABLES[0]] != active.get("current_hashes", {}).get(TABLES[0]):
            return False
        for filename in TABLES:
            backup = backup_dir / filename
            if not backup.is_file() or sha256(backup.read_bytes()) != original_hashes[filename]:
                return False
        validate_subset_structure((backup_dir / TABLES[1]).read_bytes(),
                                  (table_dir / TABLES[1]).read_bytes())
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def mostly_chinese(data: bytes) -> bool:
    """True when the table is an untouched Chinese language table (most non-empty rows contain CJK characters)."""
    try:
        texts = [text for text in extract_texts(data).values() if text]
    except (ValueError, IndexError, KeyError):
        return False
    if not texts:
        return False
    cjk = sum(any("一" <= ch <= "鿿" for ch in text) for text in texts)
    return cjk / len(texts) >= 0.5


def register_dynamic_profile(config: dict[str, str], table_dir: Path) -> None:
    """Accept a build that is not pinned above (the game keeps releasing hot updates, so any CodeRes/CacheRes/table combination can appear).

    The language pack matches rows by the Chinese text, not by build, so any build whose language tables are still the untouched Chinese ones can be
    patched. The profile is keyed by the exact versions; its original hashes are the ones of the tables found the first time (they must be Chinese
    and structurally valid) or, once patched, the ones the patcher recorded in ``active.json``.
    """
    code, cache, table = config.get("CodeResVersion"), config.get("CacheResVersion"), config.get("StcTableVersion")
    if not (code and cache and table) or any(p["code"] == code and p["cache"] == cache and p["table"] == table for p in PROFILES.values()):
        return
    name = f"dyn-{config.get('ClientVersion', 'x')}-{code}-{cache}-{table}"
    if name in PROFILES:
        return
    paths = {filename: table_dir / filename for filename in TABLES}
    if not all(path.is_file() for path in paths.values()):
        return
    originals = None
    active_path = STATE_ROOT / name / "active.json"
    if active_path.is_file():
        try:
            recorded = json.loads(active_path.read_text(encoding="utf-8")).get("original_hashes")
            if isinstance(recorded, dict) and all(filename in recorded for filename in TABLES):
                originals = recorded
        except (OSError, ValueError):
            pass
    if originals is None:
        backup_dir, _ = state_paths(name)
        backups = {filename: backup_dir / filename for filename in TABLES}
        # An interrupted first write leaves the exact originals in the backup folder.
        source = backups if all(path.is_file() for path in backups.values()) else paths
        main = source[TABLES[0]].read_bytes()
        if not mostly_chinese(main):
            # Already translated by an earlier patcher run under another profile: the same table version (StcTableVersion) has the same
            # Chinese originals, so take the exact backup of that profile and record the current files as the active patch.
            donor = next((STATE_ROOT / other / "original" for other, info in PROFILES.items()
                          if info["table"] == table and not other.startswith("dyn-")
                          and all((STATE_ROOT / other / "original" / f).is_file() for f in TABLES)
                          and sha256((STATE_ROOT / other / "original" / TABLES[0]).read_bytes()) == info["main"]), None)
            if donor is None:
                return
            backup_dir.mkdir(parents=True, exist_ok=True)
            for filename in TABLES:
                (backup_dir / filename).write_bytes((donor / filename).read_bytes())
            originals = {filename: sha256((backup_dir / filename).read_bytes()) for filename in TABLES}
            active_path.parent.mkdir(parents=True, exist_ok=True)
            active_path.write_text(json.dumps({"profile": name, "locale": "es", "original_hashes": originals,
                                               "current_hashes": {f: sha256(paths[f].read_bytes()) for f in TABLES}}, indent=2) + "\n",
                                   encoding="utf-8")
            PROFILES[name] = {"code": code, "cache": cache, "table": table, "main": originals[TABLES[0]], "builtin": originals[TABLES[1]]}
            return
        originals = {filename: sha256(source[filename].read_bytes()) for filename in TABLES}
    PROFILES[name] = {"code": code, "cache": cache, "table": table, "main": originals[TABLES[0]], "builtin": originals[TABLES[1]]}


def inspect_game(game_dir: Path) -> tuple[str, Path, dict[str, str], dict[str, str]]:
    game_dir = game_dir.expanduser().resolve()
    data = game_dir / "GF2_Exilium_Data" / "LocalCache" / "Data"
    config_path = data / "GameConfig.cfg"
    if not config_path.is_file():
        raise PatchError(f"No se encontró GameConfig.cfg en {data}")
    config = parse_config(config_path)
    register_dynamic_profile(config, data / "Table")
    for name, profile in PROFILES.items():
        if (config.get("CodeResVersion") == profile["code"] and
                config.get("CacheResVersion") == profile["cache"] and
                config.get("StcTableVersion") == profile["table"]):
            table_dir = data / "Table"
            hashes = {}
            for filename in TABLES:
                path = table_dir / filename
                if not path.is_file():
                    raise PatchError(f"Falta la tabla {path}")
                hashes[filename] = sha256(path.read_bytes())
            original_hashes = {TABLES[0]: profile["main"], TABLES[1]: profile["builtin"]}
            active_path = STATE_ROOT / name / "active.json"
            _, journal_path = state_paths(name)
            allowed_state = hashes == original_hashes
            if active_path.is_file():
                try:
                    active = json.loads(active_path.read_text(encoding="utf-8"))
                    allowed_state = allowed_state or (active.get("profile") == name and active.get("current_hashes") == hashes)
                except (OSError, ValueError):
                    pass
            normalized = managed_client_normalization(name, table_dir, hashes)
            allowed_state = allowed_state or normalized
            if journal_path.is_file():
                # A valid original backup allows crash recovery before any other action.
                backup_dir, _ = state_paths(name)
                allowed_state = allowed_state or all(
                    (backup_dir / filename).is_file() and
                    sha256((backup_dir / filename).read_bytes()) == original_hashes[filename]
                    for filename in TABLES
                )
            if not allowed_state:
                raise PatchError("La versión parece compatible, pero los hashes de las tablas no coinciden; no se modificó nada.")
            return name, table_dir, config, hashes
    raise PatchError("Versión/build/tablas no reconocidos. No se modificó ningún archivo.")


def is_game_running() -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq GF2_Exilium.exe", "/FO", "CSV", "/NH"],
                            capture_output=True, check=False)
    # Bytes: tasklist writes in the OEM code page of the machine, which is not always decodable as text.
    return b"GF2_Exilium.exe" in (result.stdout or b"")


def can_write_tables(table_dir: Path) -> bool:
    """Open an existing table with write access without changing its contents."""
    try:
        with (table_dir / TABLES[0]).open("r+b"):
            return True
    except OSError:
        return False


def pinned_download(path: Path, url: str, expected_size: int, expected_hash: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        data = path.read_bytes()
        if len(data) == expected_size and sha256(data) == expected_hash:
            return path
        path.unlink()
    temp = path.with_suffix(path.suffix + ".download")
    digest = hashlib.sha256()
    size = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Griffin-Local-Language-Patcher/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response, temp.open("wb") as output:
            if response.status != 200 or not response.geturl().startswith("https://"):
                raise PatchError("La descarga de la fuente oficial no fue HTTPS/200.")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > expected_size:
                    raise PatchError("La fuente descargada excede el tamaño fijado.")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if size != expected_size or digest.hexdigest() != expected_hash:
            raise PatchError("La fuente descargada no coincide con tamaño/hash fijados.")
        os.replace(temp, path)
        return path
    finally:
        if temp.exists():
            temp.unlink()


def sources() -> Path:
    cache = STATE_ROOT / "cache"
    archive_cache = cache / "official-global-tables.zip"
    temp_archive = Path(tempfile.gettempdir()) / "griffin-global-tables-1151583.zip"
    cache.mkdir(parents=True, exist_ok=True)
    if temp_archive.is_file() and temp_archive.stat().st_size == ARCHIVE_SIZE and sha256(temp_archive.read_bytes()) == ARCHIVE_SHA256 and not archive_cache.exists():
        shutil.copyfile(temp_archive, archive_cache)
    return pinned_download(archive_cache, ARCHIVE_URL, ARCHIVE_SIZE, ARCHIVE_SHA256)


def build_replacements(target_cn: bytes, archive: zipfile.ZipFile, locale: str,
                       machine_translations: dict[str, dict[str, str]] | None = None) -> tuple[dict[int, str], dict[str, int]]:
    source_cn_name = "LangPackageTableCnData.bytes"
    target_rows = extract_texts(target_cn)
    with archive.open(source_cn_name) as src:
        raw_cn = src.read()
    with archive.open(f"LangPackageTable{'Enus' if locale == 'en' else 'Eses'}Data.bytes") as src:
        raw_target = src.read()
    # The bundled index is a curated UI-only subset. Filtering by it silently
    # discarded the vast majority of officially localized rows. Use the full,
    # hash-pinned Global tables; exact Chinese source matching and ambiguity
    # rejection keep cross-build mapping conservative.
    global_cn = extract_texts(raw_cn)
    translated = extract_texts(raw_target)
    candidates: dict[str, set[str]] = defaultdict(set)
    for global_id, source in global_cn.items():
        text = translated.get(global_id, "")
        if text and text != source:
            candidates[source].add(text)
    replacements = {}
    ambiguous = 0
    no_match = 0
    official_translated = 0
    machine_translated = 0
    machine_translations = machine_translations or {}
    for target_id, source in target_rows.items():
        if not source:
            continue
        values = candidates.get(source, set())
        if len(values) == 1:
            translated_text = next(iter(values))
            if translated_text != source:
                replacements[target_id] = translated_text
                official_translated += 1
        elif len(values) > 1:
            ambiguous += 1
            translated_text = machine_translations.get(source, {}).get(locale, "")
            if translated_text and translated_text != source:
                replacements[target_id] = translated_text
                machine_translated += 1
        else:
            no_match += 1
            translated_text = machine_translations.get(source, {}).get(locale, "")
            if translated_text and translated_text != source:
                replacements[target_id] = translated_text
                machine_translated += 1
    return replacements, {"target_rows": len(target_rows), "translated": len(replacements),
                          "official_translated": official_translated,
                          "machine_translated": machine_translated,
                          "fallback_cn": sum(bool(text) and row_id not in replacements
                                             for row_id, text in target_rows.items()),
                          "empty_rows": sum(not text for text in target_rows.values()),
                          "ambiguous": ambiguous,
                          "no_match": no_match}


def build_replacements_from_pack(target_cn: bytes, pack: dict, locale: str, section: str) -> tuple[dict[int, str], dict[str, int]]:
    """Row id -> translated text for one table, taken only from the language pack (matched by the Chinese text of each row)."""
    rows = extract_texts(target_cn)
    replacements: dict[int, str] = {}
    machine = 0
    for row_id, source in rows.items():
        if not source:
            continue
        text, is_machine = language_pack.lookup(pack, section, locale, source)
        if text:
            replacements[row_id] = text
            machine += is_machine
    return replacements, {"target_rows": len(rows), "translated": len(replacements),
                          "official_translated": len(replacements) - machine, "machine_translated": machine,
                          "fallback_cn": sum(bool(text) and row_id not in replacements for row_id, text in rows.items()),
                          "empty_rows": sum(not text for text in rows.values()), "ambiguous": 0, "no_match": 0}


def load_machine_translations() -> dict[str, dict[str, str]]:
    """Load optional offline-generated fallback translations kept outside the checkout."""
    if not MACHINE_TRANSLATION_CACHE.is_file():
        return {}
    try:
        with gzip.open(MACHINE_TRANSLATION_CACHE, "rt", encoding="utf-8") as source:
            payload = json.load(source)
        if payload.get("format") != 1 or not isinstance(payload.get("translations"), dict):
            return {}
        return payload["translations"]
    except (OSError, ValueError, TypeError):
        return {}


def state_paths(profile: str) -> tuple[Path, Path]:
    root = STATE_ROOT / profile
    return root / "original", root / "journal.json"


def save_originals(profile: str, table_dir: Path, expected_hashes: dict[str, str]) -> Path:
    backup_dir, _ = state_paths(profile)
    backup_dir.mkdir(parents=True, exist_ok=True)
    for filename in TABLES:
        path = backup_dir / filename
        if path.exists():
            if sha256(path.read_bytes()) != expected_hashes[filename]:
                raise PatchError(f"La copia original existe pero no coincide: {path}")
            continue
        data = (table_dir / filename).read_bytes()
        if sha256(data) != expected_hashes[filename]:
            raise PatchError("La tabla cambió mientras se preparaba la copia; cancelo.")
        with path.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if sha256(path.read_bytes()) != expected_hashes[filename]:
            raise PatchError("Falló la verificación de la copia original.")
    return backup_dir


def atomic_write(path: Path, data: bytes) -> None:
    temp = path.with_name(path.name + ".griffin-tmp")
    with temp.open("wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, path)


def recover_if_needed(profile: str, table_dir: Path) -> bool:
    backup_dir, journal_path = state_paths(profile)
    if not journal_path.exists():
        return False
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        if journal.get("profile") != profile:
            raise PatchError("El diario no corresponde a este perfil.")
        for filename in TABLES:
            backup = backup_dir / filename
            expected = journal["original_hashes"][filename]
            if not backup.is_file() or sha256(backup.read_bytes()) != expected:
                raise PatchError("Hay un diario de interrupción y la copia original no valida; se preservaron archivos para diagnóstico.")
        for filename in TABLES:
            atomic_write(table_dir / filename, (backup_dir / filename).read_bytes())
        journal_path.unlink()
        return True
    except Exception:
        raise


def apply_language(game_dir: Path, locale: str, dry_run: bool = False) -> dict:
    """Switch the client language. ``dry_run`` builds and validates the tables and reports their hashes without writing anything."""
    if locale not in ("cn", "en", "es"):
        raise PatchError("Idioma no válido.")
    if is_game_running() and not dry_run:
        raise PatchError("El juego está abierto. Ciérralo antes de cambiar idioma o restaurar las tablas.")
    profile, table_dir, config, initial_hashes = inspect_game(game_dir)
    if not dry_run and not can_write_tables(table_dir):
        raise ElevationRequired("Windows protege esta carpeta: hace falta ejecutar el parcheador como administrador. No se cambió ningún archivo.")
    recovered = recover_if_needed(profile, table_dir)
    # Requiring exact installed hashes prevents stacking patches over unknown content.
    profile_info = PROFILES[profile]
    expected_originals = {TABLES[0]: profile_info["main"], TABLES[1]: profile_info["builtin"]}
    backup_dir = save_originals(profile, table_dir, expected_originals)
    originals = {filename: (backup_dir / filename).read_bytes() for filename in TABLES}
    current_hashes = {filename: sha256((table_dir / filename).read_bytes()) for filename in TABLES}
    active_path = STATE_ROOT / profile / "active.json"
    if current_hashes != expected_originals:
        try:
            active = json.loads(active_path.read_text(encoding="utf-8"))
            active_matches = active.get("profile") == profile and active.get("current_hashes") == current_hashes
            normalized = managed_client_normalization(profile, table_dir, current_hashes)
            if not active_matches and not normalized:
                raise PatchError("El hash activo no coincide con la última traducción aplicada.")
        except (OSError, ValueError) as exc:
            raise PatchError("Las tablas fueron modificadas fuera del parcheador; no se sobrescribieron.") from exc
    journal_path = state_paths(profile)[1]
    report = {"profile": profile, "locale": locale, "recovered_previous_write": recovered,
              "tables": {}, "language": locale}
    generated = dict(originals)
    if locale in ("en", "es"):
        pack = language_pack.load_pack()
        main_map, coverage = build_replacements_from_pack(originals[TABLES[0]], pack, locale, "main")
        new_main, row_count, changed = replace_table_text(originals[TABLES[0]], main_map)
        if changed != len(main_map):
            raise PatchError("Validación interna: no se aplicaron todas las filas seleccionadas.")
        validate_structure(originals[TABLES[0]], new_main)
        generated[TABLES[0]] = new_main
        builtin_map, builtin_stats = build_replacements_from_pack(originals[TABLES[1]], pack, locale, "builtin")
        new_builtin, builtin_rows, builtin_changed = replace_table_text(originals[TABLES[1]], builtin_map)
        validate_structure(originals[TABLES[1]], new_builtin)
        generated[TABLES[1]] = new_builtin
        report["coverage"] = coverage
        report["coverage"]["builtin_translated"] = builtin_changed
        report["coverage"]["builtin_official"] = builtin_stats["official_translated"]
        report["coverage"]["builtin_machine"] = builtin_stats["machine_translated"]
        report["coverage"]["builtin_fallback_cn"] = builtin_rows - builtin_changed
    if dry_run:
        report["dry_run"] = True
        report["generated_hashes"] = {key: sha256(value) for key, value in generated.items()}
        return report
    if is_game_running():
        raise PatchError("El juego se abrió durante la preparación; no se escribieron tablas.")
    journal = {"profile": profile, "locale": locale, "original_hashes": expected_originals,
               "generated_hashes": {key: sha256(value) for key, value in generated.items()}}
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(json.dumps(journal, indent=2) + "\n", encoding="utf-8")
    try:
        for filename in TABLES:
            target = table_dir / filename
            data = generated[filename]
            atomic_write(target, data)
            if sha256(target.read_bytes()) != sha256(data):
                raise PatchError(f"Falló la verificación tras escribir {filename}.")
            report["tables"][filename] = {"bytes": len(data), "sha256": sha256(data)}
        for filename in TABLES:
            patched = (table_dir / filename).read_bytes()
            validate_structure(originals[filename], patched)
        journal_path.unlink()
        if locale == "cn":
            active_path.unlink(missing_ok=True)
        else:
            active_path.write_text(json.dumps({"profile": profile, "locale": locale, "original_hashes": expected_originals,
                                               "current_hashes": {filename: sha256((table_dir / filename).read_bytes())
                                                                  for filename in TABLES}}, indent=2) + "\n",
                                    encoding="utf-8")
    except Exception:
        for filename in TABLES:
            atomic_write(table_dir / filename, originals[filename])
        journal_path.unlink(missing_ok=True)
        raise
    return report


def status(game_dir: Path) -> dict:
    if is_game_running():
        raise PatchError("El juego está abierto. Ciérralo antes de comprobar o cambiar las tablas.")
    profile, table_dir, config, hashes = inspect_game(game_dir)
    original_hashes = {TABLES[0]: PROFILES[profile]["main"], TABLES[1]: PROFILES[profile]["builtin"]}
    locale = "cn" if hashes == original_hashes else "unknown/modified"
    active_path = STATE_ROOT / profile / "active.json"
    normalized = False
    if active_path.is_file():
        try:
            active = json.loads(active_path.read_text(encoding="utf-8"))
            if active.get("current_hashes") == hashes:
                locale = active.get("locale", locale)
            elif managed_client_normalization(profile, table_dir, hashes):
                locale = active.get("locale", locale)
                normalized = True
        except (OSError, ValueError):
            pass
    return {"game_dir": str(game_dir.resolve()), "profile": profile,
            "locale": locale, "game_running": is_game_running(), "hashes": hashes,
            "write_access": can_write_tables(table_dir), "client_normalized_builtin": normalized}


def choose_default() -> Path:
    dirs = find_game_dirs()
    if not dirs:
        raise PatchError("No se detectaron instalaciones compatibles; selecciona la carpeta del juego.")
    # Prefer the user-owned Bilibili install for non-admin operation.
    return next((p for p in dirs if str(p).lower().startswith("d:\\")), dirs[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, default=None)
    parser.add_argument("command", choices=("status", "cn", "en", "es"))
    parser.add_argument("--dry-run", action="store_true", help="build and validate without writing")
    args = parser.parse_args()
    try:
        game_dir = args.game_dir or choose_default()
        if args.command == "status":
            result = status(game_dir)
        else:
            try:
                result = apply_language(game_dir, args.command, dry_run=args.dry_run)
            except ElevationRequired:
                if is_admin():
                    raise
                print("Esta carpeta necesita permisos de administrador: se abrirá la ventana de Windows para pedirlos.")
                relaunch = ["--game-dir", str(game_dir), args.command]
                if relaunch_elevated(Path(__file__).resolve(), relaunch, keep_console=True):
                    return 0
                raise PatchError("No se concedieron permisos de administrador; no se cambió nada.")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
