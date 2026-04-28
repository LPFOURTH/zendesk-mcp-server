from __future__ import annotations

import asyncio
import logging
from typing import Any

from typing_extensions import override

from azure.cosmos.aio import CosmosClient
from azure.cosmos.exceptions import (
    CosmosResourceNotFoundError,
)
from azure.identity.aio import DefaultAzureCredential

from key_value.aio._utils.compound import compound_key
from key_value.aio._utils.managed_entry import ManagedEntry
from key_value.aio._utils.serialization import (
    BasicSerializationAdapter,
    SerializationAdapter,
)
from key_value.aio.errors import DeserializationError
from key_value.aio.stores.base import BaseStore

logger = logging.getLogger(__name__)


class CosmosKeyValueStore(BaseStore):
    """Async key-value store backed by Azure Cosmos DB.

    Subclass of `key_value.aio.stores.base.BaseStore`. Uses the same pattern
    as the library's `RedisStore`: serializes `ManagedEntry` to JSON, stores
    one document per (collection, key), uses a compound key as both Cosmos
    `id` and partition key (`pk`).
    """

    _client: CosmosClient | None
    _credential: DefaultAzureCredential | None
    _adapter: SerializationAdapter

    def __init__(
        self,
        *,
        endpoint: str,
        database: str,
        container: str,
        default_collection: str | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._database_name = database
        self._container_name = container
        self._client = None
        self._credential = None
        self._client_lock = asyncio.Lock()

        self._adapter = BasicSerializationAdapter(
            date_format="isoformat", value_format="dict"
        )

        super().__init__(default_collection=default_collection, stable_api=False)

    async def _get_container(self):
        if getattr(self, "_container_override", None) is not None:
            return self._container_override

        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._credential = DefaultAzureCredential()
                    self._client = CosmosClient(
                        url=self._endpoint, credential=self._credential
                    )

        db = self._client.get_database_client(self._database_name)
        return db.get_container_client(self._container_name)

    @override
    async def _get_managed_entry(
        self, *, key: str, collection: str
    ) -> ManagedEntry | None:
        doc_id = compound_key(collection=collection, key=key)
        try:
            container = await self._get_container()
            item = await container.read_item(item=doc_id, partition_key=doc_id)
        except CosmosResourceNotFoundError:
            return None

        json_str = item.get("entry_json")
        if not isinstance(json_str, str):
            return None

        try:
            return self._adapter.load_json(json_str=json_str)
        except DeserializationError:
            logger.warning(
                "CosmosKeyValueStore: failed to deserialize entry id=%s", doc_id
            )
            return None

    @override
    async def _put_managed_entry(
        self, *, key: str, collection: str, managed_entry: ManagedEntry
    ) -> None:
        doc_id = compound_key(collection=collection, key=key)
        json_str: str = self._adapter.dump_json(
            entry=managed_entry, key=key, collection=collection
        )

        doc: dict[str, Any] = {
            "id": doc_id,
            "pk": doc_id,
            "collection": collection,
            "key": key,
            "entry_json": json_str,
        }

        if managed_entry.ttl is not None:
            doc["ttl"] = max(int(managed_entry.ttl), 1)

        container = await self._get_container()
        await container.upsert_item(doc)

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        doc_id = compound_key(collection=collection, key=key)
        try:
            container = await self._get_container()
            await container.delete_item(item=doc_id, partition_key=doc_id)
            return True
        except CosmosResourceNotFoundError:
            return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
        if self._credential is not None:
            await self._credential.close()
            self._credential = None
