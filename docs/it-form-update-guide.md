# IT Form Update Guide

Run these commands whenever the "IT Support Request" form is changed in Zendesk.
After running, update `src/constants.py`, `src/tools/tickets.py`, and `docs/it-agent-instructions.md`.

## Credentials setup

```bash
SUBDOMAIN="hotschedules1760632913"   # change to "hotschedules" for prod
EMAIL="your.email@fourth.com"
TOKEN="your_api_token"
AUTH=$(echo -n "$EMAIL/token:$TOKEN" | base64)
FORM_ID="40492655042957"             # change to 40703005823501 for prod
```

## Command 1 — Fetch form structure and conditional rules

```bash
curl -s -H "Authorization: Basic $AUTH" \
  "https://$SUBDOMAIN.zendesk.com/api/v2/ticket_forms/$FORM_ID" | python3 -m json.tool
```

Inspect:
- `ticket_field_ids` — ordered list of all field IDs on the form
- `end_user_conditions` — parent→child visibility rules (the conditional hierarchy)

## Command 2 — Fetch all field IDs, types, and option values

```bash
curl -s -H "Authorization: Basic $AUTH" \
  "https://$SUBDOMAIN.zendesk.com/api/v2/ticket_fields" | python3 -c "
import sys, json
data = json.load(sys.stdin)
fields = {f['id']: f for f in data['ticket_fields']}
# Paste ticket_field_ids from Command 1 output:
form_field_ids = [40492783035149, 44259226554637, 44392062108813]  # replace with full list
for fid in form_field_ids:
    f = fields.get(fid)
    if not f:
        print(f'MISSING: {fid}')
        continue
    opts = [(o['raw_name'], o['value']) for o in f.get('custom_field_options', [])]
    print(f'ID={fid}  type={f[\"type\"]}  title={f[\"raw_title\"]!r}')
    for name, val in opts:
        print(f'  {val!r}  ({name})')
"
```

## Update procedure

1. **Field IDs changed** — update the `"fields"` dict inside `IT_FORM_CONFIG["dev"]` (or `"prod"`) in `src/constants.py`
2. **New dropdown option added** — add `"friendly_key": "zendesk_tag_value"` to the relevant mapping dict in `src/constants.py` (e.g. `IT_INC_SOFTWARE_VALUES`), and add the friendly key to the matching `Literal[...]` in `create_it_ticket` in `src/tools/tickets.py`
3. **Option removed** — remove the entry from the mapping dict and from the `Literal`
4. **New conditional rule added** — add the field to `IT_FORM_CONFIG["fields"]`, create a mapping dict, add a parameter to `create_it_ticket`, and update the validation logic in `_build_it_custom_fields`
5. **Update `docs/it-agent-instructions.md`** — reflect new/removed options in the L2/L3/L4 tables
6. Restart the MCP server: `python -m src.main`

## Prod field IDs (TODO)

When prod access is available:
1. Re-run both commands with `SUBDOMAIN="hotschedules"` and `FORM_ID="40703005823501"`
2. Populate `IT_FORM_CONFIG["prod"]["fields"]` in `src/constants.py` (IDs differ from sandbox)
3. Add prod-specific mapping dicts if any option tag values differ between environments
