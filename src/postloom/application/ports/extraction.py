"""Port for turning raw pasted text into structured content.

Implemented by an LLM adapter (Gemini Flash by default). The output schema is a Pydantic
model so any provider's structured-output response is validated before it reaches the
use case; a malformed response fails loudly instead of corrupting the graph.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ExtractionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    article_text: str = Field(description="The article exactly as the user pasted it.")
    post_text: str = Field(description="The announcement post as pasted.")
    allowed_topics: tuple[str, ...] = Field(
        description="Topic names the article may be classified into. No others are allowed."
    )


class ExtractedContent(BaseModel):
    """Structured result of one extraction call."""

    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, description="The article title, without series suffixes.")
    body_markdown: str = Field(
        min_length=1,
        description=(
            "The article body as clean Markdown: restored headings, lists and code blocks. "
            "Wording must be preserved; do not summarize or rewrite."
        ),
    )
    summary: str = Field(default="", description="Two or three sentence summary.")
    topics: tuple[str, ...] = Field(
        default=(), description="One to three names chosen only from allowed_topics."
    )
    entities: tuple[str, ...] = Field(
        default=(), description="Technologies, methods, libraries and organisations named."
    )
    series_name: str | None = Field(
        default=None, description="Name of the multi-part series, if this is part of one."
    )
    series_part: int | None = Field(default=None, ge=1, description="Part number in the series.")


class ContentExtractor(Protocol):
    """Extracts structured content from pasted article and post text."""

    @property
    def name(self) -> str:
        """Producer name recorded in provenance, e.g. ``"llm:gemini-2.5-flash"``."""
        ...

    def extract(self, request: ExtractionRequest) -> ExtractedContent: ...


class PostTopics(BaseModel):
    """What one small model call says about a post that stands on its own."""

    model_config = ConfigDict(frozen=True)

    topics: tuple[str, ...] = Field(
        default=(), description="Zero to three names chosen only from allowed_topics."
    )
    entities: tuple[str, ...] = Field(
        default=(), description="Technologies, methods, libraries and organisations named."
    )


class PostClassifier(Protocol):
    """Chooses a post's topics. Posts keep their text exactly as pasted, so this is the
    only thing a model is needed for when adding one."""

    @property
    def name(self) -> str: ...

    def classify(self, post_text: str, allowed_topics: tuple[str, ...]) -> PostTopics: ...
