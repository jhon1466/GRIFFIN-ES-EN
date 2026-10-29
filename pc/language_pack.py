"""The language pack the patcher applies: precomputed translations keyed by the Chinese source text.

The patcher no longer needs the publisher CDN (or any other online source) to work: everything it writes comes from this file, which is shipped with the
release. ``build_language_pack.py`` (maintainers only) is the one tool that still reads the Global tables and the offline machine-translation cache.

Layout (``format`` 2, gzip + JSON, UTF-8)::

    {"format": 2, "keys": "sha1-16", "profiles": [...],
     "main":    {"en": {key: text}, "es": {key: text}},
     "builtin": {"en": {key: text}, "es": {key: text}},
     "machine": {"main": {"en": [key, ...], "es": [...]}, "builtin": {...}}}

``key`` is the first 16 hex digits of the SHA-1 of the Chinese text (UTF-8). Keys keep the file small and let the pack be matched against any build whose
tables use the same Chinese text; a row whose text is not in the pack stays Chinese.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path

FORMAT = 2
HERE = Path(__file__).resolve().parent
DEFAULT_PACK = HERE / "data" / "language-pack-v2.json.gz"
DEFAULT_PACK_SHA256 = HERE / "data" / "language-pack-v2.sha256"


class PackError(RuntimeError):
    pass


def key_of(source: str) -> str:
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]


def pack_path() -> Path:
    override = os.environ.get("GRIFFIN_LANGUAGE_PACK")
    return Path(override) if override else DEFAULT_PACK


def load_pack(path: Path | None = None, verify: bool = True) -> dict:
    """Load and validate the pack. The SHA-256 next to it (``*.sha256``) must match unless ``verify`` is False."""
    path = path or pack_path()
    if not path.is_file():
        raise PackError(f"Falta el paquete de idiomas {path.name}. Descarga el parche completo de la release (incluye la carpeta data).")
    raw = path.read_bytes()
    checksum = path.with_suffix("").with_suffix(".sha256") if path.suffix == ".gz" else path.with_suffix(".sha256")
    if verify and checksum.is_file():
        expected = checksum.read_text(encoding="utf-8").split()[0].strip().lower()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise PackError("El paquete de idiomas está dañado (el SHA-256 no coincide). Vuelve a descargarlo.")
    try:
        pack = json.loads(gzip.decompress(raw).decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise PackError("El paquete de idiomas no se puede leer.") from exc
    if pack.get("format") != FORMAT or pack.get("keys") != "sha1-16":
        raise PackError("El paquete de idiomas es de otra versión del parcheador.")
    for section in ("main", "builtin"):
        for locale in ("en", "es"):
            if not isinstance(pack.get(section, {}).get(locale), dict):
                raise PackError("El paquete de idiomas está incompleto.")
    machine = pack.setdefault("machine", {})
    for section in ("main", "builtin"):
        machine[section] = {locale: set(machine.get(section, {}).get(locale, ())) for locale in ("en", "es")}
    return pack


def write_pack(pack: dict, path: Path | None = None) -> Path:
    """Write the pack deterministically (sorted keys, fixed gzip header) and its SHA-256 file."""
    path = path or DEFAULT_PACK
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(pack)
    payload["machine"] = {section: {locale: sorted(keys) for locale, keys in values.items()}
                          for section, values in pack["machine"].items()}
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9, mtime=0) as compressed:
            compressed.write(data)
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(temp, path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix("").with_suffix(".sha256").write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return path


def lookup(pack: dict, section: str, locale: str, source: str) -> tuple[str, bool]:
    """(translation, is_machine) for a Chinese text; ('', False) when the pack has none."""
    key = key_of(source)
    text = pack[section][locale].get(key, "")
    if not text or text == source:
        return "", False
    return text, key in pack["machine"][section][locale]
