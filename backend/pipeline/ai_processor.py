"""Pipeline Step 4: Optional AI enrichment of records."""

from typing import Any

from backend.models.record import CollectedRecord
from backend.processors.base import ProcessingResult
from backend.processors.registry import get_processor


async def process_with_ai(
    records: list[CollectedRecord],
    ai_config: dict[str, Any] | None,
) -> ProcessingResult:
    """Enrich records with AI processing in-place.

    ai_config keys:
        processor_type: claude | openai | local
        model: model name
        prompt_template: Jinja2 template
        ...processor-specific options
    """
    if not ai_config or not records:
        return ProcessingResult(success=True)

    processor_type = ai_config.get("processor_type", "claude")
    try:
        processor = get_processor(processor_type)
    except ValueError:
        return ProcessingResult(success=False, error=f"Unknown processor: {processor_type}")

    result = await processor.process(
        records=records,
        prompt_template=ai_config.get("prompt_template", ""),
        config=ai_config,
    )

    for record, enrichment in zip(records, result.enrichments):
        # Failed items stay normalized so the UI and retry logic do not report
        # an AI success for an error payload.
        if isinstance(enrichment, dict) and "error" not in enrichment:
            record.ai_enrichment = enrichment
            record.status = "ai_processed"
    return result
