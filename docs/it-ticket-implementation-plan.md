# IT Ticket Tool — Implementation Plan

**Date:** 2026-05-05  
**Branch:** feat/create-it-ticket-tool

---

## Context

The production Zendesk IT Support Request form was completely overhauled (new form ID: **45108529620365**, replacing the old 40703005823501). The new form introduces:

- A 4-level cascading hierarchy that now **mirrors dev** (L2 categories are `eit_general`, `eit_software`, `eit_hardware`, `eit_security_ops`, `bizapps` — replacing the old flat prod taxonomy)
- 6 new custom ticket fields, 48 new automation triggers, 23 conditional visibility rules
- New incident-side EIT General sub-classification (5 new L4 fields for network / access mgmt / email collab / facilities / VM)
- New SR-side EIT General with L4 fields (same structure as dev but different field IDs and tag values)
- New SR-Hardware and SR-Security-Ops fields on prod (didn't exist before)

This plan also adds CC support and file attachment support to `create_it_ticket`, updates agent instructions, and creates a test plan document.

---

## Critical Pre-Implementation Step

**Run the inspect script against the new prod form to get all actual tag values:**

```bash
python scripts/inspect_it_form.py prod 45108529620365
```

This outputs all field IDs and their dropdown tag values. The PDF provides field IDs and option display names, but tag values (the strings sent to the Zendesk API) must come from this script output. The plan below flags which tag values are **confirmed from PDF** vs **TBD from inspect script**.

---

## Flags from PDF — Important Logic Notes

Before implementing, note these constraints from the migration documentation:

1. **Hidden fields (Classification-IT `360035556692`, Sub-Classification-IT `360035557932`)** are set automatically by Zendesk triggers — do NOT include them in the MCP tool's `custom_fields` payload. They get populated server-side after ticket creation.

2. **SR-Software "Other" tag changed**: old `other_cl_ser_req` → new `cl_ser_req_sw_other`. Must update `IT_PROD_SR_SOFTWARE_VALUES`.

3. **SR-Software "BACS" rename**: `gemalto_bacs` key (tag `cl_ser_req_gemalto_bacs_payment_services`) → prod now uses `bacs_payment_services` key with tag `cl_ser_req_bacs_payment_services`. Needs prod-specific override in `IT_PROD_SR_SOFTWARE_VALUES`.

4. **Incident EIT General is a completely new path** on prod: the old prod had `network`, `email_collaboration`, etc. as direct L2 incident categories. These are now L4 fields under `inc_eit_general`. The old prod-specific handling in `_build_it_custom_fields` must be removed.

5. **Tag values for the new classification and L2 category fields** (field IDs 45106525447821, 45106525487885, 45106568824205) differ from both old prod and dev — must confirm from inspect script output.

---

## Files to Modify

| File | Changes |
|---|---|
| `src/constants.py` | New prod field IDs, new/updated tag value maps |
| `src/tools/tickets.py` | New prod taxonomy, CC param, attachments param, updated validation |
| `src/zendesk_client.py` | New `upload_file` method for attachment pre-upload |
| `docs/it-agent-instructions-prod.md` | Full rewrite for new taxonomy + CC + attachments |
| `docs/it-agent-instructions-dev.md` | Add CC and attachments instructions |
| `docs/it-form-update-guide.md` | Fix stale reference to deleted `it-agent-instructions.md` |
| `docs/it-ticket-test-plan.md` | New file — test cases for AI agent to execute |

---

## 1. `src/constants.py`

### 1a. Update `IT_FORM_CONFIG["prod"]`

Replace the entire `"prod"` dict:

```python
"prod": {
    "form_id": 45108529620365,          # was 40703005823501
    "fields": {
        # L1
        "classification":          45106525447821,   # was 40703094758925
        # L2
        "sr_category":             45106525487885,   # was 40703176643085
        "inc_category":            45106568824205,   # was 40703287981325
        # L3 — Service Request paths
        "sr_software":             40703442821517,   # same
        "sr_bizapps":              45106525699981,   # was 40703484948365
        "sr_hardware":             45106525737613,   # NEW (didn't exist in old prod)
        "sr_security_ops":         45106558339981,   # NEW
        "eit_general_sr":          45106484057869,   # NEW (SR EIT General parent)
        # L4 — SR EIT General sub-fields (same structure as dev, different IDs)
        "access_request_type":     45106538379277,   # was dev-only 44391620839309
        "distribution_list_action":45106587149837,   # was dev-only 44391738257165
        "fourth_office_type":      45106484253197,   # was dev-only 44391606775949
        "email_trace_type":        45106558500109,   # was dev-only 44391610412301
        "restore_data_type":       45106538522125,   # was dev-only 44391716119693
        "vm_type":                 45106538556813,   # was dev-only 44391748764941 (SR VM)
        # L3 — Incident paths
        "inc_software":            40703497886605,   # same
        "inc_hardware":            40703415945869,   # same
        "inc_bizapps":             40703501864845,   # same
        "inc_security":            40703481085709,   # same
        "inc_eit_general":         45491116221837,   # NEW incident EIT General parent
        # L4 — Incident EIT General sub-fields (all NEW)
        "inc_eit_network":         45491169854733,
        "inc_eit_access_mgmt":     45491149674765,
        "inc_eit_email_collab":    45491127022349,
        "inc_eit_facilities":      45491136489741,
        "inc_eit_vm":              45491101913485,
        # Always-present
        "impact":                  40684744263693,   # same
        "location":                42604163385485,   # same
        "additional_location_info":45106484442893,   # was 42604239999629
    },
}
```

**Remove** the old prod-only fields: `inc_email_collaboration`, `inc_network`, `inc_access_management`, `inc_facilities` — they no longer exist in the new form.

### 1b. Update `IT_PROD_CLASSIFICATION_VALUES`

Field 45106525447821 uses new tag values — populate from inspect script output.  
_Likely format: `_incident_-_...` style matching dev, but must verify._

### 1c. Update `IT_PROD_INC_CATEGORY_VALUES`

Field 45106568824205 now uses `eit_*` style L2 categories matching dev. Populate from inspect script:
- Keys: `bizapps`, `eit_software`, `eit_hardware`, `eit_general`, `eit_security_ops`
- Tag values: TBD from inspect script

### 1d. Update `IT_PROD_SR_CATEGORY_VALUES`

Field 45106525487885 now uses `eit_*` style L2 categories. Populate from inspect script:
- Keys: `bizapps`, `eit_software`, `eit_hardware`, `eit_general`, `eit_security_ops`

### 1e. Update `IT_PROD_SR_SOFTWARE_VALUES`

Patch the "other" and BACS entries vs the dev base:
```python
IT_PROD_SR_SOFTWARE_VALUES = {
    **IT_SR_SOFTWARE_VALUES,
    "other": "cl_ser_req_sw_other",          # overrides dev's "other_cl_ser_req"
    "bacs_payment_services": "cl_ser_req_bacs_payment_services",  # renamed from gemalto_bacs
    "power_bi": "cl_ser_req_power_bi",
    "powerbi_desktop": "cl_ser_req_powerbi_desktop_app",
    "zoom": "cl_ser_req_zoom",
}
# Remove gemalto_bacs key if inherited from IT_SR_SOFTWARE_VALUES
```

### 1f. Add new prod-specific value maps (tag values from inspect script)

```python
IT_PROD_INC_EIT_GENERAL_VALUES = {
    "network":              "inc_eit_gen_network",            # confirmed from PDF
    "access_management":    "inc_eit_gen_access_management",  # confirmed from PDF
    "email_collaboration":  "inc_eit_gen_email_collab",       # confirmed from PDF
    "facilities":           "inc_eit_gen_facilities",          # confirmed from PDF
    "virtual_machine":      "inc_eit_gen_virtual_machine",    # confirmed from PDF
}

IT_PROD_INC_EIT_NETWORK_VALUES = {  # field 45491169854733, 5 options — TBD from inspect
    "wifi":              "...",
    "vpn":               "...",
    "network_drives":    "...",
    "internet":          "...",
    "dns_dhcp":          "...",
}

IT_PROD_INC_EIT_ACCESS_MGMT_VALUES = {  # field 45491149674765, 4 options — TBD
    "password_reset":       "...",
    "mfa":                  "...",
    "permissions":          "...",
    "account_provisioning": "...",
}

IT_PROD_INC_EIT_EMAIL_COLLAB_VALUES = {  # field 45491127022349, 6 options — TBD
    "outlook":              "...",
    "teams":                "...",
    "sharepoint_onedrive":  "...",
    "calendar":             "...",
    "distribution_lists":   "...",
    "email_delivery":       "...",
}

IT_PROD_INC_EIT_FACILITIES_VALUES = {  # field 45491136489741, 7 options — TBD
    "printer_scanner":      "...",
    "desk_phone_voip":      "...",
    "monitor_display":      "...",
    "docking_station":      "...",
    "conference_room":      "...",
    "badge_access":         "...",
    "power_electrical":     "...",
}

IT_PROD_INC_EIT_VM_VALUES = {  # field 45491101913485, 3 options — TBD
    "vm_performance":   "...",
    "vm_access":        "...",
    "vm_configuration": "...",
}

IT_PROD_SR_SECURITY_OPS_VALUES = {  # field 45106558339981, 6 options — TBD
    # Lucidchart suggests: unblock_website, unblock_email, unblock_software, audit, other
    # 6th option TBD from inspect script
}

IT_PROD_SR_HARDWARE_VALUES = {  # field 45106525737613, 11 options — TBD from inspect
    # Lucidchart: cable, desktop, docking_station, external_screen, keyboard,
    # laptop, mouse, printer, other — inspect will confirm the full 11 + tags
}
```

Also verify via inspect that `IT_EIT_GENERAL_VALUES` (dev tag values like `eit_access_request_3`) are reusable for the new prod `eit_general_sr` field (45106484057869), or whether prod uses different tags.

---

## 2. `src/tools/tickets.py`

### 2a. New/modified parameters for `create_it_ticket`

**Add:**
```python
# Prod new — incident EIT General sub-path (L3 under eit_general incident)
inc_eit_general_subcategory: Literal[
    "network", "access_management", "email_collaboration", "facilities", "virtual_machine"
] | None = None,

# Prod new — incident VM (L4 under inc_eit_general = virtual_machine)
incident_vm_item: Literal["vm_performance", "vm_access", "vm_configuration"] | None = None,

# CC support
cc_emails: list[str] | None = None,

# File attachments
attachments: list[dict] | None = None,
# Each dict: {"filename": str, "content_type": str, "content_base64": str}
# OR:         {"filename": str, "content_type": str, "url": str}
```

**Update `incident_network_item` options** (prod adds `network_drives` and `dns_dhcp`):
```python
incident_network_item: Literal[
    "internet", "vpn", "wifi", "slow_connection",
    # new prod options:
    "network_drives", "dns_dhcp"
] | None = None,
```

**Update `incident_access_mgmt_item` options** (prod adds `permissions`, `account_provisioning`):
```python
incident_access_mgmt_item: Literal[
    "account_lockout", "mfa", "password_reset",
    # new prod options:
    "permissions", "account_provisioning"
] | None = None,
```

**Update `incident_email_collab_item` options** (prod adds `sharepoint_onedrive`, `calendar`, `distribution_lists`, `email_delivery`):
```python
incident_email_collab_item: Literal[
    "confluence", "outlook", "sharepoint", "slack", "teams",
    # new prod options:
    "sharepoint_onedrive", "calendar", "distribution_lists", "email_delivery"
] | None = None,
```

**Update `incident_facilities_item` options** (prod uses a completely new set):
```python
incident_facilities_item: Literal[
    # old prod (keep for dev compatibility)
    "door_access", "meeting_rooms", "display_tvs", "printer", "video_conferencing",
    # new prod options:
    "printer_scanner", "desk_phone_voip", "monitor_display", "docking_station",
    "conference_room", "badge_access", "power_electrical"
] | None = None,
```

**Add SR Security Ops item** (new prod L3 field):
```python
sr_security_ops_item: Literal[
    "unblock_website", "unblock_email", "unblock_software", "audit", "other"
    # 6th option TBD from inspect
] | None = None,
```

**Add SR Hardware item** (new prod L3 field, same options as dev SR hardware):
```python
# sr_hardware_item already exists — no change needed to Literal values
```

### 2b. Update `_build_it_custom_fields`

**Remove** old prod-only handling for flat incident L2 fields:
```python
# DELETE these blocks:
if incident_email_collab_item and "inc_email_collaboration" in fids: ...
if incident_network_item and "inc_network" in fids: ...
if incident_access_mgmt_item and "inc_access_management" in fids: ...
if incident_facilities_item and "inc_facilities" in fids: ...
```

**Add** new prod-specific handling that mirrors the dev EIT General pattern but for `inc_eit_general`:
```python
# New prod incident EIT General (field exists if "inc_eit_general" in fids)
if "inc_eit_general" in fids:
    if inc_eit_general_subcategory:
        add("inc_eit_general", IT_PROD_INC_EIT_GENERAL_VALUES[inc_eit_general_subcategory])
    if incident_network_item and inc_eit_general_subcategory == "network":
        add("inc_eit_network", IT_PROD_INC_EIT_NETWORK_VALUES[incident_network_item])
    if incident_access_mgmt_item and inc_eit_general_subcategory == "access_management":
        add("inc_eit_access_mgmt", IT_PROD_INC_EIT_ACCESS_MGMT_VALUES[incident_access_mgmt_item])
    if incident_email_collab_item and inc_eit_general_subcategory == "email_collaboration":
        add("inc_eit_email_collab", IT_PROD_INC_EIT_EMAIL_COLLAB_VALUES[incident_email_collab_item])
    if incident_facilities_item and inc_eit_general_subcategory == "facilities":
        add("inc_eit_facilities", IT_PROD_INC_EIT_FACILITIES_VALUES[incident_facilities_item])
    if incident_vm_item and inc_eit_general_subcategory == "virtual_machine":
        add("inc_eit_vm", IT_PROD_INC_EIT_VM_VALUES[incident_vm_item])

# New prod SR-side fields
if sr_security_ops_item and "sr_security_ops" in fids:
    add("sr_security_ops", IT_PROD_SR_SECURITY_OPS_VALUES[sr_security_ops_item])
if sr_hardware_item and "sr_hardware" in fids:
    add("sr_hardware", IT_PROD_SR_HARDWARE_VALUES[sr_hardware_item])  # prod-specific map
```

For the `eit_general_sr` block on prod: if inspect confirms the tag values match dev's `IT_EIT_GENERAL_VALUES`, reuse it:
```python
# EIT General on SR side — dev uses "eit_general" field, prod uses "eit_general_sr" field
eit_gen_fid = "eit_general" if "eit_general" in fids else "eit_general_sr" if "eit_general_sr" in fids else None
if eit_gen_fid and eit_general_subcategory:
    add(eit_gen_fid, IT_EIT_GENERAL_VALUES[eit_general_subcategory])  # if tags match dev
    # ... same L4 handling as before
```

### 2c. Updated validation

Add validation for new prod parameters:
```python
# inc_eit_general_subcategory only valid when prod + incident_category = eit_general
if inc_eit_general_subcategory and incident_category != "eit_general":
    raise ValueError("inc_eit_general_subcategory requires incident_category='eit_general'")

# incident_vm_item requires inc_eit_general_subcategory = virtual_machine  
if incident_vm_item and inc_eit_general_subcategory != "virtual_machine":
    raise ValueError("incident_vm_item requires inc_eit_general_subcategory='virtual_machine'")

# L4 incident fields require the corresponding inc_eit_general_subcategory
if incident_network_item and inc_eit_general_subcategory is None:
    # check if prod (inc_eit_general in fids) — if so, require inc_eit_general_subcategory
    if "inc_eit_general" in fids:
        raise ValueError("incident_network_item requires inc_eit_general_subcategory='network' on prod")
```

### 2d. CC support — add to `ticket_data` assembly

```python
if cc_emails:
    ticket_data["email_ccs"] = [
        {"user_email": email, "action": "put"} for email in cc_emails
    ]
```

### 2e. Attachment support

Before assembling `ticket_data`, upload attachments and collect tokens:

```python
upload_tokens: list[str] = []
if attachments:
    for att in attachments:
        filename = att["filename"]
        content_type = att.get("content_type", "application/octet-stream")
        if "content_base64" in att:
            file_bytes = base64.b64decode(att["content_base64"])
        elif "url" in att:
            file_bytes = await _fetch_url(att["url"])  # new helper using httpx
        else:
            raise ValueError(f"Attachment '{filename}' must have 'content_base64' or 'url'")
        token = await zendesk_client.upload_file(file_bytes, filename, content_type)
        upload_tokens.append(token)

# Then in ticket_data:
ticket_data["comment"] = {"body": description}
if upload_tokens:
    ticket_data["comment"]["uploads"] = upload_tokens
```

> **Copilot Studio note**: Copilot Studio passes file content as base64 via its `contentBytes` output. The MCP tool should accept `content_base64` as a string parameter in each attachment dict. The exact mechanism Copilot Studio uses to pass this through the Power Platform custom connector to the MCP tool needs to be validated — if it cannot pass complex dict parameters, a simpler `attachment_base64: str | None` + `attachment_filename: str | None` flat parameter approach may be needed as a fallback.

---

## 3. `src/zendesk_client.py`

Add `upload_file` method:

```python
async def upload_file(self, content: bytes, filename: str, content_type: str) -> str:
    """Upload a file attachment and return the upload token (60-min TTL)."""
    target = self._get_target()
    auth = await self._get_auth_header()
    url = f"{target}/api/v2/uploads.json"
    params = {"filename": filename}
    headers = {**auth, "Content-Type": content_type}
    async with self._client.stream(
        "POST", url, params=params, content=content, headers=headers
    ) as resp:
        resp.raise_for_status()
        data = resp.json()
    return data["upload"]["token"]
```

Also add a helper (can be module-level in `tickets.py`):
```python
async def _fetch_url(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content
```

---

## 4. `docs/it-agent-instructions-prod.md` — Full Rewrite

The prod instructions need to be rewritten to reflect the new taxonomy:

- `incident_category`: `bizapps | eit_software | eit_hardware | eit_general | eit_security_ops` (replacing old flat values)
- `sr_category`: `bizapps | eit_software | eit_hardware | eit_general | eit_security_ops` (replacing flat list)
- `inc_eit_general_subcategory` (new): `network | access_management | email_collaboration | facilities | virtual_machine`
- All L4 tables updated

Add new sections for both dev and prod instructions:

### CC section (both files)
```
## CC — Carbon Copy

If the user wants to CC additional recipients on the ticket:
Ask for their email address(es) and pass them in `cc_emails` as a list.
Maximum 48 recipients.
```

### Attachments section (both files)
```
## Attachments

If the user wants to attach a file (screenshot, error log, etc.):
Ask the user to provide the file. Pass each attachment as a dict in the `attachments` list:
  {"filename": "screenshot.png", "content_type": "image/png", "content_base64": "<base64 string>"}
Or if a public URL is available:
  {"filename": "screenshot.png", "content_type": "image/png", "url": "https://..."}
```

---

## 5. `docs/it-form-update-guide.md`

Fix stale references on lines 4 and 37: change `docs/it-agent-instructions.md` → `docs/it-agent-instructions-dev.md` and `docs/it-agent-instructions-prod.md`.

Also update the default prod form ID in `scripts/inspect_it_form.py` from `40703005823501` to `45108529620365`.

---

## 6. `docs/it-ticket-test-plan.md` — New File

Create a test plan covering:

**Incidents:**
- `incident` + `eit_software` + `incident_software_item=github`
- `incident` + `eit_hardware` + `incident_hardware_item=laptop`
- `incident` + `bizapps` + `incident_bizapps_item=salesforce`
- `incident` + `eit_security_ops` + `incident_security_item=phishing`
- `incident` + `eit_general` + `inc_eit_general_subcategory=network` + `incident_network_item=vpn`
- `incident` + `eit_general` + `inc_eit_general_subcategory=access_management` + `incident_access_mgmt_item=mfa`
- `incident` + `eit_general` + `inc_eit_general_subcategory=email_collaboration` + `incident_email_collab_item=teams`
- `incident` + `eit_general` + `inc_eit_general_subcategory=facilities` + `incident_facilities_item=printer_scanner`
- `incident` + `eit_general` + `inc_eit_general_subcategory=virtual_machine` + `incident_vm_item=vm_performance`

**Service Requests:**
- `service_request` + `eit_software` + `sr_software_item=zoom`
- `service_request` + `eit_hardware` + `sr_hardware_item=laptop`
- `service_request` + `bizapps` + `sr_bizapps_item=salesforce`
- `service_request` + `eit_security_ops` + `sr_security_ops_item=unblock_website`
- `service_request` + `eit_general` + `eit_general_subcategory=access_request` + `access_request_type=security_group`
- `service_request` + `eit_general` + `eit_general_subcategory=distribution_list` + `distribution_list_action=create`
- `service_request` + `eit_general` + `eit_general_subcategory=virtual_machine` + `virtual_machine_type=windows_365_cloud_pc`

**Cross-cutting:**
- Ticket with `cc_emails=["colleague@fourth.com"]`
- Ticket with one attachment (base64 PNG)
- Validation errors: `incident_category` set with `sr_category`, `inc_eit_general_subcategory` without `eit_general`

---

## Implementation Order

1. **Run** `python scripts/inspect_it_form.py prod 45108529620365` → fill in all `TBD` tag values above
2. **Update** `scripts/inspect_it_form.py` default prod form ID
3. **Update** `src/constants.py` — new field IDs and tag value maps
4. **Update** `src/zendesk_client.py` — add `upload_file`
5. **Update** `src/tools/tickets.py` — new parameters, updated `_build_it_custom_fields`, CC, attachments, validation
6. **Rewrite** `docs/it-agent-instructions-prod.md`
7. **Update** `docs/it-agent-instructions-dev.md` — add CC + attachments sections
8. **Fix** `docs/it-form-update-guide.md` — stale file references
9. **Create** `docs/it-ticket-test-plan.md`

---

## Verification

After implementation:
1. Run `python scripts/inspect_it_form.py prod 45108529620365` — confirm output matches constants
2. Use `mcp__zendesk-sandbox2-project-stdio__create_it_ticket` in dev to test dev paths still work
3. Execute test cases from `docs/it-ticket-test-plan.md` against prod MCP endpoint
4. Verify tickets appear in hotschedules.zendesk.com with correct form fields populated and correct Classification-IT / Sub-Classification-IT values set by triggers
