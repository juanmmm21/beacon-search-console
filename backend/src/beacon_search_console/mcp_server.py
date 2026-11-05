"""Servidor MCP del buscador de documentación: expone `search` y
`fetch_document` para que un agente (Palo incluido) busque en la
documentación indexada y lea una página completa con su URL y su licencia.

Se sirve de dos formas, con las mismas herramientas:

- **stdio**, para un agente en la misma máquina:
  `beacon-search-console mcp --bundle-root <ruta>`;
- **Streamable HTTP**, montado en `/mcp` de la app del producto
  (`docs_app.py`), para agentes remotos.

Los errores que el agente puede corregir (fuente desconocida, documento que
no existe, modo híbrido no disponible) se devuelven como `ToolError`: el
modelo los lee y reintenta con otros argumentos.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from beacon_search_console.vertical import BundleError, SearchMode, VerticalSearchService

_INSTRUCTIONS = (
    "Search engine over curated technical documentation (Python, Rust, MDN Web Docs). "
    "Use `search` to find pages, then `fetch_document` with a result's doc_id to read it. "
    "Always cite the page URL and respect the source license shown with each result."
)
_MAX_DOCUMENT_CHARS = 50_000


class SearchResultItem(TypedDict):
    doc_id: int
    title: str
    url: str
    snippet: str
    source: str | None
    license: str | None
    score: float


class SearchOutput(TypedDict):
    query: str
    mode: str
    index_version: str
    results: list[SearchResultItem]


class DocumentOutput(TypedDict):
    doc_id: int
    title: str
    url: str
    text: str
    truncated: bool
    source: str | None
    license: str | None
    license_url: str | None
    attribution: str | None


def build_mcp_server(get_service: Callable[[], VerticalSearchService]) -> MCPServer:
    """`get_service` y no el servicio en sí: así el servidor MCP siempre usa
    el motor vigente tras una recarga del bundle."""
    mcp = MCPServer("beacon-docs-search", instructions=_INSTRUCTIONS)

    @mcp.tool()
    async def search(
        query: str, limit: int = 5, source: str | None = None, mode: str = "lexical"
    ) -> SearchOutput:
        """Search the indexed documentation. `source` is one of the ids listed by the
        server (python, rust, mdn); `mode` is "lexical" (BM25) or "hybrid" (BM25 plus
        dense retrieval and a cross-encoder, when the server enables it)."""
        service = get_service()
        if not query.strip():
            raise ToolError("query must not be empty")
        if not 1 <= limit <= 20:
            raise ToolError("limit must be between 1 and 20")
        if source is not None and source not in service.engine.bundle.sources:
            known = ", ".join(sorted(service.engine.bundle.sources))
            raise ToolError(f"unknown source {source!r}; known sources: {known}")
        try:
            search_mode = SearchMode(mode)
        except ValueError as error:
            raise ToolError('mode must be "lexical" or "hybrid"') from error
        try:
            result = await service.search(query, limit, source=source, mode=search_mode)
        except BundleError as error:
            raise ToolError(str(error)) from error
        return SearchOutput(
            query=result.query,
            mode=result.mode.value,
            index_version=result.index_version,
            results=[
                SearchResultItem(
                    doc_id=hit.doc_id,
                    title=hit.title,
                    url=hit.url,
                    snippet=hit.snippet.text,
                    source=hit.source.name if hit.source else None,
                    license=hit.source.license if hit.source else None,
                    score=round(hit.score, 6),
                )
                for hit in result.hits
            ],
        )

    @mcp.tool()
    async def fetch_document(doc_id: int, max_chars: int = 20_000) -> DocumentOutput:
        """Full text of one documentation page found with `search`, with its URL and
        the license and attribution its source requires."""
        if not 1 <= max_chars <= _MAX_DOCUMENT_CHARS:
            raise ToolError(f"max_chars must be between 1 and {_MAX_DOCUMENT_CHARS}")
        found = get_service().document(doc_id)
        if found is None:
            raise ToolError(f"no document with doc_id {doc_id}; use an id returned by search")
        document, source = found
        return DocumentOutput(
            doc_id=document.doc_id,
            title=document.title,
            url=document.url,
            text=document.main_text[:max_chars],
            truncated=len(document.main_text) > max_chars,
            source=source.name if source else None,
            license=source.license if source else None,
            license_url=source.license_url if source else None,
            attribution=source.attribution if source else None,
        )

    return mcp
