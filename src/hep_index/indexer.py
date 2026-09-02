"""Codebase indexer: ctags symbol extraction + file manifest into sqlite.

Contract (CONTRACT.md §indexer):
  build_index(entry, cache_root=None, ctags_bin="ctags") -> IndexStats
Wipes and recreates index_dir(entry, cache_root) holding index.db + meta.json.
Degraded mode: missing ctags binary -> empty symbols, ctags_used=False, no raise.
"""
from __future__ import annotations

import fnmatch
import json
import os
import shutil
import sqlite3
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from hep_index.registry import CodebaseEntry, index_dir

DEFAULT_EXCLUDES = [".git", "__pycache__", "*.pyc", "node_modules",
                    "*.o", "*.so", "*.a", "build", "dist"]

_SUFFIX_LANG = {".py": "Python", ".cpp": "C++", ".h": "C++", ".cc": "C++",
                ".hpp": "C++", ".f90": "Fortran", ".f": "Fortran",
                ".m": "Mathematica"}


@dataclass
class IndexStats:
    n_files: int
    n_symbols: int
    ctags_used: bool        # False when ctags binary is missing (degraded mode)
    git_head: str | None    # `git -C path rev-parse HEAD`, None if not a repo
    git_dirty: bool         # `git status --porcelain` non-empty; False if not a repo
    indexed_at: str         # ISO-8601 UTC


def _is_excluded(rel: str, name: str, patterns: list[str]) -> bool:
    """fnmatch globs against the posix-relative path AND the bare name."""
    return any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(name, pat)
               for pat in patterns)


def _walk_files(root: Path, patterns: list[str]):
    """os.walk with excluded dirs pruned; yields (rel_posix, abs_path) sorted later."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        dirnames[:] = sorted(d for d in dirnames
                             if not _is_excluded(os.path.join(rel_dir, d)
                                                 if rel_dir != "." else d, d,
                                                 patterns))
        for fname in sorted(filenames):
            rel = os.path.normpath(os.path.join(rel_dir, fname))
            if _is_excluded(rel, fname, patterns):
                continue
            found.append((PurePosixPath(Path(rel).as_posix()).as_posix(),
                          Path(dirpath) / fname))
    return found


def _git(args: list[str], root: Path, timeout: int = 30) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(root), *args],
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _git_head(root: Path) -> str | None:
    return _git(["rev-parse", "HEAD"], root)


def _git_dirty(root: Path) -> bool:
    out = _git(["status", "--porcelain"], root)
    return bool(out) if out is not None else False


def _run_ctags(root: Path, ctags_bin: str, patterns: list[str]):
    """Yield parsed ctags JSON tag records; [] if the binary is missing."""
    if shutil.which(ctags_bin) is None:
        return []
    cmd = [ctags_bin, "-R", "--output-format=json", "--fields=+n+k+s+l",
           "--extras=-F", *(f"--exclude={p}" for p in patterns), "."]
    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                           timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return []
    tags = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue  # skip any non-JSON warning lines
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("_type") == "tag":
            tags.append(rec)
    return tags


def build_index(entry: CodebaseEntry, cache_root=None,
                ctags_bin: str = "ctags") -> IndexStats:
    """(Re)index entry.path into index_dir(entry, cache_root)."""
    root = Path(entry.path)
    out_dir = index_dir(entry, cache_root)
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)

    patterns = DEFAULT_EXCLUDES + list(entry.exclude)

    # file manifest
    file_rows = []  # (rel_posix, size, language)
    for rel, abs_path in _walk_files(root, patterns):
        try:
            size = abs_path.stat().st_size
        except OSError:
            size = 0
        file_rows.append((rel, size, _SUFFIX_LANG.get(abs_path.suffix, "")))

    # symbols (degraded to [] when ctags is unavailable)
    ctags_used = shutil.which(ctags_bin) is not None
    sym_rows = []  # (name, kind, rel_posix, line, language, signature)
    for rec in _run_ctags(root, ctags_bin, patterns):
        rel = PurePosixPath(str(rec.get("path", "")).removeprefix("./")).as_posix()
        sym_rows.append((str(rec.get("name", "")), str(rec.get("kind", "")),
                         rel, int(rec.get("line") or 0),
                         str(rec.get("language", "")),
                         str(rec.get("signature") or "")))

    # deterministic sorted inserts
    file_rows.sort()
    sym_rows.sort()

    db_path = out_dir / "index.db"
    con = sqlite3.connect(db_path)
    try:
        with con:
            con.execute("CREATE TABLE symbols(name TEXT, kind TEXT, path TEXT,"
                        " line INTEGER, language TEXT, signature TEXT)")
            con.execute("CREATE INDEX idx_symbols_name ON symbols(name)")
            con.execute("CREATE INDEX idx_symbols_path ON symbols(path)")
            con.execute("CREATE TABLE files(path TEXT, size INTEGER,"
                        " language TEXT)")
            con.executemany("INSERT INTO files VALUES (?,?,?)", file_rows)
            con.executemany("INSERT INTO symbols VALUES (?,?,?,?,?,?)", sym_rows)
    finally:
        con.close()

    stats = IndexStats(
        n_files=len(file_rows),
        n_symbols=len(sym_rows),
        ctags_used=ctags_used,
        git_head=_git_head(root),
        git_dirty=_git_dirty(root),
        indexed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    meta = asdict(stats) | {"entry_id": entry.id}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return stats
