"""Tests for AUDIT-016: free-text tool args have Pydantic length caps.

The caps prevent a caller from submitting arbitrarily large payloads
(e.g. 100 MB subject) that we'd then have to hold in memory before
Zendesk rejects them. FastMCP enforces these annotations at tool-call
time via the JSON-schema layer, raising before any tool code runs.
"""

from __future__ import annotations

from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from src.tools.help_center import create_article, update_article
from src.tools.search import search
from src.tools.tickets import create_it_ticket, create_ticket, update_ticket


def _adapter_for(func, param_name: str) -> TypeAdapter:
    """Build a Pydantic TypeAdapter for a single parameter's annotation.

    Uses get_type_hints(include_extras=True) so the Annotated[...] metadata
    (specifically Field(max_length=...)) survives — without include_extras,
    Annotated unwraps to the bare base type and the constraint is lost.
    Required because the source files use `from __future__ import annotations`
    which makes raw signature annotations strings.
    """
    hints = get_type_hints(func, include_extras=True)
    return TypeAdapter(hints[param_name])


# ---- create_it_ticket (the live IT write tool) ----


def test_create_it_ticket_subject_capped_at_200():
    adapter = _adapter_for(create_it_ticket, "subject")
    adapter.validate_python("a" * 200)
    with pytest.raises(ValidationError):
        adapter.validate_python("a" * 201)


def test_create_it_ticket_description_capped_at_10000():
    adapter = _adapter_for(create_it_ticket, "description")
    adapter.validate_python("a" * 10_000)
    with pytest.raises(ValidationError):
        adapter.validate_python("a" * 10_001)


def test_create_it_ticket_additional_location_info_capped_at_5000():
    adapter = _adapter_for(create_it_ticket, "additional_location_info")
    # None is valid (optional field)
    adapter.validate_python(None)
    adapter.validate_python("a" * 5_000)
    with pytest.raises(ValidationError):
        adapter.validate_python("a" * 5_001)


# ---- create_ticket (deprecated but still gated) ----


def test_create_ticket_subject_capped_at_200():
    adapter = _adapter_for(create_ticket, "subject")
    adapter.validate_python("a" * 200)
    with pytest.raises(ValidationError):
        adapter.validate_python("a" * 201)


def test_create_ticket_comment_capped_at_10000():
    adapter = _adapter_for(create_ticket, "comment")
    adapter.validate_python("a" * 10_000)
    with pytest.raises(ValidationError):
        adapter.validate_python("a" * 10_001)


# ---- update_ticket ----


def test_update_ticket_subject_capped_at_200():
    adapter = _adapter_for(update_ticket, "subject")
    adapter.validate_python(None)
    adapter.validate_python("a" * 200)
    with pytest.raises(ValidationError):
        adapter.validate_python("a" * 201)


def test_update_ticket_comment_capped_at_10000():
    adapter = _adapter_for(update_ticket, "comment")
    adapter.validate_python(None)
    adapter.validate_python("a" * 10_000)
    with pytest.raises(ValidationError):
        adapter.validate_python("a" * 10_001)


# ---- create_article / update_article ----


def test_create_article_title_capped_at_200():
    adapter = _adapter_for(create_article, "title")
    adapter.validate_python("a" * 200)
    with pytest.raises(ValidationError):
        adapter.validate_python("a" * 201)


def test_create_article_body_capped_at_50000():
    adapter = _adapter_for(create_article, "body")
    adapter.validate_python("a" * 50_000)
    with pytest.raises(ValidationError):
        adapter.validate_python("a" * 50_001)


def test_update_article_title_capped_at_200():
    adapter = _adapter_for(update_article, "title")
    adapter.validate_python(None)
    adapter.validate_python("a" * 200)
    with pytest.raises(ValidationError):
        adapter.validate_python("a" * 201)


def test_update_article_body_capped_at_50000():
    adapter = _adapter_for(update_article, "body")
    adapter.validate_python(None)
    adapter.validate_python("a" * 50_000)
    with pytest.raises(ValidationError):
        adapter.validate_python("a" * 50_001)


# ---- search ----


def test_search_query_capped_at_500():
    adapter = _adapter_for(search, "query")
    adapter.validate_python("a" * 500)
    with pytest.raises(ValidationError):
        adapter.validate_python("a" * 501)


# ---- Sanity: caps don't reject realistic inputs ----


@pytest.mark.parametrize("tool,param,sample", [
    (create_it_ticket, "subject", "Cannot log in to LightSpeed POS"),
    (create_it_ticket, "description", "Steps to reproduce:\n1. Open the app\n2. Tap login\n3. Get spinner forever\n\nExpected: dashboard loads."),
    (create_it_ticket, "additional_location_info", "Corner desk by the south window, Denver office."),
    (create_article, "title", "How to reset your HotSchedules password"),
    (search, "query", "tickets about LightSpeed POS login from last 7 days"),
])
def test_realistic_inputs_pass_validation(tool, param, sample):
    """Sanity: caps don't break normal usage."""
    adapter = _adapter_for(tool, param)
    result = adapter.validate_python(sample)
    assert result == sample
