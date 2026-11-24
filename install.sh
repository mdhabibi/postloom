#!/bin/sh
# Install postloom on macOS or Linux:
#
#   curl -LsSf https://raw.githubusercontent.com/mdhabibi/postloom/main/install.sh | sh
#
# It installs uv (which brings its own Python, so nothing else is needed), installs
# postloom for this user only, adds a Postloom icon to your applications and opens it.
# Run it again to update. To remove postloom (your data folder is kept):
#
#   curl -LsSf https://raw.githubusercontent.com/mdhabibi/postloom/main/install.sh | sh -s -- --uninstall
#
# Nothing here needs administrator rights.
set -eu

SOURCE="${POSTLOOM_SOURCE:-}"
PYTHON_VERSION="${POSTLOOM_PYTHON:-3.12}"

say() { printf '%s\n' "$*"; }
fail() {
    printf '\npostloom could not be installed: %s\n' "$*" >&2
    printf 'Copy this message into an issue at https://github.com/mdhabibi/postloom/issues\n' >&2
    exit 1
}

download() {
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- "$1"
    else
        fail "this needs curl or wget to download uv."
    fi
}

# The latest release from PyPI; before the first release, the newest code on GitHub.
if [ -z "$SOURCE" ]; then
    if (download https://pypi.org/pypi/postloom/json) >/dev/null 2>&1; then
        SOURCE=postloom
    else
        SOURCE=https://github.com/mdhabibi/postloom/archive/refs/heads/main.zip
    fi
fi

find_uv() {
    for candidate in "$(command -v uv 2>/dev/null || true)" \
        "${XDG_BIN_HOME:-$HOME/.local/bin}/uv" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -n "$candidate" ] && [ -x "$candidate" ]; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

UV="$(find_uv || true)"

if [ "${1:-}" = "--uninstall" ]; then
    [ -n "$UV" ] || fail "uv isn't installed, so neither is postloom."
    BIN="$("$UV" tool dir --bin)"
    if [ -x "$BIN/postloom" ]; then
        "$BIN/postloom" stop >/dev/null 2>&1 || true
        "$BIN/postloom" shortcut --remove || true
    fi
    "$UV" tool uninstall postloom || fail "uv couldn't remove postloom."
    say ""
    say "postloom is removed. Your data is still in your Postloom folder (~/Postloom by default);"
    say "delete that folder yourself if you no longer want it."
    exit 0
fi

say "Installing postloom. This takes a minute or two the first time."
say ""

if [ -z "$UV" ]; then
    say "1/3  Installing uv, which installs and updates postloom and its Python..."
    # Download first: in a pipe, a failed download would look like a successful install.
    UV_INSTALLER="$(mktemp)"
    download https://astral.sh/uv/install.sh >"$UV_INSTALLER" ||
        fail "uv couldn't be downloaded. Check your internet connection and try again."
    sh "$UV_INSTALLER" --quiet || fail "uv couldn't be installed."
    rm -f "$UV_INSTALLER"
    UV="$(find_uv)" || fail "uv was installed but can't be found. Open a new terminal and try again."
else
    say "1/3  uv is already installed."
fi

say "2/3  Installing postloom (and Python $PYTHON_VERSION if needed)..."
OLD_BIN="$("$UV" tool dir --bin)"
if [ -x "$OLD_BIN/postloom" ]; then
    "$OLD_BIN/postloom" stop >/dev/null 2>&1 || true # an update replaces the running files
fi
"$UV" tool install --quiet --force --python "$PYTHON_VERSION" \
    --refresh-package postloom --reinstall-package postloom "$SOURCE" ||
    fail "uv couldn't install postloom. Check your internet connection and try again."
"$UV" tool update-shell >/dev/null 2>&1 || true
BIN="$("$UV" tool dir --bin)"
POSTLOOM="$BIN/postloom"
[ -x "$POSTLOOM" ] || fail "postloom was installed but $POSTLOOM is missing."

say "3/3  Adding the Postloom icon..."
"$POSTLOOM" shortcut || say "     (No icon this time; you can still type: postloom open)"

say ""
say "Done. postloom is opening in your browser."
say "Next time, open it from the Postloom icon, or type: postloom open"
say ""
"$POSTLOOM" open || fail "postloom was installed but didn't start."
