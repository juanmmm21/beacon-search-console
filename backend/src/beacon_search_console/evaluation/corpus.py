"""Convierte una colección BEIR a los contratos en disco del ecosistema y
construye su índice con los mismos componentes que sirven la consola.

El corpus BEIR se reescribe como un `documents.jsonl` de
`html-content-extractor` (`url`, `title`, `main_text`) y se indexa con
`inverted-index-builder`: así la evaluación mide exactamente la tokenización
y el índice que produce el bootstrap real, no una reimplementación paralela.
El `doc_id` entero de Beacon es la posición del documento en `corpus.jsonl`
(contrato de `inverted-index-builder`); `doc_ids` guarda la correspondencia
con el identificador original de BEIR, que es el que entienden los qrels.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from inverted_index_builder.pipeline import IndexBuilder
from inverted_index_builder.serialization import write_index

from beacon_search_console.evaluation.datasets import BeirDataset

logger = logging.getLogger(__name__)

_DOC_IDS_FILENAME: Final[str] = "beir_doc_ids.json"


@dataclass(frozen=True, slots=True)
class PreparedCorpus:
    documents_path: Path
    """`documents.jsonl` en el formato de `html-content-extractor`."""
    index_dir: Path
    """Índice sin comprimir de `inverted-index-builder`."""
    doc_ids: tuple[str, ...]
    """`doc_ids[beacon_doc_id]` es el `_id` de BEIR de ese documento."""

    def texts(self) -> list[str]:
        """`main_text` por `doc_id` de Beacon, para los modelos densos."""
        texts: list[str] = []
        with self.documents_path.open("r", encoding="utf-8") as documents_file:
            for line in documents_file:
                if line.strip():
                    texts.append(str(json.loads(line)["main_text"]))
        return texts


def prepare_corpus(dataset: BeirDataset, work_dir: Path) -> PreparedCorpus:
    """Idempotente: si el índice ya está construido en `work_dir`, se reutiliza."""
    documents_path = work_dir / "extracted" / "documents.jsonl"
    index_dir = work_dir / "index"
    doc_ids_path = work_dir / _DOC_IDS_FILENAME

    if not (index_dir / "manifest.json").exists() or not doc_ids_path.exists():
        documents_path.parent.mkdir(parents=True, exist_ok=True)
        doc_ids: list[str] = []
        with documents_path.open("w", encoding="utf-8") as output:
            for document in dataset.iter_corpus():
                # El título se antepone al cuerpo porque inverted-index-builder
                # solo indexa `main_text`: sin esto, los términos del título de
                # un artículo de SciFact no serían recuperables.
                main_text = (
                    f"{document.title}\n{document.text}" if document.title else document.text
                )
                record = {
                    "url": f"beir://{dataset.name}/{document.doc_id}",
                    "title": document.title or document.doc_id,
                    "main_text": main_text,
                }
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                doc_ids.append(document.doc_id)
        logger.info("indexando %d documentos de %s", len(doc_ids), dataset.name)
        index = IndexBuilder().build(documents_path)
        write_index(index, index_dir)
        doc_ids_path.write_text(json.dumps(doc_ids), encoding="utf-8")

    doc_ids_loaded = tuple(str(doc_id) for doc_id in json.loads(doc_ids_path.read_text("utf-8")))
    return PreparedCorpus(
        documents_path=documents_path, index_dir=index_dir, doc_ids=doc_ids_loaded
    )
