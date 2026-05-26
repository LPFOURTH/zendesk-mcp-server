# Zendesk MCP — Security Overview

> Audience: internal reviewers (security, IT leadership). Plain-English read first; technical references at the bottom of each section.
> Last updated: 2026-05-26. Live revision: `fourth-zendesk-mcp-server--0000111`, image `v3.10.5`.
> Scope: live Architecture C (`/mcp/dev` with `MCP_AUTH_MODE=zendesk`). Dormant paths (Architectures B/E/F) noted where relevant.

---

## 1. What this thing is and who uses it

The Zendesk MCP is an internal API that lets AI agents (Claude Code, Copilot Studio, Cursor) read and write tickets, Help Center articles, release notes and community ideas on Fourth's production Zendesk tenant `hotschedules.zendesk.com`.

- **Users:** ~50 Fourth Hospitality employees. Internal only — no external access.
- **Hosting:** Azure Container Apps, North Europe, single resource group `fourth-ai-prod`.
- **Data touched:** prod Zendesk (tickets, articles, ideas), Cosmos DB OAuth state, Key Vault secrets, Blob Storage (Ideas snapshot).
- **No PII storage of our own** — Zendesk holds it; we proxy. Our Cosmos holds OAuth tokens (Fernet-encrypted).

## 2. Architecture (one diagram)

```
   AI Agent (Claude Code / Copilot Studio / Cursor)
              │
              │  Streamable HTTP over TLS
              ▼
  ┌──────────────────────────────────────────────┐
  │ Azure Container App: fourth-zendesk-mcp-server│
  │   ASGI middleware → contextvars per request  │
  │   FastMCP server  → 14 tools                 │
  └─────┬──────────────────────────┬─────────────┘
        │ /mcp/prod (Arch B)       │ /mcp/dev  (Arch C — LIVE)
        │ API-key, no user identity │ Per-user Zendesk OAuth
        ▼                          ▼
  ┌─────────────────┐   ┌──────────────────────────┐
  │ Prod Zendesk    │   │ Prod Zendesk             │
  │ (service acct)  │   │ (per-user Bearer)        │
  └─────────────────┘   └──────────────────────────┘

  Side dependencies (Azure-managed identity, no passwords):
    Cosmos DB    — OAuth token persistence (Fernet-encrypted)
    Key Vault    — secrets (Entra client secret, Zendesk OAuth secret)
    Blob Storage — Ideas snapshot (weekly refresh)
```

**Two paths, one container:**
- **`/mcp/prod`** (Architecture B, unchanged): API-key auth, no user identity. For headless automation only.
- **`/mcp/dev`** (Architecture C, live): per-user Zendesk OAuth. Each user signs in with their own Zendesk credentials; we forward their Bearer token on every API call. **Zendesk's role-based access control is the source of truth for what each user can do.**

**Two dormant paths kept warm for revert:**
- **Architecture F** — Microsoft Entra OAuth + service-account Zendesk. Code default. Reachable by flipping `MCP_AUTH_MODE=entra`.
- **Architecture E** — Zendesk JWT SSO. Compiled in but route only registers when `ZENDESK_JWT_SSO_SECRET` is set (currently unset).

## 3. Authentication — how we know who you are

| Path | Method | Identity proven by |
|---|---|---|
| `/mcp/dev` (LIVE) | Zendesk OAuth 2.1 with PKCE | Successful login to `hotschedules.zendesk.com` |
| `/mcp/dev` (dormant Arch F) | Microsoft Entra OAuth 2.1 with PKCE | Successful Entra sign-in, JWT validated against Microsoft JWKS |
| `/mcp/prod` | Static API key | Holder of `ZENDESK_API_TOKEN` env var |
| stdio (local dev) | Email + API token from `.env` | Process-local credentials |

**No anonymous access on `/mcp/dev` or `/mcp/prod`.** A request without a valid token gets 401. Token state persists in Cosmos DB (Fernet-encrypted) so users don't re-authenticate after every deploy.

## 4. Securing the MCP — the 6 layers

We defend in 6 layers, each mapped to industry frameworks (OWASP ASVS Level 1 + OWASP API Security Top 10 + MCP spec § Authorization + CIS Microsoft Azure Foundations).

### Layer 1 — Door check (only Fourth staff get in)
Authentication. Today: ✅ enforced by Entra single-tenant config (dormant Arch F) and Zendesk OAuth (live Arch C).

### Layer 2 — Record everything (NSA-style)
Every tool call is logged with the user's identity, what was called, what arguments, what outcome. Today: ⚠️ partial — Zendesk side has full attribution, our MCP side currently has no structured audit log (gap AUDIT-004, scheduled in PR #4).

### Layer 3 — No pretending to be someone else
A user can never act with another user's permissions. Zendesk's role-based access control is the source of truth. Today: ⚠️ mostly enforced; one known weakness (AUDIT-003 contextvar leak — fix planned in PR #4).

### Layer 4 — Brake pedal (no Zendesk-killing)
A single user can't accidentally or maliciously hammer Zendesk into a 429 storm. Today: ❌ gap — only a global 200 req/min limit exists. Per-user rate limit + 429 retry handler planned in PR #5.

### Layer 5 — Filter what comes in and goes out
The server doesn't blindly trust user-supplied URLs (SSRF) or echo Zendesk content verbatim (LLM prompt-injection risk). Today: ❌ gap — SSRF currently CRITICAL (AUDIT-001, fix in PR #4). Prompt-injection mitigation planned.

### Layer 6 — Locks on the building
Operational/infrastructure hardening: secret rotation alerting, image vulnerability scanning, incident response. Today: ⚠️ partial — killswitch exists, Defender for Cloud Foundational already on; Defender for Containers/KV + IR runbook + ACR admin disable planned.

**Honest layer-by-layer status today (not after fixes):**

| Layer | Live status | Closing PR |
|---|---|---|
| 1. Door check | ✅ Pass | n/a |
| 2. Record everything | ⚠️ Partial | PR #4 |
| 3. No impersonation | ⚠️ Partial | PR #4 |
| 4. Brake pedal | ❌ Gap | PR #5 |
| 5. Filter in/out | ❌ Gap (CRITICAL SSRF) | PR #4 |
| 6. Locks on building | ⚠️ Partial | PR #5 / ops |

## 5. OAuth risks specifically

Architecture C uses Zendesk's own OAuth implementation. Risks inherent to that:

| Risk | Severity at our scale | Mitigation |
|---|---|---|
| Zendesk OAuth Bearer is opaque (not JWT) — no offline validation | Informational | Every call validates against Zendesk's `/users/me` (cached 5 min). Trade-off is 1 extra Zendesk call on cold cache; accepted. |
| Token revocation latency — up to 5 min cache hit after user is disabled in Zendesk | Low | Acceptable for an internal tool; documented in LIMITATIONS.md RISK-012. |
| Token cache DoS — invalid tokens used to be a cache miss → Zendesk call per request | High → fixed in PR #4 | Negative cache + LRU bound + per-token-prefix rate limit (AUDIT-007). |
| Token persisted in Cosmos for cross-deploy continuity | Medium | Fernet-encrypted at value level. Key in Key Vault (KV access only via container Managed Identity). |
| Prod Zendesk OAuth client secret transmitted via Slack historically | Medium | Rotated after RISK-008 disclosure; future rotations via Key Vault only. |
| No Zendesk SAML/SSO federation available on `hotschedules.zendesk.com` | Low (architectural) | Architecture E (JWT SSO) blocked on Zendesk admin enabling it. Documented in RISK-003. |
| Entra client secret expiry — silent breakage if forgotten | Medium → mitigated in PR #5 | Weekly GitHub Action checks Microsoft Graph for expiry date, alerts Teams at <30 days. |

## 6. Risks of someone abusing the MCP

Threat model — "what could a malicious or careless insider do":

| Threat | Plausible? | Mitigation today |
|---|---|---|
| Steal another user's Zendesk session (impersonation) | Theoretical (contextvar leak AUDIT-003) | Mitigated by Zendesk's per-token RBAC. PR #4 hardens it further. |
| Pull large volumes of tickets via tool loops (slow exfiltration) | Yes | Layer 4 rate limiting (PR #5) + Layer 2 audit log (PR #4) catches this. |
| Modify a ticket subtly (priority, comment redaction) | Yes | Caught by Layer 2 audit log + Zendesk's own change history. |
| Use server to call internal Azure endpoints (SSRF) | YES — currently CRITICAL | AUDIT-001 fix in PR #4 deny-lists IMDS/RFC1918/loopback and caps response size. |
| Inject instructions via Zendesk ticket bodies → trick LLM into doing something via `update_ticket` | Yes — emerging threat | Layer 5: wrap untrusted content with `<untrusted-content>` markers + length caps + content sanitization. Honest framing: reduces risk, does not eliminate. |
| Stuff garbage tokens at us to DoS the service | Yes (AUDIT-007) | Negative cache + LRU bound in PR #4. |
| Cross-origin browser attack | Low | CORS allowlist lock-down in PR #4 (currently wildcard `*`). |
| Schema enumeration via verbose error messages | Yes (AUDIT-006) | Sanitize Zendesk error bodies before return (PR #4). |
| Privilege misconfiguration drift over time | Yes (RISK-013) | Defender for Cloud secure-score + quarterly access review + startup-log assertion of `MCP_AUTH_MODE`. |

## 7. Audit tools we use, what each one covers

| Tool | Type | What it scans / does |
|---|---|---|
| **Aegis agent** (internal LLM) | Code audit | Reads `src/` + tests, looks for app-layer vulnerabilities mapped to OWASP API Top 10 + ASVS. Output: dated findings list. |
| **Oracle agent** (internal LLM) | Dependency + framework audit | Checks `requirements.txt` against CVE databases, reviews FastMCP + PyJWT + Azure SDK for known issues. |
| **Claude Sonnet 4.6 deep-dive** (external) | Focused code review | Targeted review of Entra ID authentication path (7 gaps identified, low-hanging 2 already fixed on `feature/security-entra-easy-wins`). |
| **pip-audit** (planned CI) | Dependency CVE scan | Every PR: blocks merge if any Python dep has a known CVE. |
| **bandit** (planned CI) | Python static analysis | Every PR: flags hardcoded secrets, weak crypto, SQL-i patterns, etc. |
| **gitleaks** (planned CI) | Secret scanning | Every commit: blocks merge if a secret-shaped string is committed. |
| **trivy** (planned CI) | Container image scan | Every PR: scans built Docker image for OS + lang CVEs. |
| **OWASP ZAP** (planned weekly) | DAST (dynamic) | Weekly GitHub Action probes live `/mcp/dev` for TLS / security headers / SSRF / info disclosure. |
| **Microsoft Defender for Cloud Foundational** (already on, free) | Posture | Continuous score against CIS Azure Foundations. Misconfig recommendations. |
| **Defender for Containers + KV** (planned, ~$15/mo) | Posture + threat detection | Image CVE scan post-deploy, KV anomalous-access alerts. |
| **`killswitch.sh`** (already written, uncommitted) | Recovery | 10-second traffic revert to last-known-good revision. |

Together these cover: code (aegis, bandit, oracle, Claude deep-dive), dependencies (pip-audit, oracle), container images (trivy, Defender for Containers), runtime endpoints (ZAP), infra posture (Defender for Cloud, CIS Azure), secret hygiene (gitleaks, Defender for KV), and recovery (killswitch).

## 8. Summary of findings to date

Latest audit cycle (closed 2026-05-21) — 37 total findings, deduplicated and ranked:

| Bucket | Count |
|---|---|
| 🔴 ACTIVE-CRITICAL | 1 (SSRF) |
| 🟠 ACTIVE-HIGH | 3 (contextvar leak, no audit log, token-cache DoS) |
| 🟡 ACTIVE-MEDIUM | 4 (wildcard CORS, error-body leak, env header, length caps) |
| 🟢 ACTIVE-LOW | 6 (cosmetic hardening) |
| 📋 DOCUMENTED-ACCEPTED | 9 (in `docs/LIMITATIONS.md`) |
| ⚪ DORMANT (Arch E/F only) | 9 (incl. Entra deep-dive gaps; 2 fixed on `feature/security-entra-easy-wins`) |
| ✅ VERIFIED RESOLVED | 2 |
| ⭐ FRAMEWORK OPPORTUNITIES | 2 |

**Active fixable items map cleanly to:**
- **PR #4** (8 items, ~5h): SSRF + contextvar reset + audit log + token cache + CORS + error bodies + env header strip + length caps
- **PR #5** (3 items, ~4h): per-user rate limiter + 429 handler + Layer 6 ops items

## 9. Requirements before this is "internal-ready"

We commit to having the following true before we say this MCP is at standard for ~50-user internal use:

| # | Requirement | Status |
|---|---|---|
| R1 | Critical and High findings closed | ❌ PR #4 |
| R2 | Per-tool MCP-side audit log emitting structured JSON | ❌ PR #4 |
| R3 | Per-user rate limiting on writes | ❌ PR #5 |
| R4 | SSRF deny-list on outbound URL fetches | ❌ PR #4 |
| R5 | Killswitch script committed and tested | ⚠️ Written, awaiting commit |
| R6 | First baseline audit run, dated, committed to `docs/security-audits/` | ❌ Day 1 of baseline work |
| R7 | CI security floor active (pip-audit, bandit, gitleaks, trivy) | ❌ Day 2 of baseline work |
| R8 | Defender for Containers + KV enabled | ❌ Day 2 of baseline work |
| R9 | OWASP ZAP weekly scan, results in repo | ❌ Day 2 of baseline work |
| R10 | 1-page IR runbook published | ❌ PR #5 |
| R11 | ACR admin user disabled, MI `AcrPull` granted | ❌ PR #5 |
| R12 | KV purge protection enabled | ❌ Day 2 |
| R13 | Entra client secret expiry alert wired | ❌ PR #5 |

**Estimated total effort across all 13:** ~2 days of baseline + 5h PR #4 + 8h PR #5 = ~3-4 working days end-to-end.

## 10. Backlog (deferred, not blocking internal use)

| # | Item | Why deferred |
|---|---|---|
| B1 | Architecture E browser PKCE flow (Entra gap 5) | Code path dormant; needed only if `/zendesk-sso` is activated |
| B2 | Continuous Access Evaluation (CAE) for Entra (gap 4) | Significant work; only relevant if Architecture F reactivated. Documented as accepted risk for now. |
| B3 | Cookie security attributes on Architecture E (gap 6) | Cookie not currently written; ~6 lines when the PKCE callback ships |
| B4 | Certificate-based Entra credential (replace shared secret) | Eliminates rotation burden; not urgent if R13 expiry alert is in place |
| B5 | OWASP ZAP authenticated scan (deep tool-call coverage) | Unauth ZAP baseline is the starting point; authenticated scan adds 2-3h setup |
| B6 | Private Endpoints for Cosmos/KV/Blob | Overkill at 50 users; MI auth + firewall ACLs sufficient |
| B7 | Image signing / Notary v2 | Defender for Containers gets us 80% of supply-chain value |
| B8 | Splunk / Microsoft Sentinel SIEM | Log Analytics + Workbook is the line at our scale |
| B9 | Bug bounty programme | Ops weight too high; revisit if user base crosses ~200 |
| B10 | Third-party pentest engagement | Year-2 trigger; revisit when usage justifies ~$5-10k spend |

## 11. Audit cadence and follow-up

| Activity | Cadence |
|---|---|
| Self-audit (re-run aegis + oracle, refresh checklist, ZAP scan, secure-score delta) | **Monthly for first 3 months**, then quarterly. Dated reports committed to `docs/security-audits/YYYY-MM-DD.md`. |
| CI security floor | On every PR — automatic, no human input |
| Defender for Cloud secure-score review | Weekly email digest, action items rolled into next audit |
| OWASP ZAP weekly scan | Automated GitHub Action; new findings auto-open a GitHub issue for triage |
| Access review (Zendesk OAuth members, KV access, Cosmos RBAC, Container App operators) | Quarterly, captured in audit report |
| Cross-team peer review with Stefan/Boyan + one outside engineer | Annually |
| Killswitch `--status` mode test | Monthly, captured in audit report |

**Next planned follow-up session:** week of 2026-06-01 (see meeting invite). Goal: ship baseline doc + first dated audit + CI floor, agree PR #4 SSRF variant + audit-log impl choice, then schedule PR #4 deploy.

---

## Appendix A — Frameworks we map to

- **OWASP ASVS 4.0.x — Level 1.** Industry-recognised application security verification standard. L1 is the right tier for our risk profile (50 internal users, no compliance trigger). Higher levels are for high-stakes systems.
- **OWASP API Security Top 10 (2023).** API-shaped risks (BOLA, broken auth, SSRF, etc.). Our recent audit findings map 1:1 to API items.
- **MCP spec § Authorization + § Transports + § Security Considerations.** Protocol-mandated controls (OAuth 2.1 + PKCE, audience validation, SSRF mitigation, origin allowlisting).
- **CIS Microsoft Azure Foundations Benchmark v2.x.** Infra controls (IAM, Key Vault, Storage, Container Apps, Logging). Tracked passively via Defender for Cloud secure-score.

## Appendix B — Reference docs

- `docs/DESIGN_DECISIONS.md` — 8 active architectural decisions
- `docs/LIMITATIONS.md` — 14 accepted operational risks with revert triggers
- `docs/zendesk-mcp-workflows.html` — interactive sequence diagram of Arch C flows
- `deployment/azure/scripts/killswitch.sh` — 10-second revert script
- Vault: `~/Documents/ObsidianVault/Security/Architecture C Security Audit 2026-05-20.md` — master findings list + KQL primer + killswitch design rationale

---

*Document owner: Lukasz Pelcner. Sign-off cadence: monthly for first 3 months, quarterly thereafter. Internal use only.*
