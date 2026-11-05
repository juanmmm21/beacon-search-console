"""Sistemas híbridos de la evaluación (`dense-hnsw`, `bm25+dense-rrf`,
`hybrid-rrf+ce`) sobre `beacon_search_console.hybrid`, el mismo código que
sirve la consola. Requiere el extra `hybrid` (PyTorch y los componentes de
AI Core)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from beacon_search_console.hybrid import (
    DenseIndex,
    HybridSearcher,
    SentenceEncoder,
    build_dense_index,
)

logger = logging.getLogger(__name__)


class DenseSystem:
    """Solo recuperación densa: HNSW de nano-vector-db sobre los embeddings."""

    name = "dense-hnsw"

    def __init__(self, searcher: HybridSearcher) -> None:
        self._searcher = searcher

    def retrieve(self, raw_query: str, depth: int) -> list[int]:
        return self._searcher.dense(raw_query, depth)


class HybridSystem:
    """BM25 + denso fusionados con RRF y, si `rerank`, reordenados con el
    cross-encoder (los primeros `rerank_depth` de la fusión)."""

    def __init__(self, name: str, searcher: HybridSearcher, *, rerank: bool) -> None:
        self.name = name
        self._searcher = searcher
        self._rerank = rerank

    def retrieve(self, raw_query: str, depth: int) -> list[int]:
        return [hit.doc_id for hit in self._searcher.search(raw_query, depth, rerank=self._rerank)]


def load_or_build_dense_index(
    corpus_texts: Sequence[str], encoder: SentenceEncoder, cache_dir: Path
) -> DenseIndex:
    """Los vectores son lo caro (una pasada del modelo por todo el corpus):
    se guardan en `cache_dir` y se reutilizan si son del mismo modelo. El
    grafo HNSW se reconstruye siempre a partir de ellos (`DenseIndex.load`)."""
    if (cache_dir / "manifest.json").exists():
        cached = DenseIndex.load(cache_dir)
        if cached.model_name == encoder.model_name and len(cached) == len(corpus_texts):
            return cached
        logger.info("vectores en caché de otro modelo o corpus: se recalculan")
    index = build_dense_index(list(range(len(corpus_texts))), corpus_texts, encoder)
    index.save(cache_dir)
    return index
