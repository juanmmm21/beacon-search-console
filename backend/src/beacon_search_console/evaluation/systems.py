"""Sistemas de recuperación que compara la evaluación. Cada uno envuelve los
mismos componentes que usa la consola en producción (`bm25-ranking-engine`,
`learning-to-rank-reranker`, `query-parser-autocomplete`), cargados una única
vez por colección — nunca por query.

PageRank no interviene: las colecciones BEIR son documentos sueltos sin
enlaces entre sí, así que no hay grafo del que calcularlo. La feature
`pagerank_score` del LTR vale 0 para todo documento (el mismo valor que
`learning-to-rank-reranker` asigna a una página sin enlaces), tanto al
entrenar como al evaluar.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

import numpy as np
from bm25_ranking_engine.pipeline import BM25RankingPipeline
from learning_to_rank_reranker.feature_extraction import extract_features
from learning_to_rank_reranker.index_reader import InvertedIndexReader
from learning_to_rank_reranker.model import LightGBMRankerParams, LightGBMReranker
from learning_to_rank_reranker.models import Candidate
from query_parser_autocomplete.query_parser import parse_query

logger = logging.getLogger(__name__)

_NO_PAGERANK: dict[int, float] = {}


def query_terms(raw_query: str) -> list[str]:
    """Términos por los que puntúa la consola: `required_terms` más los de
    cada frase, igual que `distributed-index-sharding` aplana la query. Las
    exclusiones y filtros no aplican a consultas en lenguaje natural."""
    parsed = parse_query(raw_query)
    return list(parsed.required_terms) + [term for phrase in parsed.phrases for term in phrase]


class RetrievalSystem(Protocol):
    name: str

    def retrieve(self, raw_query: str, depth: int) -> list[int]:
        """`doc_id` de Beacon ordenados por relevancia, como mucho `depth`."""
        ...


class Bm25System:
    name = "bm25"

    def __init__(self, index_dir: Path) -> None:
        self._pipeline = BM25RankingPipeline(index_dir)

    def close(self) -> None:
        self._pipeline.close()

    def scored(self, raw_query: str, depth: int) -> list[tuple[int, float]]:
        terms = query_terms(raw_query)
        if not terms:
            return []
        return [(hit.doc_id, hit.score) for hit in self._pipeline.search_tokens(terms, top_k=depth)]

    def retrieve(self, raw_query: str, depth: int) -> list[int]:
        return [doc_id for doc_id, _ in self.scored(raw_query, depth)]


class LtrReranker:
    """Reordena candidatos BM25 con un modelo de `learning-to-rank-reranker`
    usando su propia extracción de features, contra un lector de índice
    abierto una sola vez."""

    def __init__(self, index: InvertedIndexReader, model: LightGBMReranker) -> None:
        self._index = index
        self._model = model

    @property
    def index(self) -> InvertedIndexReader:
        return self._index

    def rerank(self, candidates: Sequence[tuple[int, float]], terms: Sequence[str]) -> list[int]:
        if not candidates or not terms:
            return [doc_id for doc_id, _ in candidates]
        features = extract_features(
            [Candidate(doc_id=doc_id, bm25_score=score) for doc_id, score in candidates],
            terms,
            self._index,
            _NO_PAGERANK,
        )
        matrix = np.array([feature.to_array() for feature in features], dtype=np.float64)
        scores = self._model.predict(matrix)
        ranked = sorted(
            zip((doc_id for doc_id, _ in candidates), scores.tolist(), strict=True),
            key=lambda item: (-item[1], item[0]),
        )
        return [doc_id for doc_id, _ in ranked]


class Bm25LtrSystem:
    """BM25 top-`depth` reordenado por LTR. Reordena el mismo conjunto de
    candidatos, así que Recall@depth es idéntico al de BM25 por construcción."""

    def __init__(self, name: str, bm25: Bm25System, reranker: LtrReranker) -> None:
        self.name = name
        self._bm25 = bm25
        self._reranker = reranker

    def retrieve(self, raw_query: str, depth: int) -> list[int]:
        candidates = self._bm25.scored(raw_query, depth)
        return self._reranker.rerank(candidates, query_terms(raw_query))


def train_ltr_on_qrels(
    bm25: Bm25System,
    index: InvertedIndexReader,
    queries: Mapping[str, str],
    train_qrels: Mapping[str, Mapping[str, int]],
    beir_to_beacon: Mapping[str, int],
    *,
    depth: int,
    max_queries: int | None,
    seed: int,
) -> tuple[LightGBMReranker, int]:
    """Entrena un `LightGBMReranker` con los juicios del split de
    entrenamiento de la colección (nunca el de test) sobre los candidatos
    BM25 top-`depth` de cada query. Una query cuyo top-`depth` no contiene
    ningún relevante no enseña nada a LambdaRank y se descarta. Devuelve el
    modelo y el número de queries usadas."""
    rows: list[np.ndarray] = []
    labels: list[int] = []
    group_sizes: list[int] = []
    query_ids = sorted(train_qrels)
    if max_queries is not None and len(query_ids) > max_queries:
        rng = np.random.default_rng(seed)
        query_ids = sorted(rng.choice(query_ids, size=max_queries, replace=False).tolist())

    for query_id in query_ids:
        raw_query = queries.get(query_id)
        if raw_query is None:
            continue
        terms = query_terms(raw_query)
        candidates = bm25.scored(raw_query, depth)
        if not candidates or not terms:
            continue
        judgments = {
            beir_to_beacon[doc_id]: grade
            for doc_id, grade in train_qrels[query_id].items()
            if doc_id in beir_to_beacon
        }
        grades = [min(4, max(0, judgments.get(doc_id, 0))) for doc_id, _ in candidates]
        if not any(grades):
            continue
        features = extract_features(
            [Candidate(doc_id=doc_id, bm25_score=score) for doc_id, score in candidates],
            terms,
            index,
            _NO_PAGERANK,
        )
        rows.extend(feature.to_array() for feature in features)
        labels.extend(grades)
        group_sizes.append(len(candidates))

    if not group_sizes:
        raise ValueError("ninguna query de entrenamiento tiene un relevante en su top BM25")
    model = LightGBMReranker(LightGBMRankerParams(seed=seed))
    model.fit(
        np.vstack(rows).astype(np.float64),
        np.asarray(labels, dtype=np.int64),
        np.asarray(group_sizes, dtype=np.int64),
    )
    return model, len(group_sizes)
