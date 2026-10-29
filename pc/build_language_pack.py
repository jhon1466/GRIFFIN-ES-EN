#!/usr/bin/env python3
"""MAINTAINERS ONLY: build ``data/language-pack-v2.json.gz`` (the file the patcher ships and applies).

This is the only script that still reads the publisher's Global tables (the hash-pinned archive of ``patcher.sources()``) and the offline machine-translation
cache (``generate-machine-fallback.py``). The pack it writes holds, per Chinese source text, the final English and Spanish text the patcher uses, so the
released patcher works with nothing else (no CDN, no cache, no network).

Rule per Chinese text, the same the patcher used before: one single official translation -> that one; several different official translations (ambiguous) or
none -> the machine translation if the cache has one that passed its quality filter; otherwise the row stays Chinese.
"""
from __future__ import annotations

import argparse
import zipfile
from collections import defaultdict
from pathlib import Path

import language_pack
import patcher
from table_codec import extract_texts

LOCALES = {"en": "Enus", "es": "Eses"}


def official_unique(archive: zipfile.ZipFile, cn_name: str, locale_name: str) -> dict[str, str]:
    cn_rows = extract_texts(archive.read(cn_name))
    target_rows = extract_texts(archive.read(locale_name))
    candidates: dict[str, set[str]] = defaultdict(set)
    for row_id, source in cn_rows.items():
        text = target_rows.get(row_id, "")
        if source and text and text != source:
            candidates[source].add(text)
    return {source: next(iter(values)) for source, values in candidates.items() if len(values) == 1}


def local_sources() -> tuple[set[str], set[str]]:
    """Chinese texts of the main and builtin tables of every pinned build whose original backup exists on this machine."""
    main: set[str] = set()
    builtin: set[str] = set()
    for profile in patcher.PROFILES:
        backup_dir, _ = patcher.state_paths(profile)
        main_path = backup_dir / patcher.TABLES[0]
        builtin_path = backup_dir / patcher.TABLES[1]
        if main_path.is_file() and patcher.sha256(main_path.read_bytes()) == patcher.PROFILES[profile]["main"]:
            main |= {text for text in extract_texts(main_path.read_bytes()).values() if text}
        if builtin_path.is_file() and patcher.sha256(builtin_path.read_bytes()) == patcher.PROFILES[profile]["builtin"]:
            builtin |= {text for text in extract_texts(builtin_path.read_bytes()).values() if text}
    return main, builtin


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=language_pack.DEFAULT_PACK)
    args = parser.parse_args()

    machine = patcher.load_machine_translations()
    if not machine:
        raise SystemExit("No hay caché de traducción automática: ejecuta generate-machine-fallback.py primero.")
    archive_path = patcher.sources()
    local_main, local_builtin = local_sources()
    pack: dict = {"format": language_pack.FORMAT, "keys": "sha1-16", "profiles": sorted(patcher.PROFILES),
                  "main": {}, "builtin": {}, "machine": {"main": {}, "builtin": {}}}
    with zipfile.ZipFile(archive_path) as archive:
        for locale, name in LOCALES.items():
            for section, cn_name, locale_name, local in (
                    ("main", "LangPackageTableCnData.bytes", f"LangPackageTable{name}Data.bytes", local_main),
                    ("builtin", "LangPackageTableCnBuiltinData.bytes", f"LangPackageTable{name}BuiltinData.bytes", local_builtin)):
                official = official_unique(archive, cn_name, locale_name)
                entries: dict[str, str] = {}
                machine_keys: set[str] = set()
                for source, text in official.items():
                    entries[language_pack.key_of(source)] = text
                # machine fallback: texts of the pinned builds (and of the Global tables) that have no single official translation
                wanted = set(local) | set(machine) if section == "main" else set(local)
                for source in wanted:
                    key = language_pack.key_of(source)
                    if key in entries:
                        continue
                    text = machine.get(source, {}).get(locale, "")
                    if text and text != source:
                        entries[key] = text
                        machine_keys.add(key)
                pack[section][locale] = entries
                pack["machine"][section][locale] = machine_keys
                print(f"{section}/{locale}: {len(entries):,} textos ({len(machine_keys):,} automáticos)")
    path = language_pack.write_pack(pack, args.output)
    print(f"Paquete: {path} ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
