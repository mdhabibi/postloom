"""Port for splitting a pasted LinkedIn comment section into individual messages."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ParsedMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    author_name: str = Field(min_length=1, description="The commenter's name as shown.")
    author_headline: str = Field(
        default="", description="Their LinkedIn headline (job title line), if shown."
    )
    is_post_author: bool = Field(
        default=False,
        description="True when LinkedIn marks the message as written by the post's author.",
    )
    text: str = Field(min_length=1, description="The message text, without UI labels.")
    posted_label: str = Field(default="", description='Relative age as shown, e.g. "4h".')
    thread: int | None = Field(
        default=None,
        description="Index of the top-level comment this reply sits under; null if top-level.",
    )
    reply_to: int | None = Field(
        default=None, description="Index of the message this one answers, if clear."
    )


class ParsedThread(BaseModel):
    model_config = ConfigDict(frozen=True)

    messages: tuple[ParsedMessage, ...] = ()


class ThreadParser(Protocol):
    @property
    def name(self) -> str: ...

    def parse(self, pasted: str, post_text: str, owner_name: str | None) -> ParsedThread:
        """Split ``pasted`` comment-section text into messages, in order."""
        ...
