"""Métricas estándar de recuperación, con las mismas definiciones que
`trec_eval`/`pytrec_eval` (las que usa BEIR al publicar sus tablas):

- nDCG@k con ganancia lineal (`rel`, no `2^rel - 1`) y descuento `log2(i + 1)`;
  el ideal se calcula sobre todos los juicios de la query, no solo sobre los
  documentos recuperados.
- MRR@k: inverso del rango del primer documento con `rel > 0` dentro de los k
  primeros; 0 si no hay ninguno.
- Recall@k: fracción de los documentos con `rel > 0` que aparecen en los k
  primeros.

Una query sin ningún juicio positivo no aporta información a ninguna de las
tres: `evaluate_run` la excluye del promedio (mismo criterio que BEIR) y lo
deja contado en `skipped_queries`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


def ndcg_at_k(ranking: Sequence[str], judgments: Mapping[str, int], k: int) -> float:
    if k < 1:
        raise ValueError(f"k debe ser >= 1, recibido {k}")
    dcg = 0.0
    for rank, doc_id in enumerate(ranking[:k], start=1):
        grade = judgments.get(doc_id, 0)
        if grade > 0:
            dcg += grade / math.log2(rank + 1)
    ideal_grades = sorted((grade for grade in judgments.values() if grade > 0), reverse=True)
    idcg = sum(grade / math.log2(rank + 1) for rank, grade in enumerate(ideal_grades[:k], start=1))
    return dcg / idcg if idcg > 0 else 0.0


def mrr_at_k(ranking: Sequence[str], judgments: Mapping[str, int], k: int) -> float:
    if k < 1:
        raise ValueError(f"k debe ser >= 1, recibido {k}")
    for rank, doc_id in enumerate(ranking[:k], start=1):
        if judgments.get(doc_id, 0) > 0:
            return 1.0 / rank
    return 0.0


def recall_at_k(ranking: Sequence[str], judgments: Mapping[str, int], k: int) -> float:
    if k < 1:
        raise ValueError(f"k debe ser >= 1, recibido {k}")
    relevant = {doc_id for doc_id, grade in judgments.items() if grade > 0}
    if not relevant:
        return 0.0
    retrieved = set(ranking[:k])
    return len(relevant & retrieved) / len(relevant)


@dataclass(frozen=True, slots=True)
class RunMetrics:
    ndcg_at_10: float
    mrr_at_10: float
    recall_at_100: float
    evaluated_queries: int
    skipped_queries: int


def evaluate_run(
    run: Mapping[str, Sequence[str]], qrels: Mapping[str, Mapping[str, int]]
) -> RunMetrics:
    """Promedia las tres métricas sobre las queries de `run` que tienen al
    menos un juicio positivo en `qrels`. Una query evaluable que no aparece en
    `run` cuenta como ranking vacío (métrica 0), nunca se ignora."""
    ndcg_total = mrr_total = recall_total = 0.0
    evaluated = skipped = 0
    for query_id, judgments in qrels.items():
        if not any(grade > 0 for grade in judgments.values()):
            skipped += 1
            continue
        ranking = run.get(query_id, ())
        ndcg_total += ndcg_at_k(ranking, judgments, 10)
        mrr_total += mrr_at_k(ranking, judgments, 10)
        recall_total += recall_at_k(ranking, judgments, 100)
        evaluated += 1
    if evaluated == 0:
        return RunMetrics(0.0, 0.0, 0.0, 0, skipped)
    return RunMetrics(
        ndcg_at_10=ndcg_total / evaluated,
        mrr_at_10=mrr_total / evaluated,
        recall_at_100=recall_total / evaluated,
        evaluated_queries=evaluated,
        skipped_queries=skipped,
    )
