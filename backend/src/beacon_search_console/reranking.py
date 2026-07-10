"""Puente entre `distributed-index-sharding` y `learning-to-rank-reranker`:
la pieza de integración que ningún README de esos dos proyectos documenta,
porque ninguno de los dos conoce al otro (`../../AGENTS.md`: la única pieza
que ensambla a las nueve es esta).

`learning_to_rank_reranker.pipeline.rerank` abre un único directorio de índice
`inverted-index-builder` por llamada (necesita longitud de documento y
posiciones de término coincidentes de un directorio concreto, ver su
`feature_extraction.py`) — pero el corpus de este proyecto vive partido en N
shards, cada uno con su propio `postings.jsonl` local
(`distributed-index-sharding`, particionado por `doc_id % num_shards`, ver su
`partitioning.py`). Así que reordenar una lista ya fusionada entre shards
exige: agrupar los candidatos por el shard al que pertenece su `doc_id`,
invocar `rerank()` una vez por shard contra el índice local de ese shard
(compartiendo el mismo directorio global de PageRank, que sí es único para
todo el corpus, a diferencia del índice), y fusionar los resultados ya
reordenados de cada shard con el mismo criterio de desempate que usa el resto
del ecosistema: score descendente, `doc_id` ascendente (`../../CLAUDE.md`,
sección 2.B). Esta fusión final es, en espíritu, el mismo k-way merge que
`distributed_index_sharding.merge` ya hace un nivel más abajo para BM25 — se
repite aquí porque el reranking no llega ya fusionado por shard: hay que
producirlo primero, shard a shard, antes de poder fusionarlo.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from distributed_index_sharding.models import ShardHit
from learning_to_rank_reranker.model import LightGBMReranker
from learning_to_rank_reranker.models import Candidate, RankedDocument
from learning_to_rank_reranker.pipeline import rerank as ltr_rerank

_CLUSTER_MANIFEST_FILENAME = "cluster_manifest.json"


@dataclass(frozen=True, slots=True)
class ShardedRerankContext:
    """Directorio de índice local por `shard_id`, leído una única vez de
    `cluster_manifest.json` al arrancar la app — nunca se asume el patrón de
    nombre `shard-<id>`, se lee el nombre real que escribió `partition`."""

    shard_index_dirs: tuple[Path, ...]

    @classmethod
    def from_partitioned_root(cls, partitioned_root: Path) -> ShardedRerankContext:
        manifest_path = partitioned_root / _CLUSTER_MANIFEST_FILENAME
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"no existe {manifest_path}: ¿se ejecutó scripts/bootstrap_corpus.sh "
                "(o build_tiny_fixture.sh) antes de arrancar la API?"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        shard_dir_names = [str(name) for name in manifest["shard_dir_names"]]
        return cls(
            shard_index_dirs=tuple(partitioned_root / name for name in shard_dir_names)
        )

    @property
    def num_shards(self) -> int:
        return len(self.shard_index_dirs)

    def index_dir_for_doc(self, doc_id: int) -> Path:
        return self.shard_index_dirs[doc_id % self.num_shards]


def rerank_sharded_hits(
    hits: Sequence[ShardHit],
    query_terms: Sequence[str],
    context: ShardedRerankContext,
    pagerank_dir: Path,
    model: LightGBMReranker,
    *,
    top_k: int,
) -> list[RankedDocument]:
    """Reordena `hits` (ya fusionados entre shards por score BM25) según el
    modelo de `learning-to-rank-reranker`. Sin candidatos o sin ningún término
    de query (p. ej. una query resuelta solo por filtros), no hay nada que
    aprenda el modelo — se devuelve la lista vacía en vez de invocar el
    reranker con features degeneradas."""
    if not hits or not query_terms:
        return []

    candidates_by_shard: dict[Path, list[Candidate]] = {}
    for hit in hits:
        index_dir = context.index_dir_for_doc(hit.doc_id)
        candidates_by_shard.setdefault(index_dir, []).append(
            Candidate(doc_id=hit.doc_id, bm25_score=hit.score)
        )

    reranked: list[RankedDocument] = []
    for index_dir, candidates in candidates_by_shard.items():
        reranked.extend(
            ltr_rerank(model, candidates, query_terms, index_dir, pagerank_dir, top_k=None)
        )

    reranked.sort(key=lambda document: (-document.final_score, document.doc_id))
    return reranked[:top_k]
