from __future__ import annotations

"""Small per-machine UI preferences that survive a browser refresh or restart
(e.g. the mock-mode switch). Stored as JSON next to the scan history, owner-only.
Settings in .env stay the defaults until a preference is changed in the app."""

import json
import os
import tempfile

from .config import settings
from .utils import harden_file_permissions

FILE_NAME = "preferences.json"


def _path():
    return settings.data_path / FILE_NAME


def load() -> dict:
    try:
        value = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # missing or unreadable: fall back to the defaults
    return value if isinstance(value, dict) else {}


def get(key: str, default=None):
    return load().get(key, default)


def set(key: str, value) -> None:  # noqa: A001 - mirrors get()
    directory = settings.data_path
    directory.mkdir(parents=True, exist_ok=True)
    harden_file_permissions(directory, mode=0o700)
    values = dict(load(), **{key: value})
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".preferences.", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(values, handle, indent=2)
    os.replace(temporary, _path())
    harden_file_permissions(_path())
