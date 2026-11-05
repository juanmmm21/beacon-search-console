"""Búsqueda híbrida: BM25 de Beacon + recuperación densa con componentes de
AI Core, fusionadas con Reciprocal Rank Fusion y reordenadas con un
cross-encoder.

Es la única pieza de la consola que usa AI Core, y lo hace como dependencias
de paquete (`nano-vector-db`, `contrastive-embedding-trainer`,
`cross-encoder-reranker`), nunca copiando su código:

- **Embeddings** — `contrastive_embedding_trainer.SiameseTransformer`: mean
  pooling + normalización L2 sobre un transformer de Hugging Face. Con
  `sentence-transformers/all-MiniLM-L6-v2` es exactamente la receta de
  inferencia de ese modelo; con un checkpoint afinado por el `EmbeddingTrainer`
  del mismo repo, la misma clase carga el modelo afinado.
- **Índice vectorial** — `nano_vector_db.NanoVectorDB` en modo HNSW, métrica
  coseno. Los vectores se guardan en `.npy` y el grafo se reconstruye al
  cargar: el formato de persistencia de nano-vector-db es un pickle, y entre
  repos solo viajan formatos documentados (`CLAUDE.md` del ecosistema).
- **Fusión** — RRF (Cormack et al., 2009): `score(d) = Σ 1 / (k + rank_i(d))`.
  Usa solo posiciones, no scores, así que no hay que normalizar BM25 (sin
  acotar) contra similitudes coseno (en [-1, 1]).
- **Rerank** — `cross_encoder_reranker.CrossEncoderReranker` sobre los
  primeros `rerank_depth` de la fusión. Ese componente cae a un heurístico
  léxico si no puede cargar el modelo; aquí eso es un error explícito, porque
  una métrica medida con el heurístico no sería la del cross-encoder.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import torch
from contrastive_embedding_trainer import SiameseTransformer
from cross_encoder_reranker import CrossEncoderReranker
from nano_vector_db import NanoVectorDB
from numpy.typing import NDArray
from transformers import AutoTokenizer

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL: Final[str] = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_CROSS_ENCODER_MODEL: Final[str] = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RRF_K: Final[int] = 60
"""Constante del artículo original de RRF; amortigua el peso del primer
puesto de cada lista para que ningún sistema domine solo por estar seguro."""

_VECTORS_FILENAME: Final[str] = "vectors.npy"
_IDS_FILENAME: Final[str] = "doc_ids.npy"
_MANIFEST_FILENAME: Final[str] = "manifest.json"
_DENSE_FORMAT_VERSION: Final[int] = 1


class HybridSearchError(RuntimeError):
    """Modelo que no carga, índice denso ilegible o de otra versión."""


def _pick_device(device: str | None) -> str:
    if device is not None:
        return device
    return "cuda" if torch.cuda.is_available() else "cpu"


class SentenceEncoder:
    """Codifica textos a vectores L2-normalizados (`float32`)."""

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        *,
        device: str | None = None,
        max_length: int = 256,
    ) -> None:
        self.model_name = model_name
        self._device = torch.device(_pick_device(device))
        self._max_length = max_length
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(model_name)
            self._model = SiameseTransformer(model_name)
        except OSError as error:
            raise HybridSearchError(f"no se pudo cargar {model_name}: {error}") from error
        self._model.to(self._device)
        self._model.eval()

    @property
    def dimension(self) -> int:
        return int(self._model.transformer.config.hidden_size)

    def encode(self, texts: Sequence[str], *, batch_size: int = 64) -> NDArray[np.float32]:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        chunks: list[NDArray[np.float32]] = []
        with torch.no_grad():
            for start in range(0, len(texts), batch_size):
                batch = self._tokenizer(
                    list(texts[start : start + batch_size]),
                    padding=True,
                    truncation=True,
                    max_length=self._max_length,
                    return_tensors="pt",
                ).to(self._device)
                embeddings = self._model(batch["input_ids"], batch["attention_mask"])
                chunks.append(embeddings.cpu().numpy().astype(np.float32))
        return np.vstack(chunks)


@dataclass(frozen=True, slots=True)
class HnswParams:
    m: int = 16
    ef_construction: int = 64
    ef_search: int = 128


class DenseIndex:
    """Vectores por `doc_id` de Beacon dentro de un `NanoVectorDB` HNSW."""

    def __init__(
        self,
        doc_ids: NDArray[np.int64],
        vectors: NDArray[np.float32],
        *,
        model_name: str,
        params: HnswParams | None = None,
    ) -> None:
        if doc_ids.shape[0] != vectors.shape[0]:
            raise HybridSearchError("doc_ids y vectores con distinto número de filas")
        self.model_name = model_name
        self.params = params if params is not None else HnswParams()
        self._doc_ids = doc_ids
        self._vectors = vectors
        self._db = NanoVectorDB(
            dimension=int(vectors.shape[1]),
            metric="cosine",
            index_type="hnsw",
            M=self.params.m,
            efConstruction=self.params.ef_construction,
            efSearch=self.params.ef_search,
        )
        # Inserción en orden de doc_id: HNSW sortea el nivel de cada nodo, y
        # nano-vector-db usa el generador global de NumPy; fijar la semilla y el
        # orden hace el grafo reproducible entre construcciones.
        np.random.seed(0)
        for doc_id, vector in zip(doc_ids.tolist(), vectors, strict=True):
            self._db.insert(int(doc_id), vector)

    def __len__(self) -> int:
        return int(self._doc_ids.shape[0])

    def search(self, query_vector: NDArray[np.float32], top_k: int) -> list[tuple[int, float]]:
        """`(doc_id, similitud coseno)` de los `top_k` vecinos aproximados."""
        if len(self) == 0:
            return []
        hits = self._db.query(query_vector, top_k=top_k)
        return [(int(hit["id"]), 1.0 - float(hit["distance"])) for hit in hits]

    def save(self, directory: Path) -> None:
        """Formato denso v1: `vectors.npy` (float32, una fila por documento),
        `doc_ids.npy` (int64, misma fila) y `manifest.json`."""
        directory.mkdir(parents=True, exist_ok=True)
        np.save(directory / _VECTORS_FILENAME, self._vectors)
        np.save(directory / _IDS_FILENAME, self._doc_ids)
        manifest = {
            "format_version": _DENSE_FORMAT_VERSION,
            "model_name": self.model_name,
            "dimension": int(self._vectors.shape[1]),
            "documents": len(self),
            "hnsw": {
                "m": self.params.m,
                "ef_construction": self.params.ef_construction,
                "ef_search": self.params.ef_search,
            },
        }
        (directory / _MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2), "utf-8")

    @classmethod
    def load(cls, directory: Path) -> DenseIndex:
        try:
            manifest = json.loads((directory / _MANIFEST_FILENAME).read_text("utf-8"))
            vectors = np.load(directory / _VECTORS_FILENAME, allow_pickle=False)
            doc_ids = np.load(directory / _IDS_FILENAME, allow_pickle=False)
        except (OSError, ValueError) as error:
            raise HybridSearchError(f"índice denso ilegible en {directory}: {error}") from error
        if int(manifest.get("format_version", -1)) != _DENSE_FORMAT_VERSION:
            raise HybridSearchError(
                f"formato denso no soportado: version {manifest.get('format_version')}"
            )
        hnsw = manifest["hnsw"]
        return cls(
            doc_ids.astype(np.int64),
            vectors.astype(np.float32),
            model_name=str(manifest["model_name"]),
            params=HnswParams(
                m=int(hnsw["m"]),
                ef_construction=int(hnsw["ef_construction"]),
                ef_search=int(hnsw["ef_search"]),
            ),
        )


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[int]], *, k: int = RRF_K, depth: int | None = None
) -> list[tuple[int, float]]:
    """Fusiona listas ordenadas de `doc_id`. Desempate por `doc_id`
    ascendente para que el resultado sea determinista."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for position, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + position)
    fused = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return fused if depth is None else fused[:depth]


class CrossEncoderStage:
    def __init__(
        self, model_name: str = DEFAULT_CROSS_ENCODER_MODEL, *, device: str | None = None
    ) -> None:
        self.model_name = model_name
        self._reranker = CrossEncoderReranker(model_name=model_name, device=_pick_device(device))
        if not self._reranker.is_online:
            raise HybridSearchError(
                f"el cross-encoder {model_name} no cargó y cross-encoder-reranker cayó a su "
                "heurístico léxico; no se sirve ni se mide como si fuera el modelo"
            )

    def rerank(
        self, query: str, doc_ids: Sequence[int], texts: Mapping[int, str]
    ) -> list[tuple[int, float]]:
        if not doc_ids:
            return []
        scores = self._reranker.compute_scores(query, [texts.get(d, "") for d in doc_ids])
        return sorted(
            zip(doc_ids, (float(s) for s in scores), strict=True),
            key=lambda item: (-item[1], item[0]),
        )


@dataclass(frozen=True, slots=True)
class HybridHit:
    doc_id: int
    score: float
    """Score del cross-encoder si se reordenó, o el de RRF si quedó fuera."""
    bm25_rank: int | None
    dense_rank: int | None


class HybridSearcher:
    """Orquesta las tres etapas sobre un recuperador léxico cualquiera
    (`lexical(query, depth) -> doc_ids ordenados`)."""

    def __init__(
        self,
        lexical: Callable[[str, int], list[int]],
        encoder: SentenceEncoder,
        dense_index: DenseIndex,
        texts: Mapping[int, str],
        cross_encoder: CrossEncoderStage | None,
        *,
        candidate_depth: int = 100,
        rerank_depth: int = 50,
    ) -> None:
        if encoder.model_name != dense_index.model_name:
            raise HybridSearchError(
                f"el índice denso se construyó con {dense_index.model_name} y el codificador "
                f"es {encoder.model_name}: los vectores no son comparables"
            )
        self._lexical = lexical
        self._encoder = encoder
        self._dense = dense_index
        self._texts = texts
        self._cross_encoder = cross_encoder
        self._candidate_depth = candidate_depth
        self._rerank_depth = rerank_depth

    def dense(self, query: str, depth: int) -> list[int]:
        vector = self._encoder.encode([query])[0]
        return [doc_id for doc_id, _ in self._dense.search(vector, depth)]

    def search(self, query: str, top_k: int, *, rerank: bool = True) -> list[HybridHit]:
        lexical = self._lexical(query, self._candidate_depth)
        dense = self.dense(query, self._candidate_depth)
        fused = reciprocal_rank_fusion([lexical, dense])
        lexical_rank = {doc_id: rank for rank, doc_id in enumerate(lexical, start=1)}
        dense_rank = {doc_id: rank for rank, doc_id in enumerate(dense, start=1)}

        ordered: list[tuple[int, float]] = fused
        if rerank and self._cross_encoder is not None and fused:
            head = [doc_id for doc_id, _ in fused[: self._rerank_depth]]
            reranked = self._cross_encoder.rerank(query, head, self._texts)
            ordered = reranked + fused[self._rerank_depth :]
        return [
            HybridHit(doc_id, score, lexical_rank.get(doc_id), dense_rank.get(doc_id))
            for doc_id, score in ordered[:top_k]
        ]


def build_dense_index(
    doc_ids: Sequence[int],
    texts: Sequence[str],
    encoder: SentenceEncoder,
    *,
    params: HnswParams | None = None,
    batch_size: int = 64,
) -> DenseIndex:
    vectors = encoder.encode(texts, batch_size=batch_size)
    return DenseIndex(
        np.asarray(doc_ids, dtype=np.int64), vectors, model_name=encoder.model_name, params=params
    )
