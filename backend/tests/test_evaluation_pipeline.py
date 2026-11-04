"""Evaluación de extremo a extremo sobre una colección BEIR diminuta escrita
en el propio test: sin red, determinista y con el resultado esperado
calculable a mano."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from beacon_search_console.evaluation.corpus import prepare_corpus
from beacon_search_console.evaluation.datasets import BeirDataset, DatasetError, ensure_dataset
from beacon_search_console.evaluation.runner import (
    EvaluationConfig,
    check_against_baseline,
    run_evaluation,
)
from beacon_search_console.evaluation.systems import Bm25System, query_terms

_CORPUS = [
    {"_id": "d1", "title": "Vitamin D", "text": "vitamin d deficiency causes bone loss"},
    {"_id": "d2", "title": "Coffee", "text": "coffee consumption and sleep quality"},
    {"_id": "d3", "title": "Bones", "text": "calcium intake and bone density in adults"},
    {"_id": "d4", "title": "Sleep", "text": "sleep deprivation affects memory"},
]
_QUERIES = [
    {"_id": "q1", "text": "vitamin d bone"},
    {"_id": "q2", "text": "coffee sleep"},
    {"_id": "q3", "text": "memory"},
]


def _write_dataset(root: Path, name: str = "tiny") -> BeirDataset:
    dataset_root = root / name
    (dataset_root / "qrels").mkdir(parents=True)
    (dataset_root / "corpus.jsonl").write_text(
        "".join(json.dumps(doc) + "\n" for doc in _CORPUS), encoding="utf-8"
    )
    (dataset_root / "queries.jsonl").write_text(
        "".join(json.dumps(query) + "\n" for query in _QUERIES), encoding="utf-8"
    )
    (dataset_root / "qrels" / "test.tsv").write_text(
        "query-id\tcorpus-id\tscore\nq1\td1\t1\nq2\td2\t1\nq3\td4\t1\n", encoding="utf-8"
    )
    return BeirDataset(name=name, root=dataset_root)


def test_query_terms_flatten_phrases_like_the_console() -> None:
    assert query_terms('Vitamin "bone loss"') == ["vitamin", "bone", "loss"]


def test_prepare_corpus_keeps_beir_id_mapping(tmp_path: Path) -> None:
    corpus = prepare_corpus(_write_dataset(tmp_path), tmp_path / "work")
    assert corpus.doc_ids == ("d1", "d2", "d3", "d4")
    assert corpus.texts()[0].startswith("Vitamin D\n")
    # Idempotente: la segunda llamada reutiliza el índice ya escrito.
    assert prepare_corpus(_write_dataset(tmp_path / "again"), tmp_path / "work") == corpus


def test_bm25_ranks_the_obvious_document_first(tmp_path: Path) -> None:
    corpus = prepare_corpus(_write_dataset(tmp_path), tmp_path / "work")
    bm25 = Bm25System(corpus.index_dir)
    try:
        assert bm25.retrieve("vitamin d bone", 10)[0] == 0
        assert bm25.retrieve("coffee sleep", 10)[0] == 1
        assert bm25.retrieve("", 10) == []
    finally:
        bm25.close()


def test_qrels_reader_rejects_malformed_lines(tmp_path: Path) -> None:
    dataset = _write_dataset(tmp_path)
    (dataset.root / "qrels" / "test.tsv").write_text("h\th\th\nq1\td1\n", encoding="utf-8")
    with pytest.raises(DatasetError):
        dataset.qrels("test")
    with pytest.raises(DatasetError):
        dataset.qrels("train")


def test_ensure_dataset_rejects_unknown_name(tmp_path: Path) -> None:
    with pytest.raises(DatasetError):
        ensure_dataset("not-a-beir-dataset", tmp_path)


def test_ensure_dataset_rejects_checksum_mismatch(tmp_path: Path) -> None:
    (tmp_path / "scifact.zip").write_bytes(b"not the real archive")
    with pytest.raises(DatasetError, match="checksum"):
        ensure_dataset("scifact", tmp_path)


def test_run_evaluation_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset = _write_dataset(tmp_path / "data", "scifact")
    monkeypatch.setattr(
        "beacon_search_console.evaluation.runner.ensure_dataset",
        lambda name, data_dir: dataset,
    )
    config = EvaluationConfig(
        dataset="scifact",
        data_dir=tmp_path / "data",
        work_dir=tmp_path / "work",
        systems=("bm25",),
    )
    report = run_evaluation(config)
    (result,) = report["results"]
    assert result["system"] == "bm25"
    assert math.isclose(result["metrics"]["ndcg_at_10"], 1.0)
    assert result["metrics"]["evaluated_queries"] == 3
    assert "cpu" in report["environment"]

    assert check_against_baseline(report, {"metrics": {"bm25": {"ndcg_at_10": 1.0}}}, 0.0) == []
    failures = check_against_baseline(
        report, {"metrics": {"bm25": {"ndcg_at_10": 1.01}, "hybrid": {"ndcg_at_10": 0.1}}}, 0.005
    )
    assert len(failures) == 2


def test_unknown_system_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        EvaluationConfig(dataset="scifact", data_dir=tmp_path, work_dir=tmp_path, systems=("x",))
