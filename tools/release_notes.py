"""Print the CHANGELOG.md section for one version (the GitHub release text).

    python tools/release_notes.py 0.2.1          # or v0.2.1
    python tools/release_notes.py --backfill     # create missing GitHub Releases for past tags (gh CLI)

Exits non-zero when the version has no section, or when the section is still "unreleased", so a
release cannot go out with an empty or undated changelog.
"""

import re
import subprocess
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
HEAD = re.compile(r"^## (\d+\.\d+\.\d+)\s+[—-]\s+(.+?)\s*$", re.M)


def sections(text: str) -> dict[str, tuple[str, str]]:
    """version -> (date or 'unreleased', body)."""
    found = list(HEAD.finditer(text))
    out = {}
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        out[m.group(1)] = (m.group(2), text[m.end():end].strip())
    return out


def notes(version: str, text: str | None = None) -> str:
    v = version.lstrip("v")
    secs = sections(text if text is not None else CHANGELOG.read_text(encoding="utf-8"))
    if v not in secs:
        raise SystemExit(f"CHANGELOG.md has no section for {v}")
    date, body = secs[v]
    if "unreleased" in date.lower():
        raise SystemExit(f"CHANGELOG.md section {v} is still marked {date!r}: date it before releasing")
    if not body:
        raise SystemExit(f"CHANGELOG.md section {v} is empty")
    link = "https://pypi.org/project/b123d-print/" + v + "/"
    return f"{body}\n\n---\nPyPI: {link} · Docker: `ghcr.io/kd5ryn/b123d-print-mcp:{v}`\n"


def backfill() -> None:
    tags = subprocess.run(["git", "tag", "--list", "v*"], capture_output=True, text=True, check=True).stdout.split()
    have = set(subprocess.run(["gh", "release", "list", "--json", "tagName", "--jq", ".[].tagName"],
                              capture_output=True, text=True, check=True).stdout.split())
    for tag in sorted(tags, key=lambda t: [int(x) for x in t[1:].split(".")]):
        if tag in have:
            continue
        body = notes(tag)
        subprocess.run(["gh", "release", "create", tag, "--title", f"b123d-print {tag[1:]}", "--notes", body,
                        "--verify-tag"], check=True)
        print(f"created release {tag}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--backfill"]:
        backfill()
    elif len(sys.argv) == 2:
        sys.stdout.write(notes(sys.argv[1]))
    else:
        raise SystemExit(__doc__)
