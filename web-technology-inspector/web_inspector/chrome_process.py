"""Chrome as its own program, for an AEM window that outlives the app.

Started with the window's saved profile and a local debugging port, Chrome
isn't a child of the app: stopping the app leaves it open and signed in, and
the next start connects to it again (Playwright's connect_over_cdp).

Chrome writes the port it chose to DevToolsActivePort in the profile, so the
port is found from the profile alone. It listens on 127.0.0.1 only.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PORT_FILE = "DevToolsActivePort"


def installed_chrome() -> str | None:
    """Google Chrome's program file, if installed."""
    if sys.platform == "win32":
        roots = [os.environ.get(name) for name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
        candidates = [Path(root) / "Google/Chrome/Application/chrome.exe" for root in roots if root]
    elif sys.platform == "darwin":
        candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    else:
        found = [shutil.which(name) for name in ("google-chrome", "google-chrome-stable")]
        candidates = [Path(path) for path in found if path]
    return next((str(path) for path in candidates if path.is_file()), None)


def running_port(profile_dir: Path) -> int | None:
    """The debugging port of a Chrome running with this profile, else None."""
    try:
        port = int((profile_dir / PORT_FILE).read_text(encoding="utf-8").splitlines()[0])
    except (OSError, ValueError, IndexError):
        return None
    try:  # the file can outlive a Chrome that crashed
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2):
            return port
    except OSError:
        return None


def launch(executable: str, profile_dir: Path, start_url: str, *, headless: bool = False,
           sandbox: bool = True, timeout: int = 30) -> int:
    """Start Chrome detached from the app; return its debugging port.

    sandbox=False only for Playwright's own Chromium, as Playwright itself
    starts it (some Linux systems don't allow its sandbox); never for the
    installed Chrome."""
    (profile_dir / PORT_FILE).unlink(missing_ok=True)
    args = [executable, f"--user-data-dir={profile_dir}", "--remote-debugging-port=0",
            "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check"]
    if headless:
        args.append("--headless=new")
    if not sandbox:
        args.append("--no-sandbox")
    options: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True  # not stopped with the app's Ctrl+C
    subprocess.Popen(args + [start_url], **options)  # noqa: S603 - fixed program and arguments
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        port = running_port(profile_dir)
        if port:
            return port
        time.sleep(0.3)
    raise RuntimeError("Chrome didn't start for the AEM window")
