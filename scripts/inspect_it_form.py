#!/usr/bin/env python3
"""Inspect the IT Support Request Zendesk form for dev or prod.

Usage:
    python scripts/inspect_it_form.py [dev|prod]
    python scripts/inspect_it_form.py [dev|prod] <form_id>

Field IDs are fetched dynamically from the form — nothing is hardcoded.
Reads ZENDESK_EMAIL and ZENDESK_API_TOKEN from .env (or environment).
Outputs form structure then field option values for every field on the form.
"""

from __future__ import annotations

import base64
import os
import sys

import dotenv
import httpx

dotenv.load_dotenv()

_SUBDOMAINS: dict[str, str] = {
    "dev": "hotschedules1760632913",
    "prod": "hotschedules",
}

_DEFAULT_FORM_IDS: dict[str, int] = {
    "dev": 40492655042957,
    "prod": 45108529620365,
}


def main() -> None:
    """
    Main entry point for inspecting the IT Support Request Zendesk form.

    - Parses command-line arguments to select environment (dev or prod) and optionally a form_id.
    - Retrieves Zendesk authentication information from environment or .env file.
    - Connects to the Zendesk API to print form structure and print field option values.
    - Requires ZENDESK_EMAIL and ZENDESK_API_TOKEN to be set in environment or .env.
    """
    env = sys.argv[1] if len(sys.argv) > 1 else "dev"
    if env not in _SUBDOMAINS:
        print("Usage: python scripts/inspect_it_form.py [dev|prod] [form_id]", file=sys.stderr)
        sys.exit(1)

    form_id = int(sys.argv[2]) if len(sys.argv) > 2 else _DEFAULT_FORM_IDS[env]

    email = os.environ.get("ZENDESK_EMAIL", "")
    token = os.environ.get("ZENDESK_API_TOKEN", "")
    if not email or not token:
        print(
            "Error: ZENDESK_EMAIL and ZENDESK_API_TOKEN must be set in .env",
            file=sys.stderr,
        )
        sys.exit(1)

    auth = base64.b64encode(f"{email}/token:{token}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    base_url = f"https://{_SUBDOMAINS[env]}.zendesk.com/api/v2"

    with httpx.Client(timeout=30.0) as client:
        field_ids = _print_form_structure(client, headers, base_url, form_id, env)
        print()
        _print_field_options(client, headers, base_url, field_ids, env)

def _print_form_structure(
    client: httpx.Client,
    headers: dict,
    base_url: str,
    form_id: int,
    env: str,
) -> list[int]:
    """Print form structure and return the list of field IDs on the form."""
    print(f"{'='*60}")
    print(f"  Form structure  [{env}]  form_id={form_id}")
    print(f"{'='*60}")
    resp = client.get(f"{base_url}/ticket_forms/{form_id}", headers=headers)
    resp.raise_for_status()
    form = resp.json()["ticket_form"]
    field_ids: list[int] = form["ticket_field_ids"]
    print(f"Name:    {form['raw_name']}")
    print(f"ID:      {form['id']}")
    print(f"Active:  {form['active']}")
    print(f"Fields:  {len(field_ids)}")
    print(f"Rules:   {len(form['end_user_conditions'])} end-user conditions")
    print()
    print("Conditional rules (parent value → child field):")
    for rule in form["end_user_conditions"]:
        parent = rule["parent_field_id"]
        val = rule["value"]
        children = [c["id"] for c in rule["child_fields"]]
        print(f"  {parent}  {val!r}")
        for c in children:
            print(f"    → {c}")
    return field_ids


def _print_field_options(
    client: httpx.Client,
    headers: dict,
    base_url: str,
    field_ids: list[int],
    env: str,
) -> None:
    print(f"{'='*60}")
    print(f"  Field option values  [{env}]")
    print(f"{'='*60}")
    resp = client.get(f"{base_url}/ticket_fields", headers=headers)
    resp.raise_for_status()
    all_fields = {f["id"]: f for f in resp.json()["ticket_fields"]}

    for fid in field_ids:
        f = all_fields.get(fid)
        if not f:
            print(f"\nMISSING: {fid}")
            continue
        opts = [(o["raw_name"], o["value"]) for o in f.get("custom_field_options", [])]
        print(f"\nID={fid}  type={f['type']}  title={f['raw_title']!r}")
        if opts:
            for name, val in opts:
                print(f"  {val!r}  ({name})")
        else:
            print("  (no options — free-text or system field)")


if __name__ == "__main__":
    main()
