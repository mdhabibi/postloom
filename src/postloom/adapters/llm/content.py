"""ContentExtractor and ThreadParser for any provider, through the gateway."""

from __future__ import annotations

from postloom.adapters.llm import prompts
from postloom.adapters.llm.gateway import LlmGateway
from postloom.adapters.llm.structured import structured
from postloom.application.ports.extraction import ExtractedContent, ExtractionRequest, PostTopics
from postloom.application.ports.thread_parser import ParsedThread
from postloom.application.ports.usage import Task

EXTRACTION_MAX_OUTPUT = 32_000
"""A long article restored as Markdown is ~10k tokens; leave room for big ones."""
THREADS_MAX_OUTPUT = 16_000
POST_TOPICS_MAX_OUTPUT = 1_024


class LlmContentExtractor:
    def __init__(self, gateway: LlmGateway, model: str) -> None:
        self._gateway = gateway
        self._model = model

    @property
    def name(self) -> str:
        return f"llm:{self._model}"

    def extract(self, request: ExtractionRequest) -> ExtractedContent:
        return structured(
            self._gateway,
            Task.EXTRACTION,
            self._model,
            ExtractedContent,
            system=prompts.EXTRACTION_SYSTEM,
            prompt=prompts.extraction_prompt(request),
            schema=prompts.extraction_schema(request.allowed_topics),
            schema_name="article",
            temperature=0.2,
            max_output_tokens=EXTRACTION_MAX_OUTPUT,
            failure="The model couldn't restore this article reliably.",
        )


class LlmPostClassifier:
    def __init__(self, gateway: LlmGateway, model: str) -> None:
        self._gateway = gateway
        self._model = model

    @property
    def name(self) -> str:
        return f"llm:{self._model}"

    def classify(self, post_text: str, allowed_topics: tuple[str, ...]) -> PostTopics:
        return structured(
            self._gateway,
            Task.EXTRACTION,
            self._model,
            PostTopics,
            system=prompts.POST_TOPICS_SYSTEM,
            prompt=prompts.post_topics_prompt(post_text),
            schema=prompts.post_topics_schema(allowed_topics),
            schema_name="post_topics",
            temperature=0.0,
            max_output_tokens=POST_TOPICS_MAX_OUTPUT,
            failure="The model couldn't choose topics for this post.",
        )


class LlmThreadParser:
    def __init__(self, gateway: LlmGateway, model: str) -> None:
        self._gateway = gateway
        self._model = model

    @property
    def name(self) -> str:
        return f"llm:{self._model}"

    def parse(self, pasted: str, post_text: str, owner_name: str | None) -> ParsedThread:
        return structured(
            self._gateway,
            Task.COMMENTS,
            self._model,
            ParsedThread,
            system=prompts.THREADS_SYSTEM,
            prompt=prompts.threads_prompt(pasted, post_text, owner_name),
            schema=prompts.THREADS_SCHEMA,
            schema_name="comment_thread",
            temperature=0.0,
            max_output_tokens=THREADS_MAX_OUTPUT,
            failure="The model couldn't split these comments reliably.",
        )
