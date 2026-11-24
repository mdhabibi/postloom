#!/bin/sh
# Run the same checks as CI's Linux jobs, on your own computer, for free:
#
#   sh scripts/check.sh            lint, types and tests
#   sh scripts/check.sh --browser  also the browser tests (installs Chromium once)
#
# Use it before pushing when GitHub Actions minutes have run out.
set -eu
cd "$(dirname "$0")/.."

step() { printf '\n== %s\n' "$*"; }

step "Lint and format"
uv run ruff check .
uv run ruff format --check .
step "Types"
uv run pyright
step "Tests"
uv run pytest -q -p no:cacheprovider

if [ "${1:-}" = "--browser" ]; then
    step "Browser tests"
    uv run playwright install chromium >/dev/null
    RUN_BROWSER_TESTS=1 uv run pytest tests/e2e -q -p no:cacheprovider
fi

printf '\nAll checks passed.\n'
