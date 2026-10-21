"""Basic public-repository preflight checks.

This is a heuristic audit, not a comprehensive
secret or intellectual-property scanner.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PATTERNS = {
    "Private network reference": (
        r"https?://(?:localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+)"
    ),
    "Possible embedded bearer token": (
        r"(?i)authorization\s*[:=]\s*['\"]bearer\s+[A-Za-z0-9._-]{16,}"
    ),
    "Possible private key": (
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
}

SKIP = {
    ".git", ".venv", "venv", "backup",
    "backups", "legacy_pages", "data",
    "reports", "screenshots", "__pycache__"
}


def tracked_files():
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True
    )

    if result.returncode != 0:
        print("Git repository not initialized.")
        return []

    return [
        ROOT / p.decode("utf-8", errors="replace")
        for p in result.stdout.split(b"\0")
        if p
    ]


def main():
    issues = []

    files = tracked_files()

    for path in files:
        relative = path.relative_to(ROOT)

        if any(part in SKIP for part in relative.parts):
            issues.append(
                f"Tracked excluded directory: {relative}"
            )
            continue

        if not path.is_file():
            continue

        if path.stat().st_size > 2_000_000:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue

        for label, pattern in PATTERNS.items():
            if re.search(pattern, text):
                issues.append(
                    f"{label}: {relative}"
                )

    if issues:
        print("Review required:")
        for issue in issues:
            print(" -", issue)
        return 1

    print("Basic repository checks passed.")
    print("Manual security and licensing review still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
