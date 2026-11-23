"""Setting up Ollama from the app, so local models need no terminal.

Settings asks four questions in order: is Ollama installed, is it running, which model
suits this computer's memory, and is that model downloaded. It can start Ollama and
download a model through Ollama's own API, showing progress. Nothing is installed
without the user clicking, and Ollama itself is installed from ollama.com by the user.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast

DOWNLOAD_PAGE = "https://ollama.com/download"
MODEL_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9._-]+)?(:[a-z0-9._-]+)?$")


@dataclass(frozen=True)
class Suggestion:
    name: str
    size_gb: float
    label: str
    why: str
    min_memory_gb: int


SUGGESTIONS = (
    Suggestion(
        "qwen3.5:4b", 3.4, "Small", "For 8 GB of memory. Fine for chat, topics and comments.", 0
    ),
    Suggestion(
        "qwen3.5:9b", 6.6, "Balanced", "For 16 GB of memory. Good answers and reply drafts.", 14
    ),
    Suggestion("qwen3.5:27b", 17.0, "Best", "For 32 GB or more. Handles long articles best.", 30),
)
"""Checked against ollama.com/library in November 2026; one family, three sizes."""


def recommended(memory_gb: float | None) -> str:
    """The largest suggestion this computer's memory runs comfortably."""
    fitting = [s for s in SUGGESTIONS if memory_gb is not None and memory_gb >= s.min_memory_gb]
    return (fitting[-1] if fitting else SUGGESTIONS[0]).name


def memory_gb() -> float | None:
    """Total memory of this computer, if the system says."""
    try:
        if sys.platform == "win32":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("load", ctypes.c_ulong),
                    ("total", ctypes.c_ulonglong),
                    ("available", ctypes.c_ulonglong),
                    ("total_page", ctypes.c_ulonglong),
                    ("available_page", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended", ctypes.c_ulonglong),
                ]

            status = Status()
            status.length = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType]
            return status.total / 2**30
        if sys.platform == "darwin":
            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=True
            )
            return int(out.stdout.strip()) / 2**30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (OSError, ValueError, AttributeError, subprocess.CalledProcessError):
        return None


def _app_paths() -> list[Path]:
    if sys.platform == "darwin":
        return [Path("/Applications/Ollama.app"), Path.home() / "Applications" / "Ollama.app"]
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return [local / "Programs" / "Ollama" / "ollama app.exe"]
    return []


def installed() -> bool:
    return shutil.which("ollama") is not None or any(p.exists() for p in _app_paths())


def start() -> None:
    """Start Ollama the way its own installer would: the app where there is one."""
    apps = [p for p in _app_paths() if p.exists()]
    if sys.platform == "darwin" and apps:
        subprocess.run(["open", "-a", str(apps[0])], check=True, capture_output=True)
        return
    if sys.platform == "win32" and apps:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        subprocess.Popen([str(apps[0])], creationflags=flags, close_fds=True)
        return
    binary = shutil.which("ollama")
    if binary is None:
        raise OSError("Ollama isn't installed.")
    options: dict[str, Any] = {"start_new_session": True}
    if sys.platform == "win32":
        options = {"creationflags": subprocess.CREATE_NO_WINDOW}
    subprocess.Popen(
        [binary, "serve"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **options,
    )


@dataclass(frozen=True)
class Download:
    model: str
    status: str = "starting"
    completed: int = 0
    total: int = 0
    done: bool = False
    error: str | None = None


@dataclass
class Downloads:
    """One model download at a time, in a background thread, with progress to poll."""

    current: Download | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self, base_url: str, model: str) -> Download:
        if not MODEL_NAME.match(model):
            raise ValueError(f"Not a model name: {model}")
        with self._lock:
            if self.current is not None and not self.current.done:
                if self.current.model == model:
                    return self.current
                raise ValueError(f"{self.current.model} is still downloading.")
            self.current = Download(model)
        thread = threading.Thread(target=self._pull, args=(base_url, model), daemon=True)
        thread.start()
        return self.current

    def _update(self, **changes: Any) -> None:
        with self._lock:
            if self.current is not None:
                self.current = replace(self.current, **changes)

    def _pull(self, base_url: str, model: str) -> None:
        request = urllib.request.Request(
            base_url.rstrip("/") + "/api/pull",
            data=json.dumps({"model": model, "stream": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=60) as reply:
                for line in reply:
                    if not line.strip():
                        continue
                    event = cast(dict[str, Any], json.loads(line))
                    if "error" in event:
                        self._update(done=True, error=str(event["error"]))
                        return
                    progress = {k: int(event[k]) for k in ("completed", "total") if k in event}
                    self._update(status=str(event.get("status", "")), **progress)
            self._update(done=True, status="success")
        except (OSError, ValueError) as error:
            self._update(done=True, error=f"The download stopped: {error}")


def running_models(base_url: str) -> list[str] | None:
    """Installed models, or None when Ollama doesn't answer at this address."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(base_url.rstrip("/") + "/api/tags", timeout=3) as reply:
            body = cast(dict[str, Any], json.loads(reply.read()))
    except (OSError, ValueError):
        return None
    models = body.get("models")
    if not isinstance(models, list):
        return []
    names = [cast(dict[str, Any], m).get("name") for m in cast(list[Any], models)]
    return sorted(n for n in names if isinstance(n, str))
