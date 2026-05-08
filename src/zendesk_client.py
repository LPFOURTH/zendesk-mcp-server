"""Zendesk HTTP client with per-request auth, target resolution, and rate limiting."""

from __future__ import annotations

import base64
import os
import re
import sys
import time
from typing import cast
from urllib.parse import urlparse

import httpx

from .constants import ENVIRONMENTS
from .request_context import (
    authorization_var,
    zendesk_base_url_var,
    zendesk_environment_var,
    zendesk_subdomain_var,
)

SUBDOMAIN_REGEX = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", re.IGNORECASE)
ZENDESK_HOST_SUFFIX = ".zendesk.com"


def _validate_subdomain(subdomain: str, label: str = "Zendesk subdomain") -> None:
    if not SUBDOMAIN_REGEX.match(subdomain):
        raise ValueError(
            f"Invalid {label} format. Must be alphanumeric with optional hyphens."
        )


def _normalize_origin_from_subdomain(
    subdomain: str, label: str = "Zendesk subdomain"
) -> str:
    _validate_subdomain(subdomain, label)
    return f"https://{subdomain}.zendesk.com"


def _normalize_origin_from_base_url(
    base_url: str, label: str = "Zendesk base URL"
) -> str:
    try:
        parsed = urlparse(base_url)
    except Exception as exc:
        raise ValueError(
            f"Invalid {label}. Must be a valid https://<subdomain>.zendesk.com URL."
        ) from exc

    if parsed.scheme != "https":
        raise ValueError(f"Invalid {label}. Only https URLs are allowed.")

    hostname = parsed.hostname or ""
    if not hostname.endswith(ZENDESK_HOST_SUFFIX):
        raise ValueError(f"Invalid {label}. Host must end with {ZENDESK_HOST_SUFFIX}.")

    subdomain = hostname[: -len(ZENDESK_HOST_SUFFIX)]
    _validate_subdomain(subdomain, label)

    return f"https://{hostname}"


def resolve_zendesk_target(
    *,
    zendesk_subdomain: str | None = None,
    zendesk_base_url: str | None = None,
    default_subdomain: str | None = None,
    default_base_url: str | None = None,
) -> dict:
    """Resolve and validate a Zendesk origin + subdomain from various input sources."""
    if zendesk_subdomain and zendesk_base_url:
        origin_from_sub = _normalize_origin_from_subdomain(
            zendesk_subdomain, "Zendesk subdomain"
        )
        origin_from_url = _normalize_origin_from_base_url(
            zendesk_base_url, "Zendesk base URL"
        )
        if origin_from_sub != origin_from_url:
            raise ValueError(
                "Zendesk subdomain and base URL point to different accounts."
            )
        return {"origin": origin_from_url, "subdomain": zendesk_subdomain}

    if zendesk_base_url:
        origin = _normalize_origin_from_base_url(zendesk_base_url, "Zendesk base URL")
        hostname = urlparse(origin).hostname or ""
        subdomain = hostname[: -len(ZENDESK_HOST_SUFFIX)]
        return {"origin": origin, "subdomain": subdomain}

    if zendesk_subdomain:
        return {
            "origin": _normalize_origin_from_subdomain(
                zendesk_subdomain, "Zendesk subdomain"
            ),
            "subdomain": zendesk_subdomain,
        }

    if default_base_url or default_subdomain:
        return resolve_zendesk_target(
            zendesk_subdomain=default_subdomain,
            zendesk_base_url=default_base_url,
        )

    return {"origin": None, "subdomain": None}


class RateLimiter:  # pylint: disable=too-few-public-methods
    """Sliding-window rate limiter that enforces a max requests-per-minute cap."""

    def __init__(self, max_per_minute: int) -> None:
        """Initialise with the maximum number of requests allowed per minute."""
        self.max_per_minute = max_per_minute
        self.timestamps: list[float] = []

    def acquire(self) -> None:
        """Raise RuntimeError if the rate limit is exceeded, otherwise record the call."""
        now = time.time()
        self.timestamps = [t for t in self.timestamps if now - t < 60]
        if len(self.timestamps) >= self.max_per_minute:
            wait_s = 60 - (now - self.timestamps[0])
            raise RuntimeError(
                f"Rate limit reached ({self.max_per_minute}/min). "
                f"Retry after {int(wait_s + 1)}s."
            )
        self.timestamps.append(now)


class ZendeskClient:
    """Async Zendesk API client with per-request auth and target resolution."""

    def __init__(self) -> None:
        """Initialise the client from environment variables."""
        self._subdomain = os.environ.get("ZENDESK_SUBDOMAIN", "")
        self._base_url_env = os.environ.get("ZENDESK_BASE_URL", "")
        self._email = os.environ.get("ZENDESK_EMAIL", "")
        self._api_token = os.environ.get("ZENDESK_API_TOKEN", "")

        default_target = resolve_zendesk_target(
            zendesk_subdomain=self._subdomain or None,
            zendesk_base_url=self._base_url_env or None,
        )
        self._subdomain = default_target["subdomain"] or ""
        self._origin = default_target["origin"] or ""

        if not self._subdomain or not self._email or not self._api_token:
            print(
                "[zendesk-client] Credentials not found. Set ZENDESK_SUBDOMAIN or "
                "ZENDESK_BASE_URL, plus ZENDESK_EMAIL and ZENDESK_API_TOKEN.",
                file=sys.stderr,
            )

        rate_limit = int(os.environ.get("ZENDESK_RATE_LIMIT", "200"))
        self._rate_limiter = RateLimiter(rate_limit)
        self._http = httpx.AsyncClient(timeout=30.0)

    def _get_target(self) -> dict:
        """Resolve the active Zendesk target from contextvars, env vars, or environment config."""
        # If environment is set (e.g. via /mcp/dev or /mcp/prod path),
        # use the environment's base_url as the default target.
        env_name = zendesk_environment_var.get(None)
        env_base_url = None
        if env_name and env_name in ENVIRONMENTS:
            env_base_url = cast("str | None", ENVIRONMENTS[env_name].get("base_url"))

        return resolve_zendesk_target(
            zendesk_subdomain=zendesk_subdomain_var.get(None),
            zendesk_base_url=zendesk_base_url_var.get(None),
            default_subdomain=self._subdomain if not env_base_url else None,
            default_base_url=env_base_url or self._origin or None,
        )

    def get_origin(self) -> str:
        """Return the base origin URL (e.g. https://acme.zendesk.com) for the active target."""
        target = self._get_target()
        if not target["origin"]:
            raise RuntimeError(
                "Zendesk target not configured. Provide X-Zendesk-Subdomain or "
                "X-Zendesk-Base-Url, or set ZENDESK_SUBDOMAIN/ZENDESK_BASE_URL."
            )
        return target["origin"]

    def get_subdomain(self) -> str | None:
        """Return the Zendesk subdomain for the active target."""
        return self._get_target()["subdomain"]

    def get_base_url(self) -> str:
        """Return the Zendesk REST API v2 base URL."""
        return f"{self.get_origin()}/api/v2"

    def get_agent_ticket_url(self, ticket_id: int) -> str:
        """Return the agent-facing URL for a ticket."""
        return f"{self.get_origin()}/agent/tickets/{ticket_id}"

    def get_help_center_article_url(self, article_id: int) -> str:
        """Return the Help Center public URL for an article."""
        return f"{self.get_origin()}/hc/articles/{article_id}"

    def _get_auth_header(self) -> str:
        """Return the Authorization header value for the current request."""
        per_request = authorization_var.get(None)
        if per_request:
            return per_request
        creds = f"{self._email}/token:{self._api_token}"
        encoded = base64.b64encode(creds.encode()).decode()
        return f"Basic {encoded}"

    async def request(  # pylint: disable=too-many-locals
        self,
        method: str,
        endpoint: str,
        *,
        data: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        """Execute an authenticated HTTP request against the Zendesk API."""
        per_request_auth = authorization_var.get(None)
        target = self._get_target()

        if not per_request_auth and (
            not self._subdomain or not self._email or not self._api_token
        ):
            raise RuntimeError(
                "Zendesk credentials not configured. Provide Authorization header "
                "or set environment variables."
            )

        if not target["origin"]:
            raise RuntimeError(
                "Zendesk target not configured. Provide X-Zendesk-Subdomain or "
                "X-Zendesk-Base-Url, or set ZENDESK_SUBDOMAIN/ZENDESK_BASE_URL."
            )

        self._rate_limiter.acquire()

        url = f"{self.get_base_url()}{endpoint}"
        headers: dict[str, str] = {"Authorization": self._get_auth_header()}
        if data is not None:
            headers["Content-Type"] = "application/json"

        try:
            response = await self._http.request(
                method,
                url,
                headers=headers,
                params=params,
                json=data,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            try:
                body = exc.response.json()
            except ValueError:
                body = {"error": exc.response.text}
            print(
                f"[zendesk-client] API error: {status} on {method} {endpoint} - "
                f"body: {body}",
                file=sys.stderr,
            )
            error_type = body.get("error", "Request failed")
            description = body.get("description", "")
            details = body.get("details")
            detail_msg = f" Details: {details}" if details else ""
            raise RuntimeError(
                f"Zendesk API Error: {status} - {error_type}. {description}{detail_msg}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError("Zendesk API request timed out after 30s") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Zendesk connection error: {exc}") from exc

    # -- Tickets --
    async def list_tickets(self, params: dict | None = None) -> dict:
        """List tickets, optionally filtered by query params."""
        return await self.request("GET", "/tickets.json", params=params)

    async def get_ticket(self, ticket_id: int) -> dict:
        """Fetch a single ticket by ID."""
        return await self.request("GET", f"/tickets/{ticket_id}.json")

    async def create_ticket(self, data: dict) -> dict:
        """Create a new ticket."""
        return await self.request("POST", "/tickets.json", data={"ticket": data})

    async def update_ticket(self, ticket_id: int, data: dict) -> dict:
        """Update an existing ticket by ID."""
        return await self.request(
            "PUT", f"/tickets/{ticket_id}.json", data={"ticket": data}
        )

    async def upload_file(
        self, content: bytes, filename: str, content_type: str
    ) -> str:
        """Upload a file attachment and return the upload token (valid for 60 minutes).

        The token is then included in comment.uploads when creating a ticket.
        """
        url = f"{self.get_base_url()}/uploads.json"
        params = {"filename": filename}
        headers = {
            "Authorization": self._get_auth_header(),
            "Content-Type": content_type,
        }

        self._rate_limiter.acquire()

        try:
            response = await self._http.request(
                "POST",
                url,
                params=params,
                content=content,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            try:
                body = exc.response.json()
            except ValueError:
                body = {"error": exc.response.text}
            print(
                f"[zendesk-client] API error: {status} on POST /uploads.json - "
                f"body: {body}",
                file=sys.stderr,
            )
            error_type = body.get("error", "Upload failed")
            description = body.get("description", "")
            raise RuntimeError(
                f"Zendesk API Error: {status} - {error_type}. {description}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError("Zendesk upload request timed out after 30s") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Zendesk connection error: {exc}") from exc

        return data["upload"]["token"]

    # -- Help Center --
    async def list_articles(self, params: dict | None = None) -> dict:
        """List Help Center articles, optionally filtered by query params."""
        return await self.request("GET", "/help_center/articles.json", params=params)

    async def get_article(self, article_id: int) -> dict:
        """Fetch a single Help Center article by ID."""
        return await self.request("GET", f"/help_center/articles/{article_id}.json")

    async def search_articles(self, query: str, params: dict | None = None) -> dict:
        """Search Help Center articles by query string."""
        p = dict(params) if params else {}
        p["query"] = query
        return await self.request("GET", "/help_center/articles/search.json", params=p)

    async def create_article(self, data: dict, section_id: int) -> dict:
        """Create a new Help Center article in the given section."""
        return await self.request(
            "POST",
            f"/help_center/sections/{section_id}/articles.json",
            data={"article": data},
        )

    async def update_article(self, article_id: int, data: dict) -> dict:
        """Update a Help Center article, routing translation vs metadata fields automatically."""
        translation_fields = {"title", "body", "locale"}
        metadata_fields = {
            "draft",
            "permission_group_id",
            "user_segment_id",
            "label_names",
        }

        translation_data = {k: v for k, v in data.items() if k in translation_fields}
        meta_data = {k: v for k, v in data.items() if k in metadata_fields}

        result = None
        if translation_data:
            locale = data.get("locale", "en-us")
            result = await self.request(
                "PUT",
                f"/help_center/articles/{article_id}/translations/{locale}.json",
                data={"translation": translation_data},
            )
        if meta_data:
            result = await self.request(
                "PUT",
                f"/help_center/articles/{article_id}.json",
                data={"article": meta_data},
            )
        if not translation_data and not meta_data:
            result = await self.request(
                "PUT",
                f"/help_center/articles/{article_id}.json",
                data={"article": data},
            )
        return result  # type: ignore[return-value]

    # -- Search --
    async def search(self, query: str, params: dict | None = None) -> dict:
        """Run a unified Zendesk search across tickets and/or articles."""
        p = dict(params) if params else {}
        p["query"] = query
        return await self.request("GET", "/search.json", params=p)


zendesk_client = ZendeskClient()
