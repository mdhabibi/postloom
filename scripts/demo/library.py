"""Build a fictional postloom library for screenshots and demos.

    uv run python scripts/demo/library.py <home folder>

Everything in it is invented: the author, the people who comment, the organisations and
the numbers. No model is called; the fakes from the test suite stand in for them, so the
result is the same on every run.
"""

from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.ports.extraction import FoundMention, FoundMentions
from postloom.application.ports.thread_parser import ParsedMessage, ParsedThread
from postloom.application.use_cases import Decision, IngestArticleCommand, IngestPostCommand
from postloom.application.use_cases.mentions import Accepted
from postloom.bootstrap import Container, build_container
from postloom.domain.graph import NodeId
from postloom.settings import Settings, save_settings
from tests.fakes import (
    FakeEmbedder,
    FakeExtractor,
    FakeImageDescriber,
    FakeMentionFinder,
    FakePostClassifier,
    FakeThreadParser,
    FixedClock,
    part3_extraction,
)

OWNER = "Alex Morgan"
OWNER_LINE = "ML engineer | Writing about LLM systems in production"

# -- people (all invented) -------------------------------------------------------------
PEOPLE = {
    "Lena Okafor": "Staff ML Engineer at Northwind Analytics",
    "Tomas Arends": "Founder at Copperline Labs",
    "Mira Castell": "Data Scientist, Helios Health",
    "Jonah Pike": "Platform Engineer | Kubernetes and GPUs",
    "Aiko Brandt": "Head of AI at Fernway Retail",
    "Samir Haddad": "Research Engineer, retrieval and ranking",
    "Ines Kowal": "Product Manager, AI assistants",
    "Ravi Thorne": "Security Engineer | LLM red teaming",
    "Hana Lindqvist": "PhD student in NLP",
    "Oskar Bremer": "CTO at Quillbase",
}


def say(name: str, text: str, label: str, thread: int | None = None) -> ParsedMessage:
    if name == OWNER:
        return ParsedMessage(
            author_name=OWNER,
            author_headline=OWNER_LINE,
            is_post_author=True,
            text=text,
            posted_label=label,
            thread=thread,
        )
    return ParsedMessage(
        author_name=name, author_headline=PEOPLE[name], text=text, posted_label=label, thread=thread
    )


# -- articles --------------------------------------------------------------------------
SERIES = "LLM costs in production"

ARTICLES: list[dict[str, object]] = [
    {
        "title": "Semantic caching cut our LLM bill in half",
        "summary": "How a semantic cache in front of the model halved spend without hurting "
        "answer quality, and the three numbers we watch every week.",
        "topics": ("LLMs", "RAG"),
        "series": 1,
        "date": date(2026, 3, 4),
        "post": "New article: semantic caching cut our LLM bill in half.\n\nThe surprising "
        "part wasn't the savings, it was how few questions are really new. #LLM #RAG",
        "body": """## Why we looked at caching

Our support assistant answered about 40,000 questions a week, and most of the bill came from
a few hundred questions asked again and again in different words. Exact-match caching caught
almost none of them.

## How the semantic cache works

Each question is embedded and compared with the questions already answered. Above a
similarity threshold we return the stored answer; below it we call the model and store the
new pair. We keep answers for seven days and drop them when the source documents change.

## What happened

Spend fell by 52% in the first month. p99 latency fell from 1,240 ms to 310 ms for cached
answers. We watch three numbers every week: hit rate, false-hit rate from an LLM-as-a-judge
sample, and how stale the cached answers are.
""",
        "thread": [
            say(
                "Lena Okafor",
                "How do you pick the similarity threshold? That's where we always get burned.",
                "3w",
            ),
            say(
                OWNER,
                "We started from a labelled sample of 500 question pairs and chose the "
                "threshold with the lowest false-hit rate. Part 2 is all about it.",
                "3w",
                0,
            ),
            say("Lena Okafor", "Perfect, waiting for part 2.", "3w", 0),
            say(
                "Jonah Pike",
                "Which vector store do you use for the cache, and does it run next to the model?",
                "3w",
            ),
            say("Aiko Brandt", "52% is impressive. Did answer quality move at all?", "2w"),
            say(
                OWNER,
                "Not measurably: the judge sample stayed within a point of the uncached baseline.",
                "2w",
                4,
            ),
        ],
    },
    {
        "title": "Choosing a cache threshold without guessing",
        "summary": "A small labelled set, a false-hit budget and a weekly re-check: how to "
        "set the similarity threshold of a semantic cache.",
        "topics": ("LLMs", "MLOps"),
        "series": 2,
        "date": date(2026, 4, 1),
        "post": "Part 2 of the series is out: choosing a semantic cache threshold without "
        "guessing. Thanks Lena for the question that started it. #LLM #MLOps",
        "body": """## Start from a false-hit budget

Decide how many wrong cached answers you can live with, say 1 in 200, before looking at any
similarity score. That number comes from the product, not from the model.

## Label a few hundred pairs

Sample real questions, pair each with its nearest cached question and label whether the
cached answer would be right. Five hundred pairs took two people an afternoon.

## Re-check it every week

Traffic drifts. Every Monday we re-run the judge on a sample of cache hits and move the
threshold if the false-hit rate leaves the budget.
""",
        "thread": [
            say(
                "Lena Okafor",
                "This is exactly what I asked for, thank you. How often did "
                "the threshold actually move?",
                "1w",
            ),
            say(
                OWNER,
                "Twice in two months, both after a product launch changed the "
                "questions people ask.",
                "1w",
                0,
            ),
            say(
                "Samir Haddad",
                "Did you try a different threshold per intent? Billing "
                "questions seem riskier than how-to questions.",
                "6d",
            ),
            say("Hana Lindqvist", "Would you share the labelling guidelines?", "5d"),
        ],
    },
    {
        "title": "Evaluating RAG without a labelled dataset",
        "summary": "Synthetic questions, an LLM judge you have checked by hand, and the "
        "failure cases that matter most.",
        "topics": ("RAG", "NLP"),
        "date": date(2026, 5, 12),
        "post": "Most teams I talk to skip RAG evaluation because they have no labelled "
        "data. You don't need much to start. New article: #RAG #Evaluation",
        "body": """## Generate questions from your own documents

Ask a model to write questions each chunk answers, then keep only the ones a person would
really ask. Two hundred good questions beat two thousand generated ones.

## Check the judge before trusting it

Grade fifty answers by hand and compare them with the judge. Ours agreed 88% of the time;
where it disagreed it was too generous with partial answers, so we changed the rubric.

## Look at failures, not averages

Retrieval misses, answers that ignore the context and answers that cite the wrong source
fail in different ways. Count them separately.
""",
        "thread": [
            say(
                "Samir Haddad",
                "88% agreement is better than I expected. Which model was the judge?",
                "4w",
            ),
            say(
                OWNER,
                "A small one on purpose: if a small judge agrees with people, we can "
                "afford to run it on every release.",
                "4w",
                0,
            ),
            say(
                "Mira Castell",
                "We do this for clinical notes and the hardest part is the "
                "questions nobody thinks to ask.",
                "3w",
            ),
            say("Ines Kowal", "Bookmarking this for our team.", "3w"),
        ],
    },
    {
        "title": "Agents in production: what broke first",
        "summary": "Six months of running tool-using agents for customers: timeouts, loops, "
        "permissions and the boring fixes that worked.",
        "topics": ("AI Agents", "MLOps"),
        "date": date(2026, 7, 8),
        "post": "We ran tool-using agents for customers for six months. Here is what broke "
        "first, and it wasn't the model. #AIAgents #MLOps",
        "body": """## Timeouts and retries

Most failures were slow tools, not wrong answers. A budget of steps and seconds per task,
and clear messages when it runs out, fixed more than any prompt change.

## Loops

Agents repeat a failing tool call with small variations. We now stop after two identical
errors and ask the user.

## Permissions

Every tool runs with the user's own permissions, never the service's. It made some tasks
impossible, and that was the point.
""",
        "thread": [
            say("Oskar Bremer", "The permissions point deserves its own article.", "2w"),
            say("Jonah Pike", "How do you set the step budget? Per tool or per task?", "2w"),
            say(OWNER, "Per task, with a lower limit for anything that writes data.", "2w", 1),
            say("Tomas Arends", "We learned the loop lesson the expensive way.", "1w"),
        ],
    },
    {
        "title": "Prompt injection: a field guide for builders",
        "summary": "Where injected instructions come from in real apps, and the defences "
        "that hold up: separation, least privilege and confirmation.",
        "topics": ("LLMs", "AI Agents"),
        "date": date(2026, 9, 2),
        "post": "Prompt injection isn't a prompt problem, it's a permissions problem. A field "
        "guide for people building with LLMs. #LLMSecurity #AIAgents",
        "body": """## Where it comes from

Web pages, emails, PDFs and tool results all reach the model as text. Any of them can carry
instructions, and the model can't tell whose they are.

## Defences that hold up

Keep untrusted text clearly separated, give tools the least privilege that works, and ask
the user before anything that sends, deletes or pays.

## Testing it

We keep a small set of injected documents and run them on every release, like any other
regression test.
""",
        "thread": [
            say(
                "Ravi Thorne",
                "Thank you for saying permissions, not prompts. Would you add "
                "indirect injection through tool outputs to the test set?",
                "5d",
            ),
            say(OWNER, "Yes, half of our test documents now arrive through a tool.", "5d", 0),
            say("Aiko Brandt", "Sharing with our security team.", "4d"),
        ],
    },
    {
        "title": "Distilling a 7B model into a 300M classifier",
        "summary": "Using a large model as a labeller to train a small, fast classifier that "
        "kept 97% of its accuracy at a fraction of the cost.",
        "topics": ("Machine Learning", "Deep Learning"),
        "date": date(2026, 10, 14),
        "post": "We replaced a 7B model call with a 300M classifier for ticket routing. "
        "97% of the accuracy, 40x cheaper. How we did it: #MachineLearning",
        "body": """## The large model as a labeller

We labelled 60,000 historical tickets with the large model, checked a sample by hand, and
kept the labels where it was confident.

## Training the small model

A 300M encoder fine-tuned for three epochs reached 97% of the large model's accuracy on a
held-out set labelled by people.

## Keeping it honest

Anything the small model is unsure about still goes to the large one, about 6% of tickets.
""",
        "thread": [
            say(
                "Hana Lindqvist",
                "Did you calibrate the confidence before using it as the routing rule?",
                "3w",
            ),
            say(
                OWNER,
                "Yes, temperature scaling on the validation set. Without it the "
                "fallback rate was twice as high.",
                "3w",
                0,
            ),
            say("Tomas Arends", "40x cheaper is the number my CFO wants to hear.", "2w"),
        ],
    },
]

POSTS: list[dict[str, object]] = [
    {
        "text": "Three things I learned speaking at Fjord AI Meetup last week:\n\n1. Everyone "
        "has a RAG demo, few have a RAG evaluation.\n2. Agents fail on tools, not on "
        "reasoning.\n3. The best questions came from people outside AI.\n\nThanks to Lena "
        "Okafor and Northwind Analytics for hosting. Slides: "
        "https://example.com/fjord-slides #AIAgents #RAG",
        "topics": ("AI Agents", "RAG"),
        "date": date(2026, 10, 28),
        "thread": [
            say("Lena Okafor", "Thanks for coming! The room didn't want to leave.", "4w"),
            say("Ines Kowal", "Point 3 is so true.", "4w"),
            say("Oskar Bremer", "Will there be a recording?", "3w"),
        ],
        "review": True,
    },
    {
        "text": "One week after turning on the semantic cache: p99 latency went from 1,240 "
        "ms to 310 ms for cached answers. Same quality, a quarter of the wait. #LLM",
        "topics": ("LLMs",),
        "date": date(2026, 3, 11),
        "thread": [
            say("Jonah Pike", "What's the hit rate behind that?", "8mo"),
            say(OWNER, "41% in week one, 47% now.", "8mo", 0),
        ],
        "image": True,
    },
    {
        "text": "Copperline Labs is hiring an ML engineer to work on evaluation. If you like "
        "turning vague quality questions into numbers, talk to Tomas Arends. #Hiring",
        "topics": ("Machine Learning",),
        "date": date(2026, 11, 3),
        "thread": [
            say("Tomas Arends", "Thanks Alex! Applications are open until December.", "3w"),
            say("Hana Lindqvist", "Is it open to people finishing a PhD?", "3w"),
        ],
    },
]

CHART_DESCRIPTION = (
    "A bar chart comparing p99 latency with and without the semantic cache: 1,240 ms "
    "without, 310 ms with.\n\nText in the image: p99 latency (ms) | No cache 1240 | "
    "Semantic cache 310"
)


def pasted(thread: list[ParsedMessage]) -> str:
    return "\n\n".join(f"{m.author_name}\n{m.text}" for m in thread)


def build(home: Path, chart: bytes | None = None) -> None:
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    save_settings(home, owner_name=OWNER)
    clock = FixedClock()
    articles: list[NodeId] = []

    def open_home(**fakes: object) -> Container:
        return build_container(
            Settings.load(home),
            embedder=FakeEmbedder(),
            clock=clock,
            **fakes,  # type: ignore[arg-type]
        )

    with open_home() as c:
        c.seed_topics().execute(DEFAULT_TOPICS)

    for spec in ARTICLES:
        body = str(spec["body"])
        title = str(spec["title"])
        extraction = part3_extraction(
            title=title,
            body_markdown=body,
            summary=spec["summary"],
            topics=spec["topics"],
            entities=(),
            series_name=SERIES if spec.get("series") else None,
            series_part=spec.get("series"),
        )
        thread = ParsedThread(messages=tuple(spec["thread"]))  # type: ignore[arg-type]
        with open_home(
            extractor=FakeExtractor(extraction), thread_parser=FakeThreadParser(thread)
        ) as c:
            added = c.ingest_article().execute(
                IngestArticleCommand(
                    f"{title}\n\n{body}",
                    str(spec["post"]),
                    published_on=spec["date"],  # type: ignore[arg-type]
                )
            )
            c.index_article().execute(added.article.id)
            drafts = c.preview_comments().execute(added.article.id, pasted(thread.messages), OWNER)  # type: ignore[arg-type]
            c.save_comments().execute(added.article.id, drafts.messages)
            articles.append(added.article.id)
        clock.advance(hours=1)

    posts: list[NodeId] = []
    for spec in POSTS:
        thread = ParsedThread(messages=tuple(spec["thread"]))  # type: ignore[arg-type]
        with open_home(
            post_classifier=FakePostClassifier(tuple(spec["topics"])),  # type: ignore[arg-type]
            thread_parser=FakeThreadParser(thread),
            image_describer=FakeImageDescriber(CHART_DESCRIPTION),
        ) as c:
            post = (
                c.ingest_post()
                .execute(
                    IngestPostCommand(str(spec["text"]), published_on=spec["date"])  # type: ignore[arg-type]
                )
                .post
            )
            drafts = c.preview_comments().execute(post.id, pasted(thread.messages), OWNER)  # type: ignore[arg-type]
            c.save_comments().execute(post.id, drafts.messages)
            if spec.get("image") and chart is not None:
                image = c.media().add(
                    post.id, "latency-chart.png", [chart], "p99 latency before and after caching"
                )
                c.media().describe(post.id, image.file)
            posts.append(post.id)
        clock.advance(hours=1)

    with open_home() as c:
        # The two caching articles and the evaluation one, linked by the author.
        c.review_link().execute(articles[0], articles[1], Decision.ACCEPT)
        c.review_link().execute(articles[2], articles[0], Decision.ACCEPT)
        c.review_link().execute(articles[3], articles[4], Decision.ACCEPT)
        # Confirmed mentions on the articles.
        confirm = c.confirm_mentions()
        confirm.execute(
            articles[1],
            [Accepted("Lena Okafor", "person", "Thanks Lena for the question that started it.")],
        )
        confirm.execute(
            posts[2],
            [
                Accepted(
                    "Copperline Labs",
                    "organisation",
                    "Copperline Labs is hiring an ML engineer to work on evaluation.",
                ),
                Accepted("Tomas Arends", "person", "talk to Tomas Arends."),
            ],
        )
        confirm.execute(articles[2], [Accepted("LLM-as-a-judge", "method", "")])
        confirm.execute(articles[0], [Accepted("LLM-as-a-judge", "method", "")])

    # The meetup post waits for review: what the model found, for the user to confirm.
    found = FoundMentions(
        mentions=(
            FoundMention(
                name="Fjord AI Meetup",
                category="event",
                evidence="Three things I learned speaking at Fjord AI Meetup last week:",
            ),
            FoundMention(
                name="Lena Okafor",
                category="person",
                evidence="Thanks to Lena Okafor and Northwind Analytics for hosting.",
            ),
            FoundMention(
                name="Northwind Analytics",
                category="organisation",
                evidence="Thanks to Lena Okafor and Northwind Analytics for hosting.",
            ),
        ),
        new_topics=("Public Speaking",),
    )
    with open_home(mention_finder=FakeMentionFinder(found)) as c:
        c.find_mentions().execute(posts[0], OWNER)


if __name__ == "__main__":
    target = Path(sys.argv[1])
    chart_file = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    build(target, chart_file.read_bytes() if chart_file else None)
    print(f"Fictional library written to {target}")
