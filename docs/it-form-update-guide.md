# IT Form Update Guide

Run this whenever the "IT Support Request" form is changed in Zendesk.
After running, update `src/constants.py`, `src/tools/tickets.py`, `docs/it-agent-instructions-dev.md`, and `docs/it-agent-instructions-prod.md`.

## Inspect the form

Reads `ZENDESK_EMAIL` and `ZENDESK_API_TOKEN` from `.env` automatically.

```bash
# Dev/Sandbox
python scripts/inspect_it_form.py dev

# Prod
python scripts/inspect_it_form.py prod
```

Output:
1. **Form structure** — field IDs and all conditional rules (parent value → child field)
2. **Field option values** — for each field: type, title, and all dropdown options with their Zendesk tag values

## Update procedure

1. **Field IDs changed** — update the `"field_ids"` list in `scripts/inspect_it_form.py`
   for the affected environment, then update the `"fields"` dict in `IT_FORM_CONFIG` in `src/constants.py`

2. **New dropdown option added** — add `"friendly_key": "zendesk_tag_value"` to the relevant
   mapping dict in `src/constants.py` (e.g. `IT_INC_SOFTWARE_VALUES`), and add the friendly key
   to the matching `Literal[...]` in `create_it_ticket` in `src/tools/tickets.py`

3. **Option removed** — remove the entry from the mapping dict and from the `Literal`

4. **New conditional rule added** — add the field to `IT_FORM_CONFIG["fields"]` and to the
   `field_ids` list in the script, create a mapping dict, add a parameter to `create_it_ticket`,
   and update the validation logic in `_build_it_custom_fields`

5. **Update `docs/it-agent-instructions-dev.md` and `docs/it-agent-instructions-prod.md`** — reflect new/removed options in the L2/L3/L4 tables

6. Restart the MCP server to test the changes
