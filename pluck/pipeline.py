"""PluckPipeline: orchestrates classify → fetch → extract → format."""

import logging
import time

from pluck.config import Config
from pluck.curation.curator import curate
from pluck.extraction.extractor import extract
from pluck.fetchers import router
from pluck.formatters import format_output
from pluck.ingester import ingest
from pluck.models import ExtractionResult, ExtractionSchema, FetchResult, PipelineResult, SiteProfile

logger = logging.getLogger(__name__)


class PluckPipeline:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._anthropic = None
        if config.anthropic_api_key:
            import anthropic
            self._anthropic = anthropic.Anthropic(api_key=config.anthropic_api_key)

    async def run(
        self,
        url: str,
        schema: ExtractionSchema | None = None,
        output_format: str = "table",
        max_items: int = 100,
        use_apify: bool = False,
        dry_run: bool = False,
    ) -> PipelineResult:
        start = time.perf_counter()
        steps: list[str] = []

        def _elapsed() -> float:
            return (time.perf_counter() - start) * 1000

        def _partial(
            profile: SiteProfile,
            fetch_result: FetchResult | None = None,
            extraction_result: ExtractionResult | None = None,
            error: str | None = None,
        ) -> PipelineResult:
            return PipelineResult(
                url=url,
                site_profile=profile,
                fetch_result=fetch_result,
                extraction_result=extraction_result,
                formatted_output="",
                output_format=output_format,
                total_time_ms=_elapsed(),
                steps_completed=list(steps),
                error=error,
            )

        # ── Step 1: ingest ────────────────────────────────────────────────────
        logger.info("ingest: %s", url)
        profile = await ingest(url)
        if not profile.error:
            steps.append("ingest")
        logger.info("ingest complete: group=%s", profile.site_group.name)

        if profile.error or dry_run:
            return _partial(profile, error=profile.error)

        # ── Step 2: fetch ─────────────────────────────────────────────────────
        logger.info("fetch: group=%s use_apify=%s", profile.site_group.name, use_apify)
        fetch_result = await router.fetch(profile, use_apify=use_apify)
        logger.info("fetch complete: success=%s fetcher=%s", fetch_result.success, fetch_result.fetcher_used)

        if not fetch_result.success:
            return _partial(profile, fetch_result=fetch_result, error=fetch_result.error)
        steps.append("fetch")

        # ── Step 3: extract (or pass through structured data) ─────────────────
        items: list[dict] = []
        extraction_result: ExtractionResult | None = None

        if fetch_result.skip_extraction:
            logger.info("extract: skipped (structured data already available)")
            items = fetch_result.structured_data or []
        else:
            if self._anthropic is None:
                return PipelineResult(
                    url=url,
                    site_profile=profile,
                    fetch_result=fetch_result,
                    extraction_result=None,
                    formatted_output="",
                    output_format=output_format,
                    total_time_ms=_elapsed(),
                    steps_completed=list(steps),
                    error="ANTHROPIC_API_KEY is not set — Claude extraction is not available",
                )

            logger.info("extract: sending to Claude (schema=%s)", schema is not None)
            extraction_result = await extract(fetch_result, schema, self._anthropic)
            logger.info(
                "extract complete: items=%d error=%s",
                len(extraction_result.items),
                extraction_result.error,
            )

            if extraction_result.error:
                return PipelineResult(
                    url=url,
                    site_profile=profile,
                    fetch_result=fetch_result,
                    extraction_result=extraction_result,
                    formatted_output="",
                    output_format=output_format,
                    total_time_ms=_elapsed(),
                    steps_completed=list(steps),
                    error=extraction_result.error,
                )

            items = extraction_result.items
            steps.append("extract")

        # ── Step 4: curate, then format ───────────────────────────────────────
        capped, _cstats = curate(
            items,
            source_url=url,
            is_structured=fetch_result.skip_extraction,
            max_items=max_items,
        )
        logger.info("format: format=%s items=%d", output_format, len(capped))
        formatted = format_output(capped, output_format)
        steps.append("format")

        return PipelineResult(
            url=url,
            site_profile=profile,
            fetch_result=fetch_result,
            extraction_result=extraction_result,
            formatted_output=formatted,
            output_format=output_format,
            total_time_ms=_elapsed(),
            steps_completed=steps,
        )
