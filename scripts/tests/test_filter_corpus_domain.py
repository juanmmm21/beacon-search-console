"""Tests de `filter_corpus_domain.py`. `unittest` de la stdlib a propósito
(nada de `pytest`): este script es un paso operativo del bootstrap, no parte
del paquete `backend/`, y no debería arrastrar una dependencia de test solo
para sí mismo. Ejecutar con `python3 -m unittest discover -s scripts/tests`
desde cualquier intérprete Python >=3.11, sin instalar nada."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from filter_corpus_domain import filter_pages_by_domain  # noqa: E402


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class FilterPagesByDomainTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_keeps_only_allowed_domain(self) -> None:
        input_path = self.tmp_path / "pages.jsonl"
        output_path = self.tmp_path / "filtered.jsonl"
        _write_jsonl(
            input_path,
            [
                json.dumps({"url": "https://docs.python.org/3/tutorial/index.html"}),
                json.dumps({"url": "https://github.com/python/cpython/blob/main/README.rst"}),
                json.dumps({"url": "https://docs.python.org/3/library/sqlite3.html"}),
            ],
        )

        stats = filter_pages_by_domain(
            input_path, output_path, frozenset({"docs.python.org"})
        )

        self.assertEqual(stats.total_lines, 3)
        self.assertEqual(stats.kept, 2)
        self.assertEqual(stats.dropped_wrong_domain, 1)
        self.assertEqual(stats.dropped_malformed, 0)

        kept_urls = [json.loads(line)["url"] for line in output_path.read_text().splitlines()]
        self.assertEqual(
            kept_urls,
            [
                "https://docs.python.org/3/tutorial/index.html",
                "https://docs.python.org/3/library/sqlite3.html",
            ],
        )

    def test_case_insensitive_host_match(self) -> None:
        input_path = self.tmp_path / "pages.jsonl"
        output_path = self.tmp_path / "filtered.jsonl"
        _write_jsonl(input_path, [json.dumps({"url": "https://DOCS.PYTHON.ORG/3/whatsnew/"})])

        stats = filter_pages_by_domain(
            input_path, output_path, frozenset({"docs.python.org"})
        )

        self.assertEqual(stats.kept, 1)

    def test_malformed_line_is_dropped_not_fatal(self) -> None:
        input_path = self.tmp_path / "pages.jsonl"
        output_path = self.tmp_path / "filtered.jsonl"
        _write_jsonl(
            input_path,
            [
                "{not valid json",
                json.dumps({"title": "sin campo url"}),
                json.dumps({"url": "https://docs.python.org/3/"}),
            ],
        )

        stats = filter_pages_by_domain(
            input_path, output_path, frozenset({"docs.python.org"})
        )

        self.assertEqual(stats.total_lines, 3)
        self.assertEqual(stats.dropped_malformed, 2)
        self.assertEqual(stats.kept, 1)

    def test_blank_lines_are_skipped_without_counting(self) -> None:
        input_path = self.tmp_path / "pages.jsonl"
        output_path = self.tmp_path / "filtered.jsonl"
        input_path.write_text(
            "\n" + json.dumps({"url": "https://docs.python.org/3/"}) + "\n\n",
            encoding="utf-8",
        )

        stats = filter_pages_by_domain(
            input_path, output_path, frozenset({"docs.python.org"})
        )

        self.assertEqual(stats.total_lines, 1)
        self.assertEqual(stats.kept, 1)

    def test_can_overwrite_input_path_in_place(self) -> None:
        input_path = self.tmp_path / "pages.jsonl"
        _write_jsonl(
            input_path,
            [
                json.dumps({"url": "https://docs.python.org/3/"}),
                json.dumps({"url": "https://github.com/python/cpython"}),
            ],
        )

        stats = filter_pages_by_domain(
            input_path, input_path, frozenset({"docs.python.org"})
        )

        self.assertEqual(stats.kept, 1)
        remaining = input_path.read_text().splitlines()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(json.loads(remaining[0])["url"], "https://docs.python.org/3/")

    def test_multiple_allowed_domains(self) -> None:
        input_path = self.tmp_path / "pages.jsonl"
        output_path = self.tmp_path / "filtered.jsonl"
        _write_jsonl(
            input_path,
            [
                json.dumps({"url": "https://docs.python.org/3/"}),
                json.dumps({"url": "https://peps.python.org/pep-0008/"}),
                json.dumps({"url": "https://example.com/"}),
            ],
        )

        stats = filter_pages_by_domain(
            input_path, output_path, frozenset({"docs.python.org", "peps.python.org"})
        )

        self.assertEqual(stats.kept, 2)
        self.assertEqual(stats.dropped_wrong_domain, 1)


if __name__ == "__main__":
    unittest.main()
