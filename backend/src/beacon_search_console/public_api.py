"""API pública del buscador de documentación (`/v1/...`), versionada desde
el primer día como el resto de contratos de la consola. La consumen la UI
del producto, los agentes vía `mcp_server.py` y cualquier cliente HTTP.

Contrato v1:

- `GET /v1/search?q=&limit=&source=&mode=` → resultados con snippet,
  fuente y licencia. `mode` es `lexical` (BM25) o `hybrid` (BM25 + denso con
  RRF y cross-encoder), este último solo si el servidor lo tiene activado.
- `GET /v1/documents/{doc_id}` → texto completo del documento, su URL
  original y la licencia de su fuente.
- `GET /v1/sources` → fuentes indexadas, con licencia y atribución, y las
  desactivadas con su motivo.
- `GET /v1/health` → versión del índice, documentos por fuente y caché.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from beacon_search_console.models import Snippet
from beacon_search_console.vertical import (
    BundleError,
    SearchMode,
    SourceInfo,
    VerticalSearchService,
)

router = APIRouter(prefix="/v1", tags=["public"])


@dataclass(frozen=True, slots=True)
class PublicSearchHit:
    doc_id: int
    url: str
    title: str
    snippet: Snippet
    score: float
    source: SourceInfo | None


@dataclass(frozen=True, slots=True)
class PublicSearchResponse:
    query: str
    mode: str
    index_version: str
    cached: bool
    took_ms: float
    results: tuple[PublicSearchHit, ...]


@dataclass(frozen=True, slots=True)
class PublicDocument:
    doc_id: int
    url: str
    title: str
    text: str
    source: SourceInfo | None


@dataclass(frozen=True, slots=True)
class DisabledSource:
    source_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class PublicSources:
    sources: tuple[SourceInfo, ...]
    disabled: tuple[DisabledSource, ...]


def get_service(request: Request) -> VerticalSearchService:
    service: VerticalSearchService = request.app.state.docs_service
    return service


@router.get("/search", response_model=PublicSearchResponse)
async def search(
    q: str = Query(..., min_length=1, max_length=256, description="Texto de la búsqueda"),
    limit: int = Query(10, ge=1, le=50),
    source: str | None = Query(None, description="Restringe a una fuente (`/v1/sources`)"),
    mode: SearchMode = Query(SearchMode.LEXICAL),
    service: VerticalSearchService = Depends(get_service),
) -> PublicSearchResponse:
    if source is not None and source not in service.engine.bundle.sources:
        raise HTTPException(status_code=400, detail=f"fuente desconocida: {source}")
    try:
        result = await service.search(q, limit, source=source, mode=mode)
    except BundleError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return PublicSearchResponse(
        query=result.query,
        mode=result.mode.value,
        index_version=result.index_version,
        cached=result.cached,
        took_ms=result.took_ms,
        results=tuple(
            PublicSearchHit(h.doc_id, h.url, h.title, h.snippet, h.score, h.source)
            for h in result.hits
        ),
    )


@router.get("/documents/{doc_id}", response_model=PublicDocument)
async def fetch_document(
    doc_id: int, service: VerticalSearchService = Depends(get_service)
) -> PublicDocument:
    found = service.document(doc_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no existe el documento {doc_id}")
    document, source = found
    return PublicDocument(document.doc_id, document.url, document.title, document.main_text, source)


@router.get("/sources", response_model=PublicSources)
async def sources(service: VerticalSearchService = Depends(get_service)) -> PublicSources:
    bundle = service.engine.bundle
    return PublicSources(
        sources=tuple(bundle.sources[key] for key in sorted(bundle.sources)),
        disabled=tuple(DisabledSource(sid, reason) for sid, reason in bundle.disabled_sources),
    )


@router.get("/health")
async def health(service: VerticalSearchService = Depends(get_service)) -> dict[str, object]:
    return {"status": "ok", **service.describe()}
