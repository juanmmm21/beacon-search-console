"""`GET /api/v1/search` — orquesta el pipeline completo: parseo y corrección
ortográfica de la query (`query-parser-autocomplete`) -> fan-out a shards
(`distributed-index-sharding`) -> reranking (`learning-to-rank-reranker`) ->
snippet real (`snippets.py`). Ningún fallo de shard llega como 500: se
degrada explícitamente (`AGENTS.md`, sección "Calidad de código")."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from query_parser_autocomplete.pipeline import parse_and_correct_query

from beacon_search_console.dependencies import AppState, get_app_state
from beacon_search_console.models import (
    QueryCorrectionInfo,
    SearchResponse,
    SearchResultItem,
    ShardStatusInfo,
)
from beacon_search_console.reranking import rerank_sharded_hits
from beacon_search_console.snippets import build_snippet

router = APIRouter(tags=["search"])

_EMPTY_QUERY_MESSAGE = "Escribe al menos un término para buscar."
_NO_RESULTS_MESSAGE = "No se encontraron resultados para esta búsqueda."
_NO_SEARCHABLE_TERMS_MESSAGE = (
    "La búsqueda no contiene ningún término por el que se pueda buscar "
    "(solo exclusiones o filtros)."
)


def _degraded_message(failed_shards: int, total_shards: int, has_results: bool) -> str:
    if has_results:
        return (
            f"Resultados parciales: {failed_shards} de {total_shards} nodos del índice "
            "no respondieron a tiempo."
        )
    return (
        f"El índice está degradado ({failed_shards} de {total_shards} nodos no responden) "
        "y no se pudo completar la búsqueda."
    )


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query("", description="Texto de la búsqueda, en español o cualquier idioma indexado"),
    limit: int = Query(10, ge=1, le=50),
    state: AppState = Depends(get_app_state),
) -> SearchResponse:
    raw_query = q.strip()
    if not raw_query:
        return SearchResponse(
            query=raw_query,
            results=(),
            corrections=(),
            shard_statuses=(),
            degraded=False,
            message=_EMPTY_QUERY_MESSAGE,
        )

    parsed = parse_and_correct_query(raw_query, state.spell_checker)
    corrections = tuple(
        QueryCorrectionInfo(original=c.original, corrected=c.corrected)
        for c in parsed.corrections
    )

    if parsed.is_empty():
        return SearchResponse(
            query=raw_query,
            results=(),
            corrections=corrections,
            shard_statuses=(),
            degraded=False,
            message=_NO_SEARCHABLE_TERMS_MESSAGE,
        )

    fetch_limit = limit * state.config.candidate_overfetch_multiplier
    fan_out = await state.pipeline.search_parsed_query(parsed.to_json_dict(), top_k=fetch_limit)

    total_shards = len(state.pipeline.targets)
    failed_shard_ids = fan_out.failed_shard_ids
    degraded = len(failed_shard_ids) > 0

    query_terms = list(parsed.required_terms) + [
        term for phrase in parsed.phrases for term in phrase
    ]
    reranked = rerank_sharded_hits(
        fan_out.merged,
        query_terms,
        state.rerank_context,
        state.config.pagerank_dir,
        state.reranker_model,
        top_k=limit,
    )

    results: list[SearchResultItem] = []
    for ranked in reranked:
        document = state.snippet_index.document(ranked.doc_id)
        if document is None:
            # Un doc_id que el shard conoce pero que no aparece en el
            # documents.jsonl de html-content-extractor indicaría un
            # bootstrap inconsistente (ficheros de distintas ejecuciones) —
            # se descarta ese resultado en vez de mostrar un snippet vacío
            # engañoso, y se sigue sirviendo el resto.
            continue
        snippet = build_snippet(document.main_text, query_terms)
        results.append(
            SearchResultItem(
                doc_id=ranked.doc_id,
                url=document.url,
                title=document.title,
                snippet=snippet,
                score=ranked.final_score,
            )
        )

    message: str | None = None
    if degraded:
        message = _degraded_message(len(failed_shard_ids), total_shards, bool(results))
    elif not results:
        message = _NO_RESULTS_MESSAGE

    shard_statuses = tuple(
        ShardStatusInfo(
            shard_id=outcome.shard_id, status=outcome.status, error_message=outcome.error_message
        )
        for outcome in fan_out.outcomes
    )

    return SearchResponse(
        query=raw_query,
        results=tuple(results),
        corrections=corrections,
        shard_statuses=shard_statuses,
        degraded=degraded,
        message=message,
    )
