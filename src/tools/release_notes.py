from __future__ import annotations

import json
import re

from ..constants import (
    ENVIRONMENTS,
    TEMPLATE_FEATURE_DETAILS_FOOTER,
    UK_TEMPLATE_HEADER,
    UK_TEMPLATE_MIDDLE,
    US_TEMPLATE_HEADER,
    US_TEMPLATE_MIDDLE,
)
from ..request_context import zendesk_environment_var
from ..zendesk_client import zendesk_client


def normalize_markdown(markdown_content: str) -> str:
    lines = []
    for line in markdown_content.strip().split("\n"):
        lines.append(line.lstrip())
    return "\n".join(lines)


def find_section_headers(normalized_md: str) -> list[dict]:
    pattern = re.compile(r"^###\s*(?P<header>[^\n]+)\s*$", re.MULTILINE)
    results = []
    for m in pattern.finditer(normalized_md):
        results.append(
            {
                "header": m.group("header").strip(),
                "start": m.start(),
                "end": m.end(),
                "full_match": m.group(0),
            }
        )
    return results


def extract_section_content(
    header_match: dict, headers: list[dict], index: int, normalized_md: str
) -> str:
    start_pos = header_match["end"]
    end_pos = headers[index + 1]["start"] if index < len(headers) - 1 else len(normalized_md)
    raw_content = normalized_md[start_pos:end_pos].strip()

    is_description = "description" in header_match["header"].lower()
    return raw_content.replace("\n", "<br>") if is_description else raw_content


def update_data_structure(
    header: str, content: str, data_structure: dict
) -> None:
    func_match = re.match(
        r"Functionality\s+(\d+)\s+(Name|Description)", header, re.IGNORECASE
    )
    if func_match:
        func_num = int(func_match.group(1))
        part = func_match.group(2)
        if func_num not in data_structure["functionalities"]:
            data_structure["functionalities"][func_num] = {}
        data_structure["functionalities"][func_num][part] = content


def process_sections(
    headers: list[dict], normalized_md: str, release_data_structure: dict
) -> None:
    for i, header_match in enumerate(headers):
        content = extract_section_content(header_match, headers, i, normalized_md)
        update_data_structure(header_match["header"], content, release_data_structure)


def parse_markdown_content(markdown_content: str) -> dict:
    if not markdown_content or not markdown_content.strip():
        raise ValueError("Markdown content cannot be empty")

    if not re.search(r"### Functionality \d+ Name", markdown_content, re.IGNORECASE):
        raise ValueError(
            "Release note must include at least one functionality name section "
            "(### Functionality N Name)"
        )
    if not re.search(
        r"### Functionality \d+ Description", markdown_content, re.IGNORECASE
    ):
        raise ValueError(
            "Release note must include at least one functionality description section "
            "(### Functionality N Description)"
        )

    normalized_md = normalize_markdown(markdown_content)
    headers = find_section_headers(normalized_md)
    release_data: dict = {"functionalities": {}}
    process_sections(headers, normalized_md, release_data)

    if not release_data["functionalities"]:
        raise ValueError(
            "Release note must include at least one functionality section"
        )

    for func_key, func_data in release_data["functionalities"].items():
        if not func_data.get("Name") or not func_data["Name"].strip():
            raise ValueError(f"Functionality {func_key} is missing a valid name")
        if not func_data.get("Description") or not func_data["Description"].strip():
            raise ValueError(
                f"Functionality {func_key} is missing a valid description"
            )

    return release_data


def format_whats_new_section(functionalities_data: dict) -> str:
    template = """<ul>
      <li>
        <span class="wysiwyg-font-size-large"><strong>{name}<br></strong></span>
        <span class="wysiwyg-font-size-medium">
          {description}
        </span>
      </li>
    </ul>
    """

    sections = []
    for _, func_data in sorted(functionalities_data["functionalities"].items()):
        if "Name" not in func_data or "Description" not in func_data:
            continue
        sections.append(
            template.format(name=func_data["Name"], description=func_data["Description"])
        )
    return "".join(sections)


def format_release_note_info_steps_section(functionalities_data: dict) -> str:
    template = """<p>
      <strong>
        <span class="wysiwyg-font-size-large">{name}</span>
      </strong>
      <span class="wysiwyg-font-size-medium"><strong><br></strong></span>
    </p>
    """

    sections = []
    for _, func_data in sorted(functionalities_data["functionalities"].items()):
        if "Name" not in func_data or "Description" not in func_data:
            continue
        sections.append(
            template.format(name=func_data["Name"]) + TEMPLATE_FEATURE_DETAILS_FOOTER
        )
    return "".join(sections)


async def create_release_note(
    markdown_content: str,
    use_us_template: bool = False,
) -> str:
    release_data = parse_markdown_content(markdown_content)

    feature_names = [
        func_data["Name"]
        for _, func_data in sorted(release_data["functionalities"].items())
        if func_data.get("Name") and func_data["Name"].strip()
    ]

    all_features = ", ".join(feature_names)
    if use_us_template:
        article_title = (
            f"New Release | Main: {all_features} - "
            f"Labor: move features here if needed | Mmm DD YYYY"
        )
    else:
        article_title = f"New Release | Product Name: {all_features} | DD Mmm YYYY"
    if len(article_title) > 256:
        article_title = article_title[:253] + "..."

    whats_new = format_whats_new_section(release_data)
    info_steps = format_release_note_info_steps_section(release_data)

    if use_us_template:
        html_body = US_TEMPLATE_HEADER + whats_new + US_TEMPLATE_MIDDLE + info_steps
    else:
        html_body = UK_TEMPLATE_HEADER + whats_new + UK_TEMPLATE_MIDDLE + info_steps

    # Resolve environment config (all params hardcoded per environment)
    env_name = zendesk_environment_var.get(None) or "dev"
    env_config = ENVIRONMENTS.get(env_name, ENVIRONMENTS["dev"])

    article_data: dict = {
        "title": article_title,
        "body": html_body,
        "locale": "en-us",
        "draft": True,
        "permission_group_id": env_config["permission_group_id"],
        "user_segment_id": env_config["user_segment_id"],
        "author_id": env_config["author_id"],
    }

    result = await zendesk_client.create_article(article_data, env_config["section_id"])

    created = result.get("article") or {}
    summary_lines = [
        "Release note created successfully!",
        f"Title: {created.get('title') or article_title}",
    ]
    if created.get("id"):
        summary_lines.append(f"ID: {created['id']}")
    if created.get("html_url"):
        summary_lines.append(f"URL: {created['html_url']}")

    summary_text = "\n".join(summary_lines)
    return f"{summary_text}\n\n{json.dumps(result, indent=2)}"
