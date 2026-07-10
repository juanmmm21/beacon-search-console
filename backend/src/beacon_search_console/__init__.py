"""beacon-search-console: capa de orquestación delgada que ensambla las nueve
piezas de infraestructura del ecosistema beacon-search-engine en un buscador
funcional (API FastAPI + UI React). No reimplementa tokenización, BM25,
PageRank, reranking ni sharding — todo se consume como paquete instalado o
como artefacto ya construido por los subproyectos anteriores."""

from __future__ import annotations
