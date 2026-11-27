"""Compare ways of choosing sources on the benchmark library, to pick the next design.

    PYTHONPATH=. uv run python scripts/eval/compare.py --out .eval/compare

For every question it records, per strategy, the articles and posts in the order the
strategy would give them with the score it relies on, and prints them as ``ROW`` lines
(one JSON object each) so thresholds can be tried afterwards without rerunning:

- ``vector``: passages by embedding similarity alone;
- ``fused``: embedding and keyword results merged by reciprocal rank fusion, as the
  search box does;
- ``rerank:<model>``: the 30 best fused passages re-scored by a cross-encoder.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from postloom.application.ports.search_index import ChunkHit
from postloom.application.use_cases.search_content import article_for
from postloom.bootstrap import Container, build_container
from postloom.domain.text import plain_letters, significant_terms, term_coverage
from postloom.settings import Settings
from scripts.eval.library import build
from scripts.eval.run import embedder_for
from tests.fakes import FakeChat

POOL = 40
RERANK = 30
RRF_K = 60


@dataclass(frozen=True)
class Candidate:
    item: str
    text: str
    vector: float
    """Embedding similarity, 0 when only keyword search found it."""
    keyword: float
    """Share of the question's distinctive words in the passage."""
    fused: float


def candidates(c: Container, embedder: Any, question: str) -> list[Candidate]:
    vector = embedder.embed_query(plain_letters(question))
    by_vector = c.search_index.vector_search(vector, embedder.name, POOL)
    by_words = c.search_index.keyword_search(question, POOL)
    terms = significant_terms(question)
    pool: dict[tuple[str, int], dict[str, Any]] = {}

    def add(hits: Sequence[ChunkHit], source: str) -> None:
        for rank, hit in enumerate(hits, start=1):
            item = article_for(c.repository, hit.node)
            if item is None:
                continue
            key = (hit.node, hit.index)
            entry = pool.setdefault(
                key,
                {
                    "item": item,
                    "text": f"{hit.title}. {hit.heading}. {hit.text}",
                    "vector": 0.0,
                    "fused": 0.0,
                },
            )
            if source == "vector":
                entry["vector"] = hit.score
            entry["fused"] += 1 / (RRF_K + rank)

    add(by_vector, "vector")
    add(by_words, "words")
    out = [
        Candidate(
            e["item"],
            e["text"],
            e["vector"],
            term_coverage(terms, e["text"]),
            e["fused"],
        )
        for e in pool.values()
    ]
    return sorted(out, key=lambda x: x.fused, reverse=True)


def by_item(scored: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Items in order of their best passage."""
    seen: dict[str, float] = {}
    for item, score in scored:
        if item not in seen:
            seen[item] = score
    return list(seen.items())


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare source selection strategies.")
    parser.add_argument("--embedder", default="local")
    parser.add_argument("--rerankers", default="Xenova/ms-marco-MiniLM-L-6-v2")
    parser.add_argument("--home", type=Path, default=Path(".eval/home"))
    parser.add_argument("--models", type=Path, default=Path(".eval/models"))
    args = parser.parse_args()
    embedder = embedder_for(args.embedder, args.models)
    asked = build(args.home, embedder)
    rerankers: dict[str, Any] = {}
    for name in [n for n in args.rerankers.split(",") if n]:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        rerankers[name] = TextCrossEncoder(name, cache_dir=str(args.models))
    timings: dict[str, float] = dict.fromkeys(rerankers, 0.0)
    with build_container(Settings.load(args.home), embedder=embedder, chat=FakeChat()) as c:
        ask = c.ask_question()
        for q in asked:
            pool = candidates(c, embedder, q.text)
            row: dict[str, Any] = {"kind": q.kind, "q": q.text, "gold": sorted(q.gold)}
            current: list[str] = []
            for source in ask.sources(q.text):
                if source.article_id is not None and source.article_id not in current:
                    current.append(source.article_id)
            row["current"] = current
            vec = sorted(pool, key=lambda x: x.vector, reverse=True)
            row["vector"] = by_item([(x.item, round(x.vector, 4)) for x in vec if x.vector])[:30]
            # Fused order, keeping the embedding similarity and keyword coverage of each
            # item's best passage, so a relevance gate can be tried afterwards.
            fused: dict[str, list[float]] = {}
            for x in pool:
                best = fused.setdefault(x.item, [round(x.fused, 5), 0.0, 0.0])
                best[1] = max(best[1], round(x.vector, 4))
                best[2] = max(best[2], round(x.keyword, 3))
            row["fused"] = [[item, *scores] for item, scores in list(fused.items())[:30]]
            top = pool[:RERANK]
            for name, model in rerankers.items():
                started = time.monotonic()
                scores = list(model.rerank(q.text, [x.text for x in top]))
                timings[name] += time.monotonic() - started
                ranked = sorted(zip(top, scores, strict=True), key=lambda p: p[1], reverse=True)
                row[f"rerank:{name}"] = by_item([(x.item, round(float(s), 4)) for x, s in ranked])
            print("ROW " + json.dumps(row), flush=True)
    for name, seconds in timings.items():
        print(f"TIMING {name}: {1000 * seconds / len(asked):.0f} ms per question")


if __name__ == "__main__":
    main()
