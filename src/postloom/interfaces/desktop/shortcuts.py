"""Desktop shortcuts, starting in the background, and messages for people without a terminal.

The installers run ``postloom shortcut`` once. It creates, for the current user only:

- macOS: ``~/Applications/Postloom.app`` (Launchpad, Spotlight, the Dock);
- Windows: ``Postloom`` in the Start menu and on the desktop;
- Linux: ``postloom.desktop`` in the applications menu.

Every shortcut runs ``python -m postloom --home <folder> open``: it opens the running
postloom in the browser, or starts one in the background first. The shortcut's own
process ends right away, so clicking it again always does something visible.
"""

from __future__ import annotations

import os
import platform
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from postloom import __version__

APP_NAME = "Postloom"
BUNDLE_ID = "io.github.mdhabibi.postloom"
LOG_FILE = "postloom.log"
LOG_LIMIT = 2_000_000
"""Past this size the log starts again; the previous one is kept as ``postloom.log.1``."""


@dataclass(frozen=True)
class Shortcuts:
    """Where postloom's shortcuts go on this computer."""

    system: str  # platform.system(): "Darwin", "Windows" or "Linux"
    user_home: Path
    python: Path
    """The interpreter of the installed postloom; on Windows the one without a window."""

    @classmethod
    def here(cls) -> Shortcuts:
        return cls(platform.system(), Path.home(), gui_python())

    def command(self, home: Path) -> list[str]:
        return [str(self.python), "-m", "postloom", "--home", str(home), "open"]

    def create(self, home: Path) -> list[Path]:
        """Create (or refresh) the shortcuts; returns what was written."""
        if self.system == "Darwin":
            return [self._mac_app(home)]
        if self.system == "Windows":
            return self._windows_links(home, remove=False)
        return [self._linux_entry(home)]

    def remove(self) -> list[Path]:
        """Remove the shortcuts; returns what was removed. The data folder is never touched."""
        removed: list[Path] = []
        if self.system == "Windows":
            return self._windows_links(None, remove=True)
        for path in self._paths():
            if path.is_dir():
                shutil.rmtree(path)
                removed.append(path)
            elif path.exists():
                path.unlink()
                removed.append(path)
        return removed

    # -- macOS -----------------------------------------------------------------------------
    def _paths(self) -> list[Path]:
        if self.system == "Darwin":
            return [self.user_home / "Applications" / f"{APP_NAME}.app"]
        share = self.user_home / ".local" / "share"
        return [
            share / "applications" / "postloom.desktop",
            share / "icons" / "hicolor" / "512x512" / "apps" / "postloom.png",
        ]

    def _mac_app(self, home: Path) -> Path:
        app = self._paths()[0]
        contents = app / "Contents"
        (contents / "MacOS").mkdir(parents=True, exist_ok=True)
        (contents / "Resources").mkdir(parents=True, exist_ok=True)
        info = {
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleExecutable": APP_NAME,
            "CFBundleIconFile": "postloom.icns",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "LSUIElement": True,  # no Dock icon for the moment it takes to open the browser
        }
        with (contents / "Info.plist").open("wb") as file:
            plistlib.dump(info, file)
        script = contents / "MacOS" / APP_NAME
        command = " ".join(_sh_quote(part) for part in self.command(home))
        script.write_text(f"#!/bin/sh\nexec {command}\n", encoding="utf-8")
        script.chmod(0o755)
        shutil.copyfile(_icon("postloom.icns"), contents / "Resources" / "postloom.icns")
        app.touch()  # Finder caches icons by modification time
        return app

    # -- Linux -----------------------------------------------------------------------------
    def _linux_entry(self, home: Path) -> Path:
        entry, icon = self._paths()
        icon.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_icon("postloom.png"), icon)
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_NAME}\n"
            "Comment=Your private LinkedIn memory\n"
            f"Exec={' '.join(_desktop_quote(part) for part in self.command(home))}\n"
            f"Icon={icon}\n"
            "Terminal=false\n"
            "Categories=Office;Network;\n"
            "StartupNotify=false\n",
            encoding="utf-8",
        )
        entry.chmod(0o755)
        return entry

    # -- Windows ---------------------------------------------------------------------------
    def _windows_links(self, home: Path | None, *, remove: bool) -> list[Path]:
        # The desktop may be redirected (OneDrive), so Windows itself says where it is.
        # Values travel in environment variables, so no path needs quoting in the script.
        env = dict(os.environ)
        if home is not None:
            env |= {
                "POSTLOOM_TARGET": str(self.python),
                "POSTLOOM_ARGS": subprocess.list2cmdline(self.command(home)[1:]),
                "POSTLOOM_ICON": str(_icon("postloom.ico")),
                "POSTLOOM_DIR": str(home),
            }
        script = _REMOVE_LINKS if remove else _CREATE_LINKS
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            raise OSError(done.stderr.strip() or "PowerShell could not change the shortcuts.")
        return [Path(line) for line in done.stdout.splitlines() if line.strip()]


_LINK_FOLDERS = """
$folders = @(
  [Environment]::GetFolderPath('Programs'),
  [Environment]::GetFolderPath('Desktop')
)
"""
_CREATE_LINKS = (
    _LINK_FOLDERS
    + """
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in $folders) {
  $path = Join-Path $folder 'Postloom.lnk'
  $link = $shell.CreateShortcut($path)
  $link.TargetPath = $env:POSTLOOM_TARGET
  $link.Arguments = $env:POSTLOOM_ARGS
  $link.IconLocation = $env:POSTLOOM_ICON
  $link.WorkingDirectory = $env:POSTLOOM_DIR
  $link.Description = 'Your private LinkedIn memory'
  $link.Save()
  Write-Output $path
}
"""
)
_REMOVE_LINKS = (
    _LINK_FOLDERS
    + """
foreach ($folder in $folders) {
  $path = Join-Path $folder 'Postloom.lnk'
  if (Test-Path $path) { Remove-Item $path; Write-Output $path }
}
"""
)


def gui_python() -> Path:
    """The interpreter to start postloom with; on Windows, the one that opens no window."""
    current = Path(sys.executable)
    windowless = current.with_name("pythonw.exe")
    return windowless if windowless.is_file() else current


def start_in_background(home: Path, python: Path | None = None) -> subprocess.Popen[bytes]:
    """Start ``postloom start`` detached from this process, logging to the data folder."""
    command = [
        str(python or gui_python()),
        "-m",
        "postloom",
        "--home",
        str(home),
        "start",
        "--no-browser",
        "--background",
    ]
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # keeps running when the shortcut's process ends
    )


def open_in_browser(url: str) -> bool:
    """Open the address in the default browser and bring it to the front.

    macOS's own `open` is used there: Python's `webbrowser` goes through AppleScript, which
    did nothing when started from the Postloom icon.
    """
    try:
        if sys.platform == "darwin":
            done = subprocess.run(["open", url], capture_output=True, check=False, timeout=30)
            if done.returncode == 0:
                return True
        elif sys.platform == "win32":
            os.startfile(url)  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType]
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    import webbrowser

    try:
        return webbrowser.open(url)
    except webbrowser.Error:
        return False


def log_to_file(home: Path) -> Path:
    """Send this process's output to the data folder's log (no terminal to show it)."""
    log = home / LOG_FILE
    home.mkdir(parents=True, exist_ok=True)
    try:
        if log.stat().st_size > LOG_LIMIT:
            log.replace(log.with_name(LOG_FILE + ".1"))
    except OSError:
        pass
    stream = log.open("a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = stream
    return log


def last_lines(path: Path, count: int = 12) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-count:])
    except OSError:
        return ""


def tell(title: str, message: str) -> None:
    """Show a message: in the terminal if there is one, otherwise in a system dialog."""
    if sys.stdout is not None and sys.stdout.isatty():
        print(f"{title}\n{message}")
        return
    if sys.stdout is not None:
        print(f"{title}\n{message}")
    try:
        if sys.platform == "darwin":
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    "on run argv",
                    "-e",
                    "display alert (item 1 of argv) message (item 2 of argv) as critical",
                    "-e",
                    "end run",
                    title,
                    message,
                ],
                check=False,
                capture_output=True,
            )
        elif sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType]
        else:
            if shutil.which("zenity"):
                dialog = ["zenity", "--error", "--title", title, "--text", message]
                subprocess.run(dialog, check=False, capture_output=True)
            elif shutil.which("notify-send"):
                subprocess.run(["notify-send", title, message], check=False, capture_output=True)
    except OSError:
        pass  # nowhere left to say it; the log has the details


def _icon(name: str) -> Path:
    return Path(str(resources.files("postloom.interfaces.desktop") / "icons" / name))


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _desktop_quote(text: str) -> str:
    """Quote one argument for a .desktop file's Exec key."""
    escaped = "".join("\\" + c if c in '"`$\\' else c for c in text).replace("%", "%%")
    return f'"{escaped}"'
