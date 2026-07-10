"""Fixtures compartidas: todo el estado de la app se construye contra
`samples/tiny_corpus/` (fixture pequeño y determinista, sin red ni
dependencia del corpus real bootstrapeado en `data/`, que no se versiona) —
mismo patrón de `samples/tiny_example/` que usan los nueve subproyectos
anteriores del ecosistema."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from beacon_search_console.config import AppConfig
from beacon_search_console.dependencies import AppState, get_app_state
from beacon_search_console.routes import autocomplete, search, stats

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "samples" / "tiny_corpus"

# Puerto dedicado a los shards locales de test, fuera del rango que usa el
# bootstrap real (9300+) para no chocar si hay un servidor de desarrollo
# corriendo en paralelo.
_TEST_SHARD_BASE_PORT = 9400


def tiny_config(*, shard_base_port: int = _TEST_SHARD_BASE_PORT) -> AppConfig:
    return AppConfig(
        global_index_dir=FIXTURE_ROOT / "index",
        extractor_documents_path=FIXTURE_ROOT / "extracted" / "documents.jsonl",
        pagerank_dir=FIXTURE_ROOT / "pagerank",
        partitioned_shards_dir=FIXTURE_ROOT / "shards",
        ltr_model_dir=FIXTURE_ROOT / "ltr-model",
        query_log_path=None,
        shard_host="127.0.0.1",
        shard_base_port=shard_base_port,
        shard_timeout_seconds=2.0,
        candidate_overfetch_multiplier=3,
        default_result_limit=10,
        autocomplete_default_limit=8,
    )


@pytest.fixture
async def app_state() -> AsyncIterator[AppState]:
    state = await AppState.build(tiny_config())
    try:
        yield state
    finally:
        await state.close()


def build_test_app(app_state: AppState) -> FastAPI:
    app = FastAPI()
    app.include_router(search.router, prefix="/api/v1")
    app.include_router(autocomplete.router, prefix="/api/v1")
    app.include_router(stats.router, prefix="/api/v1")
    app.dependency_overrides[get_app_state] = lambda: app_state
    return app


@pytest.fixture
async def client(app_state: AppState) -> AsyncIterator[httpx.AsyncClient]:
    # httpx.AsyncClient (no el `TestClient` síncrono de Starlette): el
    # pipeline distribuido real usa un `aiohttp.ClientSession` atado al loop
    # de asyncio en el que se construyó (`app_state`, fixture async de
    # pytest-asyncio); `TestClient` ejecuta cada petición en un loop propio
    # en otro hilo, lo que rompe esa sesión aiohttp con
    # "Timeout context manager should be used inside a task". Usando
    # `httpx.AsyncClient` + `ASGITransport` dentro de un test `async def`, la
    # petición corre en el mismo loop que construyó el pipeline.
    transport = httpx.ASGITransport(app=build_test_app(app_state))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client
