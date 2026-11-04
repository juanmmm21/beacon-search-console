"""Descripción de la máquina y de las versiones con las que se midió: cada
informe de evaluación o de latencia la lleva incrustada, para que ningún
número publicado quede sin contexto."""

from __future__ import annotations

import importlib.metadata
import os
import platform
from pathlib import Path
from typing import Any

_TRACKED_PACKAGES: tuple[str, ...] = (
    "beacon-search-console",
    "inverted-index-builder",
    "index-compression-codec",
    "bm25-ranking-engine",
    "learning-to-rank-reranker",
    "query-parser-autocomplete",
    "distributed-index-sharding",
    "nano-vector-db",
    "cross-encoder-reranker",
    "contrastive-embedding-trainer",
    "numpy",
    "lightgbm",
    "torch",
    "transformers",
)


def _cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or "desconocida"


def _total_memory_gib() -> float | None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return None
    for line in meminfo.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            return round(int(line.split()[1]) / (1024 * 1024), 1)
    return None


def _gpu_name() -> str | None:
    try:
        import torch
    except ImportError:
        return None
    if torch.cuda.is_available():
        return str(torch.cuda.get_device_name(0))
    return None


def describe_environment() -> dict[str, Any]:
    versions: dict[str, str] = {}
    for package in _TRACKED_PACKAGES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu": _cpu_model(),
        "logical_cpus": os.cpu_count(),
        "memory_gib": _total_memory_gib(),
        "gpu": _gpu_name(),
        "packages": versions,
    }
