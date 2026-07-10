"""Tests del puente sharding -> reranking: agrupación de candidatos por
shard, invocación de `learning-to-rank-reranker` por shard y fusión final."""

from __future__ import annotations

from pathlib import Path

from distributed_index_sharding.models import ShardHit
from learning_to_rank_reranker.model import LightGBMReranker

from beacon_search_console.reranking import ShardedRerankContext, rerank_sharded_hits

_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "samples" / "tiny_corpus"


def _load_model() -> LightGBMReranker:
    return LightGBMReranker.load(_FIXTURE_ROOT / "ltr-model")


def test_context_reads_shard_dirs_from_cluster_manifest() -> None:
    context = ShardedRerankContext.from_partitioned_root(_FIXTURE_ROOT / "shards")
    assert context.num_shards == 2
    # doc_id % num_shards, el mismo criterio que usa partitioning.py
    assert context.index_dir_for_doc(0) == context.shard_index_dirs[0]
    assert context.index_dir_for_doc(1) == context.shard_index_dirs[1]
    assert context.index_dir_for_doc(4) == context.shard_index_dirs[0]


def test_rerank_sharded_hits_spans_multiple_shards_and_merges() -> None:
    context = ShardedRerankContext.from_partitioned_root(_FIXTURE_ROOT / "shards")
    model = _load_model()
    # doc_id 1 y 3 caen en el shard 1; doc_id 0, 2 y 4 en el shard 0 — esta
    # llamada cubre ambos shards en un mismo rerank.
    hits = [
        ShardHit(doc_id=1, score=0.97),
        ShardHit(doc_id=2, score=0.61),
        ShardHit(doc_id=4, score=0.58),
        ShardHit(doc_id=0, score=0.22),
    ]
    reranked = rerank_sharded_hits(
        hits,
        ["python", "search"],
        context,
        _FIXTURE_ROOT / "pagerank",
        model,
        top_k=10,
    )
    assert {doc.doc_id for doc in reranked} == {0, 1, 2, 4}
    scores = [doc.final_score for doc in reranked]
    assert scores == sorted(scores, reverse=True)


def test_rerank_sharded_hits_respects_top_k() -> None:
    context = ShardedRerankContext.from_partitioned_root(_FIXTURE_ROOT / "shards")
    model = _load_model()
    hits = [ShardHit(doc_id=doc_id, score=1.0 / (doc_id + 1)) for doc_id in range(5)]
    reranked = rerank_sharded_hits(
        hits, ["python"], context, _FIXTURE_ROOT / "pagerank", model, top_k=2
    )
    assert len(reranked) == 2


def test_rerank_sharded_hits_empty_hits_returns_empty() -> None:
    context = ShardedRerankContext.from_partitioned_root(_FIXTURE_ROOT / "shards")
    model = _load_model()
    pagerank_dir = _FIXTURE_ROOT / "pagerank"
    assert rerank_sharded_hits([], ["python"], context, pagerank_dir, model, top_k=5) == []


def test_rerank_sharded_hits_no_query_terms_returns_empty() -> None:
    context = ShardedRerankContext.from_partitioned_root(_FIXTURE_ROOT / "shards")
    model = _load_model()
    hits = [ShardHit(doc_id=0, score=1.0)]
    assert rerank_sharded_hits(hits, [], context, _FIXTURE_ROOT / "pagerank", model, top_k=5) == []


def test_context_missing_cluster_manifest_raises(tmp_path: Path) -> None:
    try:
        ShardedRerankContext.from_partitioned_root(tmp_path)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("se esperaba FileNotFoundError sin cluster_manifest.json")
