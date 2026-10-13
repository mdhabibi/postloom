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
    SearchResults,
)
from postloom.bootstrap import Container, Settings, build_container

ContainerFactory = Callable[[Settings], Container]


def _build(settings: Settings) -> Container:
    return build_container(settings)


def main(argv: Sequence[str] | None = None, *, make_container: ContainerFactory = _build) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    home: Path | None = args.home
    settings = Settings(home=home.expanduser()) if home else Settings()

    try:
        if args.command == "init":
            return _init(settings, make_container)
        if args.command == "ingest":
            return _ingest(args, settings, make_container)
        if args.command == "reindex":
            return _reindex(settings, make_container)
        if args.command == "search":
            return _search(args, settings, make_container)
        if args.command == "start":
            print("The web app arrives later in milestone 1. Use `postloom ingest` for now.")
            return 0
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

    commands.add_parser(
        "reindex",
        parents=[common],
        help="Rebuild the search index (after upgrading or changing the embedding model).",
    )

    commands.add_parser("start", parents=[common], help="Start the local web app.")
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
    return 0


def _index_summary(result: IndexResult) -> str:
    if not result.semantic:
        return f"{result.chunks} sections indexed for keyword search (no API key for meaning)."
    return f"{result.chunks} sections indexed ({result.embedded} embedded, {result.reused} reused)."


def _reindex(settings: Settings, make_container: ContainerFactory) -> int:
    with make_container(settings) as container:
        result = container.reindex_all().execute()
        semantic = container.embedder is not None
    print(
        f"Indexed {_count(result.articles, 'article')}, {_count(result.chunks, 'section')} "
        f"({result.embedded} embedded, {result.reused} reused)."
    )
    if not semantic:
        print("No Gemini API key: keyword search only. Set GEMINI_API_KEY and reindex.")
    return 0


def _search(args: argparse.Namespace, settings: Settings, make_container: ContainerFactory) -> int:
    query = " ".join(args.query)
    with make_container(settings) as container:
        results = container.search().execute(query, limit=args.limit)
    _print_search(results)
    return 0


def _print_search(found: SearchResults) -> None:
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


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


if __name__ == "__main__":
    sys.exit(main())
