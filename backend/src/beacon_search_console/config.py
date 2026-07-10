"""Configuración de la app: rutas a los artefactos que produce
`scripts/bootstrap_corpus.sh` (o `scripts/build_tiny_fixture.sh` para tests) y
parámetros de orquestación del pipeline de consulta. Todo configurable por
variable de entorno, con valores por defecto que apuntan a `data/` en la raíz
del repo — el layout que produce el bootstrap real (ver README, sección
"Cómo levantar el pipeline")."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# backend/src/beacon_search_console/config.py -> beacon-search-console/ (raíz del repo)
_REPO_ROOT: Path = Path(__file__).resolve().parents[3]
_DEFAULT_DATA_DIR: Path = _REPO_ROOT / "data"


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Todas las rutas y parámetros que necesita `app.py` para arrancar el
    pipeline de consulta. Inmutable: se construye una vez al arrancar la app
    (`from_env`) y se pasa por `dependencies.py` al resto de la aplicación."""

    global_index_dir: Path
    """Índice global sin comprimir de `inverted-index-builder` (antes de
    particionar) — lo necesita `query-parser-autocomplete` para vocabulario
    (document_frequency global, no el local de un shard)."""

    extractor_documents_path: Path
    """`documents.jsonl` de `html-content-extractor` (con `main_text`), para
    correlacionar `doc_id` -> snippet real (ver `snippets.py`)."""

    pagerank_dir: Path
    """Directorio de salida de `pagerank-link-analysis`, único y global para
    todo el corpus (no se particiona, a diferencia del índice)."""

    partitioned_shards_dir: Path
    """Raíz de shards de `distributed-index-sharding` (`cluster_manifest.json`
    + `shard-<id>/`), la entrada de `DistributedSearchPipeline.start`."""

    ltr_model_dir: Path
    """Modelo ya entrenado de `learning-to-rank-reranker`."""

    query_log_path: Path | None
    """Log de queries frecuentes para autocompletado; `None` genera uno
    sintético a partir del vocabulario (comportamiento documentado de
    `query-parser-autocomplete`, no una carencia de este proyecto)."""

    shard_host: str
    shard_base_port: int
    shard_timeout_seconds: float

    candidate_overfetch_multiplier: int
    """`distributed-index-sharding` ya sobre-pide `top_k * 3` internamente
    para absorber el post-filtrado local; aquí se sobre-pide una segunda vez
    sobre ese resultado ya fusionado antes de invocar el reranker, para que
    reordenar por LTR tenga más de `default_result_limit` candidatos entre
    los que elegir (ver `reranking.py`)."""

    default_result_limit: int
    autocomplete_default_limit: int

    def __post_init__(self) -> None:
        if self.shard_base_port <= 0:
            raise ValueError(f"shard_base_port debe ser positivo, recibido {self.shard_base_port}")
        if self.shard_timeout_seconds <= 0:
            raise ValueError(
                f"shard_timeout_seconds debe ser positivo, recibido {self.shard_timeout_seconds}"
            )
        if self.candidate_overfetch_multiplier < 1:
            raise ValueError(
                "candidate_overfetch_multiplier debe ser >= 1, "
                f"recibido {self.candidate_overfetch_multiplier}"
            )
        if self.default_result_limit < 1:
            raise ValueError(
                f"default_result_limit debe ser >= 1, recibido {self.default_result_limit}"
            )
        if self.autocomplete_default_limit < 1:
            raise ValueError(
                "autocomplete_default_limit debe ser >= 1, "
                f"recibido {self.autocomplete_default_limit}"
            )

    @classmethod
    def from_env(cls) -> AppConfig:
        data_dir = Path(os.environ.get("BEACON_DATA_DIR", str(_DEFAULT_DATA_DIR)))
        query_log_env = os.environ.get("BEACON_QUERY_LOG_PATH", "")
        return cls(
            global_index_dir=Path(
                os.environ.get("BEACON_INDEX_DIR", str(data_dir / "index"))
            ),
            extractor_documents_path=Path(
                os.environ.get(
                    "BEACON_DOCUMENTS_PATH", str(data_dir / "extracted" / "documents.jsonl")
                )
            ),
            pagerank_dir=Path(
                os.environ.get("BEACON_PAGERANK_DIR", str(data_dir / "pagerank"))
            ),
            partitioned_shards_dir=Path(
                os.environ.get("BEACON_SHARDS_DIR", str(data_dir / "shards"))
            ),
            ltr_model_dir=Path(
                os.environ.get("BEACON_LTR_MODEL_DIR", str(data_dir / "ltr-model"))
            ),
            query_log_path=Path(query_log_env) if query_log_env else None,
            shard_host=os.environ.get("BEACON_SHARD_HOST", "127.0.0.1"),
            shard_base_port=int(os.environ.get("BEACON_SHARD_BASE_PORT", "9300")),
            shard_timeout_seconds=float(os.environ.get("BEACON_SHARD_TIMEOUT_SECONDS", "2.0")),
            candidate_overfetch_multiplier=int(
                os.environ.get("BEACON_OVERFETCH_MULTIPLIER", "3")
            ),
            default_result_limit=int(os.environ.get("BEACON_DEFAULT_RESULT_LIMIT", "10")),
            autocomplete_default_limit=int(os.environ.get("BEACON_AUTOCOMPLETE_LIMIT", "8")),
        )
