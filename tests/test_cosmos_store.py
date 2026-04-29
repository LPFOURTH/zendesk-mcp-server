from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from key_value.aio._utils.compound import compound_key
from key_value.aio._utils.managed_entry import ManagedEntry

# Will fail at import time until Task 6 creates the module.
from src.storage.cosmos_store import CosmosKeyValueStore, _doc_id


@pytest.fixture
def mock_container():
    """Stand-in for azure.cosmos.aio.ContainerProxy. SDK methods are awaitable."""
    container = MagicMock()
    container.read_item = AsyncMock()
    container.upsert_item = AsyncMock()
    container.delete_item = AsyncMock()
    return container


@pytest_asyncio.fixture
async def store(mock_container):
    s = CosmosKeyValueStore(
        endpoint="https://fake.documents.azure.com:443/",
        database="mcp_test",
        container="oauth_state_test",
    )
    # Skip real CosmosClient setup; inject mock container directly.
    s._container_override = mock_container  # type: ignore[attr-defined]
    yield s
    await s.close()


@pytest.fixture
def unique_key():
    return f"test-{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Direct tests of the 3 BaseStore abstract methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_managed_entry_returns_none_on_404(
    store, mock_container, unique_key
):
    from azure.cosmos.exceptions import CosmosResourceNotFoundError

    mock_container.read_item.side_effect = CosmosResourceNotFoundError(
        message="Not found", status_code=404
    )

    result = await store._get_managed_entry(key=unique_key, collection="client_storage")

    assert result is None
    expected_id = _doc_id(collection="client_storage", key=unique_key)
    mock_container.read_item.assert_awaited_once_with(
        item=expected_id, partition_key=expected_id
    )


@pytest.mark.asyncio
async def test_get_managed_entry_deserializes_entry_json(
    store, mock_container, unique_key
):
    # Round-trip through the same serializer the adapter uses
    from key_value.aio._utils.serialization import BasicSerializationAdapter

    original = ManagedEntry(value={"foo": "bar", "n": 42})
    serialized = BasicSerializationAdapter(
        date_format="isoformat", value_format="dict"
    ).dump_json(entry=original, key=unique_key, collection="client_storage")

    mock_container.read_item.return_value = {
        "id": _doc_id(collection="client_storage", key=unique_key),
        "pk": _doc_id(collection="client_storage", key=unique_key),
        "collection": "client_storage",
        "key": unique_key,
        "entry_json": serialized,
    }

    result = await store._get_managed_entry(key=unique_key, collection="client_storage")

    assert result is not None
    assert result.value == {"foo": "bar", "n": 42}


@pytest.mark.asyncio
async def test_get_managed_entry_returns_none_for_missing_entry_json(
    store, mock_container, unique_key
):
    mock_container.read_item.return_value = {
        "id": _doc_id(collection="client_storage", key=unique_key),
        "pk": _doc_id(collection="client_storage", key=unique_key),
        "collection": "client_storage",
        "key": unique_key,
        # entry_json missing — should be treated as no entry
    }

    result = await store._get_managed_entry(key=unique_key, collection="client_storage")

    assert result is None


@pytest.mark.asyncio
async def test_put_managed_entry_writes_correct_doc(
    store, mock_container, unique_key
):
    entry = ManagedEntry(value={"hello": "world"})

    await store._put_managed_entry(
        key=unique_key, collection="client_storage", managed_entry=entry
    )

    mock_container.upsert_item.assert_awaited_once()
    doc = mock_container.upsert_item.call_args.args[0]
    expected_id = _doc_id(collection="client_storage", key=unique_key)
    assert doc["id"] == expected_id
    assert doc["pk"] == expected_id
    assert doc["collection"] == "client_storage"
    assert doc["key"] == unique_key
    assert isinstance(doc["entry_json"], str)
    assert "hello" in doc["entry_json"]
    # No TTL on the entry → no ttl field on the doc
    assert "ttl" not in doc


@pytest.mark.asyncio
async def test_put_managed_entry_with_ttl_sets_cosmos_ttl_field(
    store, mock_container, unique_key
):
    entry = ManagedEntry.from_ttl(value={"k": "v"}, ttl=300)

    await store._put_managed_entry(
        key=unique_key, collection="transaction_storage", managed_entry=entry
    )

    doc = mock_container.upsert_item.call_args.args[0]
    assert "ttl" in doc
    assert isinstance(doc["ttl"], int)
    # Should be roughly 300 (within a few seconds of clock skew)
    assert 290 <= doc["ttl"] <= 301


@pytest.mark.asyncio
async def test_put_managed_entry_clamps_ttl_to_minimum_1(
    store, mock_container, unique_key
):
    # Tiny TTL gets clamped to 1 (Cosmos min meaningful TTL)
    entry = ManagedEntry.from_ttl(value={"k": "v"}, ttl=0.1)

    await store._put_managed_entry(
        key=unique_key, collection="transaction_storage", managed_entry=entry
    )

    doc = mock_container.upsert_item.call_args.args[0]
    assert doc["ttl"] == 1


@pytest.mark.asyncio
async def test_delete_managed_entry_returns_true_on_success(
    store, mock_container, unique_key
):
    result = await store._delete_managed_entry(
        key=unique_key, collection="client_storage"
    )

    assert result is True
    expected_id = _doc_id(collection="client_storage", key=unique_key)
    mock_container.delete_item.assert_awaited_once_with(
        item=expected_id, partition_key=expected_id
    )


@pytest.mark.asyncio
async def test_delete_managed_entry_returns_false_on_404(
    store, mock_container, unique_key
):
    from azure.cosmos.exceptions import CosmosResourceNotFoundError

    mock_container.delete_item.side_effect = CosmosResourceNotFoundError(
        message="Not found", status_code=404
    )

    result = await store._delete_managed_entry(
        key=unique_key, collection="client_storage"
    )

    assert result is False


@pytest.mark.asyncio
async def test_delete_managed_entry_re_raises_non_404_errors(
    store, mock_container, unique_key
):
    from azure.cosmos.exceptions import CosmosHttpResponseError

    mock_container.delete_item.side_effect = CosmosHttpResponseError(
        message="Server error", status_code=500
    )

    with pytest.raises(CosmosHttpResponseError):
        await store._delete_managed_entry(key=unique_key, collection="client_storage")


# ---------------------------------------------------------------------------
# Public-API tests (verify BaseStore plumbing flows through our adapter)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_put_then_get_round_trip(store, mock_container, unique_key):
    """Use BaseStore's public put/get; verify the value survives the round trip
    through our adapter's serialization."""
    payload = {"token": "secret", "count": 7}

    captured_doc: dict = {}

    async def capture(doc):
        captured_doc.clear()
        captured_doc.update(doc)

    async def read(**_):
        return dict(captured_doc)

    mock_container.upsert_item.side_effect = capture
    mock_container.read_item.side_effect = read

    await store.put(key=unique_key, value=payload, collection="client_storage")
    result = await store.get(key=unique_key, collection="client_storage")

    assert result == payload


@pytest.mark.asyncio
async def test_public_delete_returns_true_on_success(
    store, mock_container, unique_key
):
    result = await store.delete(key=unique_key, collection="client_storage")
    assert result is True
