# IT Ticket Tool — Dev (Sandbox) Test Plan

Run these tests with an MCP agent connected to the **dev sandbox** (`hotschedules1760632913.zendesk.com`).
All tickets use `[test]` in the subject. Close them in Zendesk after verification.

---

## 0. Smoke Tests — BizApps / Zendesk (run first)

### 0.1 Incident — BizApps / Zendesk
```json
{
  "subject": "[test] Zendesk views not loading",
  "description": "Test ticket — Zendesk incident via dev sandbox. Please ignore and close.",
  "classification": "incident",
  "incident_category": "bizapps",
  "incident_bizapps_item": "zendesk",
  "impact": "low",
  "location": "sofia",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify in Zendesk (dev):**
- Form = IT Support Request
- Classification = Incident, Category = BizApps
- Sub-category = Zendesk (tag `cl_inc_biz_app_zendesk`)
- Impact = Low, Location = Sofia
- CC shows Stefan.Nikolov@fourth.com

---

### 0.2 Service Request — BizApps / Zendesk
```json
{
  "subject": "[test] Request Zendesk access",
  "description": "Test ticket — Zendesk SR via dev sandbox. Please ignore and close.",
  "classification": "service_request",
  "sr_category": "bizapps",
  "sr_bizapps_item": "zendesk",
  "impact": "low",
  "location": "sofia",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify in Zendesk (dev):**
- Classification = Service Request, SR Category = BizApps
- SR BizApps = Zendesk (tag `sr_zendesk`)
- CC shows Stefan.Nikolov@fourth.com

---

## 1. Incident — L2 Category Coverage

### 1.1 EIT Software
```json
{
  "subject": "[test] Slack not loading",
  "description": "Test ticket — Slack crash. Please ignore and close.",
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

### 1.2 EIT Hardware
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

### 1.3 EIT Security Ops
```json
{
  "subject": "[test] Phishing email received",
  "description": "Test ticket — phishing attempt. Please ignore and close.",
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

### 1.4 EIT General (no L4)
```json
{
  "subject": "[test] General IT issue",
  "description": "Test ticket — EIT General other. Please ignore and close.",
  "classification": "incident",
  "incident_category": "eit_general",
  "eit_general_subcategory": "other",
  "impact": "low",
  "location": "sofia",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** Category = EIT General, EIT General subcategory = Other. No L4 field expected.

---

### 1.5 EIT General — Access Request (L4)
```json
{
  "subject": "[test] Account locked out",
  "description": "Test ticket — account lockout. Please ignore and close.",
  "classification": "incident",
  "incident_category": "eit_general",
  "eit_general_subcategory": "access_request",
  "access_request_type": "network_drive",
  "impact": "low",
  "location": "london",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** EIT General = Access Request, Access Request Type = Network Drive.

---

## 2. Service Request — L2 Category Coverage

### 2.1 EIT Software
```json
{
  "subject": "[test] Request Adobe Acrobat license",
  "description": "Test ticket — Adobe Acrobat request. Please ignore and close.",
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

### 2.2 EIT Hardware
```json
{
  "subject": "[test] Request replacement laptop",
  "description": "Test ticket — laptop replacement. Please ignore and close.",
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

### 2.3 EIT Security Ops
```json
{
  "subject": "[test] Request website unblock",
  "description": "Test ticket — unblock website. Please ignore and close.",
  "classification": "service_request",
  "sr_category": "eit_security_ops",
  "sr_security_item": "unblock_website",
  "impact": "low",
  "location": "sofia",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** SR Category = EIT Security Ops, Sub-category = Unblock Website.

---

### 2.4 BizApps / Salesforce
```json
{
  "subject": "[test] Request Salesforce access",
  "description": "Test ticket — Salesforce access. Please ignore and close.",
  "classification": "service_request",
  "sr_category": "bizapps",
  "sr_bizapps_item": "salesforce",
  "impact": "low",
  "location": "sofia",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** SR BizApps = Salesforce (tag `sr_salesforce`).

---

## 3. EIT General SR — L4 Paths

### 3.1 Access Request — Network Drive
```json
{
  "subject": "[test] Request access to shared network drive",
  "description": "Test ticket — Finance shared drive. Please ignore and close.",
  "classification": "service_request",
  "sr_category": "eit_general",
  "eit_general_subcategory": "access_request",
  "access_request_type": "network_drive",
  "impact": "low",
  "location": "london",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** EIT General = Access Request, Type = Network Drive.

---

### 3.2 Distribution List — Create
```json
{
  "subject": "[test] Create distribution list for EMEA team",
  "description": "Test ticket — new distribution list. Please ignore and close.",
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

### 3.3 Virtual Machine — Windows 365
```json
{
  "subject": "[test] Request Windows 365 Cloud PC",
  "description": "Test ticket — Cloud PC request. Please ignore and close.",
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

### 3.4 GDPR Request (no L4)
```json
{
  "subject": "[test] GDPR data access request",
  "description": "Test ticket — GDPR request. Please ignore and close.",
  "classification": "service_request",
  "sr_category": "eit_general",
  "eit_general_subcategory": "gdpr_request",
  "impact": "low",
  "location": "sofia",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** EIT General = GDPR Request, no L4 field written.

---

## 4. Attachments

### 4.1 Attachment via URL
```json
{
  "subject": "[test] Application error with screenshot",
  "description": "Test ticket — login error screenshot. Please ignore and close.",
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

## 5. Validation — Negative Cases

### 5.1 Both incident_category and sr_category
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

### 5.2 SR field passed on incident
```json
{
  "subject": "[test] Wrong branch validation",
  "description": "SR field on incident — should be ignored or rejected.",
  "classification": "incident",
  "incident_category": "bizapps",
  "sr_bizapps_item": "zendesk",
  "impact": "low",
  "location": "sofia"
}
```
**Expect:** `sr_bizapps_item` ignored; no SR field written.

---

## 6. Impact and Location Variants

### 6.1 Very High Impact
```json
{
  "subject": "[test] Full site email outage",
  "description": "Test ticket — site-wide outage. Please ignore and close.",
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

### 6.2 Remote US location
```json
{
  "subject": "[test] VPN not connecting from home",
  "description": "Test ticket — VPN from home. Please ignore and close.",
  "classification": "incident",
  "incident_category": "eit_general",
  "eit_general_subcategory": "other",
  "impact": "low",
  "location": "remote_us",
  "cc_emails": ["Stefan.Nikolov@fourth.com"]
}
```
**Verify:** Location = Remote US.
