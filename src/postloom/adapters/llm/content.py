"""ContentExtractor and ThreadParser for any provider, through the gateway."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from postloom.adapters.llm import prompts
from postloom.adapters.llm.base import Image, InvalidRequestError
from postloom.adapters.llm.gateway import LlmGateway
from postloom.adapters.llm.structured import structured
from postloom.application.errors import ProviderError
from postloom.application.ports.extraction import (
    ExtractedContent,
    ExtractionRequest,
    FoundMentions,
    PostTopics,
)
from postloom.application.ports.media import ImageDescription
from postloom.application.ports.thread_parser import ParsedThread
from postloom.application.ports.usage import Task

EXTRACTION_MAX_OUTPUT = 32_000
"""A long article restored as Markdown is ~10k tokens; leave room for big ones."""
THREADS_MAX_OUTPUT = 16_000
POST_TOPICS_MAX_OUTPUT = 1_024
MENTIONS_MAX_OUTPUT = 8_192
"""Room for an article that names many things, and for a model that thinks first."""


class LlmContentExtractor:
    def __init__(self, gateway: LlmGateway, model: str, fallbacks: Sequence[str] = ()) -> None:
        self._gateway = gateway
        self._model = model
        self._fallbacks = tuple(fallbacks)

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
            fallbacks=self._fallbacks,
        )


class LlmPostClassifier:
    def __init__(self, gateway: LlmGateway, model: str, fallbacks: Sequence[str] = ()) -> None:
        self._gateway = gateway
        self._model = model
        self._fallbacks = tuple(fallbacks)

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
            fallbacks=self._fallbacks,
        )


class LlmMentionFinder:
    def __init__(self, gateway: LlmGateway, model: str, fallbacks: Sequence[str] = ()) -> None:
        self._gateway = gateway
        self._model = model
        self._fallbacks = tuple(fallbacks)

    @property
    def name(self) -> str:
        return f"llm:{self._model}"

    def find(self, text: str, topics: tuple[str, ...], owner_name: str | None) -> FoundMentions:
        return structured(
            self._gateway,
            Task.EXTRACTION,
            self._model,
            FoundMentions,
            system=prompts.MENTIONS_SYSTEM,
            prompt=prompts.mentions_prompt(text, topics, owner_name),
            schema=prompts.mentions_schema(topics),
            schema_name="mentions",
            temperature=0.0,
            max_output_tokens=MENTIONS_MAX_OUTPUT,
            failure="The model couldn't read the names in this text.",
            fallbacks=self._fallbacks,
        )


class LlmThreadParser:
    def __init__(self, gateway: LlmGateway, model: str, fallbacks: Sequence[str] = ()) -> None:
        self._gateway = gateway
        self._model = model
        self._fallbacks = tuple(fallbacks)

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
            fallbacks=self._fallbacks,
        )


IMAGE_MAX_OUTPUT = 1_500


class _SeenImage(BaseModel):
    description: str
    text_in_image: str = ""


class LlmImageDescriber:
    """Describes an image with the reading model, so it can be found by search."""

    def __init__(self, gateway: LlmGateway, model: str, fallbacks: Sequence[str] = ()) -> None:
        self._gateway = gateway
        self._model = model
        self._fallbacks = tuple(fallbacks)

    def describe(self, image: bytes, mime: str, context: str) -> ImageDescription:
        try:
            seen = structured(
                self._gateway,
                Task.IMAGES,
                self._model,
                _SeenImage,
                system=prompts.IMAGE_SYSTEM,
                prompt=prompts.image_prompt(context),
                schema=prompts.IMAGE_SCHEMA,
                schema_name="image",
                temperature=0.0,
                max_output_tokens=IMAGE_MAX_OUTPUT,
                failure="The model couldn't describe this image.",
                fallbacks=self._fallbacks,
                images=[Image(mime, image)],
            )
        except InvalidRequestError as error:
            raise ProviderError(
                f"{self._model} refused the image ({error.detail}). It may not be able to see "
                "images: choose a model that can (most current Gemini, Claude and GPT models "
                "can; on Ollama, a vision model such as gemma3) under Models in "
                "Settings, or write a caption yourself."
            ) from error
        text = seen.description.strip()
        if seen.text_in_image.strip():
            text += f"\n\nText in the image: {seen.text_in_image.strip()}"
        return ImageDescription(text, self._model)
