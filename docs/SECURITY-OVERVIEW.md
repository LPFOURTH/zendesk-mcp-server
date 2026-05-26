# Zendesk MCP — Security Overview

> Internal Fourth tool. ~50 users. Live on Azure Container Apps. Updated 2026-05-26.
> Active revision `--0000111` · image `v3.10.5` · `MCP_AUTH_MODE=zendesk` (Architecture C).

---

## What this is, in one line

A FastMCP server that lets AI agents (Claude Code, Copilot Studio, Cursor) read and write Fourth's prod Zendesk on behalf of authenticated Fourth employees.

## Architecture

```
   AI agent (Claude Code / Copilot Studio / Cursor)
              │  Streamable HTTP, TLS
              ▼
   ┌────────────────────────────────────────────┐
   │ Azure Container App  fourth-zendesk-mcp-server │
   │  • ASGI middleware → per-request contextvars   │
   │  • FastMCP server → 14 tools                    │
   │  • Managed identity → Cosmos / KV / Blob        │
   └────────┬──────────────────────────────┬───────┘
            │ /mcp/prod (Arch B, API key)  │ /mcp/dev (Arch C, per-user OAuth — LIVE)
            ▼                              ▼
   Prod Zendesk hotschedules.zendesk.com   Prod Zendesk (user's own Bearer)
```

Full interactive sequence diagram: `docs/zendesk-mcp-workflows.html` (open in a browser).

## Authentication

| Path | Method | Who | Identity proven by |
|---|---|---|---|
| `/mcp/dev` (LIVE) | Zendesk OAuth 2.1 + PKCE | Each individual Fourth user | Successful sign-in to `hotschedules.zendesk.com` |
| `/mcp/prod` | Static API key | Automation only | Holder of the `ZENDESK_API_TOKEN` secret |

No anonymous access. Token state persists in Cosmos DB (Fernet-encrypted) so deploys don't force re-auth.

---

## Why we're secure — the 6-layer model

| # | Layer | What it protects against | How we apply it (plain English) | Why it matters | Status |
|---|---|---|---|---|---|
| 1 | **Door check** | Strangers using the tool | Every request must prove who you are — either by signing into Microsoft or into Zendesk. No login, no access. All traffic encrypted (HTTPS). | If anyone on the internet could call our tools, they could create or modify tickets at will | ✅ Live |
| 2 | **Record everything** | Misuse we can't trace back to a person | Every action records a log line: who did it, what tool, what arguments, did it work. Logs go into a searchable Azure store (kept 90 days). A dashboard shows trends. Teams gets pinged when patterns look wrong. | If something goes wrong we need to be able to answer "who did this, when, and why" — for the team, for security, and for trust | ⚠️ Partial (Zendesk side ✓, our side scheduled PR #4) |
| 3 | **No pretending to be someone else** | One user acting with another user's permissions | Each request is fully isolated — no session bleed between users. Headers that could let you forge identity are stripped before they're trusted. The final say on "what can this user do" is Zendesk itself, based on their account role. | If broken, one Fourth employee could read or change another's tickets. We'd lose the ability to trust anything in the audit log. | ⚠️ Partial (one bug scheduled PR #4) |
| 4 | **Brake pedal** | One user accidentally destroying Zendesk for everyone | Each user gets a budget: max 1,000 reads/hour, max 30 writes/hour. Single calls can't return more than 100 records. If Zendesk pushes back ("too fast"), we wait politely and retry. | An AI agent in a loop can fire thousands of calls in seconds. Without limits, a single user can take Zendesk down for the whole company. | ❌ Gap (scheduled PR #5) |
| 5 | **Filter what goes in and out** | Server tricked into doing something harmful | Outbound requests can't reach internal Azure addresses (blocks credential theft). Free-text fields have length caps (blocks DoS via huge payloads). Error messages from Zendesk are sanitized before reaching the user (no schema leaks). Content from tickets is flagged as "untrusted" so the AI doesn't follow hidden instructions inside it. | Today, a single malicious ticket attachment URL could trick our server into handing over the Azure cloud credentials it runs under. This is the most serious open gap. | ❌ Gap incl. CRITICAL (scheduled PR #4) |
| 6 | **Locks on the building** | Weaknesses outside the app — the infrastructure itself | Container images pulled with our cloud identity, not a shared password. Secrets in Key Vault can't be permanently deleted for 90 days. Microsoft scans our running image for known vulnerabilities. Monthly rebuilds keep the OS patched. A 10-second "undo" script reverts a bad deploy. Weekly check on whether the Microsoft sign-in secret is about to expire. | The app code can be perfect and you can still get breached via an outdated container image, an expired secret, or a shared admin password leaking | ⚠️ Partial (KV purge protection ✓ live, killswitch ✓ written; rest scheduled PR #5) |

Mapped to: OWASP ASVS Level 1 + OWASP API Security Top 10 (2023) + MCP spec § Authorization + CIS Microsoft Azure Foundations.

---

## OAuth-specific risks

| Risk | What could happen | Mitigation today |
|---|---|---|
| Opaque Zendesk Bearer (not JWT) — no offline validation | Every call needs a Zendesk round-trip | 5-min in-memory cache; trade-off accepted |
| Up to 5-min cache hit after a user is disabled in Zendesk | Off-boarded user retains access briefly | Documented as RISK-012; acceptable for an internal tool |
| Garbage-token DoS — invalid tokens used to bypass the success cache | Single attacker takes down the service | Negative cache + LRU bound scheduled PR #4 |
| Encrypted OAuth state in Cosmos | If Cosmos + KV are both compromised, every user's session is exposed | Fernet at value level; KV access via Managed Identity only; KV purge protection planned PR #5 |
| Prod OAuth client secret transmitted via Slack historically | Anyone in the Slack channel could exfil it | Rotated; future rotations via Key Vault only (RISK-008) |
| No Zendesk SAML on `hotschedules.zendesk.com` | Architecture E (JWT SSO) blocked | Architectural constraint, documented RISK-003 |
| Entra client secret silent expiry | All Architecture F auth breaks overnight | Weekly Microsoft Graph check → Teams alert at <30 days, scheduled PR #5 |

## Threat model — what someone using our MCP could do wrong

| Threat | Plausible? | What stops it |
|---|---|---|
| Impersonate another user (read their tickets) | Theoretical (one bug today) | Zendesk RBAC per token; contextvar reset fix scheduled PR #4 |
| Slow-drip exfil (5 tickets/hr to stay under any limit) | Yes | Layer 2 audit log + per-user write counters in dashboard |
| Subtly modify a ticket (priority, comment redaction) | Yes | Layer 2 audit log + Zendesk's own change history |
| SSRF — call Azure internal endpoints via our server | **YES, currently CRITICAL** | Fix in PR #4 (deny-list IMDS / private nets) |
| Prompt-inject via ticket body → trick LLM into writing | Yes (emerging) | `<untrusted-content>` wrapping + length caps + Layer 4 write limits |
| Garbage-token DoS | Yes | PR #4 negative cache |
| Cross-origin browser attack | Low | CORS allowlist replacing wildcard, PR #4 |
| Schema enumeration via verbose error messages | Yes | Zendesk error body sanitization, PR #4 |
| Misconfiguration drift over time | Yes | Defender for Cloud secure-score + quarterly access review |

---

## Audit coverage — what we used, what each tool actually checks

| Tool | What it audits |
|---|---|
| **Aegis agent** (internal LLM) | All `src/` code + tests for OWASP API Top 10 + ASVS L1 weaknesses |
| **Oracle agent** (internal LLM) | `requirements.txt` for CVEs, FastMCP + PyJWT + Azure SDK for known issues |
| **Claude Sonnet 4.6 deep-dive** (external) | Targeted review of the Entra authentication path (7 gaps, 2 already closed on `feature/security-entra-easy-wins`) |
| **pip-audit + bandit + gitleaks + trivy** (CI floor, planned) | Every PR: dependency CVEs / static analysis / committed secrets / container image CVEs |
| **OWASP ZAP** (planned, weekly) | DAST probe of live `/mcp/dev` for TLS, security headers, SSRF, info disclosure |
| **Defender for Cloud Foundational** (free, already on) | Continuous secure score against CIS Azure Foundations |
| **Defender for Containers + KV** (planned, ~$15/mo) | Post-deploy image CVE scan + Key Vault anomalous-access alerts |
| **killswitch.sh** (written, uncommitted) | 10-second traffic revert to last-known-good revision |

Coverage matrix:

| Domain | Covered by |
|---|---|
| Application code | Aegis · Bandit · Claude deep-dive |
| Dependencies | pip-audit · Oracle |
| Container image | trivy · Defender for Containers |
| Running endpoint | OWASP ZAP |
| Azure infrastructure | Defender for Cloud · CIS Azure Foundations |
| Secrets hygiene | gitleaks · Defender for KV |
| Recovery | killswitch.sh |

---

## Findings summary

Latest cycle closed 2026-05-21 — 37 deduplicated findings:

| Bucket | Count | Plan |
|---|---|---|
| 🔴 Critical (live Arch C) | 1 — SSRF in `create_it_ticket` | PR #4 |
| 🟠 High (live Arch C) | 3 — contextvar leak, no audit log, token-cache DoS | PR #4 |
| 🟡 Medium (live Arch C) | 4 — wildcard CORS, error body leak, env header, length caps | PR #4 |
| 🟢 Low / Info | 6 | PR #5 |
| 📋 Accepted (documented in LIMITATIONS.md) | 9 | n/a |
| ⚪ Dormant (Arch E/F only) | 9 | Closed if those paths reactivate. 2 fixed already on `feature/security-entra-easy-wins`. |
| ✅ Verified resolved | 2 | n/a |
| ⭐ Opportunities (FastMCP idioms) | 2 | Defer |

---

## What's required before we say "internal-ready"

13 line items. Status today, why each is not yet done.

| # | Requirement | Done? | Why not yet (if not) |
|---|---|---|---|
| R1 | Critical and High findings closed | ❌ | PR #4 in flight — open question on SSRF variant + audit-log impl is being walked through with Boyan |
| R2 | Per-tool MCP-side structured audit log | ❌ | Lands in PR #4. Adopting FastMCP `StructuredLoggingMiddleware` over hand-rolled — Boyan to confirm |
| R3 | Per-user rate limiting on writes | ❌ | PR #5 — depends on R2 landing first (needs user identity from audit log middleware) |
| R4 | SSRF deny-list on outbound URL fetches | ❌ | PR #4 — variant chosen: deny-list IMDS/RFC1918/loopback + log every fetch, tighten to allowlist after 30 days of data |
| R5 | Killswitch script committed and tested | ⚠️ | Script written and tested in `--status` mode. Awaiting first commit (PR #4 prerequisite) |
| R6 | First baseline self-audit, dated, committed | ❌ | Day 1 of the 1-2 day baseline track |
| R7 | CI security floor active (pip-audit + bandit + gitleaks + trivy) | ❌ | Day 2 of baseline track — needs GitHub Action workflow + repo secret for Azure auth |
| R8 | Defender for Containers + KV enabled | ❌ | Day 2 of baseline track — 5-minute `az` command, ~$15/mo recurring |
| R9 | OWASP ZAP weekly scan, results in repo | ❌ | Day 2 of baseline track — GitHub Action template ready |
| R10 | 1-page IR runbook published | ❌ | PR #5 — drafting from killswitch script as base |
| R11 | ACR admin user disabled, MI `AcrPull` granted | ❌ | PR #5 — requires deploy script update + verification run |
| R12 | KV purge protection enabled | ✅ | Verified 2026-05-26 — `enablePurgeProtection: true`, soft-delete retention 90d |
| R13 | Entra client secret expiry alert | ❌ | PR #5 — weekly GitHub Action checking Microsoft Graph |

Total effort end-to-end: ~3-4 working days (1-2 baseline + 5h PR #4 + 8h PR #5).

---

## Backlog — known and explicitly deferred

| # | Item | Why not addressed |
|---|---|---|
| B1 | Architecture E browser PKCE flow | Code path dormant — only needed if `/zendesk-sso` gets activated. Spec already exists. |
| B2 | Continuous Access Evaluation (CAE) for Entra | Significant Microsoft Graph + revocation wiring. Only matters if Architecture F reactivated. Documented as accepted risk. |
| B3 | Cookie security attributes on Architecture E | Cookie not currently written; ~6 lines when the PKCE callback ships |
| B4 | Certificate-based Entra credential (replaces shared secret) | Eliminates rotation burden but is significant work; R13 weekly expiry alert is the cheap stop-gap |
| B5 | OWASP ZAP authenticated scan (deeper coverage) | Unauth baseline first; authenticated scan adds 2-3h of token-replay setup |
| B6 | Private Endpoints for Cosmos / KV / Blob | Overkill at 50 internal users. MI auth + firewall ACLs are sufficient. Costs add up. |
| B7 | Image signing / Notary v2 | Defender for Containers gets us 80% of supply-chain value at a fraction of the toolchain weight |
| B8 | Splunk / Microsoft Sentinel SIEM | Log Analytics + Workbook is the line at our scale. SIEM costs and complexity not justified. |
| B9 | Bug bounty programme | Ops weight too high. Revisit if user base crosses ~200. |
| B10 | Third-party pentest engagement | Year-2 trigger. ~£5-10k spend; usage doesn't yet justify it. |
| B11 | Per-user write-diff audit (full payload before/after) | Layer 2 catches WHO and WHAT tool; full diff is a richer forensic story but doubles log volume. Defer until we hit an incident that demands it. |

---

## Audit cadence

| Activity | Frequency |
|---|---|
| Self-audit (re-run Aegis + Oracle, refresh baseline checklist, ZAP scan, secure-score delta) | **Monthly for first 3 months**, then quarterly. Dated report committed to `docs/security-audits/YYYY-MM-DD.md`. |
| CI security floor | Every PR — automatic |
| Defender for Cloud secure-score | Weekly review |
| OWASP ZAP scan | Weekly, auto-opens GitHub issue on new findings |
| Quarterly access review | Zendesk OAuth members, KV access, Cosmos RBAC, Container App operator roles |
| Cross-team peer review | Annually (Stefan / Boyan + one outside engineer) |
| Killswitch `--status` test | Monthly |

Next follow-up: **45-min kick-off meeting, week of 2026-06-01** (Tue 2 / Wed 3 / Thu 4 Jun) — walk this doc with Boyan, agree PR #4 scope, confirm requirements + sign-off owner per requirement, schedule PR #4 deploy.

---

## Open conversation invited

This doc is the *current* picture, not a final position. Things we'd specifically value pushback on:

- **Are the 4 layers we already have (1, 2 partial, 3 partial, 4 gap) the right priorities to close first?** Or would you weight 5 (SSRF) above 4 (rate limit)?
- **Is monthly × 3 then quarterly the right audit cadence**, or do you want a quicker drumbeat in the first quarter?
- **Are we missing a category?** Aegis red-team converged on 6 layers; if you see a 7th, raise it.
- **Defender plan budget (~$15/mo)** — is that within discretionary, or does it need a separate ask?

---

*Owner: Lukasz Pelcner. Reference docs: `DESIGN_DECISIONS.md` (architecture rationale), `LIMITATIONS.md` (14 accepted risks), `zendesk-mcp-workflows.html` (interactive sequence diagram), `deployment/azure/scripts/killswitch.sh` (revert script).*
