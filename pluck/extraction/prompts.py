"""Prompt templates for schema inference and structured extraction."""

import json

from pluck.models import ExtractionSchema

MAX_HTML_CHARS = 30_000
_TRUNCATION_MARKER = "\n...[truncated]"


SCHEMA_INFERENCE_SYSTEM = (
    "You analyze HTML pages and identify what structured data can be extracted "
    "from them. Given a cleaned HTML page and its source URL, you decide what "
    "fields a downstream extractor should pull out and return them as a JSON "
    "schema definition. You return only the JSON object — no prose, no "
    "markdown fences. The JSON object must have two keys: `description` "
    "(a short string explaining what the data represents) and `fields` "
    "(an array of field objects, each with `name`, `field_type`, "
    "`description`, and `required`). `field_type` must be one of: "
    '"string", "number", "boolean", "url", "date", "list".'
)


EXTRACTION_SYSTEM = (
    "You extract structured data from HTML and return it as JSON. You receive "
    "a cleaned HTML page and a schema describing what to extract. You return "
    "a JSON array where each element matches the schema. You return only the "
    "JSON array — no prose, no markdown fences, no explanation."
)


def _truncate_html(html: str) -> str:
    if len(html) <= MAX_HTML_CHARS:
        return html
    return html[:MAX_HTML_CHARS] + _TRUNCATION_MARKER


def build_schema_inference_prompt(cleaned_html: str, source_url: str) -> str:
    """Ask Claude to identify extractable structured data on the page."""
    html = _truncate_html(cleaned_html)
    return (
        f"Source URL: {source_url}\n\n"
        "Below is the cleaned HTML for a web page. Identify the structured "
        "data on this page that a user would want to extract (e.g., a list "
        "of products, articles, jobs, search results, or a single item's "
        "fields). Return a JSON object describing the schema.\n\n"
        "Required JSON shape:\n"
        "{\n"
        '  "description": "<what the extracted data represents>",\n'
        '  "fields": [\n'
        '    {"name": "<field_name>", "field_type": "<string|number|boolean|url|date|list>", '
        '"description": "<what this field contains>", "required": <true|false>}\n'
        "  ]\n"
        "}\n\n"
        "Return ONLY the JSON object — no prose, no markdown fences.\n\n"
        "----- HTML -----\n"
        f"{html}"
    )


def build_extraction_prompt(
    cleaned_html: str, schema: ExtractionSchema, source_url: str
) -> str:
    """Ask Claude to extract items matching the schema."""
    html = _truncate_html(cleaned_html)
    schema_json = json.dumps(schema.to_dict(), indent=2, sort_keys=True)
    return (
        f"Source URL: {source_url}\n\n"
        "Extract structured data from the HTML below according to the schema. "
        "Return a JSON array where each element is an object matching the "
        "schema's fields.\n\n"
        "Rules:\n"
        "- Return only the JSON array. No prose. No markdown fences.\n"
        "- For required fields whose value is missing on the page, use null. "
        "Do NOT guess or invent values.\n"
        "- For optional fields whose value is missing, omit the key or use null.\n"
        "- If no items matching the schema exist on the page, return [].\n"
        "- Do not include any text before or after the JSON array.\n\n"
        "Schema:\n"
        f"{schema_json}\n\n"
        "----- HTML -----\n"
        f"{html}"
    )
