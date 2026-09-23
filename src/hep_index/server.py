"""MCP server exposing the hep-index tools (see CONTRACT.md §server).

Plain *_impl functions hold the logic; create_mcp_server() wraps them as
MCP tools. The registry is re-read on every call — no startup caching.
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from pathlib import Path

from . import registry

try:  # mcp 1.x (CONTRACT.md spelling)
    from mcp.server.fastmcp import FastMCP
except ImportError:  # mcp >= 2 renamed FastMCP -> MCPServer, same API
    from mcp.server.mcpserver import MCPServer as FastMCP

_MAX_READ_LINES = 1000


def _git_head(path: Path) -> str | None:
    """Live `git rev-parse HEAD`, None if not a repo / git unavailable."""
    try:
        proc = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _read_meta(entry: registry.CodebaseEntry) -> dict:
    meta_path = registry.index_dir(entry) / "meta.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text())
    except (OSError, ValueError):
        return {}


def list_codebases_impl() -> list[dict]:
    entries = []
    for e in registry.load_registry():
        root = Path(e.path)
        idx_dir = registry.index_dir(e)
        meta = _read_meta(e)
        ok = root.is_dir() and (idx_dir / "index.db").exists()
        indexed_head = meta.get("git_head")
        live_head = _git_head(root)
        # stale only when both sides are available and disagree
        stale = bool(indexed_head and live_head and indexed_head != live_head)
        entries.append({
            "name": e.name,
            "version": e.version,
            "id": e.id,
            "path": e.path,
            "ok": ok,
            "n_files": meta.get("n_files", 0),
            "n_symbols": meta.get("n_symbols", 0),
            "git_head": indexed_head,
            "stale": stale,
        })
    return entries


def search_code_impl(query: str, codebase: str | None = None,
                     glob: str | None = None, max_results: int = 50) -> list[dict]:
    hits: list[dict] = []
    for e in registry.resolve(codebase):
        root = Path(e.path)
        if not root.is_dir():
            continue  # missing checkout: skip, don't fail the whole call
        cmd = ["rg", "--no-heading", "-n", "--max-count", "5", query, str(root)]
        if glob:
            cmd += ["-g", glob]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode not in (0, 1):  # 1 = no hits, 2 = bad regex/usage
            raise ValueError(f"rg failed on {e.id}: {proc.stderr.strip()}")
        for line in proc.stdout.splitlines():
            rel, line_no, text = line.split(":", 2)
            hits.append({
                "codebase": e.id,
                "path": str(Path(rel)),
                "line_no": int(line_no),
                "text": text,
            })
            if len(hits) >= max_results:
                return hits
    return hits


_SYMBOL_COLS = "name, kind, path, line, language, signature"


def _db_symbols(root: Path, entry: registry.CodebaseEntry, name: str,
                kind: str | None, limit: int) -> list[tuple] | None:
    """Exact-then-substring lookup; None when no usable index (-> rg fallback)."""
    db_path = registry.index_dir(entry) / "index.db"
    if not db_path.exists():
        return None
    con = sqlite3.connect(db_path)
    try:
        n_symbols = con.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        if n_symbols == 0:
            return None
        kfilter = " AND kind = ?" if kind else ""
        args: list = [name] + ([kind] if kind else [])
        rows = con.execute(
            f"SELECT {_SYMBOL_COLS} FROM symbols WHERE name = ?{kfilter} "
            f"ORDER BY path, line LIMIT ?", args + [limit]).fetchall()
        if not rows:
            rows = con.execute(
                f"SELECT {_SYMBOL_COLS} FROM symbols WHERE name LIKE ?{kfilter} "
                f"ORDER BY path, line LIMIT ?", ["%" + name + "%"] + args[1:] + [limit]
            ).fetchall()
        return rows
    finally:
        con.close()


def _rg_word_search(root: Path, name: str, limit: int) -> list[tuple[str, int, str]]:
    pattern = rf"\b{re.escape(name)}\b"
    proc = subprocess.run(
        ["rg", "--no-heading", "-n", "--max-count", "5", pattern, str(root)],
        capture_output=True, text=True, timeout=60)
    if proc.returncode not in (0, 1):
        raise ValueError(f"rg failed: {proc.stderr.strip()}")
    hits = []
    for line in proc.stdout.splitlines():
        rel, line_no, text = line.split(":", 2)
        hits.append((str(Path(rel)), int(line_no), text))
        if len(hits) >= limit:
            break
    return hits


def find_symbol_impl(name: str, codebase: str | None = None,
                     kind: str | None = None, max_results: int = 50) -> list[dict]:
    results: list[dict] = []
    for e in registry.resolve(codebase):
        if len(results) >= max_results:
            break
        root = Path(e.path)
        if not root.is_dir():
            continue
        rows = _db_symbols(root, e, name, kind, max_results - len(results))
        if rows is not None:
            for sym_name, sym_kind, rel, line, language, signature in rows:
                results.append({
                    "codebase": e.id,
                    "name": sym_name,
                    "kind": sym_kind,
                    "path": str(root / rel),
                    "line": line,
                    "language": language,
                    "signature": signature,
                })
        else:
            # no index.db or empty symbols table: rg word-search fallback
            for path, line_no, text in _rg_word_search(
                    root, name, max_results - len(results)):
                results.append({
                    "codebase": e.id, "path": path, "line_no": line_no, "text": text,
                })
    return results


def _registered_roots() -> list[tuple[registry.CodebaseEntry, Path]]:
    return [(e, Path(e.path)) for e in registry.load_registry() if Path(e.path).is_dir()]


def read_file_impl(path: str, offset: int = 1, limit: int = 200,
                   center: int | None = None, before: int = 10,
                   after: int = 10) -> dict:
    """Read numbered lines from a registered file.

    Two modes:
      * slice: offset (1-based start line) + limit (capped at 1000)
      * context window: center=<line> reads [center-before, center+after]
        (offset/limit are ignored when center is given; clamped to file bounds)
    """
    if center is not None:
        center = max(1, int(center))
        offset = max(1, center - max(0, int(before)))
        limit = max(0, int(before)) + max(0, int(after)) + 1
    p = Path(path)
    if p.is_absolute():
        target = p
    else:
        target = None
        for _, root in _registered_roots():
            candidate = root / p
            if candidate.exists():
                target = candidate
                break
        if target is None:  # nothing matched: judge against the first root
            roots = _registered_roots()
            if not roots:
                raise FileNotFoundError(f"no registered codebases; cannot resolve {path!r}")
            target = roots[0][1] / p
    resolved = target.resolve()
    for e, root in _registered_roots():
        root = root.resolve()
        if resolved.is_relative_to(root):
            if not resolved.is_file():
                raise FileNotFoundError(f"not a file: {resolved}")
            offset = max(1, offset)
            limit = min(max(limit, 0), _MAX_READ_LINES)
            lines = resolved.read_text(errors="replace").splitlines()
            selected = [
                f"{n}: {lines[n - 1]}"
                for n in range(offset, min(offset + limit, len(lines) + 1))
            ]
            return {
                "codebase": e.id,
                "rel_path": resolved.relative_to(root).as_posix(),
                "offset": offset,
                "total_lines": len(lines),
                "content": selected,
            }
    raise ValueError(
        f"path {path!r} is outside every registered codebase root")


def create_mcp_server() -> FastMCP:
    mcp = FastMCP("hep-index")

    @mcp.tool()
    def list_codebases() -> list[dict]:
        """List every registered codebase with its health status.

        Returns one dict per codebase: name, version, id ("name@version"),
        path, ok (checkout + index present), n_files, n_symbols, git_head,
        and stale (True when the checkout's git HEAD moved after indexing).
        Takes no arguments. Call this first to discover what is searchable.

        Example: list_codebases() ->
            [{"name": "madanalysis", "version": "1.11.1", "id":
              "madanalysis@1.11.1", "path": "/srv/MA5", "ok": true, ...}]
        """
        return list_codebases_impl()

    @mcp.tool()
    def search_code(query: str, codebase: str | None = None,
                    glob: str | None = None, max_results: int = 50) -> list[dict]:
        """Regex search over one or all registered codebases (ripgrep).

        `query` is a regular expression (Rust regex syntax), e.g.
        "TLorentzVector|FourVector" or "def\\s+\\w+_cut". `codebase` is an
        optional id ("madanalysis@1.11.1") or bare name (latest version);
        omit it to search ALL codebases. `glob` filters files, e.g. "*.py"
        or "*.h". At most 5 matches per file; returns up to `max_results`
        (default 50) hits: {codebase, path, line_no, text}.

        Example: search_code("class\\s+Analysis", glob="*.h") ->
            [{"codebase": "ma5@1.1", "path": "/srv/ma5/Analysis.h",
              "line_no": 12, "text": "class Analysis { ..."}]
        """
        return search_code_impl(query, codebase, glob, max_results)

    @mcp.tool()
    def find_symbol(name: str, codebase: str | None = None,
                    kind: str | None = None, max_results: int = 50) -> list[dict]:
        """Look up a class/function/variable symbol via the ctags index.

        `name` is matched exactly first, then as a substring if nothing
        matched exactly. `codebase` is an optional id or bare name (omit to
        search all); `kind` filters by ctags kind, e.g. "class", "function",
        "member". Returns {codebase, name, kind, path, line, language,
        signature}. If a codebase has no index yet, falls back to a whole-
        word ripgrep and returns grep-shaped hits
        {codebase, path, line_no, text} instead.

        Example: find_symbol("Kinematics", codebase="atlas", kind="class") ->
            [{"codebase": "atlas@1.0", "name": "Kinematics",
              "kind": "class", "path": "/srv/atlas/kine.py", "line": 3, ...}]
        """
        return find_symbol_impl(name, codebase, kind, max_results)

    @mcp.tool()
    def read_file(path: str, offset: int = 1, limit: int = 200) -> dict:
        """Read a numbered slice of a file inside any registered codebase.

        `path` may be absolute or relative to a codebase root (first
        matching root wins). Paths outside every registered root are
        rejected. `offset` is the 1-based start line (default 1); `limit`
        is the number of lines (default 200, capped at 1000). Alternatively,
        pass center=<line> (e.g. a line returned by find_symbol or search_code)
        with before/after (default 10/10) to read a context window around a
        known line. Returns
        {codebase, rel_path, offset, total_lines, content} where each
        content line is "N: text" with N the absolute line number.

        Example: read_file("src/cuts.cxx", offset=40, limit=20) ->
            {"codebase": "ma5@1.1", "rel_path": "src/cuts.cxx", ...,
             "content": ["40: void Cuts::apply() {", "41:   ..."]}
        Context window: read_file("src/cuts.cxx", center=152, before=5,
            after=20) -> lines 147-172 (useful for macro expansions).
        """
        return read_file_impl(path, offset, limit, center, before, after)

    return mcp
