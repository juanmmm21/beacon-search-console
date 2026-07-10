"""Punto de entrada FastAPI: arranca y cierra todo el estado compartido
(pipeline distribuido, modelo de reranking, índices en memoria) en el ciclo
de vida de la app, y monta las tres rutas versionadas del contrato
(`/api/v1/search`, `/api/v1/autocomplete`, `/api/v1/index/stats`)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from beacon_search_console.config import AppConfig
from beacon_search_console.dependencies import AppState
from beacon_search_console.routes import autocomplete, search, stats


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = AppConfig.from_env()
    state = await AppState.build(config)
    app.state.app_state = state
    try:
        yield
    finally:
        await state.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="beacon-search-console",
        description=(
            "Buscador funcional completo sobre el ecosistema beacon-search-engine: "
            "parseo de query, fan-out distribuido, BM25 + PageRank + reranking LTR."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        # Sin autenticación ni cookies de sesión que proteger: es un buscador de
        # solo lectura sobre un corpus público, servido a un frontend de
        # desarrollo (Vite) en otro puerto — no hay superficie de CSRF/credenciales
        # que un origen abierto pueda explotar aquí.
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(search.router, prefix="/api/v1")
    app.include_router(autocomplete.router, prefix="/api/v1")
    app.include_router(stats.router, prefix="/api/v1")
    return app


app = create_app()
