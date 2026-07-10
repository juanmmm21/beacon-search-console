"""Estado compartido de la app: todo lo que las rutas necesitan y que debe
abrirse/cerrarse una única vez por proceso (pipeline distribuido, modelo de
reranking, índices en memoria) — nunca reconstruido por request. Se construye
en el `lifespan` de `app.py` y se expone a las rutas vía `get_app_state`."""

from __future__ import annotations

from dataclasses import dataclass

from distributed_index_sharding.pipeline import DistributedSearchPipeline
from fastapi import Request
from learning_to_rank_reranker.model import LightGBMReranker
from query_parser_autocomplete import pipeline as query_parser_pipeline
from query_parser_autocomplete.autocomplete import AutocompleteIndex
from query_parser_autocomplete.spellcheck import SpellChecker

from beacon_search_console.config import AppConfig
from beacon_search_console.index_stats import GlobalIndexStats
from beacon_search_console.reranking import ShardedRerankContext
from beacon_search_console.snippets import SnippetIndex, latest_fetched_at


@dataclass(slots=True)
class AppState:
    config: AppConfig
    pipeline: DistributedSearchPipeline
    rerank_context: ShardedRerankContext
    reranker_model: LightGBMReranker
    snippet_index: SnippetIndex
    spell_checker: SpellChecker
    autocomplete_index: AutocompleteIndex
    global_stats: GlobalIndexStats
    last_crawled_at: str | None

    @classmethod
    async def build(cls, config: AppConfig) -> AppState:
        pipeline = await DistributedSearchPipeline.start(
            config.partitioned_shards_dir,
            host=config.shard_host,
            base_port=config.shard_base_port,
            timeout_seconds=config.shard_timeout_seconds,
        )
        return cls(
            config=config,
            pipeline=pipeline,
            rerank_context=ShardedRerankContext.from_partitioned_root(
                config.partitioned_shards_dir
            ),
            reranker_model=LightGBMReranker.load(config.ltr_model_dir),
            snippet_index=SnippetIndex.from_documents_path(config.extractor_documents_path),
            spell_checker=query_parser_pipeline.build_spell_checker(config.global_index_dir),
            autocomplete_index=query_parser_pipeline.build_autocomplete_index(
                config.global_index_dir, config.query_log_path
            ),
            global_stats=GlobalIndexStats.from_index_dir(config.global_index_dir),
            last_crawled_at=latest_fetched_at(config.extractor_documents_path),
        )

    async def close(self) -> None:
        await self.pipeline.close()


def get_app_state(request: Request) -> AppState:
    state: AppState = request.app.state.app_state
    return state
