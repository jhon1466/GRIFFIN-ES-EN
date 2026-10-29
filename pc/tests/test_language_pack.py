import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import language_pack
import patcher
from table_codec import extract_texts
from test_table_codec import row, table


def make_pack(main_es=None, machine=None):
    pack = {"format": language_pack.FORMAT, "keys": "sha1-16", "profiles": [],
            "main": {"en": {}, "es": main_es or {}}, "builtin": {"en": {}, "es": {}},
            "machine": {"main": {"en": set(), "es": set(machine or ())}, "builtin": {"en": set(), "es": set()}}}
    return pack


class LanguagePackTests(unittest.TestCase):
    def test_pack_round_trip_and_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "language-pack-v2.json.gz"
            pack = make_pack({language_pack.key_of("你好"): "Hola"}, {language_pack.key_of("你好")})
            language_pack.write_pack(pack, path)
            loaded = language_pack.load_pack(path)
            self.assertEqual(loaded["main"]["es"][language_pack.key_of("你好")], "Hola")
            self.assertIn(language_pack.key_of("你好"), loaded["machine"]["main"]["es"])
            # a damaged file is refused, never half-applied
            path.write_bytes(path.read_bytes()[:-5] + b"xxxxx")
            with self.assertRaises(language_pack.PackError):
                language_pack.load_pack(path)

    def test_missing_pack_explains_where_to_get_it(self):
        with self.assertRaisesRegex(language_pack.PackError, "release"):
            language_pack.load_pack(Path(tempfile.gettempdir()) / "no-such-pack.json.gz")

    def test_rows_are_matched_by_chinese_text_and_flagged(self):
        pack = make_pack({language_pack.key_of("打开"): "Abrir", language_pack.key_of("关闭"): "Cerrar"},
                         {language_pack.key_of("关闭")})
        target = table(row(1, "打开"), row(2, "关闭"), row(3, "未知"), row(4, ""))
        replacements, coverage = patcher.build_replacements_from_pack(target, pack, "es", "main")
        self.assertEqual(replacements, {1: "Abrir", 2: "Cerrar"})
        self.assertEqual(coverage["translated"], 2)
        self.assertEqual(coverage["official_translated"], 1)
        self.assertEqual(coverage["machine_translated"], 1)
        self.assertEqual(coverage["fallback_cn"], 1)
        self.assertEqual(coverage["empty_rows"], 1)

    def test_applying_a_language_needs_nothing_but_the_pack(self):
        original = table(row(1, "打开"), row(2, "未知"))
        builtin = table(row(1, "中文"))
        profile = "unit-pack"
        info = {"main": patcher.sha256(original), "builtin": patcher.sha256(builtin),
                "code": "x", "cache": "x", "table": "x"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = root / "client"
            game.mkdir()
            (game / patcher.TABLES[0]).write_bytes(original)
            (game / patcher.TABLES[1]).write_bytes(builtin)
            pack_file = root / "language-pack-v2.json.gz"
            language_pack.write_pack(make_pack({language_pack.key_of("打开"): "Abrir"}), pack_file)
            hashes = {patcher.TABLES[0]: info["main"], patcher.TABLES[1]: info["builtin"]}

            def no_network(*args, **kwargs):
                raise AssertionError("the patcher must not go online")

            with patch.dict(patcher.PROFILES, {profile: info}), \
                    patch.object(patcher, "STATE_ROOT", root / "state"), \
                    patch.object(patcher, "inspect_game", return_value=(profile, game, {}, hashes)), \
                    patch.object(patcher, "is_game_running", return_value=False), \
                    patch.dict("os.environ", {"GRIFFIN_LANGUAGE_PACK": str(pack_file)}), \
                    patch.object(patcher, "sources", side_effect=no_network), \
                    patch.object(patcher.urllib.request, "urlopen", side_effect=no_network):
                report = patcher.apply_language(game, "es")
            self.assertEqual(extract_texts((game / patcher.TABLES[0]).read_bytes()), {1: "Abrir", 2: "未知"})
            self.assertEqual(report["coverage"]["translated"], 1)
            # restoring Chinese needs only the backup taken before the first write
            with patch.dict(patcher.PROFILES, {profile: info}), \
                    patch.object(patcher, "STATE_ROOT", root / "state"), \
                    patch.object(patcher, "is_game_running", return_value=False), \
                    patch.object(patcher, "inspect_game", return_value=(profile, game, {}, {
                        name: patcher.sha256((game / name).read_bytes()) for name in patcher.TABLES})):
                patcher.apply_language(game, "cn")
            self.assertEqual((game / patcher.TABLES[0]).read_bytes(), original)

    def test_protected_folder_asks_for_administrator_instead_of_failing_silently(self):
        original = table(row(1, "打开"))
        with tempfile.TemporaryDirectory() as directory:
            game = Path(directory)
            (game / patcher.TABLES[0]).write_bytes(original)
            hashes = {patcher.TABLES[0]: patcher.sha256(original), patcher.TABLES[1]: patcher.sha256(original)}
            with patch.object(patcher, "inspect_game", return_value=("profile", game, {}, hashes)), \
                    patch.object(patcher, "is_game_running", return_value=False), \
                    patch.object(patcher, "can_write_tables", return_value=False):
                with self.assertRaises(patcher.ElevationRequired):
                    patcher.apply_language(game, "es")

    def test_cli_relaunches_elevated_when_the_folder_is_protected(self):
        calls = []
        with patch.object(patcher, "apply_language", side_effect=patcher.ElevationRequired("protegida")), \
                patch.object(patcher, "is_admin", return_value=False), \
                patch.object(patcher, "relaunch_elevated", side_effect=lambda *a, **k: calls.append((a, k)) or True), \
                patch.object(sys, "argv", ["patcher.py", "--game-dir", "C:/x", "es"]):
            self.assertEqual(patcher.main(), 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][1], ["--game-dir", str(Path("C:/x")), "es"])
        self.assertTrue(calls[0][1]["keep_console"])


if __name__ == "__main__":
    unittest.main()
