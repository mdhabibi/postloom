"""Measure similarity scores of local embedding models, to set their search cutoffs.

Prints, for each model, the best passage score per query (on-topic, near-miss,
unrelated) and article-to-article centroid scores. A search cutoff belongs between the
lowest on-topic and the highest near-miss score; a related-article cutoff between related
and same-field-but-different articles. In CI each line is also an annotation.

    uv run python scripts/calibrate_embeddings.py [model ...]
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]

from postloom.adapters.llm.local_embeddings import LocalEmbeddings  # noqa: E402
from postloom.application.ports.embeddings import DocumentText  # noqa: E402
from postloom.domain.chunking import chunk_markdown  # noqa: E402
from postloom.domain.graph import NodeId  # noqa: E402

MODELS = sys.argv[1:] or [
    "BAAI/bge-small-en-v1.5",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
]
QUERIES = {
    "on-topic": [
        "how do I know if my semantic cache serves wrong answers",
        "which metrics should I track for a semantic cache",
        "how to choose the similarity threshold for cache hits",
    ],
    "near-miss": [
        "how do I prevent data leakage between train and test splits",
        "how to fine-tune a vision transformer on my images",
    ],
    "unrelated": ["best pasta recipe for a quick dinner", "how to train for a marathon"],
}
ARTICLES = {
    "related": (
        "Semantic Caching for AI Agents - Part 1",
        "Calling a large language model for every question is slow and expensive. A semantic "
        "cache stores previous answers with an embedding of the question. When a new question "
        "is close enough to a cached one, the cached answer is returned instead of calling the "
        "model. Choosing the distance threshold is the hard part: too loose and users get "
        "wrong answers, too strict and the hit rate collapses. We build the cache with Redis "
        "and LangGraph and measure hit rate, latency and cost savings.",
    ),
    "same field": (
        "Data Leakage in Machine Learning",
        "Data leakage happens when information from the test set reaches training. Duplicates "
        "across splits, scaling fitted on the full dataset and future information in time "
        "series all inflate validation scores. Split by time and by user, fit preprocessing "
        "on the training split only, and backtest over several windows to get honest numbers.",
    ),
    "same field 2": (
        "Vision Transformers from Scratch",
        "A vision transformer splits an image into patches, embeds each patch and adds "
        "positional encodings. Multi-head self-attention lets every patch attend to every "
        "other. We implement patch embedding, the encoder blocks and the classification head "
        "in PyTorch and train on a small image dataset.",
    ),
    "unrelated": (
        "Weeknight Pasta",
        "Boil salted water, cook the spaghetti until al dente and keep a cup of the water. "
        "Fry garlic in olive oil, add crushed tomatoes and simmer. Toss the pasta with the "
        "sauce, loosen it with the cooking water and finish with basil and parmesan.",
    ),
}


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def centroid(vectors: list[list[float]]) -> list[float]:
    total = [sum(column) for column in zip(*vectors, strict=True)]
    norm = math.sqrt(sum(x * x for x in total))
    return [x / norm for x in total]


LINES: list[str] = []


def report(line: str) -> None:
    print(line)
    LINES.append(line)


def flush(model: str) -> None:
    """One annotation per model: GitHub shows only ten per step."""
    if os.environ.get("GITHUB_ACTIONS") and LINES:
        print(f"::notice title=calibration {model}::{'%0A'.join(LINES)}")
    LINES.clear()


def main() -> None:
    fixture = (ROOT / "tests/fixtures/semantic_caching_part3/article.txt").read_text("utf-8")
    title = fixture.splitlines()[0]
    chunks = chunk_markdown(NodeId("article:part3"), title, fixture)
    cache = Path(os.environ.get("POSTLOOM_TEST_MODEL_CACHE", Path.home() / ".cache/postloom-test"))
    for name in MODELS:
        model = LocalEmbeddings(cache, name)
        passages = model.embed_documents([DocumentText(c.title, c.text) for c in chunks])
        for kind, queries in QUERIES.items():
            for query in queries:
                best = max(dot(model.embed_query(query), p) for p in passages)
                report(f"{name} | search | {kind:<9} | {best:.3f} | {query}")
        part3 = centroid(passages)
        others: dict[str, list[float]] = {}
        for kind, (article_title, text) in ARTICLES.items():
            parts = chunk_markdown(NodeId("article:x"), article_title, text)
            others[kind] = centroid(
                model.embed_documents([DocumentText(article_title, p.text) for p in parts])
            )
            report(f"{name} | related | part 3 vs {kind:<12} | {dot(part3, others[kind]):.3f}")
        report(
            f"{name} | related | same field vs same field 2 | "
            f"{dot(others['same field'], others['same field 2']):.3f}"
        )
        flush(name)


if __name__ == "__main__":
    main()
