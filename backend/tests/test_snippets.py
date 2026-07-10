"""Tests de correlación doc_id -> texto real y resaltado de coincidencias."""

from __future__ import annotations

from pathlib import Path

from beacon_search_console.snippets import SnippetIndex, build_snippet, latest_fetched_at

_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "samples" / "tiny_corpus"
_DOCUMENTS_PATH = _FIXTURE_ROOT / "extracted" / "documents.jsonl"


def test_snippet_index_resolves_documents_by_line_position() -> None:
    index = SnippetIndex.from_documents_path(_DOCUMENTS_PATH)
    assert len(index) == 5
    document = index.document(0)
    assert document is not None
    assert document.url == "http://example.com/python-tutorial"
    assert document.title == "Python Tutorial"
    assert "python" in document.main_text.lower()


def test_snippet_index_out_of_range_returns_none() -> None:
    index = SnippetIndex.from_documents_path(_DOCUMENTS_PATH)
    assert index.document(999) is None


def test_build_snippet_highlights_matched_terms() -> None:
    text = "This guide shows how to build a simple search index in python using bm25 ranking."
    snippet = build_snippet(text, ["search", "python"])
    assert snippet.highlights
    for highlight in snippet.highlights:
        fragment = snippet.text[highlight.start : highlight.end].casefold()
        assert fragment in {"search", "python"}


def test_build_snippet_falls_back_to_start_without_match() -> None:
    text = "Nothing here matches the query terms at all."
    snippet = build_snippet(text, ["unrelated", "term"])
    assert snippet.highlights == ()
    assert snippet.text.startswith("Nothing here matches")


def test_build_snippet_empty_text() -> None:
    snippet = build_snippet("", ["python"])
    assert snippet.text == ""
    assert snippet.highlights == ()


def test_build_snippet_marks_window_truncation_with_ellipsis() -> None:
    text = ("padding " * 40) + "python search target " + ("padding " * 40)
    snippet = build_snippet(text, ["python"])
    assert snippet.text.startswith("…")
    assert snippet.text.endswith("…")


def test_latest_fetched_at_returns_max_timestamp() -> None:
    latest = latest_fetched_at(_DOCUMENTS_PATH)
    assert latest == "2026-07-09T10:00:00+00:00"


def test_latest_fetched_at_missing_file_returns_none(tmp_path: Path) -> None:
    assert latest_fetched_at(tmp_path / "does-not-exist.jsonl") is None
