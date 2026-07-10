"""Modelos de dominio propios de la API — nunca los tipos internos de los
paquetes que se orquestan (`ShardHit`, `RankedDocument`, `ParsedQuery`...): la
API expone su propio contrato versionado (`/api/v1/...`), independiente de
cómo cambien las representaciones internas de cada subproyecto."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HighlightRange:
    """Rango `[start, end)` de caracteres dentro de `Snippet.text` que coincide
    con un término de la query. El resaltado real (envolver en `<mark>` o
    equivalente) es responsabilidad del frontend — el backend solo declara
    dónde está la coincidencia, nunca HTML crudo, para no acoplar la API a un
    formato de presentación concreto."""

    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Snippet:
    """Fragmento de `main_text` alrededor de la primera coincidencia de algún
    término de la query, con los rangos de coincidencia ya resueltos (ver
    `snippets.py`)."""

    text: str
    highlights: tuple[HighlightRange, ...]


@dataclass(frozen=True, slots=True)
class SearchResultItem:
    doc_id: int
    url: str
    title: str
    snippet: Snippet
    score: float


@dataclass(frozen=True, slots=True)
class ShardStatusInfo:
    """Estado de un shard concreto tras una búsqueda, expuesto en la API para
    que el frontend pueda mostrar degradación explícita en vez de fallar en
    silencio (`../../CLAUDE.md`, sección 2.E / `AGENTS.md`)."""

    shard_id: int
    status: str
    error_message: str | None


@dataclass(frozen=True, slots=True)
class QueryCorrectionInfo:
    original: str
    corrected: str


@dataclass(frozen=True, slots=True)
class SearchResponse:
    query: str
    results: tuple[SearchResultItem, ...]
    corrections: tuple[QueryCorrectionInfo, ...]
    shard_statuses: tuple[ShardStatusInfo, ...]
    degraded: bool
    """`True` si al menos un shard no respondió a tiempo (`degraded`, no
    lanzar 500): los resultados de `results` provienen solo de los shards
    sanos, nunca de un estado a medias."""
    message: str | None
    """Mensaje explicativo en español para la UI: sin resultados, degradación
    parcial, o `None` si la búsqueda fue normal y con resultados."""


@dataclass(frozen=True, slots=True)
class AutocompleteSuggestion:
    text: str
    score: int


@dataclass(frozen=True, slots=True)
class AutocompleteResponse:
    prefix: str
    suggestions: tuple[AutocompleteSuggestion, ...]


@dataclass(frozen=True, slots=True)
class IndexStatsResponse:
    total_documents: int
    vocabulary_size: int
    total_postings: int
    average_document_length: float
    num_shards: int
    last_crawled_at: str | None
    """ISO 8601 de la página más reciente en `documents.jsonl` de
    `html-content-extractor` (`fetched_at`) — `None` solo si el corpus está
    vacío, nunca por un fallo de parseo silencioso."""
