"""Structured data files (JSON / YAML / TOML) (CONTRACT.md §datafiles).

  extract_data_file(root, rel) -> DataFileInfo | None   (None = not data / unparseable)

For config-driven codes, example input files and templates are the usage
documentation. Each file is flattened to its nested key paths (list elements
-> "*") with value types and sample values, and small files are kept whole so
they can be read from the index without the checkout.
"""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional at runtime; declared as a dependency
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

DATA_SUFFIXES = {".json": "json", ".yaml": "yaml", ".yml": "yaml",
                 ".toml": "toml"}
MAX_PARSE_BYTES = 2_000_000   # don't flatten bigger files (databases, dumps)
MAX_STORE_BYTES = 64_000      # keep content of files up to this size
MAX_PATHS = 5000              # per file
_MAX_SAMPLE = 80
_MAX_SAMPLES = 3


@dataclass
class DataKey:
    keys: list[str]
    types: list[str] = field(default_factory=list)    # object|array|str|int|...
    samples: list[str] = field(default_factory=list)  # JSON-encoded leaf values

    def as_tuple(self, rel: str) -> tuple:
        return (rel, json.dumps(self.keys), json.dumps(self.types),
                json.dumps(self.samples))


@dataclass
class DataFileInfo:
    path: str
    format: str
    size: int
    content: str | None        # whole file when size <= MAX_STORE_BYTES
    top_keys: list[str]
    keys: list[DataKey]
    truncated: bool = False    # hit MAX_PATHS


def _type(v) -> str:
    if isinstance(v, dict):
        return "object"
    if isinstance(v, list):
        return "array"
    if isinstance(v, bool):
        return "bool"
    if v is None:
        return "null"
    if isinstance(v, (int, float, str)):
        return type(v).__name__
    return "str"  # yaml/toml dates etc.


def _sample(v) -> str:
    if isinstance(v, dict):
        s = f"{{{len(v)} keys}}"
    elif isinstance(v, list):
        s = f"[{len(v)} items]"
    else:
        try:
            s = json.dumps(v, ensure_ascii=False)
        except (TypeError, ValueError):
            s = json.dumps(str(v), ensure_ascii=False)
    return s if len(s) <= _MAX_SAMPLE else s[:_MAX_SAMPLE - 3] + "..."


def flatten(data) -> tuple[list[DataKey], bool]:
    """Every nested key path (containers included), merged per path."""
    out: dict[tuple, DataKey] = {}
    truncated = False

    def add(path: tuple, v):
        nonlocal truncated
        if path:
            dk = out.get(path)
            if dk is None:
                if len(out) >= MAX_PATHS:
                    truncated = True
                    return
                dk = out[path] = DataKey(list(path))
            t = _type(v)
            if t not in dk.types:
                dk.types.append(t)
            s = _sample(v)
            if len(dk.samples) < _MAX_SAMPLES and s not in dk.samples:
                dk.samples.append(s)
        if isinstance(v, dict):
            for k, sub in v.items():
                add(path + (str(k),), sub)
        elif isinstance(v, list):
            for sub in v:
                add(path + ("*",), sub)

    add((), data)
    return list(out.values()), truncated


def _load(fmt: str, text: str):
    if fmt == "json":
        return json.loads(text)
    if fmt == "toml":
        return tomllib.loads(text)
    if yaml is None:
        raise ValueError("PyYAML not installed")
    docs = [d for d in yaml.safe_load_all(text) if d is not None]
    return docs[0] if len(docs) == 1 else docs


def extract_data_file(root: Path, rel: str, size: int) -> DataFileInfo | None:
    fmt = DATA_SUFFIXES.get(Path(rel).suffix.lower())
    if fmt is None or size > MAX_PARSE_BYTES:
        return None
    try:
        text = (root / rel).read_text(encoding="utf-8")
        data = _load(fmt, text)
        keys, truncated = flatten(data)  # recursive yaml anchors can recurse
    except Exception:  # unparseable / not utf-8 / yaml tags etc.
        return None
    return DataFileInfo(
        path=rel, format=fmt, size=size,
        content=text if size <= MAX_STORE_BYTES else None,
        top_keys=[str(k) for k in data] if isinstance(data, dict) else [],
        keys=keys, truncated=truncated)
