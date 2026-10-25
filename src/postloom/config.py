"""User configuration stored in ``<home>/config.json``.

Precedence: environment variable > config file > built-in default. The file is written
with owner-only permissions because it can hold an API key; it never leaves the machine.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, cast

CONFIG_FILE = "config.json"


def config_path(home: Path) -> Path:
    return home / CONFIG_FILE


def read_config(home: Path) -> dict[str, Any]:
    path = config_path(home)
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read {path}: {error}") from error
    return cast(dict[str, Any], data) if isinstance(data, dict) else {}


def update_config(home: Path, **values: object) -> None:
    """Merge ``values`` into the config file. A value of None removes the key."""
    data = read_config(home)
    for key, value in values.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    write_config(home, data)


def write_config(home: Path, data: dict[str, Any]) -> None:
    """Replace the config file atomically, readable only by the current user."""
    home.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=home, prefix=".config.", suffix=".tmp")
    try:
        Path(tmp).chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600 before any secret is written
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        Path(tmp).replace(config_path(home))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
