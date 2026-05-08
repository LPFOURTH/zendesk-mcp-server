# IT Ticket Tool — Test Plans

Tests are split by environment because an agent connects to one environment at a time.

| File | Environment | Zendesk instance |
|------|-------------|-----------------|
| [it-ticket-test-plan-dev.md](it-ticket-test-plan-dev.md) | Dev / sandbox | hotschedules1760632913.zendesk.com |
| [it-ticket-test-plan-prod.md](it-ticket-test-plan-prod.md) | Production | hotschedules.zendesk.com (form `45108529620365`) |

## Key differences between environments

- **SR BizApps tags** — dev uses `sr_*`, prod uses `sr_bizz_*` (same friendly keys, resolved automatically)
- **Incident EIT General** — prod requires both `eit_general_subcategory` AND `inc_eit_general_subcategory`; dev only needs `eit_general_subcategory`
- **Software options** — prod has additional options: AI tools, `zoom_phone`, `zoom_contact_center`, `ms_outlook`, `ms_edge`, `ms_todo`, `google_chrome`, `postman`
- **Access request type** — prod adds `mailbox` option
- **BizApps SR** — prod adds `gdpr_request` option

## Execution order

1. Start with Section 0 (smoke tests) in each plan
2. Check that form, fields, tags, and CC all appear correctly in Zendesk
3. Close all test tickets after verification
