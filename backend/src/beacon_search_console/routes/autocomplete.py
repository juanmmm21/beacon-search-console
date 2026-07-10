"""`GET /api/v1/autocomplete` — delega en `query-parser-autocomplete.suggest`.
Un prefijo vacío devuelve las queries más frecuentes (comportamiento
intencional documentado por ese proyecto: sugerencias por defecto antes de
que el usuario escriba nada, no un caso de error)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from query_parser_autocomplete.pipeline import suggest as suggest_completions

from beacon_search_console.dependencies import AppState, get_app_state
from beacon_search_console.models import AutocompleteResponse, AutocompleteSuggestion

router = APIRouter(tags=["autocomplete"])


@router.get("/autocomplete", response_model=AutocompleteResponse)
async def autocomplete(
    q: str = Query("", description="Prefijo ya escrito por el usuario"),
    limit: int = Query(8, ge=1, le=20),
    state: AppState = Depends(get_app_state),
) -> AutocompleteResponse:
    prefix = q.strip()
    suggestions = suggest_completions(prefix, state.autocomplete_index, limit)
    return AutocompleteResponse(
        prefix=prefix,
        suggestions=tuple(
            AutocompleteSuggestion(text=suggestion.text, score=suggestion.score)
            for suggestion in suggestions
        ),
    )
