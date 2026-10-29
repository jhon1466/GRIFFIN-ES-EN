#!/usr/bin/env python3
"""MAINTAINERS ONLY: build the zip of the language patcher that goes to the GitHub release of GRIFFIN-ES.

It contains everything a player needs and nothing else: the patcher and launcher, the language pack (``data/language-pack-v2.json.gz`` + its SHA-256), the
README and the two ``.cmd`` starters. The maintainers' tools (``generate-machine-fallback.py``, ``build_language_pack.py``) and the tests stay out.
"""
from __future__ import annotations

import argparse
import hashlib
import zipfile
from datetime import date
from pathlib import Path

import language_pack

HERE = Path(__file__).resolve().parent
FILES = ("patcher.py", "launcher.py", "table_codec.py", "language_pack.py", "README.md",
         "Iniciar parche de idioma.cmd", "Start language patcher.cmd")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=HERE.parent / "release")
    args = parser.parse_args()
    pack = language_pack.load_pack()          # refuses a damaged or missing pack before anything is zipped
    checksum = language_pack.DEFAULT_PACK_SHA256
    if not checksum.is_file():
        raise SystemExit("Falta el .sha256 del paquete de idiomas: ejecuta build_language_pack.py.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / f"Griffin-ClientLanguagePatcher-{date.today():%Y%m%d}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in FILES:
            archive.write(HERE / name, f"ClientLanguagePatcher/{name}")
        archive.write(language_pack.DEFAULT_PACK, f"ClientLanguagePatcher/data/{language_pack.DEFAULT_PACK.name}")
        archive.write(checksum, f"ClientLanguagePatcher/data/{checksum.name}")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f"{target} ({target.stat().st_size:,} bytes)\nSHA-256 {digest}")
    print(f"Paquete: en {len(pack['main']['en']):,} / es {len(pack['main']['es']):,} textos principales")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
