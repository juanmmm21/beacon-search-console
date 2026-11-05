"""Caché de resultados de búsqueda en memoria de proceso: LRU acotada con
caducidad por entrada.

La clave lleva la versión del índice como espacio de nombres. Cuando el
índice cambia (un bundle nuevo del vertical, ver `vertical.py`), las
consultas siguientes buscan con la versión nueva y nunca encuentran
resultados del índice anterior: no hace falta borrar nada, las entradas
viejas salen por LRU o por TTL. Es el mismo criterio de invalidación que la
caché compartida en Redis de `beacon-search-engine-at-scale` (fase 6), aquí
sin Redis porque la consola de producto es un único proceso.

Las respuestas degradadas no se cachean (lo decide quien llama): un fallo
transitorio no debe servirse durante todo un TTL.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Generic, TypeVar

V = TypeVar("V")


@dataclass(slots=True)
class CacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0

    @property
    def hit_ratio(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


class ResultCache(Generic[V]):
    def __init__(
        self,
        *,
        max_entries: int = 2048,
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries < 1:
            raise ValueError(f"max_entries debe ser >= 1, recibido {max_entries}")
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds debe ser positivo, recibido {ttl_seconds}")
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: OrderedDict[tuple[str, Hashable], tuple[float, V]] = OrderedDict()
        self.stats = CacheStats()

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, namespace: str, key: Hashable) -> V | None:
        entry_key = (namespace, key)
        entry = self._entries.get(entry_key)
        if entry is None:
            self.stats.misses += 1
            return None
        expires_at, value = entry
        if expires_at <= self._clock():
            del self._entries[entry_key]
            self.stats.misses += 1
            return None
        self._entries.move_to_end(entry_key)
        self.stats.hits += 1
        return value

    def put(self, namespace: str, key: Hashable, value: V) -> None:
        entry_key = (namespace, key)
        self._entries[entry_key] = (self._clock() + self._ttl, value)
        self._entries.move_to_end(entry_key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
            self.stats.evictions += 1
