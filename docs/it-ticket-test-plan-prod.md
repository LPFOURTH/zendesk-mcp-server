# IT Ticket Tool — Prod Test Plan

Run these tests with an MCP agent connected to **production** (`hotschedules.zendesk.com`, form ID `45108529620365`).
All tickets use `[test]` in the subject. Close them in Zendesk after verification.

**Prod-specific differences from dev:**
- SR BizApps tags use `sr_bizz_*` prefix (e.g. `sr_bizz_zendesk` vs `sr_zendesk`) — same friendly keys, server resolves automatically
- Incident EIT General requires **two** fields: `eit_general_subcategory` + `inc_eit_general_subcategory`
- Extended software lists (AI tools, zoom_phone, zoom_contact_center, ms_outlook, etc.)
- `access_request_type` includes `mailbox` option

---

## 0. Smoke Tests — BizApps / Zendesk (run first)

### 0.1 Incident — BizApps / Zendesk
```json
{
  "subject": "[test] Zendesk views not loading",
  "description": "Test ticket — Zendesk incident via PROD. Please ignore and close.",
  "classification": "incident",
  "incident_category": "bizapps",
  "incident_bizapps_item": "zendesk",
  "impact": "low",
  "location": "sofia",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify in Zendesk (prod):**
- Form = IT Support Request (form ID `45108529620365`)
- Classification = Incident, Category = BizApps
- Sub-category = Zendesk (tag `cl_inc_biz_app_zendesk`)
- Impact = Low, Location = Sofia
- CC shows Stefan.Nikolov@fourth.com

---

### 0.2 Service Request — BizApps / Zendesk
```json
{
  "subject": "[test] Request Zendesk access",
  "description": "Test ticket — Zendesk SR via PROD. Please ignore and close.",
  "classification": "service_request",
  "sr_category": "bizapps",
  "sr_bizapps_item": "zendesk",
  "impact": "low",
  "location": "sofia",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify in Zendesk (prod):**
- Classification = Service Request, SR Category = BizApps
- SR BizApps = Zendesk (tag `sr_bizz_zendesk` — prod-specific)
- CC shows Stefan.Nikolov@fourth.com

---

## 1. Incident — L2 Category Coverage

### 1.1 EIT Software
```json
{
  "subject": "[test] Slack not loading",
  "description": "Test ticket — Slack crash on PROD. Please ignore and close.",
  "classification": "incident",
  "incident_category": "eit_software",
  "incident_software_item": "slack",
  "impact": "low",
  "location": "sofia",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** Category = EIT Software, Sub-category = Slack.

---

### 1.2 EIT Software — Prod-only option (AI Copilot)
```json
{
  "subject": "[test] Copilot Studio not responding",
  "description": "Test ticket — AI Copilot Studio issue on PROD. Please ignore and close.",
  "classification": "incident",
  "incident_category": "eit_software",
  "incident_software_item": "ai_copilot_studio",
  "impact": "low",
  "location": "london",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** Sub-category = AI Copilot Studio (prod-only option, tag `cl_inc_soft_ai_copilot_studio`).

---

### 1.3 EIT Hardware
```json
{
  "subject": "[test] External screen flickering",
  "description": "Test ticket — screen flickers on docking station. Please ignore and close.",
  "classification": "incident",
  "incident_category": "eit_hardware",
  "incident_hardware_item": "external_screen",
  "impact": "low",
  "location": "remote_uk",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** Category = EIT Hardware, Sub-category = External Screen.

---

### 1.4 EIT Security Ops
```json
{
  "subject": "[test] Phishing email received",
  "description": "Test ticket — phishing attempt on PROD. Please ignore and close.",
  "classification": "incident",
  "incident_category": "eit_security_ops",
  "incident_security_item": "phishing",
  "impact": "high",
  "location": "austin",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** Category = EIT Security Ops, Sub-category = Phishing, Impact = High.

---

## 2. Incident — EIT General (dual-field, prod-only)

Prod requires both `eit_general_subcategory` (the EIT General SR field) and `inc_eit_general_subcategory` (the incident-specific sub-field) when `incident_category = eit_general`.

### 2.1 EIT General — Access Management
```json
{
  "subject": "[test] Account locked out",
  "description": "Test ticket — account lockout on PROD. Please ignore and close.",
  "classification": "incident",
  "incident_category": "eit_general",
  "eit_general_subcategory": "access_request",
  "inc_eit_general_subcategory": "access_management",
  "impact": "low",
  "location": "sofia",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** Both EIT General subcategory (`eit_access_request_3`) and incident EIT General (`access_management`) fields set.

---

### 2.2 EIT General — Facilities / Door Access (L4)
```json
{
  "subject": "[test] Office door access not working",
  "description": "Test ticket — badge access issue on PROD. Please ignore and close.",
  "classification": "incident",
  "incident_category": "eit_general",
  "eit_general_subcategory": "fourth_office",
  "inc_eit_general_subcategory": "facilities",
  "fourth_office_type": "door_access",
  "impact": "low",
  "location": "london",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** Incident EIT General = Facilities; Fourth Office Type = Door Access.

---

### 2.3 EIT General — Email Collaboration
```json
{
  "subject": "[test] Distribution list not receiving emails",
  "description": "Test ticket — email collab incident on PROD. Please ignore and close.",
  "classification": "incident",
  "incident_category": "eit_general",
  "eit_general_subcategory": "distribution_list",
  "inc_eit_general_subcategory": "email_collaboration",
  "impact": "low",
  "location": "sofia",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** Incident EIT General = Email Collaboration.

---

### 2.4 EIT General — Virtual Machine
```json
{
  "subject": "[test] RDS Denver not connecting",
  "description": "Test ticket — RDS Denver timeout on PROD. Please ignore and close.",
  "classification": "incident",
  "incident_category": "eit_general",
  "eit_general_subcategory": "virtual_machine",
  "inc_eit_general_subcategory": "virtual_machine",
  "virtual_machine_type": "remote_desktop_denver",
  "impact": "medium",
  "location": "austin",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** Incident EIT General = Virtual Machine; VM Type = Remote Desktop Denver.

---

## 3. Service Request — L2 Category Coverage

### 3.1 EIT Software
```json
{
  "subject": "[test] Request Adobe Acrobat license",
  "description": "Test ticket — Adobe Acrobat SR on PROD. Please ignore and close.",
  "classification": "service_request",
  "sr_category": "eit_software",
  "sr_software_item": "adobe_acrobat",
  "impact": "low",
  "location": "chicago",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** SR Category = EIT Software, Sub-category = Adobe Acrobat.

---

### 3.2 EIT Software — Prod-only option (Zoom Phone)
```json
{
  "subject": "[test] Request Zoom Phone licence",
  "description": "Test ticket — Zoom Phone SR on PROD. Please ignore and close.",
  "classification": "service_request",
  "sr_category": "eit_software",
  "sr_software_item": "zoom_phone",
  "impact": "low",
  "location": "london",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** Sub-category = Zoom Phone (prod-only option).

---

### 3.3 EIT Hardware
```json
{
  "subject": "[test] Request replacement laptop",
  "description": "Test ticket — laptop replacement SR on PROD. Please ignore and close.",
  "classification": "service_request",
  "sr_category": "eit_hardware",
  "sr_hardware_item": "laptop",
  "impact": "low",
  "location": "sofia",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** SR Category = EIT Hardware, Sub-category = Laptop.

---

### 3.4 BizApps — Salesforce
```json
{
  "subject": "[test] Request Salesforce access",
  "description": "Test ticket — Salesforce SR on PROD. Please ignore and close.",
  "classification": "service_request",
  "sr_category": "bizapps",
  "sr_bizapps_item": "salesforce",
  "impact": "low",
  "location": "sofia",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** SR BizApps = Salesforce (tag `sr_bizz_salesforce`).

---

### 3.5 BizApps — GDPR Request (prod-only option)
```json
{
  "subject": "[test] GDPR data request via BizApps",
  "description": "Test ticket — GDPR via BizApps on PROD. Please ignore and close.",
  "classification": "service_request",
  "sr_category": "bizapps",
  "sr_bizapps_item": "gdpr_request",
  "impact": "low",
  "location": "sofia",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** SR BizApps = GDPR Request (tag `sr_bizz_gdpr_request`, prod-only option).

---

## 4. EIT General SR — L4 Paths

### 4.1 Access Request — Mailbox (prod-only)
```json
{
  "subject": "[test] Request shared mailbox access",
  "description": "Test ticket — mailbox access request on PROD. Please ignore and close.",
  "classification": "service_request",
  "sr_category": "eit_general",
  "eit_general_subcategory": "access_request",
  "access_request_type": "mailbox",
  "impact": "low",
  "location": "london",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** Access Request Type = Mailbox (tag `eit_gen_mailbox`, prod-only option).

---

### 4.2 Distribution List — Create
```json
{
  "subject": "[test] Create EMEA distribution list",
  "description": "Test ticket — new distribution list on PROD. Please ignore and close.",
  "classification": "service_request",
  "sr_category": "eit_general",
  "eit_general_subcategory": "distribution_list",
  "distribution_list_action": "create",
  "impact": "low",
  "location": "london",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** EIT General = Distribution List, Action = Create.

---

### 4.3 Virtual Machine — Windows 365
```json
{
  "subject": "[test] Request Windows 365 Cloud PC",
  "description": "Test ticket — Cloud PC request on PROD. Please ignore and close.",
  "classification": "service_request",
  "sr_category": "eit_general",
  "eit_general_subcategory": "virtual_machine",
  "virtual_machine_type": "windows_365_cloud_pc",
  "impact": "low",
  "location": "remote_uk",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** EIT General = Virtual Machine, Type = Windows 365 Cloud PC.

---

## 5. Attachments

### 5.1 Attachment via URL
```json
{
  "subject": "[test] Application error with screenshot",
  "description": "Test ticket — login error screenshot on PROD. Please ignore and close.",
  "classification": "incident",
  "incident_category": "eit_software",
  "incident_software_item": "other",
  "impact": "low",
  "location": "remote_uk",
  "cc_emails": ["Stefan.Nikolov@fourth.com"],
  "attachments": [
    {"url": "https://upload.wikimedia.org/wikipedia/commons/4/47/PNG_transparency_demonstration_1.png", "filename": "error_screenshot.png"}
  ]
}
```
**Verify:** Ticket comment includes the attached file; CC present.

---

## 6. Validation — Negative Cases

### 6.1 Both incident_category and sr_category
```json
{
  "subject": "[test] Conflict validation",
  "description": "Should fail.",
  "classification": "incident",
  "incident_category": "eit_software",
  "sr_category": "eit_software",
  "impact": "low",
  "location": "sofia"
}
```
**Expect:** Tool returns error — cannot pass both fields.

---

### 6.2 Incident EIT General without inc_eit_general_subcategory
```json
{
  "subject": "[test] Missing dual-field validation",
  "description": "Test ticket — omitting inc_eit_general_subcategory on prod. Please ignore and close.",
  "classification": "incident",
  "incident_category": "eit_general",
  "eit_general_subcategory": "access_request",
  "impact": "low",
  "location": "sofia"
}
```
**Observe:** Ticket created but `inc_eit_general_subcategory` field left blank in Zendesk. Confirms the field is required when the category is `eit_general` on prod.

---

## 7. Impact and Location Variants

### 7.1 Very High Impact
```json
{
  "subject": "[test] Full site email outage",
  "description": "Test ticket — site-wide outage on PROD. Please ignore and close.",
  "classification": "incident",
  "incident_category": "eit_software",
  "incident_software_item": "outlook",
  "impact": "very_high",
  "location": "sofia",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** Impact = Very High.

---

### 7.2 Remote UK location
```json
{
  "subject": "[test] VPN not connecting from home",
  "description": "Test ticket — VPN from home on PROD. Please ignore and close.",
  "classification": "incident",
  "incident_category": "eit_general",
  "eit_general_subcategory": "other",
  "impact": "low",
  "location": "remote_uk",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** Location = Remote UK.
