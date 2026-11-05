"""Límite de peticiones por cliente para la API pública: un *token bucket*
por IP (capacidad `burst`, recarga `rate_per_second`), en memoria de
proceso. Suficiente para un único proceso detrás de un proxy; con varias
réplicas haría falta un contador compartido.

La IP sale de `X-Forwarded-For` solo si `trust_forwarded_for` está activo:
sin un proxy delante que la escriba, cualquiera podría inventarse una IP
nueva por petición y saltarse el límite.
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_MAX_TRACKED_CLIENTS = 50_000


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    rate_per_second: float = 2.0
    burst: int = 30
    trust_forwarded_for: bool = False
    path_prefixes: tuple[str, ...] = ("/v1/", "/mcp")

    def __post_init__(self) -> None:
        if self.rate_per_second <= 0 or self.burst < 1:
            raise ValueError("rate_per_second debe ser positivo y burst >= 1")


class TokenBucketLimiter:
    def __init__(self, config: RateLimitConfig, clock: Callable[[], float] = time.monotonic):
        self._config = config
        self._clock = clock
        # Acotado: sin tope, un barrido de IPs llenaría la memoria.
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def acquire(self, client: str) -> float:
        """0 si la petición pasa; si no, segundos hasta el siguiente token."""
        now = self._clock()
        tokens, updated = self._buckets.get(client, (float(self._config.burst), now))
        tokens = min(
            float(self._config.burst), tokens + (now - updated) * self._config.rate_per_second
        )
        if tokens >= 1.0:
            self._buckets[client] = (tokens - 1.0, now)
            self._buckets.move_to_end(client)
            while len(self._buckets) > _MAX_TRACKED_CLIENTS:
                self._buckets.popitem(last=False)
            return 0.0
        self._buckets[client] = (tokens, now)
        return (1.0 - tokens) / self._config.rate_per_second

    def client_id(self, request: Request) -> str:
        if self._config.trust_forwarded_for:
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return request.client.host if request.client is not None else "unknown"

    async def middleware(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not request.url.path.startswith(self._config.path_prefixes):
            return await call_next(request)
        wait = self.acquire(self.client_id(request))
        if wait > 0:
            return JSONResponse(
                {"detail": "Demasiadas peticiones: espera un momento y vuelve a intentarlo."},
                status_code=429,
                headers={"Retry-After": str(max(1, math.ceil(wait)))},
            )
        return await call_next(request)
