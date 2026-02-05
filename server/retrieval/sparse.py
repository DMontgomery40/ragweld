from server.db.postgres import PostgresClient
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import SparseSearchConfig
from server.services.config_store import get_config as load_scoped_config


class SparseRetriever:
    def __init__(self, postgres: PostgresClient):
        self.postgres = postgres

    async def search(
        self,
        repo_id: str,
        query: str,
        config: SparseSearchConfig,
        *,
        ts_config: str | None = None,
    ) -> list[ChunkMatch]:
        import inspect

        if not bool(getattr(config, "enabled", True)):
            return []

        if ts_config is None:
            cfg = await load_scoped_config(repo_id=repo_id)
            ts_config = cfg.indexing.postgres_ts_config

        # Production path: PostgresClient supports engine selection + query mode.
        if isinstance(self.postgres, PostgresClient):
            return await self.postgres.sparse_search_engine(
                repo_id,
                query,
                int(getattr(config, "top_k", 0) or 0),
                ts_config=str(ts_config or "english"),
                engine=str(getattr(config, "engine", "postgres_fts") or "postgres_fts"),
                query_mode=str(getattr(config, "query_mode", "plain") or "plain"),
                highlight=bool(getattr(config, "highlight", False)),
            )

        # Test / mock path: allow older mocks to only implement `sparse_search`.
        legacy = getattr(self.postgres, "sparse_search", None)
        if legacy is not None:
            res = legacy(repo_id, query, int(getattr(config, "top_k", 0) or 0), ts_config=str(ts_config or "english"))
            if inspect.isawaitable(res):
                return await res
            return res

        res = getattr(self.postgres, "sparse_search_engine")(
            repo_id,
            query,
            int(getattr(config, "top_k", 0) or 0),
            ts_config=str(ts_config or "english"),
            engine=str(getattr(config, "engine", "postgres_fts") or "postgres_fts"),
            query_mode=str(getattr(config, "query_mode", "plain") or "plain"),
            highlight=bool(getattr(config, "highlight", False)),
        )
        if inspect.isawaitable(res):
            return await res
        return res
