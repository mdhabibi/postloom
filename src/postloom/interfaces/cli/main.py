"""``postloom`` command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import cast

from postloom import __version__, how_to_run
from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.errors import ApplicationError, BudgetExceededError, ProviderError
from postloom.application.use_cases import (
    IndexResult,
    IngestArticleCommand,
    IngestArticleResult,
    IngestPostCommand,
    Passage,
    SearchResults,
    SyncReport,
)
from postloom.bootstrap import Container, Settings, build_container
from postloom.interfaces.cli import doctor
from postloom.interfaces.desktop.shortcuts import (
    LOG_FILE,
    Shortcuts,
    blocked_message,
    last_lines,
    log_to_file,
    open_in_browser,
    open_privacy_settings,
    record_failure,
    start_in_background,
    tell,
)

ContainerFactory = Callable[[Settings], Container]
DEFAULT_PORT = 8765


def _build(settings: Settings) -> Container:
    return build_container(settings)


def main(argv: Sequence[str] | None = None, *, make_container: ContainerFactory = _build) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    home: Path | None = args.home
    if args.command == "open":
        return _open_from_icon(home)
    settings = Settings.load(home)

    def opened(settings: Settings) -> Container:
        """Open the data folder, and say so when that changed something."""
        container = make_container(settings)
        _print_vault_report(container.vault_report, settings)
        return container

    try:
        if args.command == "sync":
            return _sync(settings, make_container)
        if args.command == "doctor":
            return _doctor(settings, opened)
        if args.command == "init":
            return _init(settings, opened)
        if args.command == "ingest":
            return _ingest(args, settings, opened)
        if args.command == "post":
            return _post(args, settings, opened)
        if args.command == "reindex":
            return _reindex(settings, opened)
        if args.command == "usage":
            return _usage(settings, opened)
        if args.command == "links":
            return _links(args, settings, opened)
        if args.command == "search":
            return _search(args, settings, opened)
        if args.command == "start":
            return _start(args, settings, opened)
        if args.command == "open":
            return _open(settings)
        if args.command == "stop":
            return _stop(settings)
        if args.command == "shortcut":
            return _shortcut(args, settings)
    except ApplicationError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    parser.print_help()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="postloom",
        description="Local-first knowledge graph and chat for your LinkedIn writing.",
    )
    home_help = "Data folder (default: ~/Postloom, or $POSTLOOM_HOME)."
    parser.add_argument("--version", action="version", version=f"postloom {__version__}")
    parser.add_argument("--home", type=Path, help=home_help)

    # Accept --home after the command too ("postloom init --home X"). SUPPRESS keeps a
    # value given before the command from being overwritten when it is absent after it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", type=Path, default=argparse.SUPPRESS, help=home_help)

    commands = parser.add_subparsers(dest="command", metavar="<command>")
    commands.add_parser("init", parents=[common], help="Create your vault with the default topics.")

    ingest = commands.add_parser(
        "ingest",
        parents=[common],
        help="Add an article and its announcement post from text files.",
        description=(
            "Add an article and its announcement post. Paste each into a text file first, "
            "e.g. `pbpaste > article.txt` on macOS."
        ),
    )
    ingest.add_argument("article", type=Path, help="Text file with the pasted article.")
    ingest.add_argument("post", type=Path, help="Text file with the pasted announcement post.")
    ingest.add_argument("--url", help="The article's LinkedIn URL.")
    ingest.add_argument("--post-url", help="The post's LinkedIn URL.")
    ingest.add_argument("--date", type=date.fromisoformat, help="Publish date, YYYY-MM-DD.")

    post = commands.add_parser(
        "post",
        parents=[common],
        help="Add a post that doesn't announce an article, from a text file.",
        description=(
            "Add a stand-alone post. Paste it into a text file first, e.g. "
            "`pbpaste > post.txt` on macOS. Adding the same post again updates it."
        ),
    )
    post.add_argument("file", type=Path, help="Text file with the pasted post.")
    post.add_argument("--url", help="The post's LinkedIn URL.")
    post.add_argument("--date", type=date.fromisoformat, help="Publish date, YYYY-MM-DD.")

    search = commands.add_parser(
        "search", parents=[common], help="Search your articles by keywords and meaning."
    )
    search.add_argument("query", nargs="+", help="What you're looking for, in your own words.")
    search.add_argument("--limit", type=int, default=5, help="How many articles to show.")
    search.add_argument(
        "--explain", action="store_true", help="Show the relevance scores behind each match."
    )

    commands.add_parser(
        "reindex",
        parents=[common],
        help="Rebuild the search index (after upgrading or changing the embedding model).",
    )

    links = commands.add_parser(
        "links",
        parents=[common],
        help="Suggest links between related articles (you accept or dismiss them in the app).",
    )
    links.add_argument(
        "--explain", action="store_true", help="Show the similarity of every pair of articles."
    )

    commands.add_parser(
        "usage", parents=[common], help="Show this month's model calls, tokens and cost."
    )
    commands.add_parser(
        "sync",
        parents=[common],
        help="Read your vault again: after editing notes by hand, or to rebuild a lost index.",
    )
    commands.add_parser(
        "doctor",
        parents=[common],
        help="Check that your provider, models, search and vault all work (tiny real calls).",
    )

    start = commands.add_parser(
        "start", parents=[common], help="Open postloom in your browser (runs on this computer)."
    )
    start.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on.")
    start.add_argument("--no-browser", action="store_true", help="Don't open a browser tab.")
    start.add_argument(
        "--background",
        action="store_true",
        help=f"Write messages to {LOG_FILE} in the data folder instead of the terminal.",
    )
    commands.add_parser(
        "open",
        parents=[common],
        help="Open postloom in your browser, starting it in the background if needed.",
        description="What the desktop shortcut does. `postloom start` runs in this terminal.",
    )
    commands.add_parser(
        "stop",
        parents=[common],
        help="Stop a postloom that runs in the background (the installer does this to update).",
    )
    shortcut = commands.add_parser(
        "shortcut",
        parents=[common],
        help="Add a Postloom icon to your applications (the installer does this).",
    )
    shortcut.add_argument("--remove", action="store_true", help="Remove the icon instead.")
    return parser


def _sync(settings: Settings, make_container: ContainerFactory) -> int:
    with make_container(settings) as container:
        # Opening the data folder already syncs when notes changed; otherwise do it now,
        # so the command always checks the whole vault.
        report = container.vault_report or container.sync_vault().execute()
    _print_vault_report(report, settings, always=True)
    return 0 if report.applied else 1


def _doctor(settings: Settings, make_container: ContainerFactory) -> int:
    with make_container(settings) as container:
        return doctor.print_report(settings, doctor.run_checks(settings, container))


def _print_vault_report(
    report: SyncReport | None, settings: Settings, *, always: bool = False
) -> None:
    if report is None:
        return
    if not report.applied:
        print("Some notes in your vault can't be read, so your recent edits were not applied:")
        for problem in report.problems:
            print(f"  {problem.path}: {problem.reason}")
        print(f"Fix them (or undo the edit), then run `{how_to_run('sync')}`.")
        return
    contents = (
        f"{_count(report.articles, 'article')}, {_count(report.comments, 'comment')}, "
        f"{_count(report.people, 'person', 'people')}"
    )
    if report.reason == "rebuilt":
        print(f"Rebuilt the index from your vault: {contents}.")
    elif report.reason == "upgraded":
        print("Rewrote your vault's notes in the current format, so they can be read back.")
    elif report.reason == "restored":
        print(f"Your vault's notes were missing; wrote them again from the index ({contents}).")
    elif report.changed:
        print(f"Read {_count(report.changed, 'edited note')} from your vault: {contents}.")
    elif always:
        print(f"Your vault and the index agree: {contents}.")
    for problem in report.problems:
        print(f"  Skipped {problem.path}: {problem.reason}")
    if report.trashed:
        trash = settings.vault_dir / ".postloom" / "trash"
        print(f"Moved {_count(len(report.trashed), 'note')} that match nothing to {trash}.")
    if report.index_error:
        print(
            f"Search by meaning is incomplete ({report.index_error}). "
            f"Run `{how_to_run('reindex')}`."
        )


def _init(settings: Settings, make_container: ContainerFactory) -> int:
    with make_container(settings) as container:
        created = container.seed_topics().execute(DEFAULT_TOPICS, only_when_empty=True)
    print(f"Vault ready at {settings.vault_dir} ({len(created)} topics created).")
    print("Open that folder in Obsidian to browse it as a graph.")
    return 0


def _ingest(args: argparse.Namespace, settings: Settings, make_container: ContainerFactory) -> int:
    texts: list[str] = []
    for path in (args.article, args.post):
        file = Path(path).expanduser()
        if not file.is_file():
            raise ApplicationError(f"File not found: {file}")
        texts.append(file.read_text(encoding="utf-8"))

    command = IngestArticleCommand(
        article_text=texts[0],
        post_text=texts[1],
        article_url=args.url,
        post_url=args.post_url,
        published_on=args.date,
    )
    with make_container(settings) as container:
        provider = settings.spec.label if settings.spec else "the model"
        print(f"Restoring the article with {provider}; this can take a minute or more...")
        result = container.ingest_article().execute(command)
        _print_result(result)
        try:
            indexed = container.index_article().execute(result.article.id)
        except (ProviderError, BudgetExceededError) as error:
            print(f"  Warning:  Saved, but not indexed for search ({error}).")
            print(f"            Run `{how_to_run('reindex')}` to retry.")
        else:
            print(f"  Search:   {_index_summary(indexed)}")
            suggested = container.suggest_links().execute()
            if suggested.added:
                print(f"  Links:    {_count(suggested.added, 'related article')} suggested")
    return 0


def _post(args: argparse.Namespace, settings: Settings, make_container: ContainerFactory) -> int:
    file = Path(args.file).expanduser()
    if not file.is_file():
        raise ApplicationError(f"File not found: {file}")
    command = IngestPostCommand(
        text=file.read_text(encoding="utf-8"), url=args.url, published_on=args.date
    )
    with make_container(settings) as container:
        result = container.ingest_post().execute(command)
        status = "Updated" if result.is_update else "Added"
        print(f'\n{status} post: "{result.post.title}"')
        print(f"  Topics:   {', '.join(t.name for t in result.topics) or '(none)'}")
        print(f"  Note:     {result.note_path}")
        for warning in result.warnings:
            print(f"  Warning:  {warning}")
        try:
            indexed = container.index_article().execute(result.post.id)
        except (ProviderError, BudgetExceededError) as error:
            print(f"  Warning:  Saved, but not indexed for search ({error}).")
            print(f"            Run `{how_to_run('reindex')}` to retry.")
        else:
            print(f"  Search:   {_index_summary(indexed)}")
    return 0


def _index_summary(result: IndexResult) -> str:
    if not result.semantic:
        return f"{result.chunks} sections indexed for keyword search (embeddings are off)."
    return f"{result.chunks} sections indexed ({result.embedded} embedded, {result.reused} reused)."


def _reindex(settings: Settings, make_container: ContainerFactory) -> int:
    with make_container(settings) as container:
        result = container.reindex_all().execute()
        semantic = container.embedder is not None
        links = container.suggest_links().execute()
    print(
        f"Indexed {_count(result.articles, 'article')}, {_count(result.chunks, 'section')} "
        f"({result.embedded} embedded, {result.reused} reused)."
    )
    if not semantic:
        print("Embeddings are off, so search uses keywords only. Turn them on in Settings.")
    elif links.added or links.retired:
        print(f"Links: {links.added} new suggestions, {links.retired} retired.")
    return 0


def _links(args: argparse.Namespace, settings: Settings, make_container: ContainerFactory) -> int:
    with make_container(settings) as container:
        result = container.suggest_links().execute()
        titles = {a.id: a.title for a in container.repository.list_articles()}
        cutoff = container.related_similarity
    if not result.semantic:
        print("Link suggestions compare articles by meaning, and embeddings are off.")
        print("Turn them on in Settings (local embeddings are free), then run this again.")
        return 1
    print(
        f"{_count(result.added, 'new suggestion')}, {result.updated} updated, "
        f"{result.retired} retired (cutoff {cutoff:.2f})."
    )
    if result.compared < 2:
        print(
            f"Nothing to compare yet: {_count(result.compared, 'article')} of "
            f"{result.articles} {'has' if result.compared == 1 else 'have'} embeddings, and "
            "suggestions need at least two. Add another article"
            + (f", or run `{how_to_run('reindex')}`." if result.compared < result.articles else ".")
        )
    if args.explain:
        for pair in result.pairs:
            mark = "+" if pair.similarity >= cutoff else " "
            first, second = titles.get(pair.first, pair.first), titles.get(pair.second, pair.second)
            print(f" {mark} {pair.similarity:.3f}  {_clip(first)}  <->  {_clip(second)}")
    print("Review suggestions on each article's page, or in the graph view.")
    return 0


def _usage(settings: Settings, make_container: ContainerFactory) -> int:
    with make_container(settings) as container:
        summary = container.usage().execute()
    calls, cost = _count(summary.calls, "call"), _money(summary.cost_usd)
    print(f"Model usage in {summary.month}: {calls}, {cost}")
    for task in summary.by_task:
        tokens = f"{task.input_tokens:,} in / {task.output_tokens:,} out"
        print(
            f"  {task.task.value:<11} {task.calls:>5} calls  {tokens:<26} {_money(task.cost_usd)}"
        )
    if summary.unpriced_calls:
        print(
            f"  {_count(summary.unpriced_calls, 'call')} used models without a known price "
            '(not included). Add prices in config.json under "prices".'
        )
    if summary.budget_usd is not None:
        left = _money(summary.remaining_usd or 0)
        print(f"Budget: {_money(summary.budget_usd)} a month, {left} left.")
    return 0


def _money(amount: float) -> str:
    return f"${amount:.4f}" if 0 < amount < 0.01 else f"${amount:.2f}"


def _clip(text: str, width: int = 40) -> str:
    return text if len(text) <= width else text[: width - 3] + "..."


def _search(args: argparse.Namespace, settings: Settings, make_container: ContainerFactory) -> int:
    query = " ".join(args.query)
    with make_container(settings) as container:
        results = container.search().execute(query, limit=args.limit)
    _print_search(results, explain=args.explain)
    return 0


def _print_search(found: SearchResults, *, explain: bool = False) -> None:
    for warning in found.warnings:
        print(f"Warning: {warning}")
    if not found.results:
        print(f'No articles match "{found.query}".')
        return
    methods = " + ".join(sorted(found.methods))
    print(f'{_count(len(found.results), "article")} for "{found.query}" ({methods}):')
    for rank, result in enumerate(found.results, start=1):
        print(f"\n{rank}. {result.title}")
        if result.url:
            print(f"   {result.url}")
        for passage in result.passages:
            where = passage.heading or "Introduction"
            how = "+".join(sorted(passage.matched_by))
            print(f"   - [{where}] ({how})")
            if explain:
                print(f"     scores: {_scores(passage)}")
            print(f"     {passage.excerpt}")


def _print_result(result: IngestArticleResult) -> None:
    article = result.article
    status = "Updated" if result.is_update else "Added"
    print(f'\n{status}: "{article.title}"')
    print(f"  Topics:   {', '.join(t.name for t in result.topics) or '(none)'}")
    if article.series is not None:
        part = f", part {article.series_part}" if article.series_part else ""
        print(f"  Series:   {article.series.name}{part}")
    if article.entities:
        print(f"  Entities: {', '.join(article.entities)}")
    if result.post.links:
        print(f"  Links:    {', '.join(result.post.links)}")
    print(f"  Note:     {result.note_path}")
    for warning in result.warnings:
        print(f"  Warning:  {warning}")


def _scores(passage: Passage) -> str:
    parts: list[str] = []
    if passage.similarity is not None:
        parts.append(f"meaning similarity {passage.similarity:.3f}")
    if passage.keyword_score is not None:
        parts.append(f"keyword relevance {passage.keyword_score:.2f}")
    return ", ".join(parts)


def _start(args: argparse.Namespace, settings: Settings, make_container: ContainerFactory) -> int:
    import threading

    import uvicorn

    from postloom.interfaces.web.app import create_app

    home = settings.home
    if args.background or sys.stdout is None:  # sys.stdout is None under pythonw
        log_to_file(home)
    running = already_running(home)
    if running is not None:
        # A second start (say, the desktop shortcut clicked again) must not serve the same
        # data folder twice: two servers would write the same database and vault.
        print(f"postloom is already running at {running}")
        if not args.no_browser:
            open_in_browser(running)
        return 0

    port = _free_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    servers: list[uvicorn.Server] = []

    def shutdown() -> None:  # the app's Quit button: there may be no window to close
        for server in servers:
            server.should_exit = True

    app = create_app(lambda: Settings.load(home), make_container, shutdown=shutdown)

    with make_container(settings) as container:  # first run: start with the default topics
        container.seed_topics().execute(DEFAULT_TOPICS, only_when_empty=True)

    print(f"postloom is running at {url}")
    print(f"Your data: {home}")
    if not args.background:
        print("Keep this window open while you use postloom. Close it, press Ctrl+C or")
        print("choose Quit in the app to stop.")
    if not args.no_browser:
        threading.Timer(1.0, open_in_browser, args=(url,)).start()
    marker = home / RUNNING_FILE
    _write_running(marker, port)
    try:
        # Listen on the loopback interface only: postloom is never reachable from the network.
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        servers.append(uvicorn.Server(config))
        servers[0].run()
    finally:
        marker.unlink(missing_ok=True)
    return 0


STARTUP_SECONDS = 90
"""How long `open` waits for a background start (a first start may upgrade the vault)."""


def _open_from_icon(home: Path | None) -> int:
    """`open` as the icon runs it: no terminal, so every failure becomes a dialog."""
    import traceback

    folder = home or Path("~/Postloom")
    try:
        settings = Settings.load(home)
        folder = settings.home
        folder.mkdir(parents=True, exist_ok=True)
        next(folder.iterdir(), None)  # macOS refuses here when the app may not read the drive
        return _open(settings)
    except PermissionError:
        log = record_failure(traceback.format_exc())
        tell("postloom can't open your data folder", blocked_message(folder, log))
        open_privacy_settings()
        return 1
    except Exception:
        log = record_failure(traceback.format_exc())
        tell("postloom could not start", f"The details are in {log}.")
        return 1


def _open(settings: Settings) -> int:
    import time

    home = settings.home
    url = already_running(home)
    if url is None:
        process = start_in_background(home)
        deadline = time.monotonic() + STARTUP_SECONDS
        while url is None and time.monotonic() < deadline:
            if process.poll() is not None:
                break
            time.sleep(0.3)
            url = already_running(home)
        if url is None:
            details = last_lines(home / LOG_FILE)
            tell(
                "postloom could not start",
                f"Details are in {home / LOG_FILE}."
                + (f"\n\nThe last lines:\n{details}" if details else ""),
            )
            return 1
    print(f"postloom is running at {url}")
    if not open_in_browser(url):
        tell("postloom is running", f"Open {url} in your browser.")
    return 0


def _stop(settings: Settings) -> int:
    import http.client
    import time
    import urllib.request

    url = already_running(settings.home)
    if url is None:
        print("postloom isn't running.")
        return 0
    request = urllib.request.Request(
        url + "api/quit",
        data=b"{}",
        method="POST",
        headers={"X-Postloom": "1", "Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        opener.open(request, timeout=5).close()
    except (ConnectionError, http.client.HTTPException):
        pass  # it closed the connection while stopping; the check below says whether it did
    except OSError as error:
        raise ApplicationError(f"postloom at {url} didn't stop: {error}") from error
    deadline = time.monotonic() + 15
    while already_running(settings.home) is not None and time.monotonic() < deadline:
        time.sleep(0.2)
    if already_running(settings.home) is not None:
        raise ApplicationError(f"postloom at {url} is still running.")
    print("postloom has stopped.")
    return 0


def _shortcut(args: argparse.Namespace, settings: Settings) -> int:
    shortcuts = Shortcuts.here()
    try:
        changed = shortcuts.remove() if args.remove else shortcuts.create(settings.home)
    except OSError as error:
        raise ApplicationError(f"Couldn't change the Postloom icon: {error}") from error
    if args.remove:
        print("Removed the Postloom icon." if changed else "There was no Postloom icon to remove.")
        print(f"Your data stays in {settings.home}.")
        return 0
    for path in changed:
        print(f"Added {path}")
    where = {
        "Darwin": "in Launchpad, Spotlight and Applications",
        "Windows": "in the Start menu and on your desktop",
    }.get(shortcuts.system, "in your applications menu")
    print(f"Open postloom any time from the Postloom icon {where}.")
    return 0


RUNNING_FILE = ".running.json"
"""Written while `postloom start` serves a data folder: which port to find it on."""


def already_running(home: Path) -> str | None:
    """The address of a postloom already serving this data folder, if one answers."""
    import json
    import urllib.request

    try:
        port = int(json.loads((home / RUNNING_FILE).read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    url = f"http://127.0.0.1:{port}/"
    # Never through a proxy: the address is this computer's.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url + "api/ping", timeout=2) as reply:
            answer: object = json.loads(reply.read())
    except (OSError, ValueError):
        return None  # left behind by a postloom that was killed; the port is someone else's
    if not isinstance(answer, dict):
        return None
    fields = cast("dict[str, object]", answer)
    if fields.get("app") != "postloom":
        return None
    try:
        same = Path(str(fields.get("home"))).resolve() == home.resolve()
    except OSError:
        return None
    return url if same else None


def _write_running(marker: Path, port: int) -> None:
    import json
    import os

    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    except OSError:
        pass  # only a convenience for a second start; never a reason not to run


def _free_port(preferred: int) -> int:
    """The preferred port, or the next free one if another program is using it."""
    import socket

    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise ApplicationError(f"No free port between {preferred} and {preferred + 19}.")


def _count(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {plural or noun + 's'}"


if __name__ == "__main__":
    sys.exit(main())
