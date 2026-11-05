"""Latencia p50/p99 del buscador de documentación, antes y después de la
caché de resultados, sobre un registro de consultas sintético reproducible.

    python scripts/bench_docs_latency.py --bundle-root <raíz> --output eval/results/latency.json
    python scripts/bench_docs_latency.py --bundle-root <raíz> --url http://127.0.0.1:8001 --hybrid

El registro reparte `--requests` peticiones entre las consultas de
`QUERIES` con una ley de Zipf (s = 1.1, semilla fija): pocas consultas muy
repetidas y una cola larga, la forma habitual del tráfico de un buscador, y
justo la que determina cuánto ayuda una caché. "Antes" es el motor sin
caché; "después", el servicio con su caché, recorriendo el mismo registro.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from beacon_search_console.cache import ResultCache
from beacon_search_console.vertical import (
    HybridModels,
    SearchMode,
    VerticalSearchService,
)

QUERIES = [
    "async context manager",
    "asyncio timeout",
    "list comprehension",
    "dataclass default factory",
    "pathlib glob",
    "f-string format spec",
    "typing protocol",
    "itertools groupby",
    "subprocess run capture output",
    "json dumps indent",
    "logging config",
    "argparse subcommands",
    "enum auto",
    "functools lru_cache",
    "decorator with arguments",
    "generator send",
    "exception chaining",
    "with statement",
    "unittest mock patch",
    "datetime timezone",
    "borrow checker lifetimes",
    "ownership move semantics",
    "trait objects dyn",
    "iterator map filter",
    "result question mark operator",
    "option unwrap or",
    "vec push pop",
    "hashmap entry api",
    "string slices utf-8",
    "pattern matching enums",
    "smart pointers box rc",
    "refcell interior mutability",
    "threads channels",
    "mutex arc",
    "closures capture",
    "generic type parameters",
    "flexbox gap",
    "css grid template areas",
    "array prototype map",
    "promise all",
    "fetch api headers",
    "async await javascript",
    "let const var",
    "arrow functions this",
    "html form validation",
    "input type date",
    "media queries",
    "position sticky",
    "object destructuring",
    "spread syntax",
    "regular expressions lookahead",
    "set has",
    "map vs object",
    "template literals",
    "class private fields",
    "event listener options",
    "string replaceall",
    "number tofixed",
    "json parse reviver",
    "web components shadow dom",
]


def query_log(requests: int, seed: int) -> list[str]:
    rng = np.random.default_rng(seed)
    ranks = np.arange(1, len(QUERIES) + 1, dtype=np.float64)
    weights = ranks**-1.1
    weights /= weights.sum()
    picks = rng.choice(len(QUERIES), size=requests, p=weights)
    return [QUERIES[i] for i in picks]


def percentiles(samples_ms: list[float]) -> dict[str, float]:
    ordered = sorted(samples_ms)
    return {
        "p50_ms": round(statistics.median(ordered), 3),
        "p99_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))], 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
        "requests": len(ordered),
    }


async def run_in_process(
    service: VerticalSearchService, log: list[str], mode: SearchMode
) -> dict[str, Any]:
    engine = service.engine
    before: list[float] = []
    for query in log:
        started = time.perf_counter()
        engine.search(query, 10, source=None, mode=mode)
        before.append((time.perf_counter() - started) * 1000)
    after: list[float] = []
    for query in log:
        started = time.perf_counter()
        await service.search(query, 10, mode=mode)
        after.append((time.perf_counter() - started) * 1000)
    return {
        "mode": mode.value,
        "without_cache": percentiles(before),
        "with_cache": percentiles(after),
        "cache_hit_ratio": round(service.cache.stats.hit_ratio, 4),
    }


async def run_http(url: str, log: list[str], mode: SearchMode) -> dict[str, Any]:
    samples: list[float] = []
    cached = 0
    async with httpx.AsyncClient(base_url=url, timeout=60) as client:
        for query in log:
            started = time.perf_counter()
            response = await client.get(
                "/v1/search", params={"q": query, "limit": 10, "mode": mode.value}
            )
            samples.append((time.perf_counter() - started) * 1000)
            response.raise_for_status()
            cached += bool(response.json()["cached"])
    return {
        "mode": mode.value,
        "end_to_end": percentiles(samples),
        "cached_responses": cached,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--hybrid", action="store_true")
    parser.add_argument(
        "--url",
        default=None,
        help="Mide también por HTTP contra un servidor ya arrancado",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    log = query_log(args.requests, args.seed)
    report: dict[str, Any] = {
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
            "python": platform.python_version(),
        },
        "versions": {
            name: version(name)
            for name in (
                "beacon-search-console",
                "bm25-ranking-engine",
                "inverted-index-builder",
            )
        },
        "requests": args.requests,
        "distinct_queries": len(set(log)),
        "zipf_s": 1.1,
        "seed": args.seed,
        "runs": [],
    }
    modes = [SearchMode.LEXICAL]
    models: HybridModels | None = None
    if args.hybrid:
        from beacon_search_console.hybrid import CrossEncoderStage, SentenceEncoder

        models = HybridModels(
            encoder=SentenceEncoder(), cross_encoder=CrossEncoderStage()
        )
        modes.append(SearchMode.HYBRID)
    for mode in modes:
        service = VerticalSearchService(
            args.bundle_root, models=models, cache=ResultCache()
        )
        report["bundle"] = service.describe()
        report["bundle"].pop("cache")
        report["runs"].append(await run_in_process(service, log, mode))
        service.close()
        if args.url:
            report["runs"].append(await run_http(args.url, log, mode))
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
