import json
from pathlib import Path
from typing import Iterable

from elasticsearch import AsyncElasticsearch


class ElasticsearchLoader:
    def __init__(self, elasticsearch_url: str, index_name: str, schema_path: str) -> None:
        self.client = AsyncElasticsearch(elasticsearch_url)
        self.index_name = index_name
        self.schema_path = schema_path

    async def ensure_index(self) -> None:
        if await self.client.indices.exists(index=self.index_name):
            return
        schema = json.loads(Path(self.schema_path).read_text(encoding="utf-8"))
        await self.client.indices.create(index=self.index_name, **schema)

    async def load_batch(self, docs: Iterable[dict]) -> None:
        actions = []
        for doc in docs:
            actions.append({"index": {"_index": self.index_name, "_id": doc["id"]}})
            actions.append(doc)
        if not actions:
            return
        await self.client.bulk(operations=actions, refresh=True)

    async def close(self) -> None:
        await self.client.close()
