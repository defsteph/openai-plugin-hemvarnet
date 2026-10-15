"""Behavior checks for cached search, invalidation, and PDF page lookup."""

import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "search_handbooks", Path(__file__).with_name("search_handbooks.py"))
search = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(search)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "references"
        self.root.mkdir()
        self.books = {"a": "Bok A", "b": "Bok B"}
        (self.root / "a.txt").write_text(
            "HANDBOK\nSjukvård avtal ÅÄÖ ﬁnns\n1\f\f"
            "HANDBOK\nsjukvård sjukvård avtal\n3\f", encoding="utf-8")
        (self.root / "b.txt").write_text(
            "HANDBOK\navtal ÅÄÖ finns\n1\f", encoding="utf-8")
        for target, value in [("ROOT", self.root), ("BOOKS", self.books)]:
            p = patch.object(search, target, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(search, "CACHE_ROOT", Path(self.tmp.name) / "cache")
        p.start()
        self.addCleanup(p.stop)

    def run_cli(self, *args):
        output = io.StringIO()
        with patch("sys.argv", ["search_handbooks.py", *args]), contextlib.redirect_stdout(output):
            search.main()
        return output.getvalue()

    def test_cache_preserves_substrings_unicode_scores_and_ties(self):
        for query in ["sjukvård avtal", "ÅÄÖ", "finns", "ju", "avtal avtal", "saknas"]:
            with self.subTest(query=query):
                self.assertEqual(self.run_cli(query), self.run_cli(query, "--no-cache"))
        result = self.run_cli("sjukvård avtal")
        self.assertLess(result.index("PDF-sida 3"), result.index("PDF-sida 1"))

    def test_source_edit_rebuilds_cache(self):
        self.assertIn("No matches", self.run_cli("nyterm"))
        with (self.root / "b.txt").open("a", encoding="utf-8") as f:
            f.write("nyterm\n2\f")
        self.assertIn("Bok B | b | s. 2 (PDF-sida 2)", self.run_cli("nyterm"))

    def test_corrupt_cache_is_rebuilt(self):
        expected = self.run_cli("avtal")
        cache = next(Path(self.tmp.name).rglob("*.sqlite3"))
        cache.write_bytes(b"not a database")
        self.assertEqual(expected, self.run_cli("avtal"))

    def test_unwritable_cache_falls_back_to_source(self):
        expected = self.run_cli("avtal", "--no-cache")
        with patch.object(search, "open_index", side_effect=PermissionError):
            self.assertEqual(expected, self.run_cli("avtal"))

    def test_context_preserves_blank_pdf_page_positions(self):
        args = ("--book", "a", "--page", "3", "--context", "2")
        result = self.run_cli(*args)
        self.assertEqual(result, self.run_cli(*args, "--no-cache"))
        self.assertIn("PDF-sida 1", result)
        self.assertIn("PDF-sida 3", result)
        self.assertNotIn("PDF-sida 2", result)

    def test_single_book_and_page_lookup_skip_cache_startup(self):
        with patch.object(search, "open_index") as index:
            self.assertIn("Bok A", self.run_cli("sjukvård", "--book", "a"))
            self.assertIn("PDF-sida 3", self.run_cli("--book", "a", "--page", "3"))
            index.assert_not_called()


if __name__ == "__main__":
    unittest.main()
