import json
import os
import pytest


@pytest.fixture
def sample_json(tmp_path):
    data = {
        "exported_at": "2026-04-01T10:00:00Z",
        "total_posts": 3,
        "archived_posts": 1,
        "posts": [
            {
                "id": 1, "title": "Top voted idea", "details": "<p>Details about payroll</p>",
                "status": "planned", "topic": "Ideas: WFM",
                "author": "Alice", "organization": "Acme",
                "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-06-01T00:00:00Z",
                "tags": ["Payroll"], "vote_count": 22, "vote_sum": 22,
                "follower_count": 10, "comment_count": 3,
                "comments": [{"id": 100, "author": "Bob", "organization": "Acme", "body": "Great!", "created_at": "2025-02-01T00:00:00Z"}],
                "html_url": "https://ex.com/1", "is_archived": False,
            },
            {
                "id": 2, "title": "Another payroll idea", "details": "Payroll thing",
                "status": "not_planned", "topic": "Ideas: WFM",
                "author": "Bob", "organization": "Beta Inc",
                "created_at": "2025-03-01T00:00:00Z", "updated_at": "2025-03-01T00:00:00Z",
                "tags": ["Payroll", "HR"], "vote_count": 5, "vote_sum": 5,
                "follower_count": 2, "comment_count": 0,
                "comments": [],
                "html_url": "https://ex.com/2", "is_archived": False,
            },
            {
                "id": 3, "title": "Old archived idea", "details": "Very old",
                "status": "completed", "topic": "Ideas: Inventory",
                "author": "Carol", "organization": "Gamma",
                "created_at": "2020-01-01T00:00:00Z", "updated_at": "2020-01-01T00:00:00Z",
                "tags": ["Inventory"], "vote_count": 1, "vote_sum": 1,
                "follower_count": 0, "comment_count": 0,
                "comments": [],
                "html_url": "https://ex.com/3", "is_archived": True,
            },
        ],
    }
    path = tmp_path / "ideas_latest.json"
    path.write_text(json.dumps(data))
    return str(path)


def test_cache_loads_from_file(sample_json):
    from src.ideas_cache import IdeasCache
    cache = IdeasCache(local_file=sample_json)
    assert cache.total_count == 3
    assert cache.archived_count == 1
    assert cache.exported_at == "2026-04-01T10:00:00Z"


def test_cache_posts_by_id(sample_json):
    from src.ideas_cache import IdeasCache
    cache = IdeasCache(local_file=sample_json)
    post = cache.get_by_id(1)
    assert post is not None
    assert post["title"] == "Top voted idea"
    assert cache.get_by_id(999) is None


def test_cache_list_excludes_archived(sample_json):
    from src.ideas_cache import IdeasCache
    cache = IdeasCache(local_file=sample_json)
    result = cache.list_ideas(include_archived=False)
    assert len(result["posts"]) == 2
    assert result["archived_count"] == 1


def test_cache_list_includes_archived(sample_json):
    from src.ideas_cache import IdeasCache
    cache = IdeasCache(local_file=sample_json)
    result = cache.list_ideas(include_archived=True)
    assert len(result["posts"]) == 3
    assert result["archived_count"] == 0


def test_cache_filter_by_topic(sample_json):
    from src.ideas_cache import IdeasCache
    cache = IdeasCache(local_file=sample_json)
    result = cache.list_ideas(topic="WFM")
    assert len(result["posts"]) == 2


def test_cache_filter_by_tag(sample_json):
    from src.ideas_cache import IdeasCache
    cache = IdeasCache(local_file=sample_json)
    result = cache.list_ideas(tag="HR")
    assert len(result["posts"]) == 1
    assert result["posts"][0]["id"] == 2


def test_cache_filter_by_status(sample_json):
    from src.ideas_cache import IdeasCache
    cache = IdeasCache(local_file=sample_json)
    result = cache.list_ideas(status="planned")
    assert len(result["posts"]) == 1


def test_cache_search(sample_json):
    from src.ideas_cache import IdeasCache
    cache = IdeasCache(local_file=sample_json)
    result = cache.search("payroll")
    assert len(result["posts"]) == 2


def test_cache_search_excludes_archived(sample_json):
    from src.ideas_cache import IdeasCache
    cache = IdeasCache(local_file=sample_json)
    result = cache.search("old", include_archived=False)
    assert len(result["posts"]) == 0
    assert result["archived_count"] == 1


def test_cache_pagination(sample_json):
    from src.ideas_cache import IdeasCache
    cache = IdeasCache(local_file=sample_json)
    result = cache.list_ideas(per_page=1, page=1)
    assert len(result["posts"]) == 1
    assert result["posts"][0]["id"] == 1

    result2 = cache.list_ideas(per_page=1, page=2)
    assert len(result2["posts"]) == 1
    assert result2["posts"][0]["id"] == 2
