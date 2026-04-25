import json
import os
import pytest


@pytest.fixture
def loaded_cache(tmp_path):
    data = {
        "exported_at": "2026-04-01T10:00:00Z",
        "total_posts": 2,
        "archived_posts": 0,
        "posts": [
            {
                "id": 1, "title": "Top idea", "details": "<p>Details about payroll</p>",
                "status": "planned", "topic": "Ideas: WFM",
                "author": "Alice", "organization": "Acme",
                "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-06-01T00:00:00Z",
                "tags": ["Payroll"], "vote_count": 22, "vote_sum": 22,
                "follower_count": 10, "comment_count": 1,
                "comments": [{"id": 100, "author": "Bob", "organization": "Acme", "body": "Great!", "created_at": "2025-02-01T00:00:00Z"}],
                "html_url": "https://ex.com/1", "is_archived": False,
            },
            {
                "id": 2, "title": "Second idea about HR", "details": "HR details",
                "status": "not_planned", "topic": "Ideas: WFM",
                "author": "Bob", "organization": "Beta",
                "created_at": "2025-03-01T00:00:00Z", "updated_at": "2025-03-01T00:00:00Z",
                "tags": ["HR"], "vote_count": 5, "vote_sum": 5,
                "follower_count": 2, "comment_count": 0,
                "comments": [],
                "html_url": "https://ex.com/2", "is_archived": False,
            },
        ],
    }
    path = tmp_path / "ideas_latest.json"
    path.write_text(json.dumps(data))

    from src.ideas_cache import IdeasCache
    import src.tools.community as community_mod
    test_cache = IdeasCache(local_file=str(path))
    community_mod._cache = test_cache
    return test_cache


@pytest.mark.asyncio
async def test_list_ideas(loaded_cache):
    from src.tools.community import list_ideas
    result = json.loads(await list_ideas())
    assert result["total"] == 2
    assert len(result["posts"]) == 2
    assert result["posts"][0]["title"] == "Top idea"


@pytest.mark.asyncio
async def test_get_idea(loaded_cache):
    from src.tools.community import get_idea
    result = json.loads(await get_idea(id=1))
    assert result["title"] == "Top idea"
    assert len(result["comments"]) == 1


@pytest.mark.asyncio
async def test_get_idea_not_found(loaded_cache):
    from src.tools.community import get_idea
    result = json.loads(await get_idea(id=999))
    assert "error" in result


@pytest.mark.asyncio
async def test_search_ideas(loaded_cache):
    from src.tools.community import search_ideas
    result = json.loads(await search_ideas(query="payroll"))
    assert result["total"] == 1
    assert result["posts"][0]["id"] == 1


@pytest.mark.asyncio
async def test_ideas_analytics(loaded_cache):
    from src.tools.community import ideas_analytics
    result = json.loads(await ideas_analytics())
    assert result["total_posts"] == 2
    assert "top_ideas" in result
    assert len(result["top_ideas"]) == 2
