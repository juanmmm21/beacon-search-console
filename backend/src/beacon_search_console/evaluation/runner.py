"""Ejecuta una evaluación completa sobre una colección BEIR y produce un
informe JSON autocontenido (métricas, tiempos, máquina y versiones)."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from learning_to_rank_reranker.index_reader import InvertedIndexReader
from learning_to_rank_reranker.model import LightGBMRankerParams, LightGBMReranker
from learning_to_rank_reranker.pipeline import train as train_synthetic_ltr

from beacon_search_console.evaluation.corpus import PreparedCorpus, prepare_corpus
from beacon_search_console.evaluation.datasets import BEIR_DATASETS, ensure_dataset
from beacon_search_console.evaluation.environment import describe_environment
from beacon_search_console.evaluation.metrics import RunMetrics, evaluate_run
from beacon_search_console.evaluation.systems import (
    Bm25LtrSystem,
    Bm25System,
    LtrReranker,
    RetrievalSystem,
    train_ltr_on_qrels,
)

logger = logging.getLogger(__name__)

RETRIEVAL_DEPTH = 100
"""Profundidad de cada ranking: la que necesita Recall@100."""

SYSTEM_NAMES: tuple[str, ...] = ("bm25", "bm25+ltr-synthetic", "bm25+ltr-qrels")


@dataclass(frozen=True, slots=True)
class SystemResult:
    system: str
    metrics: RunMetrics
    seconds: float
    queries_per_second: float
    notes: str


@dataclass(frozen=True, slots=True)
class EvaluationConfig:
    dataset: str
    data_dir: Path
    work_dir: Path
    systems: tuple[str, ...]
    max_queries: int | None = None
    """Primeras N queries de test (orden por `query_id`); `None` = todas."""
    ltr_train_max_queries: int | None = 1000
    seed: int = 42

    def __post_init__(self) -> None:
        unknown = set(self.systems) - set(SYSTEM_NAMES)
        if unknown:
            raise ValueError(f"sistemas desconocidos {sorted(unknown)}; válidos: {SYSTEM_NAMES}")
        if self.dataset not in BEIR_DATASETS:
            raise ValueError(f"dataset desconocido {self.dataset!r}")


def _run_system(
    system: RetrievalSystem,
    queries: dict[str, str],
    qrels: dict[str, dict[str, int]],
    corpus: PreparedCorpus,
    notes: str,
) -> SystemResult:
    run: dict[str, list[str]] = {}
    started = time.perf_counter()
    for query_id in sorted(qrels):
        raw_query = queries.get(query_id)
        if raw_query is None:
            continue
        run[query_id] = [
            corpus.doc_ids[doc_id] for doc_id in system.retrieve(raw_query, RETRIEVAL_DEPTH)
        ]
    elapsed = time.perf_counter() - started
    metrics = evaluate_run(run, qrels)
    return SystemResult(
        system=system.name,
        metrics=metrics,
        seconds=round(elapsed, 3),
        queries_per_second=round(len(run) / elapsed, 2) if elapsed > 0 else 0.0,
        notes=notes,
    )


def run_evaluation(config: EvaluationConfig) -> dict[str, Any]:
    dataset = ensure_dataset(config.dataset, config.data_dir)
    corpus = prepare_corpus(dataset, config.work_dir / config.dataset)
    queries = dataset.queries()
    test_qrels = dataset.qrels("test")
    if config.max_queries is not None:
        test_qrels = {qid: test_qrels[qid] for qid in sorted(test_qrels)[: config.max_queries]}

    bm25 = Bm25System(corpus.index_dir)
    results: list[SystemResult] = []
    # El lector del LTR carga todas las posiciones en memoria: solo se abre si
    # algún sistema pedido lo necesita, y una única vez para los dos LTR.
    needs_ltr = bool({"bm25+ltr-synthetic", "bm25+ltr-qrels"} & set(config.systems))
    ltr_index = InvertedIndexReader(corpus.index_dir) if needs_ltr else None
    try:
        if "bm25" in config.systems:
            results.append(_run_system(bm25, queries, test_qrels, corpus, ""))

        if ltr_index is not None and "bm25+ltr-synthetic" in config.systems:
            # Mismo entrenamiento que scripts/bootstrap_corpus.sh: el modelo que
            # la consola sirve hoy, entrenado solo con datos sintéticos.
            model = LightGBMReranker(LightGBMRankerParams())
            train_synthetic_ltr(model, num_queries=300, candidates_per_query=25, seed=42)
            system = Bm25LtrSystem("bm25+ltr-synthetic", bm25, LtrReranker(ltr_index, model))
            results.append(
                _run_system(
                    system,
                    queries,
                    test_qrels,
                    corpus,
                    "modelo entrenado con el dataset sintético del bootstrap (300 queries)",
                )
            )

        if ltr_index is not None and "bm25+ltr-qrels" in config.systems:
            spec = BEIR_DATASETS[config.dataset]
            if spec.train_split is None:
                raise ValueError(f"{config.dataset} no tiene split de entrenamiento")
            beir_to_beacon = {doc_id: index for index, doc_id in enumerate(corpus.doc_ids)}
            model, used_queries = train_ltr_on_qrels(
                bm25,
                ltr_index,
                queries,
                dataset.qrels(spec.train_split),
                beir_to_beacon,
                depth=RETRIEVAL_DEPTH,
                max_queries=config.ltr_train_max_queries,
                seed=config.seed,
            )
            system = Bm25LtrSystem("bm25+ltr-qrels", bm25, LtrReranker(ltr_index, model))
            results.append(
                _run_system(
                    system,
                    queries,
                    test_qrels,
                    corpus,
                    f"modelo entrenado con qrels/{spec.train_split}.tsv ({used_queries} queries)",
                )
            )

    finally:
        bm25.close()

    return {
        "dataset": config.dataset,
        "split": "test",
        "documents": len(corpus.doc_ids),
        "queries": len(test_qrels),
        "max_queries": config.max_queries,
        "retrieval_depth": RETRIEVAL_DEPTH,
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "environment": describe_environment(),
        "results": [{**asdict(result), "metrics": asdict(result.metrics)} for result in results],
    }


def metrics_by_system(report: dict[str, Any]) -> dict[str, dict[str, float]]:
    return {
        str(result["system"]): {
            key: float(value)
            for key, value in result["metrics"].items()
            if key in ("ndcg_at_10", "mrr_at_10", "recall_at_100")
        }
        for result in report["results"]
    }


def check_against_baseline(
    report: dict[str, Any], baseline: dict[str, Any], tolerance: float
) -> Sequence[str]:
    """Regresiones de `report` frente a `baseline` (`system -> metric ->
    valor`): una métrica que baja más de `tolerance` (absoluta) es un fallo."""
    measured = metrics_by_system(report)
    failures: list[str] = []
    for system, expected_metrics in baseline["metrics"].items():
        actual_metrics = measured.get(system)
        if actual_metrics is None:
            failures.append(f"{system}: no se midió")
            continue
        for metric, expected in expected_metrics.items():
            actual = actual_metrics.get(metric)
            if actual is None:
                failures.append(f"{system}.{metric}: no se midió")
            elif actual < float(expected) - tolerance:
                failures.append(
                    f"{system}.{metric}: {actual:.4f} < base {float(expected):.4f} - {tolerance}"
                )
    return failures
