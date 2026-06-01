"""Validates extracted rows against the schema that was used to produce them."""

from dataclasses import dataclass

from pluck.models import ExtractionSchema

_NULL_SENTINEL = object()


def _is_empty(val) -> bool:
    return val is None or val == "" or val == []


@dataclass
class ValidationResult:
    ok: bool
    reason: str = ""


def validate_extraction(schema: ExtractionSchema, rows: list[dict]) -> ValidationResult:
    """Return ValidationResult indicating whether rows satisfy the schema.

    Fails if:
    - zero rows were extracted, OR
    - more than 50% of required-field cells are null/empty across all rows.

    Optional fields (FieldDef.required=False) are not counted in the null ratio,
    so legitimately sparse optional fields never trigger invalidation.
    """
    if not rows:
        return ValidationResult(ok=False, reason="zero rows extracted")

    required = [f.name for f in schema.fields if f.required]
    if not required:
        return ValidationResult(ok=True, reason="")

    total = len(required) * len(rows)
    null_count = sum(
        1
        for row in rows
        for name in required
        if _is_empty(row.get(name, None))
    )

    ratio = null_count / total
    if ratio > 0.5:
        return ValidationResult(
            ok=False,
            reason=(
                f"{ratio:.0%} of required fields null/empty "
                f"across {len(rows)} row(s)"
            ),
        )

    return ValidationResult(ok=True, reason="")
