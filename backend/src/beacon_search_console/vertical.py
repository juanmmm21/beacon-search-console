"""Buscador vertical de documentación técnica: carga el *bundle* que exporta
`beacon-search-engine-at-scale` (`export-vertical`) y lo sirve.

## Contrato del bundle (formato v1, definido en at-scale `vertical/bundle.py`)

```text
<root>/current -> bundle-<versión>/
    manifest.json     format = "beacon-vertical-bundle", format_version = 1, index_version
    index/            índice segmentado de inverted-index-builder (segments.json v1)
    documents.jsonl   doc_id, url, title, main_text, source_id (solo documentos vivos)
    sources.json      sources[] (nombre, licencia, atribución) y disabled[]
```

El índice segmentado lo lee `bm25-ranking-engine` (>= 0.2.0) directamente,
con sus tombstones; esta consola no reimplementa nada de ranking.

## Recarga en caliente

`VerticalSearchService.maybe_reload` mira la versión de `current` y, si
cambió, construye el motor nuevo en un hilo (abrir el índice y, con la
búsqueda híbrida, codificar el corpus y construir el HNSW) y solo entonces
lo cambia por el viejo: las búsquedas en curso terminan sobre el motor con
el que empezaron y nunca ven un índice a medio cargar. La versión forma
parte de la clave de caché, así que un índice nuevo invalida la caché sin
borrarla (`cache.py`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from bm25_ranking_engine.pipeline import BM25RankingPipeline
from query_parser_autocomplete.query_parser import parse_query

from beacon_search_console.cache import ResultCache
from beacon_search_console.models import Snippet
from beacon_search_console.snippets import build_snippet

if TYPE_CHECKING:
    from beacon_search_console.hybrid import (
        CrossEncoderStage,
        DenseIndex,
        HybridSearcher,
        SentenceEncoder,
    )

logger = logging.getLogger(__name__)

BUNDLE_FORMAT: Final[str] = "beacon-vertical-bundle"
BUNDLE_FORMAT_VERSION: Final[int] = 1
_CANDIDATE_DEPTH: Final[int] = 100


class BundleError(RuntimeError):
    """Bundle ausente, de otro formato o incoherente."""


class SearchMode(StrEnum):
    LEXICAL = "lexical"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class SourceInfo:
    source_id: str
    name: str
    license: str
    license_url: str
    attribution: str
    home_url: str


@dataclass(frozen=True, slots=True)
class VerticalDocument:
    doc_id: int
    url: str
    title: str
    main_text: str
    source_id: str | None


@dataclass(frozen=True, slots=True)
class DocsHit:
    doc_id: int
    url: str
    title: str
    snippet: Snippet
    score: float
    source: SourceInfo | None


@dataclass(frozen=True, slots=True)
class DocsSearchResult:
    query: str
    mode: SearchMode
    hits: tuple[DocsHit, ...]
    index_version: str
    cached: bool
    took_ms: float


@dataclass(frozen=True, slots=True)
class VerticalBundle:
    path: Path
    index_version: str
    created_at: str
    documents: Mapping[int, VerticalDocument]
    sources: Mapping[str, SourceInfo]
    disabled_sources: tuple[tuple[str, str], ...]

    @classmethod
    def load(cls, root: Path) -> VerticalBundle:
        """`root` puede ser la raíz con `current` o un bundle concreto."""
        path = (root / "current").resolve() if (root / "current").exists() else root
        try:
            manifest = json.loads((path / "manifest.json").read_text("utf-8"))
            sources_json = json.loads((path / "sources.json").read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BundleError(f"bundle ilegible en {path}: {error}") from error
        if manifest.get("format") != BUNDLE_FORMAT:
            raise BundleError(f"{path} no es un bundle del vertical")
        if int(manifest.get("format_version", -1)) != BUNDLE_FORMAT_VERSION:
            raise BundleError(f"formato de bundle no soportado: {manifest.get('format_version')}")
        sources = {
            str(entry["source_id"]): SourceInfo(
                source_id=str(entry["source_id"]),
                name=str(entry["name"]),
                license=str(entry["license"]),
                license_url=str(entry["license_url"]),
                attribution=str(entry["attribution"]),
                home_url=str(entry["home_url"]),
            )
            for entry in sources_json.get("sources", [])
        }
        documents: dict[int, VerticalDocument] = {}
        with (path / "documents.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                document = VerticalDocument(
                    doc_id=int(record["doc_id"]),
                    url=str(record["url"]),
                    title=str(record.get("title") or record["url"]),
                    main_text=str(record.get("main_text", "")),
                    source_id=None if record.get("source_id") is None else str(record["source_id"]),
                )
                documents[document.doc_id] = document
        return cls(
            path=path,
            index_version=str(manifest["index_version"]),
            created_at=str(manifest.get("created_at", "")),
            documents=documents,
            sources=sources,
            disabled_sources=tuple(
                (str(entry["source_id"]), str(entry["reason"]))
                for entry in sources_json.get("disabled", [])
            ),
        )


def bundle_version(root: Path) -> str | None:
    """Versión del bundle al que apunta `root` ahora mismo, sin cargarlo."""
    path = root / "current" if (root / "current").exists() else root
    try:
        return str(json.loads((path / "manifest.json").read_text("utf-8"))["index_version"])
    except (OSError, json.JSONDecodeError, KeyError):
        return None


_HIGHLIGHT_STOPWORDS: Final[frozenset[str]] = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
        "when",
        "with",
    ]
)
"""Solo para el resaltado: BM25 ya da poco peso a estas palabras, pero
marcarlas en el snippet llena el texto de resaltados que no dicen nada."""


def query_terms(raw_query: str) -> list[str]:
    parsed = parse_query(raw_query)
    return list(parsed.required_terms) + [term for phrase in parsed.phrases for term in phrase]


@dataclass(frozen=True, slots=True)
class HybridModels:
    """Modelos compartidos entre bundles: cargarlos cuesta segundos y no
    dependen del índice, así que una recarga solo reconstruye el HNSW."""

    encoder: SentenceEncoder
    cross_encoder: CrossEncoderStage | None
    rerank_depth: int = 20


class VerticalSearchEngine:
    """Motor inmutable sobre un bundle concreto."""

    def __init__(self, bundle: VerticalBundle, models: HybridModels | None) -> None:
        self.bundle = bundle
        self._bm25 = BM25RankingPipeline(bundle.path / "index")
        self._hybrid: HybridSearcher | None = None
        self._dense_index: DenseIndex | None = None
        if models is not None:
            from beacon_search_console.hybrid import HybridSearcher, build_dense_index

            doc_ids = sorted(bundle.documents)
            texts = [
                f"{bundle.documents[d].title}\n{bundle.documents[d].main_text}" for d in doc_ids
            ]
            self._dense_index = build_dense_index(doc_ids, texts, models.encoder)
            self._hybrid = HybridSearcher(
                self._lexical_ids,
                models.encoder,
                self._dense_index,
                {d: texts[i] for i, d in enumerate(doc_ids)},
                models.cross_encoder,
                candidate_depth=_CANDIDATE_DEPTH,
                rerank_depth=models.rerank_depth,
            )

    @property
    def supports_hybrid(self) -> bool:
        return self._hybrid is not None

    def close(self) -> None:
        self._bm25.close()

    def _lexical_ids(self, raw_query: str, depth: int) -> list[int]:
        return [doc_id for doc_id, _ in self._lexical(raw_query, depth)]

    def _lexical(self, raw_query: str, depth: int) -> list[tuple[int, float]]:
        terms = query_terms(raw_query)
        if not terms:
            return []
        return [(hit.doc_id, hit.score) for hit in self._bm25.search_tokens(terms, top_k=depth)]

    def search(
        self, raw_query: str, limit: int, *, source: str | None, mode: SearchMode
    ) -> list[DocsHit]:
        if mode is SearchMode.HYBRID and self._hybrid is None:
            raise BundleError("la búsqueda híbrida no está activada en este servidor")
        depth = _CANDIDATE_DEPTH if source is not None else limit
        if mode is SearchMode.HYBRID and self._hybrid is not None:
            ranked = [(hit.doc_id, hit.score) for hit in self._hybrid.search(raw_query, depth)]
        else:
            ranked = self._lexical(raw_query, depth)
        highlight = [t for t in query_terms(raw_query) if t.casefold() not in _HIGHLIGHT_STOPWORDS]
        hits: list[DocsHit] = []
        for doc_id, score in ranked:
            document = self.bundle.documents.get(doc_id)
            if document is None:
                continue
            if source is not None and document.source_id != source:
                continue
            hits.append(
                DocsHit(
                    doc_id=doc_id,
                    url=document.url,
                    title=document.title,
                    snippet=build_snippet(document.main_text, highlight),
                    score=score,
                    source=self.bundle.sources.get(document.source_id or ""),
                )
            )
            if len(hits) == limit:
                break
        return hits


class VerticalSearchService:
    """Lo que usan la API pública, la UI y el servidor MCP."""

    def __init__(
        self,
        root: Path,
        *,
        models: HybridModels | None = None,
        cache: ResultCache[tuple[DocsHit, ...]] | None = None,
    ) -> None:
        self._root = root
        self._models = models
        self._cache = cache if cache is not None else ResultCache()
        self._engine = VerticalSearchEngine(VerticalBundle.load(root), models)
        self._reload_lock = asyncio.Lock()
        self.reloads = 0

    @property
    def engine(self) -> VerticalSearchEngine:
        return self._engine

    @property
    def cache(self) -> ResultCache[tuple[DocsHit, ...]]:
        return self._cache

    def close(self) -> None:
        self._engine.close()

    async def maybe_reload(self) -> bool:
        version = bundle_version(self._root)
        if version is None or version == self._engine.bundle.index_version:
            return False
        async with self._reload_lock:
            if version == self._engine.bundle.index_version:
                return False
            started = time.perf_counter()
            bundle = await asyncio.to_thread(VerticalBundle.load, self._root)
            engine = await asyncio.to_thread(VerticalSearchEngine, bundle, self._models)
            previous, self._engine = self._engine, engine
            previous.close()
            self.reloads += 1
            logger.info(
                "bundle %s cargado en %.1f s (%d documentos)",
                bundle.index_version[:12],
                time.perf_counter() - started,
                len(bundle.documents),
            )
            return True

    async def search(
        self,
        raw_query: str,
        limit: int,
        *,
        source: str | None = None,
        mode: SearchMode = SearchMode.LEXICAL,
    ) -> DocsSearchResult:
        started = time.perf_counter()
        engine = self._engine
        query = " ".join(raw_query.split())
        key = (query.casefold(), limit, source, mode.value)
        cached = self._cache.get(engine.bundle.index_version, key)
        if cached is None:
            # El híbrido codifica la query y pasa el cross-encoder: segundos de
            # CPU que no deben bloquear el event loop del resto de peticiones.
            if mode is SearchMode.HYBRID:
                hits = await asyncio.to_thread(
                    engine.search, query, limit, source=source, mode=mode
                )
            else:
                hits = engine.search(query, limit, source=source, mode=mode)
            result_hits = tuple(hits)
            self._cache.put(engine.bundle.index_version, key, result_hits)
        else:
            result_hits = cached
        return DocsSearchResult(
            query=query,
            mode=mode,
            hits=result_hits,
            index_version=engine.bundle.index_version,
            cached=cached is not None,
            took_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    def document(self, doc_id: int) -> tuple[VerticalDocument, SourceInfo | None] | None:
        bundle = self._engine.bundle
        document = bundle.documents.get(doc_id)
        if document is None:
            return None
        return document, bundle.sources.get(document.source_id or "")

    def describe(self) -> dict[str, Any]:
        bundle = self._engine.bundle
        per_source: dict[str, int] = {}
        for document in bundle.documents.values():
            key = document.source_id or "unknown"
            per_source[key] = per_source.get(key, 0) + 1
        return {
            "index_version": bundle.index_version,
            "created_at": bundle.created_at,
            "documents": len(bundle.documents),
            "documents_per_source": dict(sorted(per_source.items())),
            "hybrid": self._engine.supports_hybrid,
            "cache": {
                "entries": len(self._cache),
                "hits": self._cache.stats.hits,
                "misses": self._cache.stats.misses,
                "hit_ratio": round(self._cache.stats.hit_ratio, 4),
            },
        }
