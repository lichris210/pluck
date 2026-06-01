from dataclasses import dataclass, field
from enum import Enum


class SiteGroup(Enum):
    STATIC_HTML = 1
    SERVER_RENDERED_PAGINATED = 2
    JS_RENDERED_CLEAN_API = 3
    JS_RENDERED_MESSY_DOM = 4
    INTERACTIVE_GATED = 5
    AUTH_GATED = 6
    FORTRESS = 7


@dataclass
class SiteProfile:
    url: str
    final_url: str
    status_code: int
    headers: dict
    content_type: str
    html: str
    site_group: SiteGroup
    classification_reasons: list[str]
    response_time_ms: float
    error: str | None = None


@dataclass
class FetchResult:
    url: str
    html: str
    fetcher_used: str
    fetch_time_ms: float
    success: bool
    structured_data: list[dict] | None = None
    error: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def skip_extraction(self) -> bool:
        """True when structured_data is populated — downstream can skip Claude."""
        return bool(self.structured_data)


@dataclass
class FieldDef:
    name: str
    field_type: str  # one of: "string", "number", "boolean", "url", "date", "list"
    description: str
    required: bool = True


@dataclass
class ExtractionSchema:
    fields: list[FieldDef]
    description: str

    @classmethod
    def from_dict(cls, d: dict) -> "ExtractionSchema":
        raw_fields = d.get("fields") or []
        fields = [
            FieldDef(
                name=str(f.get("name", "")),
                field_type=str(f.get("field_type") or f.get("type") or "string"),
                description=str(f.get("description", "")),
                required=bool(f.get("required", True)),
            )
            for f in raw_fields
            if isinstance(f, dict) and f.get("name")
        ]
        return cls(fields=fields, description=str(d.get("description", "")))

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "fields": [
                {
                    "name": f.name,
                    "field_type": f.field_type,
                    "description": f.description,
                    "required": f.required,
                }
                for f in self.fields
            ],
        }


@dataclass
class ExtractionResult:
    items: list[dict]
    schema_used: ExtractionSchema
    source_url: str
    total_input_tokens: int
    total_output_tokens: int
    extraction_time_ms: float
    model_used: str
    error: str | None = None
    schema_cache_hit: bool = False


@dataclass
class PipelineResult:
    url: str
    site_profile: "SiteProfile"
    fetch_result: "FetchResult | None"
    extraction_result: "ExtractionResult | None"
    formatted_output: str
    output_format: str
    total_time_ms: float
    steps_completed: list[str]
    error: str | None = None
