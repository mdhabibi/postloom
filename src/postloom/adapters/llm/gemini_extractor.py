"""ContentExtractor backed by Gemini structured output."""

from __future__ import annotations

from pydantic import ValidationError

from postloom.adapters.llm.gemini import GeminiClient
from postloom.adapters.llm.http import JsonObject
from postloom.application.errors import ExtractionError
from postloom.application.ports.extraction import ExtractedContent, ExtractionRequest

SYSTEM_PROMPT = """\
You restore LinkedIn articles that were copy-pasted as plain text into clean Markdown, \
and extract metadata about them.

Rules for body_markdown:
1. Preserve the author's wording exactly. Never summarize, shorten, rewrite, translate, \
correct or add content. Only restore structure: paragraphs, headings (## for main \
sections, ### for subsections), bullet or numbered lists, bold labels, quotes and fenced \
code blocks with a language tag.
2. Copy-paste often glues words together where a line break was lost (for example \
"Part 3In Parts 1 and 2"). Put the missing break or space back.
3. Leave out LinkedIn artefacts: the title line (it goes in "title"), placeholder lines \
such as "Article content" where an image was, and the trailing block of hashtags.

Rules for the other fields:
- title: the article title exactly as written, including any "Part N".
- summary: two or three plain sentences on what the article teaches.
- topics: one to three entries from the allowed list that the article is mainly about.
- entities: named technologies, libraries, frameworks, methods, products and \
organisations (for example "LangGraph", "Redis", "LLM-as-a-judge"). No generic words.
- series_name: if the article or its post says it belongs to a series, the series name \
without "Part N"; otherwise null. series_part: its part number, otherwise null.
"""


def build_prompt(request: ExtractionRequest) -> str:
    return (
        "<article>\n"
        f"{request.article_text.strip()}\n"
        "</article>\n\n"
        "<announcement_post>\n"
        f"{request.post_text.strip()}\n"
        "</announcement_post>"
    )


def build_schema(allowed_topics: tuple[str, ...]) -> JsonObject:
    """Gemini response schema (OpenAPI subset). Topics are an enum: no free-form topics."""
    return {
        "type": "OBJECT",
        "properties": {
            "title": {"type": "STRING"},
            "body_markdown": {"type": "STRING"},
            "summary": {"type": "STRING"},
            "topics": {
                "type": "ARRAY",
                "items": {"type": "STRING", "enum": list(allowed_topics)},
            },
            "entities": {"type": "ARRAY", "items": {"type": "STRING"}},
            "series_name": {"type": "STRING", "nullable": True},
            "series_part": {"type": "INTEGER", "nullable": True},
        },
        "required": ["title", "body_markdown", "summary", "topics", "entities"],
        "propertyOrdering": [
            "title",
            "summary",
            "topics",
            "entities",
            "series_name",
            "series_part",
            "body_markdown",
        ],
    }


class GeminiContentExtractor:
    def __init__(self, client: GeminiClient, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def name(self) -> str:
        return f"llm:{self._model}"

    def extract(self, request: ExtractionRequest) -> ExtractedContent:
        raw = self._client.generate_json(
            self._model,
            system=SYSTEM_PROMPT,
            prompt=build_prompt(request),
            schema=build_schema(request.allowed_topics),
        )
        try:
            return ExtractedContent.model_validate(raw)
        except ValidationError as error:
            fields = ", ".join(str(e["loc"][0]) for e in error.errors() if e["loc"])
            raise ExtractionError(
                f"Gemini's answer was missing or had invalid fields: {fields or 'unknown'}."
            ) from error
