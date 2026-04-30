"""In-memory cache for pre-computed Community Ideas data."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import datetime, time as dtime, timedelta, timezone
from html import unescape


def _strip_html(text: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", text))


def _make_blob_client(account: str, container: str, name: str):
    """Indirection so tests can monkeypatch this."""
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobClient

    credential = DefaultAzureCredential()
    return BlobClient(
        account_url=f"https://{account}.blob.core.windows.net",
        container_name=container,
        blob_name=name,
        credential=credential,
    )


class IdeasCache:
    def __init__(
        self,
        local_file: str | None = None,
        blob_account: str | None = None,
        blob_container: str | None = None,
        blob_name: str | None = None,
    ):
        self.posts: list[dict] = []
        self.posts_by_id: dict[int, dict] = {}
        self.exported_at: str = ""
        self.total_count: int = 0
        self.archived_count: int = 0
        self._loaded = False

        self._blob_account = blob_account or os.environ.get("IDEAS_BLOB_ACCOUNT")
        self._blob_container = blob_container or os.environ.get("IDEAS_BLOB_CONTAINER")
        self._blob_name = blob_name or os.environ.get("IDEAS_BLOB_NAME", "ideas_latest.json")
        self._blob_etag: str | None = None
        self._lock = threading.Lock()
        self._reload_thread: threading.Thread | None = None

        file_path = local_file or os.environ.get("IDEAS_CACHE_FILE")

        if self._blob_configured():
            ok = self._try_load_from_blob()
            if not ok and file_path:
                self._load_from_file(file_path)
        elif file_path:
            self._load_from_file(file_path)

    def _blob_configured(self) -> bool:
        return bool(self._blob_account and self._blob_container and self._blob_name)

    def _try_load_from_blob(self) -> bool:
        try:
            client = _make_blob_client(self._blob_account, self._blob_container, self._blob_name)
            data_bytes = client.download_blob().readall()
            data = json.loads(data_bytes)
            etag = client.get_blob_properties().etag
            with self._lock:
                self._ingest(data)
                self._blob_etag = etag
            print(
                f"[ideas-cache] Loaded {self.total_count} posts from blob "
                f"{self._blob_account}/{self._blob_container}/{self._blob_name} (etag={etag})",
                file=sys.stderr,
            )
            return True
        except Exception as exc:
            print(
                f"[ideas-cache] Blob load failed ({type(exc).__name__}: {exc}); "
                f"will use fallback if available",
                file=sys.stderr,
            )
            return False

    def _load_from_file(self, path: str) -> None:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self._ingest(data)
            print(f"[ideas-cache] Loaded {self.total_count} posts from {path}", file=sys.stderr)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[ideas-cache] Failed to load {path}: {exc}", file=sys.stderr)

    def _ingest(self, data: dict) -> None:
        self.exported_at = data.get("exported_at", "")
        self.total_count = data.get("total_posts", 0)
        self.archived_count = data.get("archived_posts", 0)
        self.posts = data.get("posts", [])
        self.posts_by_id = {p["id"]: p for p in self.posts}
        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def get_by_id(self, post_id: int, include_archived: bool = False) -> dict | None:
        post = self.posts_by_id.get(post_id)
        if post is None:
            return None
        if post.get("is_archived") and not include_archived:
            return None
        return post

    def list_ideas(
        self,
        topic: str | None = None,
        tag: str | None = None,
        status: str | None = None,
        sort_by: str = "votes",
        sort_order: str = "desc",
        page: int = 1,
        per_page: int = 25,
        include_archived: bool = False,
    ) -> dict:
        filtered = list(self.posts)
        archived_excluded = 0

        if not include_archived:
            active = []
            for p in filtered:
                if p.get("is_archived"):
                    archived_excluded += 1
                else:
                    active.append(p)
            filtered = active

        if topic:
            topic_lower = topic.lower()
            filtered = [p for p in filtered if topic_lower in p.get("topic", "").lower()]

        if tag:
            tag_lower = tag.lower()
            filtered = [p for p in filtered if any(t.lower() == tag_lower for t in p.get("tags", []))]

        if status:
            status_lower = status.lower()
            filtered = [p for p in filtered if (p.get("status") or "").lower() == status_lower]

        if not include_archived and (topic or tag or status):
            archived_matching = [p for p in self.posts if p.get("is_archived")]
            if topic:
                archived_matching = [p for p in archived_matching if topic_lower in p.get("topic", "").lower()]
            if tag:
                archived_matching = [p for p in archived_matching if any(t.lower() == tag_lower for t in p.get("tags", []))]
            if status:
                archived_matching = [p for p in archived_matching if (p.get("status") or "").lower() == status_lower]
            archived_excluded = len(archived_matching)

        sort_keys = {
            "votes": lambda p: p.get("vote_count", 0),
            "date": lambda p: p.get("created_at", ""),
            "updated": lambda p: p.get("updated_at", ""),
        }
        key_fn = sort_keys.get(sort_by, sort_keys["votes"])
        reverse = sort_order.lower() != "asc"
        filtered.sort(key=key_fn, reverse=reverse)

        total = len(filtered)
        start = (page - 1) * per_page
        end = start + per_page
        page_posts = filtered[start:end]

        return {
            "posts": page_posts,
            "total": total,
            "page": page,
            "per_page": per_page,
            "archived_count": archived_excluded,
        }

    def search(
        self,
        query: str,
        topic: str | None = None,
        tag: str | None = None,
        status: str | None = None,
        page: int = 1,
        per_page: int = 25,
        include_archived: bool = False,
    ) -> dict:
        query_lower = query.lower()
        matches = []
        archived_excluded = 0

        for p in self.posts:
            searchable = f"{p.get('title', '')} {_strip_html(p.get('details', ''))} {' '.join(p.get('tags', []))}".lower()
            if query_lower not in searchable:
                continue
            if p.get("is_archived") and not include_archived:
                archived_excluded += 1
                continue
            matches.append(p)

        if topic:
            topic_lower = topic.lower()
            matches = [p for p in matches if topic_lower in p.get("topic", "").lower()]
        if tag:
            tag_lower = tag.lower()
            matches = [p for p in matches if any(t.lower() == tag_lower for t in p.get("tags", []))]
        if status:
            status_lower = status.lower()
            matches = [p for p in matches if (p.get("status") or "").lower() == status_lower]

        matches.sort(key=lambda p: p.get("vote_count", 0), reverse=True)

        total = len(matches)
        start = (page - 1) * per_page
        end = start + per_page

        return {
            "posts": matches[start:end],
            "total": total,
            "page": page,
            "per_page": per_page,
            "archived_count": archived_excluded,
        }

    def analytics(
        self,
        group_by: str | None = None,
        top_n: int = 10,
        include_archived: bool = False,
    ) -> dict:
        posts = self.posts if include_archived else [p for p in self.posts if not p.get("is_archived")]

        if group_by == "topic":
            groups = {}
            for p in posts:
                t = p.get("topic", "n/a")
                groups.setdefault(t, []).append(p)
            return {
                "group_by": "topic",
                "groups": [
                    {"name": name, "count": len(items), "total_votes": sum(p.get("vote_count", 0) for p in items), "top_idea": max(items, key=lambda p: p.get("vote_count", 0))["title"]}
                    for name, items in sorted(groups.items(), key=lambda kv: -len(kv[1]))
                ],
            }

        if group_by == "tag":
            groups = {}
            for p in posts:
                for tg in p.get("tags", []) or ["n/a"]:
                    groups.setdefault(tg, []).append(p)
            return {
                "group_by": "tag",
                "groups": [
                    {"name": name, "count": len(items), "total_votes": sum(p.get("vote_count", 0) for p in items)}
                    for name, items in sorted(groups.items(), key=lambda kv: -len(kv[1]))
                ],
            }

        if group_by == "status":
            groups = {}
            for p in posts:
                s = p.get("status") or "none"
                groups.setdefault(s, []).append(p)
            return {
                "group_by": "status",
                "groups": [
                    {"name": name, "count": len(items), "example": items[0]["title"] if items else ""}
                    for name, items in sorted(groups.items(), key=lambda kv: -len(kv[1]))
                ],
            }

        sorted_by_votes = sorted(posts, key=lambda p: p.get("vote_count", 0), reverse=True)
        status_dist = {}
        for p in posts:
            s = p.get("status") or "none"
            status_dist[s] = status_dist.get(s, 0) + 1

        return {
            "total_posts": len(posts),
            "total_archived": self.archived_count,
            "data_freshness": self.exported_at,
            "status_distribution": status_dist,
            "top_ideas": [
                {"title": p["title"], "votes": p["vote_count"], "status": p["status"], "topic": p["topic"]}
                for p in sorted_by_votes[:top_n]
            ],
        }


ideas_cache = IdeasCache()
