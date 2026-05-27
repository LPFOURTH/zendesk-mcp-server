# Zendesk MCP — Security Overview

> Internal Fourth tool. ~50 users. Live on Azure Container Apps. Updated 2026-05-27.
> Active revision `--0000111` · image `v3.10.5` · `MCP_AUTH_MODE=zendesk` (Architecture C).
> **Current state:** PR #4 ([fourth/zendesk-mcp-fourth#4](https://github.com/fourth/zendesk-mcp-fourth/pull/4)) is open with 14 commits closing all 8 active audit findings + the security CI floor. Code passes 243 tests. Awaiting review and `v3.10.6` deploy ceremony.

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
| 2 | **Record everything** | Misuse we can't trace back to a person | Every action records a log line: who did it, what tool, what arguments, did it work. Logs go into a searchable Azure store (kept 90 days). A dashboard shows trends. Teams gets pinged when patterns look wrong. | If something goes wrong we need to be able to answer "who did this, when, and why" — for the team, for security, and for trust | ✅ Code in PR #4 — emits per tool call, payloads redacted |
| 3 | **No pretending to be someone else** | One user acting with another user's permissions | Each request is fully isolated — no session bleed between users. Headers that could let you forge identity are stripped before they're trusted. The final say on "what can this user do" is Zendesk itself, based on their account role. | If broken, one Fourth employee could read or change another's tickets. We'd lose the ability to trust anything in the audit log. | ✅ Code in PR #4 — contextvar reset + env-header strip, with regression tests |
| 4 | **Brake pedal** | One user accidentally destroying Zendesk for everyone | Each user gets a budget: max 1,000 reads/hour, max 30 writes/hour. Single calls can't return more than 100 records. If Zendesk pushes back ("too fast"), we wait politely and retry. | An AI agent in a loop can fire thousands of calls in seconds. Without limits, a single user can take Zendesk down for the whole company. | ⚠️ Partial — input length caps + DoS-resilient token cache ✅ in PR #4. Per-user rate limit still scheduled PR #5 |
| 5 | **Filter what goes in and out** | Server tricked into doing something harmful | Outbound requests can't reach internal Azure addresses (blocks credential theft). Free-text fields have length caps (blocks DoS via huge payloads). Error messages from Zendesk are sanitized before reaching the user (no schema leaks). Cross-origin browser policy locked to a known list. | Before PR #4, a single malicious ticket attachment URL could trick our server into handing over the Azure cloud credentials. This was the most serious gap — now closed. | ✅ Code in PR #4 — SSRF deny-list, length caps, error sanitization, CORS allowlist. Prompt-injection content-wrapping is a backlog item (B11) |
| 6 | **Locks on the building** | Weaknesses outside the app — the infrastructure itself | Container images pulled with our cloud identity, not a shared password. Secrets in Key Vault can't be permanently deleted for 90 days. Microsoft scans our running image for known vulnerabilities. Monthly rebuilds keep the OS patched. A 10-second "undo" script reverts a bad deploy. Weekly check on whether the Microsoft sign-in secret is about to expire. | The app code can be perfect and you can still get breached via an outdated container image, an expired secret, or a shared admin password leaking | ⚠️ Partial — KV purge protection ✓, Defender for Containers + KV ✓ (Standard tier), killswitch ✓ committed, IR runbook ✓, Entra expiry workflow ✓ (manual until secrets added). ACR admin disable + monthly base rebuild still PR #5 |

Mapped to: OWASP ASVS Level 1 + OWASP API Security Top 10 (2023) + MCP spec § Authorization + CIS Microsoft Azure Foundations.

---

## OAuth-specific risks

| Risk | What could happen | Mitigation today |
|---|---|---|
| Opaque Zendesk Bearer token (not a JWT — meaning we can't read its contents locally) | Every call needs a Zendesk round-trip to validate | 5-min in-memory cache; trade-off accepted |
| Up to 5-min cache hit after a user is disabled in Zendesk | Off-boarded user retains access briefly | Documented as RISK-012; acceptable for an internal tool |
| Garbage-token DoS — invalid tokens used to overwhelm Zendesk validation | Single attacker takes down the service | ✅ Negative cache + LRU bound in PR #4 |
| Encrypted OAuth state in Cosmos | If Cosmos + KV are both compromised, every user's session is exposed | Fernet at value level; KV access via Managed Identity only; KV purge protection ✓ enabled |
| Prod OAuth client secret transmitted via Slack historically | Anyone in the Slack channel could exfil it | Rotated; future rotations via Key Vault only (RISK-008) |
| No Zendesk SAML on `hotschedules.zendesk.com` | Architecture E (JWT SSO) blocked | Architectural constraint, documented RISK-003 |
| Entra client secret silent expiry | All Architecture F auth breaks overnight | ⚠️ Weekly workflow committed in PR #4 — manual-trigger until `AZURE_CREDENTIALS` + `TEAMS_WEBHOOK_URL` GitHub repo secrets are added |

## Threat model — what someone using our MCP could do wrong

| Threat | Plausible? | What stops it |
|---|---|---|
| Impersonate another user (read their tickets) | No longer plausible after PR #4 | Zendesk RBAC per token + ✅ contextvar reset (no auth-state leak between requests) |
| Slow-drip exfil (5 tickets/hr to stay under any limit) | Yes | ✅ Layer 2 audit log (PR #4) — every read recorded with user identity. Per-user write counters in dashboard. |
| Subtly modify a ticket (priority, comment redaction) | Yes | ✅ Layer 2 audit log + Zendesk's own change history |
| SSRF — call Azure internal endpoints via our server | Was CRITICAL, **now closed** in PR #4 | ✅ Deny-list of IMDS / private networks + 10MB response cap on outbound fetches |
| Prompt-inject via ticket body → trick LLM into writing | Yes (emerging threat — applies to any AI assistant reading user content) | Length caps + Layer 4 write limits + Layer 2 audit log catches the action. Content-wrapping with `<untrusted-content>` markers tracked as B11. |
| Garbage-token DoS | No longer plausible after PR #4 | ✅ Negative cache (30s TTL) + LRU bound + cache-key-as-hash |
| Cross-origin browser attack | Low | ✅ CORS allowlist (PR #4) replaces wildcard `*` |
| Schema enumeration via verbose error messages | No longer plausible after PR #4 | ✅ Zendesk error bodies sanitized — only HTTP status + generic category returned |
| Misconfiguration drift over time | Yes | Defender for Cloud secure-score (Standard tier active) + quarterly access review + RISK-013/016 in LIMITATIONS.md |

---

## Audit coverage — what we used, what each tool actually checks

| Tool | What it audits |
|---|---|
| **Aegis agent** (internal LLM) | All `src/` code + tests for OWASP API Top 10 + ASVS L1 weaknesses |
| **Oracle agent** (internal LLM) | `requirements.txt` for CVEs, FastMCP + PyJWT + Azure SDK for known issues |
| **Claude Sonnet 4.6 deep-dive** (external) | Targeted review of the Entra authentication path (7 gaps, 2 already closed on `feature/security-entra-easy-wins`) |
| **pip-audit + bandit + gitleaks + trivy** (CI floor, ✅ active via `.github/workflows/ci-security.yml`) | Every PR: dependency CVEs / static analysis / committed secrets / container image CVEs. Blocks merge on HIGH+ CVE or any secret finding. |
| **OWASP ZAP** (planned, weekly) | DAST probe of live `/mcp/dev` for TLS, security headers, SSRF, info disclosure |
| **Defender for Cloud Foundational** (free, already on) | Continuous secure score against CIS Azure Foundations |
| **Defender for Containers + KV** (planned, ~$15/mo) | Post-deploy image CVE scan + Key Vault anomalous-access alerts |
| **killswitch.sh** (✅ committed in PR #4) | 10-second traffic revert to last-known-good revision |

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

| # | Requirement | Done? | Status / what's left |
|---|---|---|---|
| R1 | Critical and High findings closed | ✅ | All 8 active audit findings closed in PR #4. 1 CRITICAL (SSRF) + 3 HIGH + 4 MEDIUM, each with regression tests. |
| R2 | Per-tool MCP-side structured audit log | ✅ | PR #4 — FastMCP `StructuredLoggingMiddleware` on `tools/call`, payloads redacted, sizes logged. Env-var killswitch `MCP_AUDIT_LOG=disabled`. |
| R3 | Per-user rate limiting on writes | ❌ | PR #5 — depends on R2 (now landed). Estimated ~4h. |
| R4 | SSRF deny-list on outbound URL fetches | ✅ | PR #4 — Variant B shipped (deny IMDS/RFC1918/loopback/IPv6 ULA + 10MB cap + DNS resolution check). Env-var killswitch `MCP_ATTACHMENT_URL_VALIDATION=permissive`. |
| R5 | Killswitch script committed and tested | ✅ | Committed in PR #4. `--status` mode confirms target revision live at 100% traffic. |
| R6 | First baseline self-audit, dated, committed | ✅ | `docs/security-audits/2026-05-26-Q2.md` — honest FAIL/PASS snapshot of pre-PR-#4 state. |
| R7 | CI security floor active (pip-audit + bandit + gitleaks + trivy) | ✅ | `.github/workflows/ci-security.yml` — 5 parallel jobs gate every PR. No external secrets needed. |
| R8 | Defender for Containers + KV enabled | ✅ | Both Standard tier active at the subscription level. ~$15/mo. |
| R9 | OWASP ZAP weekly scan, results in repo | ⚠️ | Workflow template ready — needs `AZURE_CREDENTIALS` GitHub repo secret before it can probe the live endpoint. |
| R10 | 1-page IR runbook published | ✅ | `docs/INCIDENT-RESPONSE.md` — declaration criteria, roles, first-5/first-30 actions, comms templates, post-mortem template. |
| R11 | ACR admin user disabled, MI `AcrPull` granted | ❌ | PR #5 — deploy-risky, needs a focused session with smoke test. |
| R12 | KV purge protection enabled | ✅ | `enablePurgeProtection: true`, soft-delete retention 90d. |
| R13 | Entra client secret expiry alert | ⚠️ | Workflow file committed in PR #4 — manual-trigger until `AZURE_CREDENTIALS` + `TEAMS_WEBHOOK_URL` repo secrets are added (~5 min of your time). |

**Score:** 10 ✅ + 2 ⚠️ (awaiting GitHub repo secrets) + 1 ❌ (PR #5). **~85% green**, up from 0% at session start.

Total effort remaining: PR #5 (rate limiter + ACR admin disable + 2 ops items) ≈ ~8h. Then GitHub repo secret addition (~5 min of your time) flips both ⚠️s to ✅.

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
| B12 | `<untrusted-content>` wrapping on tool return values (prompt-injection mitigation) | Layer 5 mentions this; not yet shipped. Effectiveness is partial (LLMs may ignore the marker). Pair with stronger Layer 4 write limits when shipped. |
| B13 | Read-only mode env var (`MCP_READ_ONLY=1` disables all `create_*`/`update_*` tools at startup) | Comparison with Broadcom Rally's MCP server (2026-05-27 research) surfaced this as the one concrete feature they have that we don't. Low effort (~30 min). Useful as a Copilot Studio safety net or break-glass mode. Defer to PR #5 batch. |

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

- **Are the 6 layers + their priorities right?** Aegis red-team and Codex peer-review converged on this shape — if you see a 7th, raise it.
- **Is monthly × 3 then quarterly the right audit cadence**, or do you want a quicker drumbeat in the first quarter?
- **Defender plan budget (~$15/mo)** — is that within discretionary, or does it need a separate ask?
- **PR #5 priority** — per-user rate limiter (Layer 4 finish) vs ACR admin-disable (Layer 6 finish). Which first?

---

## Glossary (for non-security readers)

| Term | Plain English |
|---|---|
| **OAuth 2.1** | The modern industry standard for "click sign-in, get a token, use the token for API calls." What you experience when an app says "Sign in with Microsoft / Google / GitHub." |
| **PKCE** | An extra step in OAuth that prevents the auth code from being intercepted mid-flight. Adds protection without extra user friction. |
| **Bearer token** | The string the user's browser receives after signing in. Whoever holds it can call the API as that user — that's why it's protected like a password. |
| **JWT** | A token format where the contents can be read locally without asking the issuer. Zendesk uses *non-JWT* (opaque) tokens — so we can't peek inside, every check requires a Zendesk round-trip. |
| **SSRF** | Server-Side Request Forgery — tricking our server into fetching a URL the attacker chose. The classic exploit is making the server fetch Azure's internal "metadata" endpoint to steal cloud credentials. |
| **CORS** | Browser rule that controls which websites can call our API from JavaScript. We list allowed origins explicitly; non-listed origins get blocked by the user's browser. |
| **RBAC** | Role-Based Access Control. Zendesk decides what each user can read/write based on their role (admin, agent, end-user) — we trust Zendesk's decision rather than re-inventing it. |
| **Managed Identity** | An Azure feature that lets our container authenticate to Cosmos / Key Vault / Storage without holding a password. The cloud platform vouches for our container's identity. |
| **Key Vault** | Azure's password / secret storage service. Our secrets live there, not in env vars or code. |
| **Fernet** | A standard way to encrypt strings symmetrically. We use it on Cosmos OAuth-token storage so a stolen Cosmos export doesn't directly leak active sessions. |
| **IMDS** | Instance Metadata Service. An internal Azure endpoint at `169.254.169.254` that returns the container's managed-identity token. Blocking SSRF to this address is the headline AUDIT-001 fix. |
| **CI / CD** | Continuous Integration / Continuous Deployment. Automated workflows that run on every code change. Our CI runs the 5-job security floor on every PR (pip-audit, bandit, gitleaks, trivy, pytest). |
| **DAST / SAST** | Dynamic / Static Application Security Testing. SAST reads source code looking for bugs (bandit); DAST probes a running app (OWASP ZAP). We use both. |
| **CVE** | A publicly disclosed software vulnerability with a unique identifier. CVE-2025-XXXX is the index a scanner looks against when it tells you a dependency is out of date. |

---

*Owner: Lukasz Pelcner. Reference docs: `DESIGN_DECISIONS.md` (architecture rationale), `LIMITATIONS.md` (16 accepted risks), `zendesk-mcp-workflows.html` (interactive sequence diagram), `deployment/azure/scripts/killswitch.sh` (revert script), `.github/workflows/ci-security.yml` (security CI floor).*
