"""Pluck CLI — classify, fetch, and extract structured data from a URL."""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(encoding="utf-8-sig")

from pluck.config import get_config
from pluck.models import ExtractionSchema
from pluck.pipeline import PluckPipeline

_EXT_FORMAT: dict[str, str] = {
    ".json": "json",
    ".csv": "csv",
    ".md": "table",
    ".txt": "table",
}

# $/MTok: input, output
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-7": (5.00, 25.00),
}


def _infer_format(output_path: str | None, explicit_format: str) -> str:
    """If output_path has a recognised extension and no explicit format was set, use it."""
    if output_path and explicit_format == "table":
        ext = Path(output_path).suffix.lower()
        inferred = _EXT_FORMAT.get(ext)
        if inferred:
            return inferred
    return explicit_format


def _load_schema(path: str) -> ExtractionSchema:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return ExtractionSchema.from_dict(data)
    except FileNotFoundError:
        print(f"Error: schema file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in schema file {path}: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error loading schema: {exc}", file=sys.stderr)
        sys.exit(1)


def _confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pluck",
        description="Classify, fetch, and extract structured data from a URL.",
    )
    parser.add_argument("url", help="URL to process")
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        help="Save output to file (format inferred from .json/.csv/.md extension)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["table", "json", "csv"],
        default="table",
        dest="fmt",
        metavar="FORMAT",
        help="Output format: table, json, csv (default: table)",
    )
    parser.add_argument(
        "--schema",
        metavar="FILE",
        help="Path to JSON schema file (skips schema inference)",
    )
    parser.add_argument(
        "--use-apify",
        action="store_true",
        help="Force Apify fetch path regardless of site group",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=100,
        metavar="N",
        help="Max items to return (default: 100)",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Skip confirmation prompts",
    )
    parser.add_argument(
        "--show-steps",
        action="store_true",
        help="Print each pipeline step with timing",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only run ingest + classify; skip fetch and extract",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


async def _run(args: argparse.Namespace) -> None:
    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")

    config = get_config()

    if not config.anthropic_api_key and not args.dry_run:
        print(
            "Warning: ANTHROPIC_API_KEY is not set. "
            "Claude extraction will fail unless the site returns structured data.",
            file=sys.stderr,
        )

    if not config.apify_token:
        if args.use_apify:
            print("Warning: APIFY_TOKEN is not set — --use-apify will fail.", file=sys.stderr)

    schema = _load_schema(args.schema) if args.schema else None
    output_format = _infer_format(args.output, args.fmt)

    pipeline = PluckPipeline(config)

    if not args.auto:
        profile_preview_done = False

        async def _confirm_after_classify() -> bool:
            nonlocal profile_preview_done
            if profile_preview_done:
                return True
            profile_preview_done = True
            return True  # prompt happens after ingest below

    result = await pipeline.run(
        url=args.url,
        schema=schema,
        output_format=output_format,
        max_items=args.max_items,
        use_apify=args.use_apify,
        dry_run=args.dry_run,
    )

    # ── Site profile ──────────────────────────────────────────────────────────
    if result.site_profile:
        p = result.site_profile
        print(f"URL:       {p.url}")
        if p.final_url != p.url:
            print(f"Final URL: {p.final_url}")
        print(f"Status:    {p.status_code}")
        print(f"Group:     {p.site_group.name} (group {p.site_group.value})")
        for reason in p.classification_reasons:
            print(f"  · {reason}")

    # ── Step timing ───────────────────────────────────────────────────────────
    if args.show_steps:
        print(f"\nSteps:     {' -> '.join(result.steps_completed) or '(none)'}")
        print(f"Time:      {result.total_time_ms:.0f} ms")

    # ── Errors ────────────────────────────────────────────────────────────────
    if result.error:
        print(f"\nError: {result.error}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        return

    # ── Fetch summary ─────────────────────────────────────────────────────────
    if result.fetch_result:
        fr = result.fetch_result
        print(f"\nFetcher:   {fr.fetcher_used}")
        if fr.structured_data is not None:
            source = "Apify" if fr.metadata.get("actor_id") else "XHR"
            print(f"{source} items: {len(fr.structured_data)}")
            if fr.metadata.get("actor_id"):
                print(f"Actor:     {fr.metadata['actor_id']}")

    # ── Extraction summary ────────────────────────────────────────────────────
    if result.extraction_result:
        er = result.extraction_result
        in_per_mtok, out_per_mtok = _MODEL_PRICING.get(er.model_used, (0.0, 0.0))
        cost = (er.total_input_tokens / 1_000_000) * in_per_mtok + (
            er.total_output_tokens / 1_000_000
        ) * out_per_mtok
        print(f"\nItems:     {len(er.items)}")
        print(f"Model:     {er.model_used}")
        print(f"Tokens:    {er.total_input_tokens:,} in / {er.total_output_tokens:,} out")
        print(f"Est. cost: ${cost:.4f}")

    # ── Output ────────────────────────────────────────────────────────────────
    if not result.formatted_output:
        print("\n(No items to display)")
        return

    if args.output:
        Path(args.output).write_text(result.formatted_output, encoding="utf-8")
        n = _item_count(result)
        print(f"\nSaved {n} items to {args.output}")
    else:
        print(f"\n{result.formatted_output}")


def _item_count(result) -> int:
    if result.extraction_result:
        return len(result.extraction_result.items)
    if result.fetch_result and result.fetch_result.structured_data is not None:
        return len(result.fetch_result.structured_data)
    return 0


def _clear_plan_cache_main(argv: list[str]) -> None:
    """`pluck clear-plan-cache` — bulk-clear cached planner plans, print the count."""
    parser = argparse.ArgumentParser(
        prog="pluck clear-plan-cache",
        description="Clear all cached planner plans from pluck_cache.db.",
    )
    parser.parse_args(argv)  # no options; surfaces -h/--help

    from pluck.storage.cache_store import SchemaCacheStore

    store = SchemaCacheStore()
    cleared = store.clear_plan_cache()
    store.close()
    print(f"Cleared {cleared} cached plan(s).")


def main() -> None:
    # Non-disruptive subcommand intercept: keep the flat url-positional parser
    # (and _build_parser, used by tests) untouched for every other invocation.
    if len(sys.argv) > 1 and sys.argv[1] == "clear-plan-cache":
        _clear_plan_cache_main(sys.argv[2:])
        return

    parser = _build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
