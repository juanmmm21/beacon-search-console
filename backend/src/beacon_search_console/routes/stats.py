"""`GET /api/v1/index/stats` — panel de estadísticas del índice: documentos
indexados, términos únicos, nº de shards y última actualización del crawl."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from beacon_search_console.dependencies import AppState, get_app_state
from beacon_search_console.models import IndexStatsResponse

router = APIRouter(tags=["stats"])


@router.get("/index/stats", response_model=IndexStatsResponse)
async def index_stats(state: AppState = Depends(get_app_state)) -> IndexStatsResponse:
    return IndexStatsResponse(
        total_documents=state.global_stats.total_documents,
        vocabulary_size=state.global_stats.vocabulary_size,
        total_postings=state.global_stats.total_postings,
        average_document_length=state.global_stats.average_document_length,
        num_shards=state.rerank_context.num_shards,
        last_crawled_at=state.last_crawled_at,
    )
