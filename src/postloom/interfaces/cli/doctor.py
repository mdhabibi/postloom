"""``postloom doctor``: check that everything postloom depends on actually works.

"Test connection" in Settings only lists a provider's models. This goes further and makes
one tiny real call of each kind postloom uses (structured output, plain text, embeddings)
with the models that are configured, so a wrong model name, a key without credits or a
model that can't return structured output shows up here and not in the middle of adding
an article. The calls are metered like any other and cost a fraction of a cent.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field

from postloom import __version__
from postloom.application.errors import ApplicationError
from postloom.application.ports.usage import Task
from postloom.bootstrap import Container, Settings
from postloom.settings import MODEL_TASKS

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
STRUCTURED_TASKS = ("extraction", "comments")
"""Tasks whose model must return JSON that follows a schema."""
SLOW_SECONDS = 15.0
"""A test call this small should take a few seconds; above this, say why it didn't."""


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str
    notes: tuple[str, ...] = field(default=(), compare=False)
    """What happened along the way: retries, and why a call was slow."""


def run_checks(settings: Settings, container: Container) -> list[Check]:
    checks = [_vault(container)]
    checks += _models(settings, container)
    checks.append(_embeddings(container))
    return checks


def print_report(settings: Settings, checks: list[Check]) -> int:
    print(f"postloom {__version__}")
    print(f"Data folder: {settings.home}")
    spec = settings.spec
    print(f"Provider:    {spec.label if spec else 'none chosen yet'}")
    print()
    for check in checks:
        print(f"  {'ok  ' if check.ok else 'FAIL'}  {check.name}: {check.detail}")
        for note in check.notes:
            print(f"          {note}")
    failed = [c for c in checks if not c.ok]
    print()
    if failed:
        print(f"{len(failed)} of {len(checks)} checks failed. Fix those and run this again.")
        return 1
    print("Everything works.")
    return 0


def _vault(container: Container) -> Check:
    snapshot = container.vault.read()
    if snapshot.problems:
        first = snapshot.problems[0]
        more = f" (and {len(snapshot.problems) - 1} more)" if len(snapshot.problems) > 1 else ""
        return Check("Vault", False, f"{first.path} can't be read: {first.reason}{more}")
    posts = sum(1 for n in snapshot.posts if n.announces is None)
    counts = (
        f"{len(snapshot.articles)} articles, {posts} posts, {len(snapshot.comments)} comments, "
        f"{len(snapshot.people)} people, {len(snapshot.entities)} mentioned entries"
    )
    pending = container.vault.changes().count
    if pending:
        return Check("Vault", True, f"{counts}; {pending} edited notes will be read on start")
    return Check("Vault", True, f"{counts}; every note is readable")


def _models(settings: Settings, container: Container) -> list[Check]:
    gateway = container.gateway
    if gateway is None:
        return [Check("Models", False, container.not_configured)]
    checks: list[Check] = []
    tested: dict[tuple[str, bool], Check] = {}
    for task in MODEL_TASKS:
        model = settings.model(task)
        if task == "embedding" or not model:
            continue
        structured = task in STRUCTURED_TASKS
        if (model, structured) not in tested:
            if structured:
                call: Callable[[], object] = lambda m=model: gateway.json(  # noqa: E731
                    Task.TEST,
                    m,
                    system="You are a connection test.",
                    prompt='Return {"ok": true}.',
                    schema=SCHEMA,
                    schema_name="connection_test",
                    temperature=0.0,
                    max_output_tokens=512,
                )
            else:
                call = lambda m=model: gateway.text(  # noqa: E731
                    Task.TEST,
                    m,
                    system="You are a connection test.",
                    turns=[("user", "Reply with the single word OK.")],
                    temperature=0.0,
                    max_output_tokens=512,
                )
            kind = "structured output" if structured else "text"
            tested[(model, structured)] = _timed(f"{model} ({kind})", call)
        result = tested[(model, structured)]
        checks.append(Check(f"{task.capitalize()} model", result.ok, result.detail))
    return checks


def _embeddings(container: Container) -> Check:
    embedder = container.embedder
    if embedder is None:
        return Check("Search by meaning", True, "off; search uses keywords only")
    result = _timed(embedder.name, lambda: embedder.embed_query("connection test"))
    return Check("Search by meaning", result.ok, result.detail)


def _timed(what: str, call: Callable[[], object]) -> Check:
    started = time.perf_counter()
    with _retries() as retries:
        try:
            call()
        except ApplicationError as error:  # provider, budget and configuration errors
            return Check(what, False, f"{what}: {error}", tuple(retries))
    seconds = time.perf_counter() - started
    notes = list(retries)
    if seconds > SLOW_SECONDS:
        notes.append(_slow_hint(seconds, bool(retries)))
    return Check(what, True, f"{what}, {seconds:.1f}s", tuple(notes))


def _slow_hint(seconds: int | float, retried: bool) -> str:
    if retried:
        return (
            f"Slow ({seconds:.0f}s) because the provider was busy and postloom waited and "
            "retried. Usually temporary; if it keeps happening, choose another model."
        )
    return (
        f"Slow ({seconds:.0f}s) without any retry: the model itself took that long. If it "
        "keeps happening, the provider is overloaded or the model thinks a lot; choose a "
        "faster model for this task in Settings."
    )


@contextmanager
def _retries() -> Generator[list[str], None, None]:
    """Collect the retries the provider adapters log, instead of printing them."""
    found: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            found.append(f"Retry: {record.getMessage()}")

    logger = logging.getLogger("postloom.llm")
    handler, propagate = Collect(logging.WARNING), logger.propagate
    logger.addHandler(handler)
    logger.propagate = False
    try:
        yield found
    finally:
        logger.removeHandler(handler)
        logger.propagate = propagate
