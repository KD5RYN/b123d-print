"""Reference corpus: a manifest of permissively licensed parts (URL, author, license, sha256,
description and the dimensions an agent is given) and a fetcher that downloads them into a cache
and verifies the hashes. The model files themselves are never committed."""

from __future__ import annotations

import hashlib
import os
import tomllib
import urllib.request
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

MAX_DOWNLOAD = 25_000_000
DEFAULT_CACHE = Path(".b123d-eval") / "cache"  # under the cwd; git-ignored in this repo


def default_manifest() -> Path:
    return Path(str(files("b123d_print.evals").joinpath("corpus.toml")))


@dataclass
class Item:
    id: str
    title: str
    description: str
    dimensions: list[str]
    format: str
    sha256: str = ""
    url: str = ""  # https download (pinned), or
    file: str = ""  # a local file, relative to the manifest (tests, private references)
    source: str = ""
    author: str = ""
    license: str = ""
    license_url: str = ""
    category: str = ""
    difficulty: str = ""
    bbox_mm: list[float] = field(default_factory=list)
    volume_mm3: float = 0.0
    notes: str = ""
    bytes: int = 0
    base: Path = Path(".")  # folder of the manifest

    def cached(self, cache: Path) -> Path:
        return (self.base / self.file) if self.file else cache / f"{self.id}.{self.format}"


def load_manifest(path: str | Path | None = None) -> list[Item]:
    path = Path(path) if path else default_manifest()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    known = set(Item.__dataclass_fields__) - {"base"}
    items = []
    for d in data.get("part", []):
        extra = set(d) - known
        if extra:
            raise ValueError(f"{path}: part {d.get('id')!r} has unknown keys {sorted(extra)}")
        if not (d.get("url") or d.get("file")):
            raise ValueError(f"{path}: part {d.get('id')!r} needs url or file")
        items.append(Item(**d, base=path.parent))
    ids = [i.id for i in items]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate ids")
    return items


def select(items: list[Item], only: str | None) -> list[Item]:
    if not only:
        return items
    want = [s.strip() for s in only.split(",") if s.strip()]
    missing = set(want) - {i.id for i in items}
    if missing:
        raise ValueError(f"not in the corpus: {sorted(missing)}")
    return [i for i in items if i.id in want]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(item: Item, cache: Path = DEFAULT_CACHE, timeout: float = 60.0) -> Path:
    """The verified local file for an item, downloading it if needed. Raises on a hash mismatch."""
    dest = item.cached(cache)
    if dest.is_file() and (not item.sha256 or sha256(dest) == item.sha256):
        return dest
    if item.file:
        raise ValueError(f"{item.id}: {dest} {'missing' if not dest.is_file() else 'does not match its sha256'}")
    if not item.url.startswith("https://"):
        raise ValueError(f"{item.id}: only https URLs are fetched ({item.url!r})")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(item.url, headers={"User-Agent": "b123d-print-eval (+https://github.com/KD5RYN/b123d-print)"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
        n = 0
        while chunk := r.read(1 << 20):
            n += len(chunk)
            if n > MAX_DOWNLOAD:
                raise ValueError(f"{item.id}: download larger than {MAX_DOWNLOAD // 1_000_000} MB")
            f.write(chunk)
    got = sha256(tmp)
    if item.sha256 and got != item.sha256:
        tmp.unlink()
        raise ValueError(f"{item.id}: sha256 mismatch (manifest {item.sha256[:12]}..., got {got[:12]}...); the file at {item.url} changed")
    os.replace(tmp, dest)
    return dest


def fetch_all(items: list[Item], cache: Path = DEFAULT_CACHE) -> dict[str, str]:
    """{id: 'ok <path>' | 'FAILED <reason>'}"""
    out = {}
    for it in items:
        try:
            out[it.id] = f"ok {fetch(it, cache)}"
        except Exception as e:  # report every item, then fail
            out[it.id] = f"FAILED {e}"
    return out
