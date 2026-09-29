"""MCP server exposing the hep-index tools (see CONTRACT.md §server).

Plain *_impl functions hold the logic; create_mcp_server() wraps them as
MCP tools. The registry is re-read on every call — no startup caching.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path

from . import catalog, fetch, indexer, recipes, registry

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


def index_codebase_impl(path: str, name: str, version: str,
                        recipe: str | None = None,
                        exclude: list[str] | None = None) -> dict:
    """Register a local directory and build its index (CONTRACT.md §D4).

    Local paths only, no network. Refuses a duplicate name@version (rebuild
    via CLI `hep-index reindex`); unknown recipe -> ValueError. Returns the
    fetch_and_register stats shape.
    """
    abs_path = os.path.abspath(path)
    if not os.path.isdir(abs_path):
        raise FileNotFoundError(f"not a directory: {abs_path}")
    if recipe is not None and recipe not in recipes.RECIPES:
        raise ValueError(f"unknown recipe: {recipe} "
                         f"(available: {', '.join(sorted(recipes.RECIPES))})")
    entry_id = f"{name}@{version}"
    if any(e.id == entry_id for e in registry.load_registry()):
        raise ValueError(
            f"already registered: {entry_id} — use 'hep-index reindex"
            f" {entry_id}' to rebuild its index")
    entry = registry.CodebaseEntry(
        name=name, version=version, path=abs_path,
        exclude=(recipes.RECIPES[recipe] if recipe else []) + (exclude or []))
    registry.add_entry(entry)
    stats = indexer.build_index(entry)
    return {"codebase": entry.id, "path": abs_path,
            "n_files": stats.n_files, "n_symbols": stats.n_symbols,
            "ctags_used": stats.ctags_used, "git_head": stats.git_head}


def fetch_codebase_impl(name: str, version: str | None = None,
                        root: str | None = None) -> dict:
    """Fetch a catalog entry via fetch.fetch_and_register (CONTRACT.md §D4).

    Catalog-gated only: unknown name -> ValueError pointing at
    `hep-index catalog` / CLI add; version defaults to the catalog latest and
    must be listed in entry.versions (render_url enforces this).
    """
    cat = catalog.load_catalog()
    if name not in cat:
        raise ValueError(f"not in catalog: {name} — run hep-index catalog; "
                         f"use CLI add for local paths")
    entry = cat[name]
    version = version or catalog.latest(entry)
    dest_root = (Path(root).expanduser() if root else
                 Path(os.environ.get("HEP_INDEX_ROOT",
                                     "~/hep-codebases")).expanduser())
    return fetch.fetch_and_register(
        name=name, version=version, kind=entry.type,
        url=catalog.render_url(entry, version),
        extract_root=catalog.render_extract_root(entry, version),
        root=dest_root, recipe=entry.recipe)


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

        If unsure which codebases are indexed, call list_codebases first; selectors are 'name' (latest) or 'name@version'.
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

        If unsure which codebases are indexed, call list_codebases first; selectors are 'name' (latest) or 'name@version'.
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

        If unsure which codebases are indexed, call list_codebases first; selectors are 'name' (latest) or 'name@version'.
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

        If unsure which codebases are indexed, call list_codebases first; selectors are 'name' (latest) or 'name@version'.
        """
        return read_file_impl(path, offset, limit, center, before, after)

    @mcp.tool()
    def index_codebase(path: str, name: str, version: str,
                       recipe: str | None = None,
                       exclude: list[str] | None = None) -> dict:
        """Index a directory tree already on this machine. No network. For known
        HEP packages prefer fetch_codebase.

        `path` must be an existing local directory (absolute, or relative to
        the server's working directory). `name` + `version` form the id
        "name@version"; a duplicate id is refused — rebuild it with the CLI
        command `hep-index reindex <name>@<version>` instead. `recipe`
        applies a preset exclude list (madgraph, madanalysis, delphes);
        `exclude` adds extra glob patterns on top. Returns
        {codebase, path, n_files, n_symbols, ctags_used, git_head}.

        Example: index_codebase("/srv/mycode", "mycode", "1.0",
                                recipe="delphes") ->
            {"codebase": "mycode@1.0", "n_files": 123,
             "n_symbols": 456, "ctags_used": true, ...}
        """
        return index_codebase_impl(path, name, version, recipe, exclude)

    @mcp.tool()
    def fetch_codebase(name: str, version: str | None = None,
                       root: str | None = None) -> dict:
        """Fetch a catalog package from its pinned upstream source and index it.
        Only curated catalog entries are fetchable — no arbitrary URLs.

        `name` must be a catalog entry (see `hep-index catalog`);
        `version` defaults to the catalog's latest known-good version and
        must be one it lists. `root` overrides the destination root
        (default ~/hep-codebases). Recipe excludes are applied
        automatically from the catalog entry. Returns
        {codebase, path, n_files, n_symbols, ctags_used, git_head}.

        Example: fetch_codebase("pythia8") ->
            {"codebase": "pythia8@8.3.17",
             "path": "/home/me/hep-codebases/pythia8-8317", ...}
        """
        return fetch_codebase_impl(name, version, root)

    return mcp
