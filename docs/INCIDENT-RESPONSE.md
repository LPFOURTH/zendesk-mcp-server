# Incident Response — Zendesk MCP

> One page. Read in 60 seconds. Act in 5 minutes.
> Owner: Lukasz Pelcner. Backup: Boyan.

---

## When to declare an incident

Any of these:
- `/mcp/dev` or `/mcp/prod` returns 5xx for >5 min
- Defender for Cloud alert on container compromise or KV anomalous access
- Audit log shows unauthorized write activity (someone writing tickets / articles outside their normal pattern)
- A user reports "a ticket got modified I didn't touch" or "Claude did something I didn't ask"
- Entra OAuth or Zendesk OAuth dance breaks for everyone
- Cosmos DB returning 5xx or 429s sustained

If unsure → declare it. Easier to stand down than to escalate late.

## Roles (1 person can wear all hats)

- **IC (Incident Commander):** Lukasz Pelcner. Backup: Boyan.
- **Comms:** same as IC unless explicitly delegated.
- **Tech lead:** whoever is most familiar with the affected component.

## First 5 minutes

1. **Snapshot logs** — they'll roll if you don't:
   ```bash
   az containerapp logs show -n fourth-zendesk-mcp-server -g fourth-ai-prod \
     --revision $(az containerapp show -n fourth-zendesk-mcp-server -g fourth-ai-prod \
       --query "properties.latestRevisionName" -o tsv) \
     --tail 1000 > ~/incidents/$(date +%Y%m%d-%H%M)-mcp.log
   ```

2. **If user impact > information** → run the killswitch:
   ```bash
   cd ~/PycharmProjects/zendesk_product_mentor/zendesk-mcp-server
   bash deployment/azure/scripts/killswitch.sh --force
   ```
   ~10 seconds. Reverts traffic to last-known-good revision.

3. **Post in Teams `#ai-enablement`** (or whichever channel is current):
   > 🚨 **Incident declared on Zendesk MCP** — `{1-line symptom}`. Investigating. IC: Lukasz. Updates here.

## First 30 minutes

- **Identify scope:** Who's affected? What data was touched? What's the blast radius?
- **Form a root cause hypothesis** — write it down even if it's wrong, gives Boyan/Stefan something to react to.
- **Decide:** extend mitigation (e.g. disable a specific tool via `DISABLED_TOOLS` env var), escalate to Stefan / Toma, or stand down.

## After mitigation

- Open `docs/incidents/YYYY-MM-DD-<slug>.md` using the post-mortem template below.
- Schedule blameless review within 1 week (Lukasz + Boyan + anyone affected).
- Close out by either fixing the root cause or adding a `LIMITATIONS.md` entry with revert triggers.

## Comms templates (paste-ready)

**Declared:**
> 🚨 Incident declared on Zendesk MCP at HH:MM UTC. Symptom: `{1-line}`. IC: Lukasz. We're investigating. Updates here every 15 min until resolved.

**Mitigation in place:**
> ⚠️ Killswitch fired — traffic reverted to revision `--0000XXX`. Service should be restored. Investigating root cause. ETA on post-mortem: 24h.

**Resolved:**
> ✅ Resolved at HH:MM UTC. Root cause: `{1-line}`. Post-mortem: `docs/incidents/YYYY-MM-DD-<slug>.md`. Thanks all.

**Stand down (false alarm):**
> 🟢 False alarm — `{what was actually happening}`. No user impact. No further action.

## Post-mortem template

```markdown
# Incident YYYY-MM-DD — <slug>

**Severity:** S1 / S2 / S3 (S1 = users blocked, S2 = degraded, S3 = internal-only)
**Duration:** HH:MM UTC → HH:MM UTC (Nh Nm)
**Detected by:** alert / user report / monitoring / chance
**IC:** Lukasz

## Timeline (UTC)
- HH:MM — first signal
- HH:MM — declared
- HH:MM — killswitch fired (if applicable)
- HH:MM — mitigation confirmed
- HH:MM — resolved

## What happened
1–2 paragraphs. Plain English.

## Why it happened
Root cause. Not "human error" — what enabled the error.

## What we did well
Honestly — what helped us recover fast?

## What we did poorly
Honestly — what slowed us down?

## Action items
- [ ] AI 1 — owner — due date
- [ ] AI 2 — owner — due date

## Where to look in logs
Specific KQL queries / log paths for next time someone investigates similar.
```

## Don't do (in an incident)

- Don't push to `main`/`fourth/main` under pressure — use the killswitch first, push the fix calmly later
- Don't `az containerapp update --set-env-vars` with a partial list (it replaces the whole env-var collection — see RISK-013)
- Don't delete the bad revision — keep it for forensics
- Don't blame individuals in the post-mortem — blame the system that let the bug ship

---

*Last updated 2026-05-26. Review quarterly with the security audit.*
