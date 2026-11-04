"""Descarga, verificación y lectura de colecciones BEIR.

Las tres colecciones soportadas se descargan del mirror oficial de BEIR (UKP,
TU Darmstadt) y se verifican contra un SHA-256 fijado aquí: si el mirror
cambiara el contenido de un zip, las métricas dejarían de ser comparables con
las ya publicadas en el README, así que la evaluación falla en vez de medir en
silencio sobre otro corpus.
"""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

_BEIR_BASE_URL: Final[str] = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets"
_DOWNLOAD_TIMEOUT_SECONDS: Final[float] = 120.0


@dataclass(frozen=True, slots=True)
class BeirDatasetSpec:
    name: str
    sha256: str
    train_split: str | None
    """Split con qrels de entrenamiento, para entrenar el LTR sin tocar el
    split de test; `None` si la colección no publica ninguno."""


BEIR_DATASETS: Final[dict[str, BeirDatasetSpec]] = {
    "scifact": BeirDatasetSpec(
        name="scifact",
        sha256="536e14446a0ba56ed1398ab1055f39fe852686ecad24a6306c80c490fa8e0165",
        train_split="train",
    ),
    "nfcorpus": BeirDatasetSpec(
        name="nfcorpus",
        sha256="efe5be03f8c5b86a5870102d0599d227c8c6e2484328e68c6522560385671b0b",
        train_split="train",
    ),
    "fiqa": BeirDatasetSpec(
        name="fiqa",
        sha256="32c7df99ed21252fdfb2cf3f5673502a8d245ee0c44c4a133570d92ce2b3ad02",
        train_split="train",
    ),
}


class DatasetError(RuntimeError):
    """Descarga fallida, checksum distinto o fichero BEIR malformado."""


@dataclass(frozen=True, slots=True)
class BeirDocument:
    doc_id: str
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class BeirDataset:
    name: str
    root: Path

    @property
    def corpus_path(self) -> Path:
        return self.root / "corpus.jsonl"

    def iter_corpus(self) -> Iterator[BeirDocument]:
        with self.corpus_path.open("r", encoding="utf-8") as corpus_file:
            for line_number, raw_line in enumerate(corpus_file, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    yield BeirDocument(
                        doc_id=str(data["_id"]),
                        title=str(data.get("title", "")),
                        text=str(data.get("text", "")),
                    )
                except (json.JSONDecodeError, KeyError) as error:
                    raise DatasetError(
                        f"{self.corpus_path}:{line_number}: documento BEIR malformado: {error}"
                    ) from error

    def queries(self) -> dict[str, str]:
        path = self.root / "queries.jsonl"
        queries: dict[str, str] = {}
        with path.open("r", encoding="utf-8") as queries_file:
            for line_number, raw_line in enumerate(queries_file, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    queries[str(data["_id"])] = str(data["text"])
                except (json.JSONDecodeError, KeyError) as error:
                    raise DatasetError(
                        f"{path}:{line_number}: query BEIR malformada: {error}"
                    ) from error
        return queries

    def qrels(self, split: str) -> dict[str, dict[str, int]]:
        """`query_id -> doc_id -> grado de relevancia`, tal como lo publica
        BEIR en `qrels/<split>.tsv` (cabecera + `query-id corpus-id score`)."""
        path = self.root / "qrels" / f"{split}.tsv"
        if not path.exists():
            raise DatasetError(f"{self.name} no publica el split {split!r} ({path})")
        qrels: dict[str, dict[str, int]] = {}
        with path.open("r", encoding="utf-8") as qrels_file:
            next(qrels_file, None)
            for line_number, raw_line in enumerate(qrels_file, start=2):
                parts = raw_line.strip().split("\t")
                if len(parts) != 3:
                    if raw_line.strip():
                        raise DatasetError(f"{path}:{line_number}: línea de qrels malformada")
                    continue
                query_id, doc_id, grade = parts
                try:
                    qrels.setdefault(query_id, {})[doc_id] = int(grade)
                except ValueError as error:
                    raise DatasetError(f"{path}:{line_number}: grado no entero") from error
        return qrels


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_dataset(name: str, data_dir: Path) -> BeirDataset:
    """Descarga (si hace falta), verifica y descomprime `name` bajo
    `data_dir`. Idempotente: una segunda llamada reutiliza lo ya extraído."""
    spec = BEIR_DATASETS.get(name)
    if spec is None:
        raise DatasetError(f"dataset desconocido {name!r}; soportados: {sorted(BEIR_DATASETS)}")

    extracted_root = data_dir / name
    if (extracted_root / "corpus.jsonl").exists():
        return BeirDataset(name=name, root=extracted_root)

    data_dir.mkdir(parents=True, exist_ok=True)
    zip_path = data_dir / f"{name}.zip"
    if not zip_path.exists():
        url = f"{_BEIR_BASE_URL}/{name}.zip"
        logger.info("descargando %s", url)
        partial_path = zip_path.with_suffix(".zip.part")
        try:
            with (
                urllib.request.urlopen(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response,
                partial_path.open("wb") as output,
            ):
                while chunk := response.read(1 << 20):
                    output.write(chunk)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            partial_path.unlink(missing_ok=True)
            raise DatasetError(f"no se pudo descargar {url}: {error}") from error
        partial_path.rename(zip_path)

    actual = _sha256(zip_path)
    if actual != spec.sha256:
        raise DatasetError(
            f"checksum de {zip_path} no coincide (esperado {spec.sha256}, obtenido {actual}): "
            "bórralo y vuelve a descargarlo, o revisa si el mirror de BEIR cambió el contenido"
        )

    try:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(data_dir)
    except zipfile.BadZipFile as error:
        raise DatasetError(f"{zip_path} no es un zip válido: {error}") from error

    if not (extracted_root / "corpus.jsonl").exists():
        raise DatasetError(f"{zip_path} no contiene {name}/corpus.jsonl")
    return BeirDataset(name=name, root=extracted_root)
