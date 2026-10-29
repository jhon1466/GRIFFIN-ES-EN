"""Builds gf2-es-android-<version>.zip: the Spanish language tables for the Android CN client.

The tables are generated with the PC language patcher (pc/): every Chinese row is replaced by the official
Global Spanish text (or the filtered machine translation) matched by its exact Chinese text; ids, order and every other
column stay as they are, and the page index is rebuilt and validated.

    python tools/build_patch_zip.py --tables <folder with the original Chinese LangPackageTableCn*.bytes> --stc 1195672
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATCHER = ROOT / "pc"
sys.path.insert(0, str(PATCHER))

import language_pack  # noqa: E402
from patcher import build_replacements_from_pack  # noqa: E402
from table_codec import replace_table_text, validate_structure  # noqa: E402

GAME = "com.Sunborn.SnqxExilium"
TABLES = (("LangPackageTableCnData.bytes", "main"), ("LangPackageTableCnBuiltinData.bytes", "builtin"))
PATCH_VERSION = "1.0.0"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tables", type=Path, required=True)
    parser.add_argument("--stc", required=True, help="StcTableVersion of those tables (GameConfig.cfg)")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()

    pack = language_pack.load_pack()
    files, payload, coverage = [], {}, {}
    for name, section in TABLES:
        original = (args.tables / name).read_bytes()
        replacements, stats = build_replacements_from_pack(original, pack, "es", section)
        patched, _, changed = replace_table_text(original, replacements)
        if changed != len(replacements):
            raise SystemExit(f"{name}: solo se aplicaron {changed} de {len(replacements)} filas")
        validate_structure(original, patched)
        path = f"LocalCache/Data/Table/{name}"
        payload[path] = patched
        files.append({"path": path, "sha256": sha256(patched), "originalSha256": sha256(original), "size": len(patched)})
        coverage[section] = {k: stats[k] for k in ("target_rows", "translated", "official_translated", "machine_translated")}
        print(f"{name}: {changed}/{stats['target_rows']} filas en español "
              f"({stats['official_translated']} oficiales, {stats['machine_translated']} automáticas)")

    manifest = {
        "format": "gf2-es-patch", "schemaVersion": 1, "platform": "android", "gamePackage": GAME,
        "patchVersion": PATCH_VERSION, "stcTableVersion": args.stc, "coverage": coverage, "files": files,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    out = args.output / f"gf2-es-android-{PATCH_VERSION}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for path, data in payload.items():
            z.writestr(f"payload/{path}", data)
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
