"""Constants for Zendesk MCP: HTML templates, environment configs, and section/author IDs."""

US_TEMPLATE_HEADER = """<h2 class="first:mt-1.5">What's New?</h2>

<p>
  <span class="wysiwyg-font-size-medium">
    Use the links below to find out more about each item release for
    <a href="#h_01JQXYFHC80BWHZKT57J5HNC7N">Labor Main</a>,
    <a href="#h_01JQXYFHC8R57QW1SDFY29RW86">Platform</a>, and
    <a href="#h_01JQXYVPMAK8ZP2EWXW9A58577">General Improvements</a>
  </span>
</p>

<p>
  <span class="wysiwyg-font-size-medium"><strong>Release date:</strong> DD Month name YYYY</span>
</p>

<p>&nbsp;</p>

<h2 id="h_01JQXYFHC80BWHZKT57J5HNC7N">Labor Main</h2>
<p>&nbsp;</p>

<h2 id="h_01JQXYFHC8R57QW1SDFY29RW86">Platform</h2>
<p>&nbsp;</p>
<h2 id="h_01JQXYVPMAK8ZP2EWXW9A58577">General Improvements</h2>
<p>A list of defect/bug fixes</p>
<p>&nbsp;</p>
<h2>All features - move them to the right place</h2>
"""

US_TEMPLATE_MIDDLE = """
<p>
  <span class="wysiwyg-font-size-medium">---------------------------------------------------------------</span>
</p>

<p class="first:mt-1.5">
  <em>
    <strong>
      <span class="wysiwyg-font-size-medium wysiwyg-color-black">
        This information will be removed from here and used to create separate articles for each feature
      </span>
    </strong>
  </em>
</p>

<h2 class="first:mt-1.5">Release Note Info/Steps</h2>
"""

TEMPLATE_FEATURE_DETAILS_FOOTER = """
<ul>
  <li><span class="wysiwyg-font-size-medium">Enabled by default? - Y/N</span></li>
  <li><span class="wysiwyg-font-size-medium">Set up by customer admin? - Y/N</span></li>
  <li><span class="wysiwyg-font-size-medium">Enable via support ticket? - Y/N</span></li>
  <li><span class="wysiwyg-font-size-medium">Affects configuration or data? - Y/N</span></li>
  <li><span class="wysiwyg-font-size-medium">Roles affected: If applicable</span></li>
</ul>

<h2>Instructions/Screenshots</h2>

<p>
  <span class="wysiwyg-font-size-medium">
    Description and instructions for enabling (if applicable) and using the new/changed functionality. If there's a large amount of information, include headers (which can be turned into a table of contents if required).
  </span>
</p>

<p>&nbsp;</p>
"""

UK_TEMPLATE_HEADER = """
<h2 class="first:mt-1.5">What's New?</h2>
"""

UK_TEMPLATE_MIDDLE = """
<p>
  <span class="wysiwyg-font-size-medium">
    Use the links above to find out more about this release.
  </span>
</p>
<p>
  <span class="wysiwyg-font-size-medium">
    <strong>Release date:</strong> DD Month name YYYY
  </span>
</p>
<p>&nbsp;</p>

<p>
  <span class="wysiwyg-font-size-medium">---------------------------------------------------------------</span>
</p>

<p class="first:mt-1.5">
  <em>
    <strong>
      <span class="wysiwyg-font-size-medium wysiwyg-color-black">
        This information will be removed from here and used to create separate articles for each feature
      </span>
    </strong>
  </em>
</p>

<h2 class="first:mt-1.5">Release Note Info/Steps</h2>
"""

ENVIRONMENTS = {
    "prod": {
        "base_url": "https://hotschedules.zendesk.com",
        "section_id": 5404916050957,
        "permission_group_id": 1721132,
        "user_segment_id": 171472,
        "author_id": 397321102531,
    },
    "dev": {
        "base_url": "https://hotschedules1626093811.zendesk.com",
        "section_id": 34086316530573,
        "permission_group_id": 4407361031693,
        "user_segment_id": None,
        "author_id": 420190638631,
    },
}

# ---------------------------------------------------------------------------
# IT Support Request form
# Field IDs are account-specific. "dev" = sandbox2 (hotschedules1760632913).
# To update after a form change: see docs/it-form-update-guide.md
# ---------------------------------------------------------------------------
IT_FORM_CONFIG: dict[str, dict] = {
    "dev": {
        "form_id": 40492655042957,
        "fields": {
            "classification": 40492783035149,
            "sr_category": 44259226554637,
            "inc_category": 44392062108813,
            "sr_software": 40494082746765,
            "sr_hardware": 44390546919821,
            "sr_bizapps": 40494132085517,
            "sr_security": 44390551532813,
            "inc_software": 40493871814029,
            "inc_hardware": 40493602774029,
            "inc_bizapps": 40493887086221,
            "inc_security": 40493792674189,
            "eit_general": 44390531736717,
            "access_request_type": 44391620839309,
            "distribution_list_action": 44391738257165,
            "fourth_office_type": 44391606775949,
            "email_trace_type": 44391610412301,
            "restore_data_type": 44391716119693,
            "vm_type": 44391748764941,
            "impact": 42474276604557,
            "location": 42474440198925,
            "additional_location_info": 42474481817485,
        },
    },
    "prod": {
        "form_id": 40703005823501,
        "fields": None,  # TODO: fill after prod access — see docs/it-form-update-guide.md
    },
}

IT_CLASSIFICATION_VALUES = {
    "incident": "_incident_-_something_is_broken_or_not_working",
    "service_request": "service_request_-_i_need_something",
}
IT_INCIDENT_CATEGORY_VALUES = {
    "bizapps": "inc_bizapps",
    "eit_software": "inc_eit_software",
    "eit_hardware": "inc_eit_hardware",
    "eit_general": "inc_eit_general",
    "eit_security_ops": "inc_eit_security_ops",
}
IT_SR_CATEGORY_VALUES = {
    "bizapps": "sr_bizapps",
    "eit_software": "sr_eit_software",
    "eit_hardware": "sr_eit_hardware",
    "eit_general": "sr_eit_general",
    "eit_security_ops": "sr_eit_security_ops",
}
IT_IMPACT_VALUES = {
    "low": "it_impact_low",
    "medium": "it_impact_medium",
    "high": "it_impact_high",
    "very_high": "it_impact_very_high",
}
IT_LOCATION_VALUES = {
    "atlanta": "location/office_atlanta",
    "austin": "location/office_austin",
    "cape_town": "location/office_cape_town",
    "denver": "location/office_denver",
    "london": "location/office_london",
    "macclesfield": "location/office_macclesfield",
    "miami": "location/office_miami",
    "remote": "location/office_remote",
    "shanghai": "location/office_shanghai",
    "sofia": "location/office_sofia",
    "sydney": "location/office_sydney",
    "tampa": "location/office_tampa",
    "ukraine": "location/office_ukraine",
    "other": "location/office_other",
    "remote_uk": "location/office_remote_-_uk",
    "remote_us": "location/office_remote_-_us",
    "remote_germany": "location/office_remote_-_germany",
    "remote_india": "location/office_remote_-_india",
    "remote_austria": "location/office_remote_-_austria",
    "remote_armenia": "location/office_remote_-_armenia",
    "remote_poland": "location/office_remote_-_poland",
    "remote_thailand": "location/office_remote_-_thailand",
    "remote_argentina": "location/office_remote_-_argentina",
    "remote_honduras": "location/office_remote_-_honduras",
    "remote_colombia": "location/office_remote_-_colombia",
    "remote_south_africa": "location/office_remote_-_south_africa",
    "remote_ukraine": "location/office_remote_-_ukraine",
    "remote_philippines": "location/office_remote_-_philippines",
}
IT_INC_SOFTWARE_VALUES = {
    "1password": "cl_inc_soft_1password",
    "8x8": "cl_inc_soft_8x8",
    "adobe_acrobat": "cl_inc_soft_adobe_acrobat",
    "adobe_creative_cloud": "cl_inc_soft_adobe_creative_cloud",
    "adobe_photoshop": "cl_inc_soft_adobe_photoshop",
    "bacs_payment_services": "cl_inc_soft_bacs_payment_services",
    "confluence": "cl_inc_soft_confluence",
    "copilot": "cl_inc_soft_copilot",
    "denver_other": "cl_inc_soft_denver_-_other",
    "denver_timeclock_manager": "cl_inc_soft_denver_-_timeclock_manager",
    "denver_ua": "cl_inc_soft_denver_-_ua",
    "denver_ua_database": "cl_inc_soft_denver_-_ua_database/sql_issues",
    "developer_apple_id": "cl_inc_soft_developer_apple_id",
    "github": "cl_inc_soft_github",
    "hmrc_tools": "cl_inc_soft_hmrc_tools",
    "hotschedules_app": "cl_inc_soft_hotschedules_app",
    "hs_support_site": "cl_inc_soft_hs-support_site",
    "intranet": "cl_inc_soft_intranet",
    "lever": "cl_inc_soft_lever",
    "logmein": "cl_inc_soft_logmein",
    "lucidchart": "cl_inc_soft_lucidchart",
    "ms_excel": "cl_inc_soft_ms_excel_",
    "ms_onenote": "cl_inc_soft_ms_onenote",
    "ms_powerpoint": "cl_inc_soft_ms_powerpoint_",
    "ms_project": "cl_inc_soft_ms_project",
    "ms_visio": "cl_inc_soft_ms_visio",
    "ms_visual_studio": "cl_inc_soft_ms_visual_studio",
    "ms_word": "cl_inc_soft_ms_word",
    "navan": "cl_inc_soft_navan",
    "onedrive": "cl_inc_soft_onedrive",
    "openvpn": "cl_inc_soft_openvpn",
    "peoplesystem_wfm": "cl_inc_soft_peoplesystem/wfm",
    "prism_hrp": "cl_inc_soft_prism_/_hrp",
    "rally": "cl_inc_soft_rally",
    "redgate": "cl_inc_soft_redgate",
    "resharper": "cl_inc_soft_resharper",
    "sapling": "cl_inc_soft_sapling",
    "schoox": "cl_inc_soft_schoox",
    "seismic": "cl_inc_soft_seismic",
    "sharpen": "cl_inc_soft_sharpen",
    "smartsheet": "cl_inc_soft_smartsheet",
    "suitepeople": "cl_inc_soft_suitepeople",
    "sumo": "cl_inc_soft_sumo",
    "testrail": "cl_inc_soft_testrail",
    "web_browser": "cl_inc_soft_web_browser",
    "windows_upgrade": "cl_inc_soft_windows_upgrade",
    "xml_spy": "cl_inc_soft_xml_spy",
    "other": "other_inc_soft",
}
IT_INC_HARDWARE_VALUES = {
    "cable": "cl_inc_hd_cable",
    "desktop": "cl_inc_hd_desktop",
    "docking_station": "cl_inc_hd_docking_station",
    "external_screen": "cl_inc_hd_external_screen",
    "keyboard": "cl_inc_hd_keyboard",
    "laptop": "cl_inc_hd_laptop",
    "mouse": "cl_inc_hd_mouse",
    "printer": "cl_inc_hd_printer",
    "other": "cl_inc_hd_other",
}
IT_INC_BIZAPPS_VALUES = {
    "zendesk": "cl_inc_biz_app_zendesk",
    "salesforce": "cl_inc_biz_app_salesforce",
    "netsuite": "cl_inc_biz_app_netsuite",
    "jira": "cl_inc_biz_app_jira",
    "jitterbit": "cl_inc_biz_app_jitterbit",
    "docusign": "cl_inc_biz_app_docusign",
    "other": "other_inc_biz_app_docusign",
}
IT_INC_SECURITY_VALUES = {
    "email_blocked": "cl_inc_sec_email_blocked",
    "password_compromised": "cl_inc_sec_password_compromised",
    "phishing": "cl_inc_sec_phished_or_phishing_attempt",
    "other": "other_inc_sec",
}
IT_SR_SOFTWARE_VALUES = {
    "1password": "cl_ser_req_1password",
    "8x8": "cl_ser_req_8x8",
    "admin_by_request": "cl_ser_req_admin_by_request",
    "adobe_acrobat": "cl_ser_req_adobe_acrobat",
    "adobe_creative_cloud": "cl_ser_req_adobe_creative_cloud",
    "adobe_photoshop": "cl_ser_req_adobe_photoshop",
    "concur": "cl_ser_req_concur",
    "confluence": "cl_ser_req_confluence",
    "copilot": "cl_ser_req_copilot",
    "denver_other": "cl_ser_req_denver_other",
    "denver_timeclock_manager": "cl_ser_req_denver_timeclock_manager",
    "denver_ua": "cl_ser_req_denver_ua",
    "denver_ua_database": "cl_ser_req_denver_-_ua_database_sql_issues",
    "gemalto_bacs": "cl_ser_req_gemalto_bacs_payment_services",
    "github": "cl_ser_req_github",
    "hmrc_tools": "cl_ser_req_hmrc_tools",
    "hotschedules_app": "cl_ser_req_hotschedules_app",
    "hs_support_site": "cl_ser_req_hs-support_site",
    "intranet": "cl_ser_req_intranet",
    "lever": "cl_ser_req_lever",
    "logmein": "cl_ser_req_logmein",
    "lucidchart": "cl_ser_req_lucidchart",
    "managed_apple_id": "cl_ser_req_managed_apple_id",
    "ms_excel": "cl_ser_req_ms_excel_",
    "ms_onenote": "cl_ser_req_ms_onenote",
    "ms_powerpoint": "cl_ser_req_ms_powerpoint",
    "ms_project": "cl_ser_req_ms_project",
    "ms_visio": "cl_ser_req_ms_visio",
    "ms_word": "cl_ser_req_ms_word",
    "navan": "cl_ser_req_navan",
    "onedrive": "cl_ser_req_onedrive",
    "openvpn": "cl_ser_req_openvpn",
    "peoplesystem_wfm": "cl_ser_req_peoplesystem_wfm",
    "prism_hrp": "cl_ser_req_prism_hrp",
    "rally": "cl_ser_req_rally",
    "redgate": "cl_ser_req_redgate",
    "resharper": "cl_ser_req_resharper",
    "sapling": "cl_ser_req_sapling",
    "schoox": "cl_ser_req_schoox",
    "seismic": "cl_ser_req_seismic",
    "sharpen": "cl_ser_req_sharpen",
    "smartsheet": "cl_ser_req_smartsheet",
    "suitepeople": "cl_ser_req_suitepeople",
    "sumo": "cl_ser_req_sumo",
    "testrail": "cl_ser_req_testrail",
    "visual_studio": "cl_ser_req_visual_studio",
    "web_browser": "cl_ser_req_web_browser",
    "windows_upgrade": "cl_ser_req_windows_upgrade",
    "xml_spy": "cl_ser_req_xml_spy",
    "other": "other_cl_ser_req",
}
IT_SR_HARDWARE_VALUES = {
    "cable": "eit_cable_1",
    "desktop": "eit_desktop_2",
    "docking_station": "eit_docking_station_3",
    "external_screen": "eit_external_screen_4",
    "headset": "eit_headset_5",
    "keyboard": "eit_keyboard_6",
    "laptop": "eit_laptop_7",
    "mouse": "eit_mouse_8",
    "monitor": "eit_monitor_9",
    "printer": "eit_printer_10",
    "other": "eit_other_11",
}
IT_SR_BIZAPPS_VALUES = {
    "zendesk": "sr_zendesk",
    "salesforce": "sr_salesforce",
    "netsuite": "sr_netsuite",
    "jira": "sr_jira",
    "jitterbit": "sr_jitterbit",
    "docusign": "sr_docusign",
    "data_team": "sr_data_team",
    "other": "other_sr",
}
IT_SR_SECURITY_VALUES = {
    "security_request": "eit_security_request_1",
    "unblock_website": "eit_unblock_website_2",
    "unblock_email": "eit_unblock_email_3",
    "unblock_software": "eit_unblock_software_4",
    "audit": "eit_audit_5",
    "other": "eit_other_6",
}
IT_EIT_GENERAL_VALUES = {
    "gdpr_request": "eit_gdpr_request_1",
    "lad_maintenance": "eit_lad_maintenance_2",
    "access_request": "eit_access_request_3",
    "distribution_list": "eit_distribution_list_group_4",
    "fourth_office": "eit_fourth_office_5",
    "email_trace": "eit_email_trace_6",
    "restore_lost_data": "eit_restore_lost_data_7",
    "virtual_machine": "eit_virtual_machine_request_8",
    "other": "eit_other_9",
}
IT_ACCESS_REQUEST_VALUES = {
    "network_drive": "eit_gen_network_drive_1",
    "security_group": "eit_gen_security_group_2",
    "web_portal": "eit_gen_web_portal_3",
    "other": "eit_gen_other_4",
}
IT_DISTRIBUTION_LIST_VALUES = {
    "create": "dist_list_create",
    "update": "dist_list_update",
    "delete": "dist_list_delete",
    "other": "dist_list_other",
}
IT_FOURTH_OFFICE_VALUES = {
    "desk_move": "eit_gen_desk_move_1",
    "office_move": "eit_gen_office_move_2",
    "door_access": "eit_gen_door_access_3",
    "printer_access": "eit_gen_printer_access_4",
    "other": "eit_gen_other_5",
}
IT_EMAIL_TRACE_VALUES = {
    "fourth_customer_email": "eit_gen_fourth_customer_email_1",
    "fourth_user_email": "eit_gen_fourth_user_email_2",
    "other": "eit_gen_other_3",
}
IT_RESTORE_DATA_VALUES = {
    "network_drives": "restore_network_drives",
    "sharepoint": "restore_sharepoint",
    "onedrive": "restore_onedrive",
    "emails": "restore_emails",
    "other": "restore_other",
}
IT_VM_VALUES = {
    "remote_desktop_denver": "vm_rds_denver",
    "windows_365_cloud_pc": "vm_win365_cloudpc",
    "other": "vm_other",
}
