"""Registry of indexed codebases: name@version -> local checkout path.

Registry is a TOML file (hand-editable). Env overrides for tests:
  HEP_INDEX_CONFIG  path to registry TOML   (default ~/.config/hep-index/codebases.toml)
  HEP_INDEX_CACHE   index store root        (default ~/.cache/hep-index)
"""
from __future__ import annotations

import os
import tomllib
import tomli_w
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class CodebaseEntry:
    name: str                      # e.g. "madanalysis"
    version: str                   # e.g. "1.11.1"
    path: str                      # absolute path to checkout
    exclude: list[str] = field(default_factory=list)  # glob patterns, relative to root
    added_at: str = ""             # ISO-8601 UTC

    @property
    def id(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def index_dirname(self) -> str:
        return f"{self.name}-{self.version}"


def default_registry_path() -> Path:
    p = os.environ.get("HEP_INDEX_CONFIG")
    if p:
        return Path(p).expanduser()
    return Path.home() / ".config" / "hep-index" / "codebases.toml"


def default_cache_root() -> Path:
    p = os.environ.get("HEP_INDEX_CACHE")
    if p:
        return Path(p).expanduser()
    return Path.home() / ".cache" / "hep-index"


def load_registry(path: Path | None = None) -> list[CodebaseEntry]:
    path = path or default_registry_path()
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text())
    return [CodebaseEntry(**cb) for cb in data.get("codebase", [])]


def save_registry(entries: list[CodebaseEntry], path: Path | None = None) -> None:
    path = path or default_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"codebase": [asdict(e) for e in entries]}
    path.write_bytes(tomli_w.dumps(doc).encode())


def add_entry(entry: CodebaseEntry, path: Path | None = None) -> None:
    """Register a codebase. ValueError on duplicate id, FileNotFoundError on bad path."""
    entries = load_registry(path)
    if any(e.id == entry.id for e in entries):
        raise ValueError(f"already registered: {entry.id}")
    p = Path(entry.path).expanduser()
    if not p.is_dir():
        raise FileNotFoundError(f"not a directory: {p}")
    if not entry.added_at:
        entry.added_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entries.append(entry)
    entries.sort(key=lambda e: (e.name, e.version))
    save_registry(entries, path)


def remove_entry(name: str, version: str | None = None,
                 path: Path | None = None) -> list[CodebaseEntry]:
    """Unregister name@version (or all versions of name if version is None).

    Returns the removed entries; KeyError if nothing matched."""
    entries = load_registry(path)
    kept, removed = [], []
    for e in entries:
        if e.name == name and (version is None or e.version == version):
            removed.append(e)
        else:
            kept.append(e)
    if not removed:
        raise KeyError(f"not registered: {name}@{version or '*'}")
    save_registry(kept, path)
    return removed


def _version_key(v: str) -> list[tuple[int, object]]:
    # numeric-aware: "1.10" sorts after "1.9"; mixed tokens compare as strings
    return [(0, int(tok)) if tok.isdigit() else (1, tok)
            for tok in v.replace("-", ".").split(".")]


def resolve(selector: str | None, path: Path | None = None) -> list[CodebaseEntry]:
    """selector None -> all entries; 'name@version' -> that entry;
    'name' -> latest registered version of name. KeyError if unknown."""
    entries = load_registry(path)
    if selector is None:
        return entries
    if "@" in selector:
        name, _, ver = selector.partition("@")
        for e in entries:
            if e.name == name and e.version == ver:
                return [e]
        raise KeyError(f"not registered: {selector}")
    same_name = [e for e in entries if e.name == selector]
    if not same_name:
        raise KeyError(f"not registered: {selector}")
    return [sorted(same_name, key=lambda e: _version_key(e.version))[-1]]


def index_dir(entry: CodebaseEntry, cache_root: Path | None = None) -> Path:
    """Directory holding this entry's index.db + meta.json."""
    return (cache_root or default_cache_root()) / entry.index_dirname
