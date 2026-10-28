from __future__ import annotations

import os
from pathlib import Path


def harden_file_permissions(path: Path, *, mode: int = 0o600) -> None:
    """Restrict a local data file (SQLite DB, log file, .env) to the owning
    user only. Defaults to 0o600; pass mode=0o700 for a directory.

    POSIX only — chmod doesn't provide equivalent access control on Windows,
    so this is a no-op there. Best-effort: never raises, so it can't block
    app startup or logging."""
    if os.name == "nt":
        return
    try:
        path.chmod(mode)
    except OSError:
        pass
