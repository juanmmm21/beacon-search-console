"""Lector mínimo de `stats.json` de `inverted-index-builder`: solo los cuatro
campos que necesita el panel de estadísticas del índice, leídos una vez al
arrancar la app (el índice global no cambia mientras el proceso vive)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GlobalIndexStats:
    total_documents: int
    vocabulary_size: int
    total_postings: int
    average_document_length: float

    @classmethod
    def from_index_dir(cls, index_dir: Path) -> GlobalIndexStats:
        stats_path = index_dir / "stats.json"
        if not stats_path.exists():
            raise FileNotFoundError(
                f"no existe {stats_path}: ¿se ejecutó scripts/bootstrap_corpus.sh?"
            )
        data = json.loads(stats_path.read_text(encoding="utf-8"))
        return cls(
            total_documents=int(data["total_documents"]),
            vocabulary_size=int(data["vocabulary_size"]),
            total_postings=int(data["total_postings"]),
            average_document_length=float(data["average_document_length"]),
        )
