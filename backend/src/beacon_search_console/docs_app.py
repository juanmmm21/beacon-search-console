"""App del producto: el buscador público de documentación técnica.

Separada de `app.py` (la consola original sobre el clúster de shards de
docs.python.org) porque sirve otra cosa con otro ciclo de vida: un bundle
del vertical que se recarga en caliente, la API pública `/v1`, el servidor
MCP en `/mcp` y un límite de peticiones por cliente. Ninguna de las dos
rompe el contrato `/api/v1` de la otra.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.transport_security import TransportSecuritySettings

from beacon_search_console import public_api
from beacon_search_console.cache import ResultCache
from beacon_search_console.mcp_server import build_mcp_server
from beacon_search_console.rate_limit import RateLimitConfig, TokenBucketLimiter
from beacon_search_console.vertical import BundleError, HybridModels, VerticalSearchService

logger = logging.getLogger(__name__)


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class DocsConfig:
    bundle_root: Path
    hybrid: bool = False
    cross_encoder: bool = True
    reload_seconds: float = 30.0
    cache_entries: int = 2048
    cache_ttl_seconds: float = 300.0
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    mcp_allowed_hosts: tuple[str, ...] = ()
    """Hosts públicos del endpoint MCP (`docs.example.com`, `docs.example.com:*`).
    Vacío = solo localhost, la protección por defecto del SDK de MCP."""
    cors_origins: tuple[str, ...] = ("*",)

    @classmethod
    def from_env(cls) -> DocsConfig:
        root = os.environ.get("BEACON_DOCS_BUNDLE_ROOT")
        if not root:
            raise RuntimeError("BEACON_DOCS_BUNDLE_ROOT es obligatoria (raíz del bundle)")
        hosts = os.environ.get("BEACON_MCP_ALLOWED_HOSTS", "")
        origins = os.environ.get("BEACON_CORS_ORIGINS", "*")
        return cls(
            bundle_root=Path(root),
            hybrid=_flag("BEACON_DOCS_HYBRID", False),
            cross_encoder=_flag("BEACON_DOCS_CROSS_ENCODER", True),
            reload_seconds=float(os.environ.get("BEACON_DOCS_RELOAD_SECONDS", "30")),
            cache_entries=int(os.environ.get("BEACON_DOCS_CACHE_ENTRIES", "2048")),
            cache_ttl_seconds=float(os.environ.get("BEACON_DOCS_CACHE_TTL_SECONDS", "300")),
            rate_limit=RateLimitConfig(
                rate_per_second=float(os.environ.get("BEACON_RATE_PER_SECOND", "2")),
                burst=int(os.environ.get("BEACON_RATE_BURST", "30")),
                trust_forwarded_for=_flag("BEACON_TRUST_PROXY", False),
            ),
            mcp_allowed_hosts=tuple(h.strip() for h in hosts.split(",") if h.strip()),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        )


def _load_models(config: DocsConfig) -> HybridModels | None:
    if not config.hybrid:
        return None
    from beacon_search_console.hybrid import CrossEncoderStage, SentenceEncoder

    return HybridModels(
        encoder=SentenceEncoder(),
        cross_encoder=CrossEncoderStage() if config.cross_encoder else None,
    )


async def _reload_loop(service: VerticalSearchService, every: float) -> None:
    while True:
        await asyncio.sleep(every)
        try:
            await service.maybe_reload()
        except (BundleError, OSError, ValueError, KeyError) as error:
            # Un bundle nuevo roto no debe tumbar el servidor: se sigue
            # sirviendo el anterior y se reintenta en la siguiente vuelta.
            logger.error("no se pudo recargar el bundle (%s); se mantiene el actual", error)


def create_docs_app(config: DocsConfig | None = None) -> FastAPI:
    resolved = config if config is not None else DocsConfig.from_env()
    holder: dict[str, VerticalSearchService] = {}
    mcp = build_mcp_server(lambda: holder["service"])
    security = (
        TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(resolved.mcp_allowed_hosts),
            allowed_origins=[f"https://{h.split(':')[0]}" for h in resolved.mcp_allowed_hosts],
        )
        if resolved.mcp_allowed_hosts
        else None
    )
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        models = await asyncio.to_thread(_load_models, resolved)
        service = await asyncio.to_thread(
            VerticalSearchService,
            resolved.bundle_root,
            models=models,
            cache=ResultCache(
                max_entries=resolved.cache_entries, ttl_seconds=resolved.cache_ttl_seconds
            ),
        )
        holder["service"] = service
        app.state.docs_service = service
        reloader = asyncio.create_task(_reload_loop(service, resolved.reload_seconds))
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            reloader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reloader
            service.close()

    app = FastAPI(
        title="Beacon Docs Search",
        description=(
            "Public search API over curated technical documentation, built from scratch "
            "on the beacon-search-engine components."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    limiter = TokenBucketLimiter(resolved.rate_limit)
    app.middleware("http")(limiter.middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id", "Retry-After"],
    )
    app.include_router(public_api.router)
    app.mount("/mcp", mcp_app)
    return app
