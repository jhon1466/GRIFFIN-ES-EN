#!/usr/bin/env python3
"""Create offline Argos fallback translations for target rows lacking an official unique match."""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
import zipfile
from collections import defaultdict
from pathlib import Path


def _configure_device() -> str:
    """Use the NVIDIA GPU when CTranslate2 can (the pip packages nvidia-cublas-cu12 / nvidia-cuda-nvrtc-cu12 provide the CUDA 12 runtime on Windows);
    ARGOS_DEVICE_TYPE=cpu forces the processor. Returns the device in use."""
    requested = os.environ.get("ARGOS_DEVICE_TYPE", "").lower()
    if requested == "cpu":
        return "cpu"
    site = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for folder in sorted(site.glob("*/bin")) if site.is_dir() else []:
        try:
            os.add_dll_directory(str(folder))
        except OSError:
            pass
        os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
    try:
        import ctranslate2
        cuda_devices = ctranslate2.get_cuda_device_count()
        if cuda_devices > 0:
            os.environ["ARGOS_DEVICE_TYPE"] = "cuda"
            return "cuda"
    except Exception:
        if requested == "cuda" or os.environ.get("GRIFFIN_REQUIRE_GPU") == "1":
            raise RuntimeError("GPU CUDA solicitada, pero CTranslate2 no pudo inicializarla.")
    if requested == "cuda" or os.environ.get("GRIFFIN_REQUIRE_GPU") == "1":
        raise RuntimeError("GPU CUDA solicitada, pero no hay ningún dispositivo disponible.")
    os.environ["ARGOS_DEVICE_TYPE"] = "cpu"
    return "cpu"


DEVICE = _configure_device()

import argostranslate.translate as argos

import patcher
from table_codec import extract_texts

# Tags, escapes and printf fields are what the models garble; {0}-style fields they keep fine, so those stay inside the text.
PROT = re.compile(r"<[^<>]{1,256}>|%[0-9$#.+-]*[a-zA-Z]|\[nrt]")
TOKEN = re.compile(r"<[^<>]{1,256}>|\{[^{}]{1,80}\}|%[0-9$#.+-]*[a-zA-Z]|\\[nrt]|\r\n|[\r\n]")
MARKER = "QZXPH{index:06d}QXZ"


def get_translation(from_code: str, to_code: str):
    langs = argos.get_installed_languages()
    source = next((lang for lang in langs if lang.code == from_code), None)
    target = next((lang for lang in langs if lang.code == to_code), None)
    if source is None or target is None:
        raise RuntimeError(f"Falta el paquete Argos {from_code}->{to_code}.")
    translation = source.get_translation(target)
    if translation is None:
        raise RuntimeError(f"No existe la traducción Argos {from_code}->{to_code}.")
    model = translation.underlying
    model.hypotheses("warmup", 1)
    return model


def official_maps(target: dict[int, str], global_cn: dict[int, str],
                  localized: dict[int, str]) -> tuple[dict[str, str], set[str]]:
    candidates: dict[str, set[str]] = defaultdict(set)
    for source_id, text in global_cn.items():
        value = localized.get(source_id, "")
        if text and value and text != value:
            candidates[text].add(value)
    unique = {text: next(iter(values)) for text, values in candidates.items() if len(values) == 1}
    fallback = {text for text in target.values() if text and len(candidates.get(text, ())) != 1}
    return unique, fallback


def encode_protected(text: str) -> tuple[str, list[str]]:
    protected: list[str] = []
    def replace(match: re.Match[str]) -> str:
        marker = MARKER.format(index=len(protected))
        protected.append(match.group(0))
        return marker
    return TOKEN.sub(replace, text), protected


CYRILLIC = re.compile(r"[Ѐ-ӿ]")
CJK = re.compile(r"[一-鿿]")
REPEAT = re.compile(r"(.{2,8}){4,}")


def is_sane(source: str, value: str) -> bool:
    """Reject the garbage the small local models produce on short or marker-heavy strings: Cyrillic, leftover Chinese, endless repetition,
    runaway length, the text returned unchanged, or lost/changed format tokens ({0}, <color=..>, \n, %s)."""
    value = value.strip()
    if not value:
        return False
    if CYRILLIC.search(value) and not CYRILLIC.search(source):
        return False
    if CJK.search(TOKEN.sub("", value)):   # Chinese left outside the format tokens = not translated
        return False
    if REPEAT.search(value) and not REPEAT.search(source):
        return False
    if len(value) > 6 * len(source) + 30:
        return False
    if sorted(TOKEN.findall(source)) != sorted(TOKEN.findall(value)):
        return False
    return True


def segment_only(model, sources: list[str]) -> dict[str, str]:
    """Translate only the text between the format tokens (each span alone), keeping every token exactly."""
    plan: list[tuple[str, list[tuple[str, str]]]] = []
    spans: list[str] = []
    for source in sources:
        segments: list[tuple[str, str]] = []
        cursor = 0
        for match in PROT.finditer(source):
            segments.append(("text", source[cursor:match.start()]))
            segments.append(("token", match.group(0)))
            cursor = match.end()
        segments.append(("text", source[cursor:]))
        for kind, segment in segments:
            if kind == "text" and segment.strip():
                spans.append(segment.strip())
        plan.append((source, segments))
    translated = iter(batch_translate(model, spans)) if spans else iter(())
    out: dict[str, str] = {}
    for source, segments in plan:
        pieces = []
        for kind, segment in segments:
            if kind == "token" or not segment.strip():
                pieces.append(segment)
            else:
                value = next(translated, "")
                leading = segment[:len(segment) - len(segment.lstrip())]
                trailing = segment[len(segment.rstrip()):]
                pieces.append(leading + value + trailing)
        out[source] = "".join(pieces).strip()
    return out


def batch_translate(model, texts: list[str], batch_size: int | None = None) -> list[str]:
    # On the GPU the batches have to be big (8192 tokens, 4096 sentences per call: about 30x the sentences per second of the 128-token batches used on the CPU).
    if batch_size is None:
        batch_size = 4096 if DEVICE == "cuda" else 128
    max_tokens = 8192 if DEVICE == "cuda" else batch_size
    tokenizer = model.pkg.tokenizer
    results: list[str] = []
    total = len(texts)
    for start in range(0, total, batch_size):
        batch = texts[start:start + batch_size]
        translated = model.translator.translate_batch(
            [tokenizer.encode(text) for text in batch], replace_unknowns=True,
            max_batch_size=max_tokens, batch_type="tokens", beam_size=1,
            num_hypotheses=1, length_penalty=0.2, return_scores=True)
        results.extend(tokenizer.decode(item.hypotheses[0]).strip() for item in translated)
        done = min(start + len(batch), total)
        if done == total or done % 5000 < batch_size:
            print(f"  {done:,}/{total:,}", flush=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, action="append",
                        help="repeat to include multiple client builds; default: every detected build with a verified backup")
    args = parser.parse_args()
    game_dirs = args.game_dir or patcher.find_game_dirs()
    if not game_dirs:
        raise RuntimeError("No se detectaron instalaciones del juego.")
    targets: list[tuple[str, dict[int, str], dict[int, str]]] = []
    archive_path = patcher.sources()
    with zipfile.ZipFile(archive_path) as archive:
        global_cn = extract_texts(archive.read("LangPackageTableCnData.bytes"))
        official_en = extract_texts(archive.read("LangPackageTableEnusData.bytes"))
        official_es = extract_texts(archive.read("LangPackageTableEsesData.bytes"))
        builtin_cn = extract_texts(archive.read("LangPackageTableCnBuiltinData.bytes"))
        builtin_en = extract_texts(archive.read("LangPackageTableEnusBuiltinData.bytes"))
        builtin_es = extract_texts(archive.read("LangPackageTableEsesBuiltinData.bytes"))
        builtin_pivot: dict[str, str] = {}
        builtin_need_en: set[str] = set()
        builtin_need_es: set[str] = set()
        for source in set(builtin_cn.values()):
            en_values = {builtin_en[key] for key, value in builtin_cn.items()
                         if value == source and builtin_en.get(key) and builtin_en[key] != source}
            es_values = {builtin_es[key] for key, value in builtin_cn.items()
                         if value == source and builtin_es.get(key) and builtin_es[key] != source}
            if len(en_values) == 1:
                builtin_pivot[source] = next(iter(en_values))
            else:
                builtin_need_en.add(source)
            if len(es_values) != 1:
                builtin_need_es.add(source)

        for game_dir in game_dirs:
            profile, _, _, _ = patcher.inspect_game(game_dir)
            backup_dir, _ = patcher.state_paths(profile)
            main_backup = backup_dir / patcher.TABLES[0]
            builtin_backup = backup_dir / patcher.TABLES[1]
            expected = patcher.PROFILES[profile]
            if (not main_backup.is_file() or patcher.sha256(main_backup.read_bytes()) != expected["main"] or
                    not builtin_backup.is_file() or patcher.sha256(builtin_backup.read_bytes()) != expected["builtin"]):
                print(f"Omitido {profile}: no tiene respaldo CN verificado.", flush=True)
                continue
            targets.append((profile, extract_texts(main_backup.read_bytes()),
                            extract_texts(builtin_backup.read_bytes())))

    if not targets:
        raise RuntimeError("No encuentro copias CN originales verificadas para los builds detectados.")
    need_en: set[str] = set()
    need_es: set[str] = set()
    en_pivot: dict[str, str] = {}
    for profile, target_main, target_builtin in targets:
        current_en, fallback_en = official_maps(target_main, global_cn, official_en)
        current_es, fallback_es = official_maps(target_main, global_cn, official_es)
        need_en |= fallback_en
        need_es |= fallback_es
        en_pivot.update(current_en)
        for source in set(target_builtin.values()):
            values = {builtin_en[key] for key, value in builtin_cn.items()
                      if value == source and builtin_en.get(key) and builtin_en[key] != source}
            es_values = {builtin_es[key] for key, value in builtin_cn.items()
                         if value == source and builtin_es.get(key) and builtin_es[key] != source}
            if len(values) == 1:
                en_pivot[source] = next(iter(values))
            else:
                need_en.add(source)
            if len(es_values) != 1:
                need_es.add(source)

    output = patcher.MACHINE_TRANSLATION_CACHE
    existing: dict[str, dict[str, str]] = {}
    if output.is_file():
        try:
            with gzip.open(output, "rt", encoding="utf-8") as source:
                existing = json.load(source).get("translations", {})
        except (OSError, ValueError, TypeError):
            existing = {}
    purged = 0
    if os.environ.get("GRIFFIN_REGEN_ES") == "1":   # the Spanish of older runs was made from the Chinese text: do it all again from the English
        for values in existing.values():
            if values.pop("es", None):
                purged += 1
    for source, values in existing.items():
        for locale in ("en", "es"):
            if values.get(locale) and not is_sane(source, values[locale]):
                del values[locale]
                purged += 1
        if values.get("es") and values.get("es") == values.get("en") and CJK.search(source):
            del values["es"]   # English fallback from an older run: translate it into Spanish again
            purged += 1
    print(f"Entradas de la caché descartadas por no pasar el filtro de calidad: {purged:,}", flush=True)
    for source in need_en | need_es:
        existing.setdefault(source, {})
    todo_en = sorted(s for s in need_en if not existing.get(s, {}).get("en"))
    # For Spanish, use the exact official English equivalent when available.
    todo_es = sorted(s for s in need_es if not existing.get(s, {}).get("es"))
    todo_zh = sorted(set(todo_en) | {s for s in todo_es
                                     if not existing.get(s, {}).get("en") and s not in en_pivot})
    print(f"Builds: {', '.join(profile for profile, _, _ in targets)}; frases CN→EN: {len(todo_zh):,}; EN→ES: {len(todo_es):,}", flush=True)
    zh_en = get_translation("zh", "en") if todo_zh else None
    en_es = get_translation("en", "es") if todo_es else None

    rejected = 0
    def translate_and_restore(model, sources: list[str]) -> dict[str, str]:
        """Strings without tags are translated whole ({0} stays in the text); strings with tags or escapes are translated span by span so the
        tags stay exact. Everything goes through is_sane; what is still garbage is left out (A-130)."""
        nonlocal rejected
        plain = [source for source in sources if not PROT.search(source)]
        tagged = [source for source in sources if PROT.search(source)]
        restored: dict[str, str] = {}
        if plain:
            for source, value in zip(plain, batch_translate(model, plain)):
                restored[source] = value.strip()
        if tagged:
            restored.update(segment_only(model, tagged))
        bad = [source for source, value in restored.items() if not is_sane(source, value)]
        if bad:
            # one more try, span by span (plain strings that came out wrong; tagged ones were already done that way)
            retried = segment_only(model, [source for source in bad if source in plain]) if any(source in plain for source in bad) else {}
            for source in bad:
                value = retried.get(source, "")
                if value and is_sane(source, value):
                    restored[source] = value
                else:
                    del restored[source]
                    rejected += 1
        return restored

    def write_cache() -> None:
        # Entries with text only; written through a temp file so an interruption never leaves a half-written cache.
        kept = {source: {locale: value for locale, value in values.items() if value}
                for source, values in existing.items() if any(values.values())}
        payload = {"format": 1, "profiles": [profile for profile, _, _ in targets],
                   "models": {"zh-en": "Argos 1.9", "en-es": "Argos 1.0"},
                   "method": "offline machine translation; official unique matches remain preferred",
                   "strings": len(kept), "rejected_placeholder_rows": rejected, "translations": kept}
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_suffix(output.suffix + ".tmp")
        with temp.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0) as compressed:
                compressed.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            raw.flush()
            os.fsync(raw.fileno())
        temp.replace(output)

    CHECKPOINT = 20000 if DEVICE == "cuda" else 5000
    print(f"Dispositivo de traducción: {DEVICE}; guardado cada {CHECKPOINT:,} frases", flush=True)
    for start in range(0, len(todo_zh), CHECKPOINT):
        translated_en = translate_and_restore(zh_en, todo_zh[start:start + CHECKPOINT])
        for source, value in translated_en.items():
            if source in need_en or source in need_es:
                existing.setdefault(source, {}).setdefault("en", en_pivot.get(source, value))
        write_cache()
        print(f"  [guardado] CN→EN {min(start + CHECKPOINT, len(todo_zh)):,}/{len(todo_zh):,}", flush=True)
    for source in todo_es:
        if not existing.get(source, {}).get("en"):
            existing.setdefault(source, {}).setdefault("en", en_pivot.get(source, ""))
    for start in range(0, len(todo_es), CHECKPOINT):
        # The Spanish model is English->Spanish: it must be fed the ENGLISH text of each string (official or machine), never the Chinese source
        # (feeding it Chinese is what produced the Cyrillic and repeated garbage, A-130).
        chunk = todo_es[start:start + CHECKPOINT]
        pairs = [(source, existing.get(source, {}).get("en") or en_pivot.get(source, "")) for source in chunk]
        pairs = [(source, english) for source, english in pairs if english]
        translated_es = translate_and_restore(en_es, sorted({english for _, english in pairs}))
        es_values = {source: translated_es[english] for source, english in pairs if english in translated_es}
        for source, value in es_values.items():
            existing.setdefault(source, {})["es"] = value
        # no usable Spanish: a sane English text is better than leaving the Chinese
        for source in todo_es[start:start + CHECKPOINT]:
            entry = existing.setdefault(source, {})
            if not entry.get("es") and entry.get("en") and is_sane(source, entry["en"]):
                entry["es"] = entry["en"]
        write_cache()
        print(f"  [guardado] EN→ES {min(start + CHECKPOINT, len(todo_es)):,}/{len(todo_es):,}", flush=True)

    write_cache()
    data = existing
    print(f"Cache: {output}; entradas={len(data):,}; marcadores rechazados={rejected:,}; bytes={output.stat().st_size:,}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
