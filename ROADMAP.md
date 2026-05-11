# Project Roadmap

## Current Focus
**`create_it_ticket` — IT Support Request Form-Aware Tool**
- Builds the correct `custom_fields` array and sets `ticket_form_id`; `src/constants.py`: — Add `IT_FORM_CONFIG`, field ID dicts, and **human-name → tag-value mapping dicts* for every L3/L4/impact/location field
- Started: 2026-04-22

## Completed
_No completed items yet._

## Planned
_No planned items yet._

## Recent Planning Sessions
### 2026-05-05: Planning Session
### 2026-04-22: `create_it_ticket` — IT Support Request Form-Aware Tool
**Key Decisions:**
- Builds the correct `custom_fields` array and sets `ticket_form_id`
- `src/constants.py`: — Add `IT_FORM_CONFIG`, field ID dicts, and **human-name → tag-value mapping dicts* for every L3/L4/impact/location field
- `src/tools/tickets.py`: — Add `create_it_ticket` with `Literal` params using friendly names; internal mapping via constants
- `src/server.py`: — Add entry in `ALL_TOOLS`
- `docs/it-form-update-guide.md`: — Commands + full update procedure when the form changes
