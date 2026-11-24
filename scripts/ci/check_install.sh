#!/bin/sh
# CI: install postloom the way a user does (install.sh), then check the icon, a second
# open, an update while it runs, and the uninstall. POSTLOOM_SOURCE points at the checkout.
set -eux

ping() { curl -sf --noproxy '*' http://127.0.0.1:8765/api/ping; }
stopped() { # a plain `! ping` would not stop the script under set -e
    if ping >/dev/null 2>&1; then
        echo "postloom is still running" >&2
        exit 1
    fi
}

sh install.sh
ping  # the installer opened postloom
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
POSTLOOM="$("$UV" tool dir --bin)/postloom"

if [ "$(uname)" = Darwin ]; then
    ICON="/Applications/Postloom.app"
    [ -d "$ICON" ] || ICON="$HOME/Applications/Postloom.app"
    plutil -lint "$ICON/Contents/Info.plist"
    test -s "$ICON/Contents/Resources/postloom.icns"
    LAUNCH="$ICON/Contents/MacOS/Postloom"
else
    ICON="$HOME/.local/share/applications/postloom.desktop"
    LAUNCH="$(mktemp)"
    printf '%s\n' "$(sed -n 's/^Exec=//p' "$ICON")" >"$LAUNCH"
fi
test -e "$ICON"

"$POSTLOOM" open  # a second open finds the running one
test "$(ls "$HOME/Postloom")" != ""

"$POSTLOOM" stop
stopped
if [ "$(uname)" = Darwin ]; then
    # Exactly as Launchpad starts it, so macOS chooses how the app runs (it once ran the
    # launcher as Intel on Apple silicon, which only showed when started this way).
    open -W --stderr "$RUNNER_TEMP/icon.err" "$ICON" || true
    cat "$RUNNER_TEMP/icon.err" || true
    ping
    "$POSTLOOM" stop
fi
sh "$LAUNCH" # what clicking the icon runs
ping

sh install.sh  # updating while postloom runs
ping

sh install.sh --uninstall
stopped
test ! -e "$ICON"
test ! -e "$POSTLOOM"
test -d "$HOME/Postloom/vault"  # the data is kept
