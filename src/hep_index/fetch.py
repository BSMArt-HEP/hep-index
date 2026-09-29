"""Fetch a codebase from git or a tarball and register + index it (CONTRACT §D3).

Transport + registration only: takes primitives (kind/url/version/extract_root),
never imports catalog — callers (server D4, cli D5) resolve catalog entries.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from hep_index import indexer, recipes, registry

# Non-negotiable (CONTRACT): never allow git to prompt for credentials.
GIT_ENV = {
    "GIT_ASKPASS": "/bin/true",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_SSH_COMMAND": "ssh -o BatchMode=yes",
}


def _as_url(url: str) -> str:
    """Plain local paths (tests) -> file:// URLs for urllib.request."""
    return url if "://" in url else Path(url).resolve().as_uri()


def _fail(dest: Path, detail: str) -> RuntimeError:
    """Remove the partial dest and build the fetch-failure error."""
    shutil.rmtree(dest, ignore_errors=True)
    return RuntimeError(f"fetch failed into {dest}: {detail.strip()}")


def fetch_source(*, kind: str, url: str, version: str, dest: Path,
                 extract_root: str | None = None) -> Path:
    """Populate dest from url: kind='git' clone, kind='tarball' download+extract.

    Returns dest. Raises ValueError on unknown kind, RuntimeError on fetch
    failure (partial dest removed, stderr detail included).
    """
    dest = Path(dest)
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ValueError(f"destination not empty: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    if kind == "git":
        r = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", version, url, str(dest)],
            capture_output=True, text=True,
            env={**os.environ, **GIT_ENV})
        if r.returncode != 0:
            raise _fail(dest, r.stderr)
        return dest

    if kind == "tarball":
        try:
            with tempfile.NamedTemporaryFile(suffix=".tar") as tmp:
                with urllib.request.urlopen(_as_url(url), timeout=120) as resp:
                    shutil.copyfileobj(resp, tmp)
                tmp.flush()
                staging = Path(tempfile.mkdtemp(prefix="hep-fetch-"))
                try:
                    with tarfile.open(tmp.name, "r:*") as tar:
                        tar.extractall(staging, filter="data")
                    top = Path(staging) / extract_root if extract_root else None
                    if top is None:
                        entries = sorted(staging.iterdir())
                        if len(entries) != 1 or not entries[0].is_dir():
                            raise _fail(dest, "archive has no single top-level"
                                        " dir; pass extract_root")
                        top = entries[0]
                    if not top.is_dir():
                        raise _fail(dest, f"extract_root missing in archive:"
                                    f" {extract_root}")
                    if dest.exists():
                        dest.rmdir()  # empty dir; move() must create it fresh
                    shutil.move(str(top), str(dest))
                finally:
                    shutil.rmtree(staging, ignore_errors=True)
        except (ValueError, RuntimeError):
            raise
        except Exception as e:  # urllib/tarfile/OS errors -> uniform contract error
            raise _fail(dest, str(e)) from e
        return dest

    raise ValueError(f"unknown fetch kind: {kind!r} (expected 'git' or 'tarball')")


def fetch_and_register(*, name: str, version: str, kind: str, url: str,
                       extract_root: str | None, root: Path,
                       recipe: str | None = None,
                       exclude: list[str] | None = None) -> dict:
    """Fetch (or reuse) root/name-version, register it, build its index.

    Merges recipes.RECIPES[recipe] with `exclude`. Reuses a non-empty dest
    without fetching. Raises ValueError on unknown recipe or duplicate
    name@version; RuntimeError on fetch failure.
    """
    if recipe is not None and recipe not in recipes.RECIPES:
        raise ValueError(f"unknown recipe: {recipe} "
                         f"(available: {', '.join(sorted(recipes.RECIPES))})")

    dest = Path(root) / f"{name}-{version}"
    already = any(e.id == f"{name}@{version}"
                  for e in registry.load_registry())
    if not already:
        if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
            pass  # reuse existing tree, skip fetch
        else:
            fetch_source(kind=kind, url=url, version=version, dest=dest,
                         extract_root=extract_root)

    entry = registry.CodebaseEntry(
        name=name, version=version, path=str(dest),
        exclude=(recipes.RECIPES[recipe] if recipe else []) + (exclude or []))
    registry.add_entry(entry)  # ValueError on duplicate (authoritative guard)
    stats = indexer.build_index(entry)
    return {"codebase": entry.id, "path": str(dest),
            "n_files": stats.n_files, "n_symbols": stats.n_symbols,
            "ctags_used": stats.ctags_used, "git_head": stats.git_head}
