"""Tests del buscador de documentación: bundle, caché, recarga en caliente,
API pública `/v1`, límite de peticiones y servidor MCP. El bundle se
construye en cada test con el índice segmentado real de
`inverted-index-builder`, en el formato que exporta at-scale."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from inverted_index_builder.pipeline import IndexBuilder
from inverted_index_builder.segments import SegmentedIndex
from mcp import Client

from beacon_search_console.cache import ResultCache
from beacon_search_console.docs_app import DocsConfig, create_docs_app
from beacon_search_console.mcp_server import build_mcp_server
from beacon_search_console.rate_limit import RateLimitConfig, TokenBucketLimiter
from beacon_search_console.vertical import (
    BundleError,
    SearchMode,
    VerticalBundle,
    VerticalSearchService,
)

_SOURCES = {
    "sources": [
        {
            "source_id": "python",
            "name": "Python 3 documentation",
            "license": "PSF License Version 2",
            "license_url": "https://docs.python.org/3/license.html",
            "attribution": "© Python Software Foundation",
            "home_url": "https://docs.python.org/3/",
        },
        {
            "source_id": "rust",
            "name": "The Rust Programming Language",
            "license": "MIT OR Apache-2.0",
            "license_url": "https://github.com/rust-lang/book/blob/main/LICENSE-MIT",
            "attribution": "© The Rust Project Developers",
            "home_url": "https://doc.rust-lang.org/book/",
        },
    ],
    "disabled": [{"source_id": "swift", "reason": "DocC app rendered client-side"}],
}

_DOCS = [
    (
        "https://docs.python.org/3/library/asyncio.html",
        "asyncio",
        "python",
        "asyncio is a library to write concurrent code using the async and await syntax.",
    ),
    (
        "https://docs.python.org/3/library/itertools.html",
        "itertools",
        "python",
        "Functions creating iterators for efficient looping over sequences.",
    ),
    (
        "https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html",
        "Ownership",
        "rust",
        "Ownership is a set of rules that govern how a Rust program manages memory.",
    ),
    (
        "https://doc.rust-lang.org/book/ch13-02-iterators.html",
        "Iterators",
        "rust",
        "The iterator pattern allows you to perform some task on a sequence of items in turn.",
    ),
]


def write_bundle(root: Path, version: str, docs: list[tuple[str, str, str, str]]) -> Path:
    bundle = root / f"bundle-{version}"
    index = SegmentedIndex.create(bundle / "index", IndexBuilder())
    records = [{"url": u, "title": t, "main_text": f"{t}\n{x}"} for u, t, _, x in docs]
    doc_ids = index.add_documents(records)
    with (bundle / "documents.jsonl").open("w", encoding="utf-8") as handle:
        for doc_id, (url, title, source, text) in zip(doc_ids, docs, strict=True):
            handle.write(
                json.dumps(
                    {
                        "doc_id": doc_id,
                        "url": url,
                        "title": title,
                        "main_text": f"{title}\n{text}",
                        "source_id": source,
                    }
                )
                + "\n"
            )
    (bundle / "sources.json").write_text(json.dumps(_SOURCES))
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "format": "beacon-vertical-bundle",
                "format_version": 1,
                "index_version": version * 4,
                "created_at": "2026-11-05T10:00:00+00:00",
                "documents": len(docs),
            }
        )
    )
    link = root / "current"
    temporary = root / ".current-tmp"
    temporary.symlink_to(bundle.name)
    os.replace(temporary, link)
    return bundle


@pytest.fixture
def bundle_root(tmp_path: Path) -> Path:
    write_bundle(tmp_path, "v1", _DOCS)
    return tmp_path


async def test_lexical_search_returns_sources_licenses_and_snippets(bundle_root: Path) -> None:
    service = VerticalSearchService(bundle_root)
    result = await service.search("ownership memory", 5)
    assert result.hits[0].title == "Ownership"
    assert result.hits[0].source is not None
    assert result.hits[0].source.license == "MIT OR Apache-2.0"
    assert result.hits[0].snippet.highlights
    service.close()


async def test_source_filter_and_cache_namespaced_by_index_version(bundle_root: Path) -> None:
    service = VerticalSearchService(bundle_root)
    first = await service.search("iterators", 5, source="python")
    assert first.hits
    assert all(hit.source is not None and hit.source.source_id == "python" for hit in first.hits)
    assert not first.cached
    again = await service.search("  Iterators ", 5, source="python")
    assert again.cached and again.hits == first.hits
    assert service.cache.stats.hits == 1

    write_bundle(
        bundle_root,
        "v2",
        [
            *_DOCS,
            (
                "https://docs.python.org/3/library/iter.html",
                "iter",
                "python",
                "iter returns an iterator object over iterators.",
            ),
        ],
    )
    assert await service.maybe_reload()
    assert not await service.maybe_reload()
    after = await service.search("iterators", 5, source="python")
    assert not after.cached
    assert after.index_version == "v2" * 4
    assert any(hit.title == "iter" for hit in after.hits)
    service.close()


async def test_hybrid_mode_requires_models(bundle_root: Path) -> None:
    service = VerticalSearchService(bundle_root)
    with pytest.raises(BundleError):
        await service.search("ownership", 5, mode=SearchMode.HYBRID)
    service.close()


def test_bundle_rejects_other_formats(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path, "v1", _DOCS)
    (bundle / "manifest.json").write_text(json.dumps({"format": "other", "format_version": 1}))
    with pytest.raises(BundleError):
        VerticalBundle.load(tmp_path)


def test_result_cache_lru_and_ttl() -> None:
    now = [0.0]
    cache: ResultCache[str] = ResultCache(max_entries=2, ttl_seconds=10, clock=lambda: now[0])
    cache.put("v1", "a", "A")
    cache.put("v1", "b", "B")
    assert cache.get("v1", "a") == "A"
    cache.put("v1", "c", "C")
    assert cache.get("v1", "b") is None  # el menos usado recientemente sale
    assert cache.get("v2", "a") is None  # otra versión del índice, otro espacio
    now[0] = 11.0
    assert cache.get("v1", "a") is None
    assert cache.stats.evictions == 1


def test_token_bucket_refills() -> None:
    now = [0.0]
    limiter = TokenBucketLimiter(RateLimitConfig(rate_per_second=1, burst=2), clock=lambda: now[0])
    assert limiter.acquire("ip") == 0 and limiter.acquire("ip") == 0
    assert limiter.acquire("ip") > 0
    assert limiter.acquire("other") == 0
    now[0] = 1.0
    assert limiter.acquire("ip") == 0


@asynccontextmanager
async def docs_client(bundle_root: Path, *, burst: int = 50) -> AsyncIterator[httpx.AsyncClient]:
    # Gestor de contexto dentro del test y no fixture async: el lifespan abre
    # cancel scopes de anyio que deben cerrarse en la misma tarea.
    app = create_docs_app(
        DocsConfig(
            bundle_root=bundle_root,
            rate_limit=RateLimitConfig(rate_per_second=1, burst=burst),
            mcp_allowed_hosts=("test",),
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as http,
    ):
        yield http


async def test_public_api_contract(bundle_root: Path) -> None:
    async with docs_client(bundle_root) as client:
        response = await client.get("/v1/search", params={"q": "asyncio await", "limit": 3})
        assert response.status_code == 200
        body: dict[str, Any] = response.json()
        assert body["mode"] == "lexical"
        top = body["results"][0]
        assert top["url"].endswith("asyncio.html")
        assert top["source"]["attribution"] == "© Python Software Foundation"
        assert {"text", "highlights"} <= set(top["snippet"])

        document = await client.get(f"/v1/documents/{top['doc_id']}")
        assert document.status_code == 200
        assert "async and await" in document.json()["text"]
        assert (await client.get("/v1/documents/9999")).status_code == 404

        sources = (await client.get("/v1/sources")).json()
        assert [s["source_id"] for s in sources["sources"]] == ["python", "rust"]
        assert sources["disabled"][0]["source_id"] == "swift"

        unknown_source = await client.get("/v1/search", params={"q": "x", "source": "go"})
        assert unknown_source.status_code == 400
        assert (await client.get("/v1/search", params={"q": ""})).status_code == 422
        health = (await client.get("/v1/health")).json()
        assert health["documents"] == 4
        assert health["documents_per_source"] == {"python": 2, "rust": 2}


async def test_rate_limit_answers_429_with_retry_after(bundle_root: Path) -> None:
    async with docs_client(bundle_root, burst=8) as client:
        statuses = [(await client.get("/v1/sources")).status_code for _ in range(12)]
        assert statuses[:8] == [200] * 8 and 429 in statuses
        limited = await client.get("/v1/sources")
        assert limited.status_code == 429 and int(limited.headers["retry-after"]) >= 1


async def test_mcp_tools_search_and_fetch_document(bundle_root: Path) -> None:
    service = VerticalSearchService(bundle_root)
    mcp = build_mcp_server(lambda: service)
    async with Client(mcp) as mcp_client:
        tools = {tool.name for tool in (await mcp_client.list_tools()).tools}
        assert tools == {"search", "fetch_document"}
        found = await mcp_client.call_tool("search", {"query": "rust ownership", "limit": 2})
        assert not found.is_error
        assert found.structured_content is not None
        top = found.structured_content["results"][0]
        assert top["title"] == "Ownership" and top["license"] == "MIT OR Apache-2.0"

        document = await mcp_client.call_tool(
            "fetch_document", {"doc_id": top["doc_id"], "max_chars": 20}
        )
        assert document.structured_content is not None
        assert document.structured_content["truncated"] is True
        assert len(document.structured_content["text"]) == 20

        missing = await mcp_client.call_tool("fetch_document", {"doc_id": 999})
        assert missing.is_error
        unknown = await mcp_client.call_tool("search", {"query": "x", "source": "go"})
        assert unknown.is_error
    service.close()


async def test_mcp_over_http_mount(bundle_root: Path) -> None:
    async with docs_client(bundle_root) as client:
        response = await client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 200, response.text
        names = {tool["name"] for tool in response.json()["result"]["tools"]}
        assert names == {"search", "fetch_document"}
