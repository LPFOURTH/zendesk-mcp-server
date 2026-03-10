from __future__ import annotations

import base64
import os
import re
import time
from urllib.parse import urlparse

import httpx

from .request_context import (
    authorization_var,
    zendesk_base_url_var,
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
    except Exception:
        raise ValueError(
            f"Invalid {label}. Must be a valid https://<subdomain>.zendesk.com URL."
        )

    if parsed.scheme != "https":
        raise ValueError(f"Invalid {label}. Only https URLs are allowed.")

    hostname = parsed.hostname or ""
    if not hostname.endswith(ZENDESK_HOST_SUFFIX):
        raise ValueError(
            f"Invalid {label}. Host must end with {ZENDESK_HOST_SUFFIX}."
        )

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


class RateLimiter:
    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self.timestamps: list[float] = []

    def acquire(self) -> None:
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
    def __init__(self) -> None:
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
            import sys

            print(
                "[zendesk-client] Credentials not found. Set ZENDESK_SUBDOMAIN or "
                "ZENDESK_BASE_URL, plus ZENDESK_EMAIL and ZENDESK_API_TOKEN.",
                file=sys.stderr,
            )

        rate_limit = int(os.environ.get("ZENDESK_RATE_LIMIT", "200"))
        self._rate_limiter = RateLimiter(rate_limit)
        self._http = httpx.AsyncClient(timeout=30.0)

    def _get_target(self) -> dict:
        return resolve_zendesk_target(
            zendesk_subdomain=zendesk_subdomain_var.get(None),
            zendesk_base_url=zendesk_base_url_var.get(None),
            default_subdomain=self._subdomain or None,
            default_base_url=self._origin or None,
        )

    def get_origin(self) -> str:
        target = self._get_target()
        if not target["origin"]:
            raise RuntimeError(
                "Zendesk target not configured. Provide X-Zendesk-Subdomain or "
                "X-Zendesk-Base-Url, or set ZENDESK_SUBDOMAIN/ZENDESK_BASE_URL."
            )
        return target["origin"]

    def get_subdomain(self) -> str | None:
        return self._get_target()["subdomain"]

    def get_base_url(self) -> str:
        return f"{self.get_origin()}/api/v2"

    def get_agent_ticket_url(self, ticket_id: int) -> str:
        return f"{self.get_origin()}/agent/tickets/{ticket_id}"

    def get_help_center_article_url(self, article_id: int) -> str:
        return f"{self.get_origin()}/hc/articles/{article_id}"

    def _get_auth_header(self) -> str:
        per_request = authorization_var.get(None)
        if per_request:
            return per_request
        creds = f"{self._email}/token:{self._api_token}"
        encoded = base64.b64encode(creds.encode()).decode()
        return f"Basic {encoded}"

    async def request(
        self,
        method: str,
        endpoint: str,
        *,
        data: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        per_request_auth = authorization_var.get(None)
        target = self._get_target()

        if (
            not per_request_auth
            and (not self._subdomain or not self._email or not self._api_token)
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
            except Exception:
                body = {"error": exc.response.text}
            import sys

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
        except httpx.TimeoutException:
            raise RuntimeError("Zendesk API request timed out after 30s")
        except httpx.RequestError as exc:
            raise RuntimeError(f"Zendesk connection error: {exc}") from exc

    # -- Tickets --
    async def list_tickets(self, params: dict | None = None) -> dict:
        return await self.request("GET", "/tickets.json", params=params)

    async def get_ticket(self, ticket_id: int) -> dict:
        return await self.request("GET", f"/tickets/{ticket_id}.json")

    async def create_ticket(self, data: dict) -> dict:
        return await self.request("POST", "/tickets.json", data={"ticket": data})

    async def update_ticket(self, ticket_id: int, data: dict) -> dict:
        return await self.request(
            "PUT", f"/tickets/{ticket_id}.json", data={"ticket": data}
        )

    # -- Help Center --
    async def list_articles(self, params: dict | None = None) -> dict:
        return await self.request(
            "GET", "/help_center/articles.json", params=params
        )

    async def get_article(self, article_id: int) -> dict:
        return await self.request("GET", f"/help_center/articles/{article_id}.json")

    async def search_articles(
        self, query: str, params: dict | None = None
    ) -> dict:
        p = dict(params) if params else {}
        p["query"] = query
        return await self.request(
            "GET", "/help_center/articles/search.json", params=p
        )

    async def create_article(self, data: dict, section_id: int) -> dict:
        return await self.request(
            "POST",
            f"/help_center/sections/{section_id}/articles.json",
            data={"article": data},
        )

    async def update_article(self, article_id: int, data: dict) -> dict:
        translation_fields = {"title", "body", "locale"}
        metadata_fields = {"draft", "permission_group_id", "user_segment_id", "label_names"}

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
        p = dict(params) if params else {}
        p["query"] = query
        return await self.request("GET", "/search.json", params=p)


zendesk_client = ZendeskClient()
