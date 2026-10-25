"""Prompts and output schemas shared by every provider.

Schemas are plain JSON Schema. Each backend translates them to its provider's dialect
(Gemini's OpenAPI subset, Anthropic tool input, OpenAI ``response_format``, Ollama
``format``), so a prompt change never has to be made four times.
"""

from __future__ import annotations

from postloom.adapters.llm.http import JsonObject
from postloom.application.ports.extraction import ExtractionRequest

# -- articles ------------------------------------------------------------------------
EXTRACTION_SYSTEM = """\
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


def extraction_prompt(request: ExtractionRequest) -> str:
    return (
        "<article>\n"
        f"{request.article_text.strip()}\n"
        "</article>\n\n"
        "<announcement_post>\n"
        f"{request.post_text.strip()}\n"
        "</announcement_post>"
    )


def extraction_schema(allowed_topics: tuple[str, ...]) -> JsonObject:
    """Topics are an enum: the model can't invent topics outside the user's taxonomy.

    Property order matters for providers that generate in schema order: metadata first,
    the long body last, so a cut-off answer loses the end of the body, not the title.
    """
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "topics": {"type": "array", "items": {"type": "string", "enum": list(allowed_topics)}},
            "entities": {"type": "array", "items": {"type": "string"}},
            "series_name": {"type": ["string", "null"]},
            "series_part": {"type": ["integer", "null"]},
            "body_markdown": {"type": "string"},
        },
        "required": [
            "title",
            "summary",
            "topics",
            "entities",
            "series_name",
            "series_part",
            "body_markdown",
        ],
        "additionalProperties": False,
    }


# -- comment threads ---------------------------------------------------------------
THREADS_SYSTEM = """\
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


def threads_prompt(pasted: str, post_text: str, owner_name: str | None) -> str:
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


THREADS_SCHEMA: JsonObject = {
    "type": "object",
    "properties": {
        "messages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "author_name": {"type": "string"},
                    "author_headline": {"type": "string"},
                    "is_post_author": {"type": "boolean"},
                    "posted_label": {"type": "string"},
                    "thread": {"type": ["integer", "null"]},
                    "reply_to": {"type": ["integer", "null"]},
                    "text": {"type": "string"},
                },
                "required": [
                    "author_name",
                    "author_headline",
                    "is_post_author",
                    "posted_label",
                    "thread",
                    "reply_to",
                    "text",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["messages"],
    "additionalProperties": False,
}
