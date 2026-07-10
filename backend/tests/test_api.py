"""Tests end-to-end de la API contra `samples/tiny_corpus/` (clúster local de
2 shards reales, arrancado por `app_state`/`client` en `conftest.py`).

La degradación por caída de shard se cubre aquí con un `pipeline` de prueba en
memoria que sustituye a `DistributedSearchPipeline` (mismo patrón que usa
`distributed-index-sharding` para testear `SearchCoordinator` con un
`ShardTransport` doble, según documenta su propio README) — matar un proceso
de shard real de verdad es el smoke test manual que exige el checklist de
cierre del proyecto, no algo que deba repetirse aquí para cada caso de
degradación."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from conftest import build_test_app
from distributed_index_sharding.models import FanOutResult, ShardHit, ShardOutcome

from beacon_search_console.dependencies import AppState


async def test_search_returns_ranked_results_with_snippet(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/search", params={"q": "python search", "limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is False
    assert body["message"] is None
    assert body["results"]
    first = body["results"][0]
    assert first["url"].startswith("http://example.com/")
    assert first["snippet"]["text"]


async def test_search_empty_query_returns_message(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/search", params={"q": "   "})
    assert response.status_code == 200
    body = response.json()
    assert body["results"] == []
    assert body["message"]


async def test_search_no_results_message(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/search", params={"q": "qqxxzzyy123456"})
    assert response.status_code == 200
    body = response.json()
    assert body["results"] == []
    assert body["degraded"] is False
    assert body["message"] == "No se encontraron resultados para esta búsqueda."


async def test_search_applies_spelling_correction(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/search", params={"q": "pyhton"})
    assert response.status_code == 200
    body = response.json()
    assert body["corrections"] == [{"original": "pyhton", "corrected": "python"}]
    assert body["results"]


async def test_search_only_exclusion_has_no_searchable_terms(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/search", params={"q": "-python"})
    assert response.status_code == 200
    body = response.json()
    assert body["results"] == []
    assert "filtros" in body["message"] or "exclusiones" in body["message"]


async def test_autocomplete_returns_suggestions(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/autocomplete", params={"q": "pyth", "limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert any(s["text"].startswith("pyth") for s in body["suggestions"])


async def test_autocomplete_empty_prefix_returns_trending(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/autocomplete", params={"q": ""})
    assert response.status_code == 200
    assert response.json()["suggestions"]


async def test_index_stats(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/index/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["total_documents"] == 5
    assert body["num_shards"] == 2
    assert body["last_crawled_at"] == "2026-07-09T10:00:00+00:00"


@dataclass
class _FakePipeline:
    """Doble mínimo de `DistributedSearchPipeline`: solo implementa lo que
    `routes/search.py` usa (`targets`, `search_parsed_query`, `close`)."""

    fan_out: FanOutResult
    num_targets: int

    @property
    def targets(self) -> tuple[int, ...]:
        return tuple(range(self.num_targets))

    async def search_parsed_query(
        self, parsed_query: dict[str, object], *, top_k: int
    ) -> FanOutResult:
        return self.fan_out

    async def close(self) -> None:
        return None


async def test_search_degrades_on_partial_shard_failure(app_state: AppState) -> None:
    fan_out = FanOutResult(
        outcomes=(
            ShardOutcome(
                shard_id=0, status="ok", hits=(ShardHit(doc_id=1, score=0.9),), latency_ms=1.0
            ),
            ShardOutcome(
                shard_id=1,
                status="timeout",
                hits=(),
                error_message="tiempo de espera agotado",
                latency_ms=2000.0,
            ),
        ),
        merged=(ShardHit(doc_id=1, score=0.9),),
    )
    # `app_state.pipeline` real (con subprocesos de shard de verdad) se
    # sustituye por el doble en memoria para simular la degradación; el
    # `finally` de `AppState.close()` en el fixture cerraría el doble (un
    # no-op), no el pipeline real, así que hay que cerrarlo aquí explícitamente
    # para no dejar procesos huérfanos.
    real_pipeline = app_state.pipeline
    app_state.pipeline = _FakePipeline(fan_out=fan_out, num_targets=2)  # type: ignore[assignment]
    try:
        transport = httpx.ASGITransport(app=build_test_app(app_state))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/v1/search", params={"q": "python"})
        assert response.status_code == 200
        body = response.json()
        assert body["degraded"] is True
        assert body["results"]
        assert "parciales" in body["message"]
        assert {s["shard_id"]: s["status"] for s in body["shard_statuses"]} == {
            0: "ok",
            1: "timeout",
        }
    finally:
        await real_pipeline.close()


async def test_search_degrades_fully_when_all_shards_fail(app_state: AppState) -> None:
    fan_out = FanOutResult(
        outcomes=(
            ShardOutcome(shard_id=0, status="error", hits=(), error_message="conexión rechazada"),
            ShardOutcome(shard_id=1, status="timeout", hits=(), error_message="tiempo agotado"),
        ),
        merged=(),
    )
    real_pipeline = app_state.pipeline
    app_state.pipeline = _FakePipeline(fan_out=fan_out, num_targets=2)  # type: ignore[assignment]
    try:
        transport = httpx.ASGITransport(app=build_test_app(app_state))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/v1/search", params={"q": "python"})
        assert response.status_code == 200
        body = response.json()
        assert body["degraded"] is True
        assert body["results"] == []
        assert "no se pudo completar" in body["message"]
    finally:
        await real_pipeline.close()
