"""ThreadParser backed by Gemini structured output."""

from __future__ import annotations

from pydantic import ValidationError

from postloom.adapters.llm.gemini import GeminiClient
from postloom.adapters.llm.http import JsonObject
from postloom.application.errors import ExtractionError
from postloom.application.ports.thread_parser import ParsedThread

SYSTEM_PROMPT = """\
You split a LinkedIn comment section, copied from the browser as plain text, into the \
individual messages it contains, in the order they appear.

How the pasted text looks:
- Each message starts with the author's name, often followed by a connection marker \
such as "• 1st", "• 2nd", "• 3rd+" or "• Following", sometimes by the word "Author" (the \
post's author), then their headline (job title line) and a relative age like "4h", "2d" \
or "1w". Then comes the message text.
- Interface words are noise and must be dropped: "Like", "Reply", "Report", "Load more \
comments", "See more", "View more replies", "Most relevant", reaction counts such as \
"3 reactions" or "12 Reactions", "(edited)", and "Show translation".
- Indentation is lost. Replies follow the top-level comment they belong to. A message is \
a reply when it @mentions an earlier participant, answers the previous message, or is \
written by the post author after a comment. A message by someone new that changes \
subject usually starts a new top-level comment.

For each message return:
- author_name exactly as shown; author_headline if present, else "".
- is_post_author: true if marked "Author" or if the name is the owner's name given below.
- text: the message itself, unchanged, without the interface words. Keep @mentions.
- posted_label: the relative age as shown, else "".
- thread: null for a top-level comment; for a reply, the index of the top-level comment it \
sits under.
- reply_to: for a reply, the index of the specific earlier message it answers when that is \
clear (an @mention or a direct answer), else null.
Indexes are 0-based positions in your returned list.
"""


def build_prompt(pasted: str, post_text: str, owner_name: str | None) -> str:
    owner = owner_name.strip() if owner_name else "unknown"
    return (
        f"Owner (the post's author): {owner}\n\n"
        "<post>\n"
        f"{post_text.strip()}\n"
        "</post>\n\n"
        "<comments>\n"
        f"{pasted.strip()}\n"
        "</comments>"
    )


SCHEMA: JsonObject = {
    "type": "OBJECT",
    "properties": {
        "messages": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "author_name": {"type": "STRING"},
                    "author_headline": {"type": "STRING"},
                    "is_post_author": {"type": "BOOLEAN"},
                    "text": {"type": "STRING"},
                    "posted_label": {"type": "STRING"},
                    "thread": {"type": "INTEGER", "nullable": True},
                    "reply_to": {"type": "INTEGER", "nullable": True},
                },
                "required": ["author_name", "text", "is_post_author"],
                "propertyOrdering": [
                    "author_name",
                    "author_headline",
                    "is_post_author",
                    "posted_label",
                    "thread",
                    "reply_to",
                    "text",
                ],
            },
        }
    },
    "required": ["messages"],
}


class GeminiThreadParser:
    def __init__(self, client: GeminiClient, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def name(self) -> str:
        return f"llm:{self._model}"

    def parse(self, pasted: str, post_text: str, owner_name: str | None) -> ParsedThread:
        raw = self._client.generate_json(
            self._model,
            system=SYSTEM_PROMPT,
            prompt=build_prompt(pasted, post_text, owner_name),
            schema=SCHEMA,
            temperature=0.0,
        )
        try:
            return ParsedThread.model_validate(raw)
        except ValidationError as error:
            raise ExtractionError("Gemini couldn't split these comments reliably.") from error
