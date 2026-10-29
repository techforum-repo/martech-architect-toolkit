"""Web Technology Inspector: browser-observed technology and AEM evidence."""

VERSION = "1.0.0"


def code_version() -> str:
    """The git commit this copy runs (short), or "" outside a git checkout.

    Shown in the sidebar, so it's clear whether a pull and restart took effect."""
    import subprocess
    from pathlib import Path
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).resolve().parent,
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


CODE_VERSION = code_version()  # read once at start: a restart picks up a pull
