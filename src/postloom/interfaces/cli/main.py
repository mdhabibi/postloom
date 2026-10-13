"""``postloom`` command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from postloom import __version__
from postloom.application.defaults import DEFAULT_TOPICS
from postloom.bootstrap import Settings, build_container


def main(argv: Sequence[str] | None = None) -> int:
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
    commands.add_parser("start", parents=[common], help="Start the local web app.")

    args = parser.parse_args(argv)
    home: Path | None = args.home
    settings = Settings(home=home.expanduser()) if home else Settings()

    if args.command == "init":
        container = build_container(settings)
        created = container.seed_topics().execute(DEFAULT_TOPICS)
        print(f"Vault ready at {settings.vault_dir} ({len(created)} topics created).")
        print("Open that folder in Obsidian to browse it as a graph.")
        return 0
    if args.command == "start":
        print("The web app arrives in milestone 1. Run `postloom init` to create your vault.")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
