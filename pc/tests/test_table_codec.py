import sys
import tempfile
import unittest
import json
import io
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from table_codec import (extract_texts, length_field, replace_table_text, validate_structure,
                         validate_subset_structure, varint)
import patcher
from launcher import Launcher


def row(identifier: int, text: str, extra: bytes = b"") -> bytes:
    return varint(8) + varint(identifier) + length_field(2, text.encode()) + extra


def table(*rows: bytes) -> bytes:
    header = varint(8) + varint(len(rows))
    return len(header).to_bytes(4, "little") + header + b"".join(length_field(1, r) for r in rows)


def sectioned_table(*rows: bytes) -> bytes:
    body = b"".join(length_field(1, r) for r in rows)
    groups = {}
    position = 0
    for raw, wrapped in zip(rows, [length_field(1, r) for r in rows]):
        identifier, _, _ = __import__("table_codec").row_info(raw)
        page = identifier // 10
        groups.setdefault(page, [position, 0])
        groups[page][1] += len(wrapped)
        position += len(wrapped)
    header = varint(8) + varint(10) + varint(16) + varint(1)
    for page, (offset, size) in groups.items():
        value = (varint(8) + varint(offset) if offset else b"") + varint(16) + varint(size)
        entry = varint(8) + varint(page) + length_field(2, value)
        header += length_field(3, entry)
    return len(header).to_bytes(4, "little") + header + body


class CodecTests(unittest.TestCase):
    def test_round_trip_restores_bytes_exactly(self):
        original = table(row(1, "中文", varint(24) + varint(99)), row(2, "第二行"))
        patched, row_count, changed = replace_table_text(original, {1: "Español ¿¡"})
        self.assertEqual((row_count, changed), (2, 1))
        self.assertEqual(extract_texts(patched), {1: "Español ¿¡", 2: "第二行"})
        self.assertEqual(validate_structure(original, patched), (2, 1))
        restored, _, _ = replace_table_text(patched, {1: "中文"})
        self.assertEqual(restored, original)

    def test_untranslated_rows_and_header_are_byte_identical(self):
        original = table(row(1, "中文", varint(24) + varint(7)), row(2, "unchanged"))
        patched, _, _ = replace_table_text(original, {1: "English"})
        self.assertEqual(patched[:len(original[:4]) + 2], original[:len(original[:4]) + 2])
        self.assertIn(length_field(1, row(2, "unchanged")), patched)
        self.assertEqual(list(__import__("table_codec").table_rows(original))[1],
                         list(__import__("table_codec").table_rows(patched))[1])
        self.assertEqual(validate_structure(original, patched), (2, 1))

    def test_section_index_is_rebuilt_when_translated_text_changes_lengths(self):
        original = sectioned_table(row(10, "中文"), row(11, "第二行"),
                                   row(20, "另一组"), row(21, "最后一行"))
        patched, _, changed = replace_table_text(original, {10: "A much longer translation"})
        self.assertEqual(changed, 1)
        self.assertEqual(validate_structure(original, patched), (4, 1))
        self.assertEqual(__import__("table_codec").validate_section_index(patched), 2)
        # Replacing text back restores the original body and canonical index exactly.
        restored, _, _ = replace_table_text(patched, {10: "中文"})
        self.assertEqual(restored, original)

    def test_stale_section_index_is_rejected(self):
        original = sectioned_table(row(10, "中文"), row(11, "第二行"))
        header, body = __import__("table_codec").table_header(original)
        stale = header + length_field(1, row(10, "a much longer translation")) + \
            length_field(1, row(11, "第二行"))
        with self.assertRaisesRegex(ValueError, "truncated|section"):
            __import__("table_codec").validate_section_index(stale)

    def test_structural_mutation_is_rejected(self):
        original = table(row(1, "中文", varint(24) + varint(7)))
        invalid = table(row(1, "English", varint(24) + varint(8)))
        with self.assertRaisesRegex(ValueError, "non-text columns"):
            validate_structure(original, invalid)

    def test_client_row_subset_is_recognized_only_when_protected_fields_match(self):
        original = table(row(1, "中文", varint(24) + varint(7)), row(2, "第二行"))
        normalized = table(row(1, "reloaded text", varint(24) + varint(7)))
        self.assertEqual(validate_subset_structure(original, normalized), (1, 1))
        invalid = table(row(3, "unknown"))
        with self.assertRaisesRegex(ValueError, "unknown row"):
            validate_subset_structure(original, invalid)

    def test_managed_normalization_requires_known_active_main_and_valid_backup(self):
        original_main = table(row(1, "中文"))
        active_main, _, _ = replace_table_text(original_main, {1: "Español"})
        original_builtin = table(row(1, "中文"), row(2, "第二行"))
        normalized_builtin = table(row(1, "texto cliente"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_state_root = patcher.STATE_ROOT
            try:
                patcher.STATE_ROOT = root
                profile = "unit-test"
                patcher.PROFILES[profile] = {"main": patcher.sha256(original_main),
                                             "builtin": patcher.sha256(original_builtin)}
                backup, _ = patcher.state_paths(profile)
                backup.mkdir(parents=True)
                (backup / patcher.TABLES[0]).write_bytes(original_main)
                (backup / patcher.TABLES[1]).write_bytes(original_builtin)
                active = {"profile": profile, "locale": "es", "current_hashes": {
                    patcher.TABLES[0]: patcher.sha256(active_main),
                    patcher.TABLES[1]: "client-reencoded",
                }}
                (root / profile / "active.json").write_text(json.dumps(active), encoding="utf-8")
                client_dir = root / "client"
                client_dir.mkdir()
                (client_dir / patcher.TABLES[0]).write_bytes(active_main)
                (client_dir / patcher.TABLES[1]).write_bytes(normalized_builtin)
                hashes = {name: patcher.sha256((client_dir / name).read_bytes()) for name in patcher.TABLES}
                self.assertTrue(patcher.managed_client_normalization(profile, client_dir, hashes))
                (client_dir / patcher.TABLES[0]).write_bytes(original_main)
                hashes[patcher.TABLES[0]] = patcher.sha256(original_main)
                self.assertFalse(patcher.managed_client_normalization(profile, client_dir, hashes))
            finally:
                patcher.STATE_ROOT = old_state_root
                patcher.PROFILES.pop("unit-test", None)

    def test_duplicate_ids_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            replace_table_text(table(row(1, "one"), row(1, "again")), {})

    def test_full_official_table_sources_expand_coverage_and_keep_ambiguous_text(self):
        target = table(row(1, "Hello"), row(2, "Hello"), row(3, "Open"))
        source_cn = table(row(100, "Hello"), row(101, "Hello"),
                          row(102, "Open"), row(103, "Open"))
        source_es = table(row(100, "Hola"), row(101, "Hola"),
                          row(102, "Abrir"), row(103, "Abierto"))
        memory = io.BytesIO()
        with patcher.zipfile.ZipFile(memory, "w") as archive:
            archive.writestr("LangPackageTableCnData.bytes", source_cn)
            archive.writestr("LangPackageTableEsesData.bytes", source_es)
        memory.seek(0)
        with patcher.zipfile.ZipFile(memory) as archive:
            replacements, coverage = patcher.build_replacements(
                target, archive, "es", {"Open": {"es": "Abierto"}})
        self.assertEqual(replacements, {1: "Hola", 2: "Hola", 3: "Abierto"})
        self.assertEqual(coverage["translated"], 3)
        self.assertEqual(coverage["official_translated"], 2)
        self.assertEqual(coverage["machine_translated"], 1)
        self.assertEqual(coverage["ambiguous"], 1)
        self.assertEqual(coverage["no_match"], 0)

    def test_unknown_replacement_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            replace_table_text(table(row(1, "one")), {2: "two"})

    def test_truncated_table_rejected(self):
        with self.assertRaises(ValueError):
            extract_texts(b"\x05\x00\x00\x00x")

    def test_interrupted_write_restores_the_pinned_original(self):
        original = table(row(1, "中文"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = "unit-test"
            patcher.STATE_ROOT = root
            target_dir = root / "client"
            target_dir.mkdir()
            backup_dir, journal_path = patcher.state_paths(profile)
            backup_dir.mkdir(parents=True)
            (backup_dir / patcher.TABLES[0]).write_bytes(original)
            (backup_dir / patcher.TABLES[1]).write_bytes(original)
            (target_dir / patcher.TABLES[0]).write_bytes(table(row(1, "English")))
            (target_dir / patcher.TABLES[1]).write_bytes(table(row(1, "English")))
            hashes = {name: patcher.sha256(original) for name in patcher.TABLES}
            journal_path.write_text(json.dumps({"profile": profile, "original_hashes": hashes}), encoding="utf-8")
            self.assertTrue(patcher.recover_if_needed(profile, target_dir))
            self.assertEqual((target_dir / patcher.TABLES[0]).read_bytes(), original)
            self.assertEqual((target_dir / patcher.TABLES[1]).read_bytes(), original)
            self.assertFalse(journal_path.exists())

    def test_open_game_blocks_before_any_state_is_written(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("patcher.inspect_game", return_value=("profile", Path(directory), {}, {})), \
                patch("patcher.is_game_running", return_value=True):
            with self.assertRaisesRegex(patcher.PatchError, "juego está abierto"):
                patcher.apply_language(Path(directory), "es")

    def test_gui_result_is_short_and_user_facing(self):
        message = Launcher._format_result("es", {
            "profile": "bilibili-4.0.5142-1192505",
            "coverage": {"translated": 335326, "target_rows": 518227,
                          "official_translated": 335326, "machine_translated": 0,
                          "fallback_cn": 182901, "ambiguous": 59542, "no_match": 123359,
                          "builtin_translated": 67},
            "tables": {"sha256": "hidden technical detail"},
        })
        self.assertIn("Español aplicado correctamente", message)
        self.assertIn("335.326 de 518.227", message)
        self.assertIn("64,7%", message)
        self.assertNotIn("sha256", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
