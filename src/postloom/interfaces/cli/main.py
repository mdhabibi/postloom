"""``postloom`` command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from postloom import __version__
from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.errors import ApplicationError, ProviderError
from postloom.application.use_cases import (
    IndexResult,
    IngestArticleCommand,
    IngestArticleResult,
    Passage,
    SearchResults,
)
from postloom.bootstrap import Container, Settings, build_container

ContainerFactory = Callable[[Settings], Container]
DEFAULT_PORT = 8765


def _build(settings: Settings) -> Container:
    return build_container(settings)


def main(argv: Sequence[str] | None = None, *, make_container: ContainerFactory = _build) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    home: Path | None = args.home
    settings = Settings.load(home)

    try:
        if args.command == "init":
            return _init(settings, make_container)
        if args.command == "ingest":
            return _ingest(args, settings, make_container)
        if args.command == "reindex":
            return _reindex(settings, make_container)
        if args.command == "links":
            return _links(args, settings, make_container)
        if args.command == "search":
            return _search(args, settings, make_container)
        if args.command == "start":
            return _start(args, settings, make_container)
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

    start = commands.add_parser(
        "start", parents=[common], help="Open postloom in your browser (runs on this computer)."
    )
    start.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on.")
    start.add_argument("--no-browser", action="store_true", help="Don't open a browser tab.")
    return parser


def _init(settings: Settings, make_container: ContainerFactory) -> int:
    with make_container(settings) as container:
        created = container.seed_topics().execute(DEFAULT_TOPICS)
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
    print("Restoring the article with Gemini; this can take up to a minute...")
    with make_container(settings) as container:
        result = container.ingest_article().execute(command)
        _print_result(result)
        try:
            indexed = container.index_article().execute(result.article.id)
        except ProviderError as error:
            print(f"  Warning:  Saved, but not indexed for search ({error}).")
            print("            Run `postloom reindex` to retry.")
        else:
            print(f"  Search:   {_index_summary(indexed)}")
            suggested = container.suggest_links().execute()
            if suggested.added:
                print(f"  Links:    {_count(suggested.added, 'related article')} suggested")
    return 0


def _index_summary(result: IndexResult) -> str:
    if not result.semantic:
        return f"{result.chunks} sections indexed for keyword search (no API key for meaning)."
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
        print("No Gemini API key: keyword search only. Set GEMINI_API_KEY and reindex.")
    elif links.added or links.retired:
        print(f"Links: {links.added} new suggestions, {links.retired} retired.")
    return 0


def _links(args: argparse.Namespace, settings: Settings, make_container: ContainerFactory) -> int:
    with make_container(settings) as container:
        result = container.suggest_links().execute()
        titles = {a.id: a.title for a in container.repository.list_articles()}
    if not result.semantic:
        print("Link suggestions need a Gemini API key (they compare articles by meaning).")
        print(_KEY_HELP.format(home=settings.home))
        return 1
    print(
        f"{_count(result.added, 'new suggestion')}, {result.updated} updated, "
        f"{result.retired} retired (cutoff {settings.related_similarity:.2f})."
    )
    if args.explain:
        for pair in result.pairs:
            mark = "+" if pair.similarity >= settings.related_similarity else " "
            first, second = titles.get(pair.first, pair.first), titles.get(pair.second, pair.second)
            print(f" {mark} {pair.similarity:.3f}  {_clip(first)}  <->  {_clip(second)}")
    print("Review suggestions on each article's page, or in the graph view.")
    return 0


_KEY_HELP = (
    "Save your key once in the app (postloom start, then Settings); it is kept in "
    "{home}/config.json and used by every command. Or set it for this terminal only "
    "with: export GEMINI_API_KEY=..."
)


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
    import webbrowser

    import uvicorn

    from postloom.interfaces.web.app import create_app

    port = _free_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    home = settings.home
    app = create_app(lambda: Settings.load(home), make_container)

    with make_container(settings) as container:  # first run: make sure topics exist
        container.seed_topics().execute(DEFAULT_TOPICS)

    print(f"postloom is running at {url}")
    print(f"Your data: {home}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    # Listen on the loopback interface only: postloom is never reachable from the network.
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


def _free_port(preferred: int) -> int:
    """The preferred port, or the next free one if another program is using it."""
    import socket

    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise ApplicationError(f"No free port between {preferred} and {preferred + 19}.")


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


if __name__ == "__main__":
    sys.exit(main())
