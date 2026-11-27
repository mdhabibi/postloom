"""Measure how well postloom finds the sources for questions about a year of writing.

    PYTHONPATH=. uv run python scripts/eval/run.py --embedder local --out eval-results

It builds the benchmark library (scripts/eval/library.py), asks every question the way
the app's search box does for the whole library, and scores the sources postloom would
give the model: no model is called, so the numbers measure retrieval alone, and they are
the same on every run.

For each question the right sources are known, because the library was written with the
answer in them. Scores:

- found: at least one right source is among those given to the model;
- recall: the share of right sources given (for questions with several);
- complete: every right source given;
- first: how high the first right source ranks (1 is best);
- absent questions: "nothing found" is the right answer, so they score when no article
  or post is given at all.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path

from postloom.application.ports.embeddings import EmbeddingProvider
from postloom.bootstrap import build_container
from postloom.settings import Settings
from scripts.eval.library import Question, build
from tests.fakes import FakeChat, FakeEmbedder

KINDS = {
    "fact": "A detail in one article or post",
    "comment": "A detail in one comment",
    "when": "A subject in one month",
    "broad": "A subject across all comments",
    "absent": "Not in the library",
}


@dataclass(frozen=True)
class Result:
    question: Question
    given: tuple[str, ...]
    """Articles and posts given to the model, in order, without repeats."""

    @property
    def right(self) -> list[str]:
        return [g for g in self.given if g in self.question.gold]

    @property
    def found(self) -> bool:
        return bool(self.right) if self.question.gold else not self.given

    @property
    def recall(self) -> float:
        gold = self.question.gold
        return len(self.right) / len(gold) if gold else float(not self.given)

    @property
    def complete(self) -> bool:
        return set(self.question.gold) <= set(self.given) and (
            bool(self.question.gold) or not self.given
        )

    @property
    def first(self) -> int | None:
        for rank, item in enumerate(self.given, start=1):
            if item in self.question.gold:
                return rank
        return None


def embedder_for(name: str, models: Path) -> EmbeddingProvider:
    if name == "fake":
        return FakeEmbedder()
    from postloom.adapters.llm.local_embeddings import LocalEmbeddings

    model = "BAAI/bge-small-en-v1.5" if name == "local" else name
    return LocalEmbeddings(models, model)


def measure(home: Path, embedder: EmbeddingProvider) -> list[Result]:
    started = time.monotonic()
    asked = build(home, embedder)
    print(
        f"Built the library in {time.monotonic() - started:.0f} s; asking {len(asked)} questions."
    )
    results: list[Result] = []
    with build_container(Settings.load(home), embedder=embedder, chat=FakeChat()) as c:
        ask = c.ask_question()
        for q in asked:
            given: list[str] = []
            for source in ask.sources(q.text):
                if source.article_id is not None and source.article_id not in given:
                    given.append(source.article_id)
            results.append(Result(q, tuple(given)))
    return results


def report(results: list[Result], embedder: str) -> str:
    lines = [
        f"# postloom retrieval benchmark ({embedder})",
        "",
        f"{len(results)} questions about a fictional year of writing: 30 articles, 80 posts "
        "and their comment sections.",
        "",
        "| Questions | n | Found | Recall | Complete | First right source |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for kind, label in KINDS.items():
        group = [r for r in results if r.question.kind == kind]
        if not group:
            continue
        ranks = [r.first for r in group if r.first is not None]
        first = f"{sum(ranks) / len(ranks):.1f}" if ranks else "-"
        lines.append(
            f"| {label} | {len(group)} | {_pct(sum(r.found for r in group), len(group))} | "
            f"{sum(r.recall for r in group) / len(group):.2f} | "
            f"{_pct(sum(r.complete for r in group), len(group))} | {first} |"
        )
    scored = [r for r in results if r.question.kind != "absent"]
    absent = [r for r in results if r.question.kind == "absent"]
    lines += [
        "",
        f"Answerable questions found: {_pct(sum(r.found for r in scored), len(scored))}. "
        f"Unanswerable ones correctly empty: "
        f"{_pct(sum(r.found for r in absent), len(absent))}.",
        "",
        "## Misses",
        "",
    ]
    for r in results:
        if not r.complete:
            got = len(r.right)
            lines.append(
                f"- [{r.question.kind}] {r.question.text} "
                f"({got} of {len(r.question.gold)} right; {len(r.given)} given)"
            )
    return "\n".join(lines) + "\n"


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "-"


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure postloom's retrieval.")
    parser.add_argument("--embedder", default="fake", help="fake, local, or a FastEmbed model name")
    parser.add_argument("--home", type=Path, default=Path(".eval/home"))
    parser.add_argument("--models", type=Path, default=Path(".eval/models"))
    parser.add_argument("--out", type=Path, default=Path(".eval"))
    args = parser.parse_args()
    embedder = embedder_for(args.embedder, args.models)
    results = measure(args.home, embedder)
    args.out.mkdir(parents=True, exist_ok=True)
    text = report(results, embedder.name)
    (args.out / "report.md").write_text(text, encoding="utf-8")
    rows = [
        {
            "kind": r.question.kind,
            "question": r.question.text,
            "gold": sorted(r.question.gold),
            "given": list(r.given),
            "found": r.found,
            "recall": r.recall,
            "complete": r.complete,
            "first": r.first,
        }
        for r in results
    ]
    (args.out / "results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
