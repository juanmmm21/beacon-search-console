"""Tests de `hybrid.py` que no necesitan descargar modelos: RRF, el índice
denso de nano-vector-db (HNSW real) con vectores sintéticos, la orquestación
con un codificador de prueba y el rechazo explícito del modo léxico de
respaldo de cross-encoder-reranker."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from beacon_search_console.hybrid import (
    CrossEncoderStage,
    DenseIndex,
    HybridSearcher,
    HybridSearchError,
    reciprocal_rank_fusion,
)


def test_rrf_by_hand() -> None:
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 1]], k=60)
    scores = dict(fused)
    assert scores[1] == pytest.approx(1 / 61 + 1 / 62)
    assert scores[3] == pytest.approx(1 / 63 + 1 / 61)
    assert scores[2] == pytest.approx(1 / 62)
    assert [doc_id for doc_id, _ in fused] == [1, 3, 2]


def test_rrf_ties_break_by_doc_id() -> None:
    assert [d for d, _ in reciprocal_rank_fusion([[5], [4]])] == [4, 5]


def _vectors(count: int, dimension: int = 16, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    matrix = rng.normal(size=(count, dimension)).astype(np.float32)
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def test_dense_index_finds_exact_vector_and_round_trips(tmp_path: Path) -> None:
    vectors = _vectors(200)
    index = DenseIndex(np.arange(200, dtype=np.int64) * 10, vectors, model_name="test-model")
    assert index.search(vectors[42], 1)[0][0] == 420
    assert index.search(vectors[42], 1)[0][1] == pytest.approx(1.0, abs=1e-5)
    index.save(tmp_path / "dense")
    loaded = DenseIndex.load(tmp_path / "dense")
    assert loaded.model_name == "test-model" and len(loaded) == 200
    expected = [doc_id for doc_id, _ in index.search(vectors[7], 5)]
    assert [doc_id for doc_id, _ in loaded.search(vectors[7], 5)] == expected


def test_dense_index_rejects_other_versions(tmp_path: Path) -> None:
    DenseIndex(np.arange(3), _vectors(3), model_name="m").save(tmp_path)
    (tmp_path / "manifest.json").write_text('{"format_version": 9}')
    with pytest.raises(HybridSearchError):
        DenseIndex.load(tmp_path)


class _FakeEncoder:
    model_name = "fake"

    def __init__(self, table: dict[str, np.ndarray]) -> None:
        self._table = table

    def encode(self, texts: Sequence[str], *, batch_size: int = 64) -> np.ndarray:
        return np.vstack([self._table[text] for text in texts])


def test_hybrid_searcher_fuses_lexical_and_dense() -> None:
    vectors = _vectors(4)
    index = DenseIndex(np.arange(4), vectors, model_name="fake")
    encoder = _FakeEncoder({"q": vectors[3]})
    searcher = HybridSearcher(
        lambda query, depth: [0, 1],
        encoder,  # type: ignore[arg-type]
        index,
        {i: f"doc {i}" for i in range(4)},
        None,
        candidate_depth=4,
    )
    hits = searcher.search("q", 4)
    assert {hit.doc_id for hit in hits} == {0, 1, 2, 3}
    by_id = {hit.doc_id: hit for hit in hits}
    assert by_id[3].dense_rank == 1 and by_id[3].bm25_rank is None
    assert by_id[0].bm25_rank == 1


def test_hybrid_searcher_refuses_vectors_from_another_model() -> None:
    index = DenseIndex(np.arange(2), _vectors(2), model_name="model-a")
    with pytest.raises(HybridSearchError):
        HybridSearcher(
            lambda q, d: [],
            _FakeEncoder({}),  # type: ignore[arg-type]
            index,
            {},
            None,
        )


def test_cross_encoder_fallback_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    with pytest.raises(HybridSearchError):
        CrossEncoderStage("beacon/this-model-does-not-exist", device="cpu")
