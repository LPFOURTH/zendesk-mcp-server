"""Unit tests for Architecture F attribution helpers and email→user_id resolver.

Stdlib + unittest.mock only. Run:
    python tests/test_attribution_and_resolver.py
"""
from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.attribution import (  # noqa: E402
    apply_article_attribution,
    apply_ticket_attribution,
    get_current_entra_email,
)
from src.zendesk_user_resolver import ZendeskUserResolver  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class TicketAttributionTests(unittest.TestCase):
    def test_sets_requester_when_missing(self):
        payload = {"subject": "x"}
        apply_ticket_attribution(payload, 42)
        self.assertEqual(payload["requester_id"], 42)

    def test_does_not_override_explicit_requester(self):
        payload = {"subject": "x", "requester_id": 999}
        apply_ticket_attribution(payload, 42)
        self.assertEqual(payload["requester_id"], 999)

    def test_sets_comment_author_when_comment_present(self):
        payload = {"subject": "x", "comment": {"body": "hi"}}
        apply_ticket_attribution(payload, 42)
        self.assertEqual(payload["comment"]["author_id"], 42)

    def test_does_not_override_explicit_comment_author(self):
        payload = {"subject": "x", "comment": {"body": "hi", "author_id": 7}}
        apply_ticket_attribution(payload, 42)
        self.assertEqual(payload["comment"]["author_id"], 7)

    def test_no_comment_no_author_field_added(self):
        payload = {"subject": "x"}
        apply_ticket_attribution(payload, 42)
        self.assertNotIn("comment", payload)

    def test_user_id_zero_is_noop(self):
        payload = {"subject": "x", "comment": {"body": "hi"}}
        apply_ticket_attribution(payload, 0)
        self.assertNotIn("requester_id", payload)
        self.assertNotIn("author_id", payload["comment"])

    def test_disable_requester_flag(self):
        payload = {"subject": "x", "comment": {"body": "hi"}}
        apply_ticket_attribution(payload, 42, set_requester=False)
        self.assertNotIn("requester_id", payload)
        self.assertEqual(payload["comment"]["author_id"], 42)

    def test_disable_comment_author_flag(self):
        payload = {"subject": "x", "comment": {"body": "hi"}}
        apply_ticket_attribution(payload, 42, set_comment_author=False)
        self.assertEqual(payload["requester_id"], 42)
        self.assertNotIn("author_id", payload["comment"])


class ArticleAttributionTests(unittest.TestCase):
    def test_sets_author_when_missing(self):
        p = {"title": "x", "body": "y"}
        apply_article_attribution(p, 42)
        self.assertEqual(p["author_id"], 42)

    def test_does_not_override_explicit_author(self):
        p = {"title": "x", "author_id": 99}
        apply_article_attribution(p, 42)
        self.assertEqual(p["author_id"], 99)

    def test_zero_is_noop(self):
        p = {"title": "x"}
        apply_article_attribution(p, 0)
        self.assertNotIn("author_id", p)


class ResolverTests(unittest.TestCase):
    def test_resolves_email_to_user_id(self):
        search = AsyncMock(return_value={"users": [{"id": 42, "email": "a@x.com"}]})
        r = ZendeskUserResolver(search)
        uid = run(r.resolve("a@x.com"))
        self.assertEqual(uid, 42)
        search.assert_awaited_once()

    def test_returns_none_for_no_match(self):
        search = AsyncMock(return_value={"users": []})
        r = ZendeskUserResolver(search)
        self.assertIsNone(run(r.resolve("ghost@x.com")))

    def test_caches_positive_hit(self):
        search = AsyncMock(return_value={"users": [{"id": 7, "email": "a@x.com"}]})
        r = ZendeskUserResolver(search, cache_ttl_seconds=300)
        run(r.resolve("a@x.com"))
        run(r.resolve("a@x.com"))
        run(r.resolve("A@X.com"))  # case-insensitive cache key
        self.assertEqual(search.await_count, 1)

    def test_caches_negative_hit_short_ttl(self):
        search = AsyncMock(return_value={"users": []})
        r = ZendeskUserResolver(search, cache_ttl_seconds=300)
        run(r.resolve("ghost@x.com"))
        run(r.resolve("ghost@x.com"))
        # Cached None still hit — only one upstream call
        self.assertEqual(search.await_count, 1)

    def test_swallows_search_exception_and_caches_negative(self):
        search = AsyncMock(side_effect=RuntimeError("zendesk down"))
        r = ZendeskUserResolver(search, cache_ttl_seconds=300)
        self.assertIsNone(run(r.resolve("a@x.com")))
        self.assertIsNone(run(r.resolve("a@x.com")))
        # Cached the exception path
        self.assertEqual(search.await_count, 1)

    def test_empty_email_returns_none_without_search(self):
        search = AsyncMock()
        r = ZendeskUserResolver(search)
        self.assertIsNone(run(r.resolve("")))
        self.assertIsNone(run(r.resolve(None)))
        search.assert_not_awaited()

    def test_picks_user_with_exactly_matching_email(self):
        """Zendesk search can return broader matches; prefer the exact one."""
        search = AsyncMock(return_value={"users": [
            {"id": 1, "email": "almost-a@x.com"},
            {"id": 2, "email": "a@x.com"},
            {"id": 3, "email": "a@x.com.fake"},
        ]})
        r = ZendeskUserResolver(search)
        uid = run(r.resolve("a@x.com"))
        self.assertEqual(uid, 2)

    def test_expired_cache_triggers_refresh(self):
        search = AsyncMock(return_value={"users": [{"id": 9, "email": "a@x.com"}]})
        r = ZendeskUserResolver(search, cache_ttl_seconds=1)
        run(r.resolve("a@x.com"))
        # Force expiry
        r._cache["a@x.com"] = (9, time.time() - 1)
        run(r.resolve("a@x.com"))
        self.assertEqual(search.await_count, 2)


class EntraEmailExtractionTests(unittest.TestCase):
    def test_returns_none_outside_oauth_context(self):
        # No FastMCP context active — must not raise
        self.assertIsNone(get_current_entra_email())

    def test_extracts_preferred_username_first(self):
        from src import attribution
        original = attribution.get_current_entra_email

        # Patch the FastMCP get_access_token to return a faked token
        fake_token = MagicMock()
        fake_token.claims = {
            "preferred_username": "lukasz.pelcner@fourth.com",
            "upn": "ignored@fourth.com",
            "email": "also_ignored@fourth.com",
        }

        import fastmcp.server.dependencies as deps
        orig_get = deps.get_access_token
        deps.get_access_token = lambda: fake_token
        try:
            self.assertEqual(original(), "lukasz.pelcner@fourth.com")
        finally:
            deps.get_access_token = orig_get

    def test_falls_through_to_upn(self):
        import fastmcp.server.dependencies as deps
        from src import attribution

        fake_token = MagicMock()
        fake_token.claims = {"upn": "u@x.com"}
        orig = deps.get_access_token
        deps.get_access_token = lambda: fake_token
        try:
            self.assertEqual(attribution.get_current_entra_email(), "u@x.com")
        finally:
            deps.get_access_token = orig

    def test_ignores_non_email_strings(self):
        import fastmcp.server.dependencies as deps
        from src import attribution

        fake_token = MagicMock()
        fake_token.claims = {"preferred_username": "no-at-sign", "email": "real@x.com"}
        orig = deps.get_access_token
        deps.get_access_token = lambda: fake_token
        try:
            self.assertEqual(attribution.get_current_entra_email(), "real@x.com")
        finally:
            deps.get_access_token = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
