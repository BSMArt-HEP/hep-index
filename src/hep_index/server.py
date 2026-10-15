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
        cmd = (["rg", "--no-heading", "-n", "--max-count", "5", "-e", query]
               + (["-g", glob] if glob else []) + ["--", str(root)])
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


# ------------------------------------------------------------- python ast layer

_API_COLS = ("qualname, name, kind, path, line, end_line, parent, signature,"
             " doc, bases, decorators, value")


def _py_con(entry: registry.CodebaseEntry) -> sqlite3.Connection | None:
    """Open index.db if it carries the py_api tables (older indexes don't)."""
    db_path = registry.index_dir(entry) / "index.db"
    if not db_path.exists():
        return None
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table'"
                   " AND name='py_api'").fetchone() is None:
        con.close()
        return None
    return con


def _summary(doc: str) -> str:
    """First paragraph of a docstring, joined onto one line."""
    lines = [ln for ln in doc.strip().splitlines()
             if ln.strip(" -=*#~_") or not ln.strip()]  # drop banner rules
    para = "\n".join(lines).strip().split("\n\n", 1)[0]
    return " ".join(para.split())


def _is_private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__")
                                         and name.endswith("__"))


def _api_by_qualname(con, qualname: str, kind: str | None = None) -> list:
    kfilter = " AND kind = ?" if kind else ""
    return con.execute(f"SELECT {_API_COLS} FROM py_api WHERE qualname = ?"
                       f"{kfilter} ORDER BY path, line",
                       [qualname] + ([kind] if kind else [])).fetchall()


def _resolve_dotted(con, dotted: str, kind: str | None = None,
                    depth: int = 0, seen: set[str] | None = None) -> list:
    """Exact qualname, else follow imports/re-exports (pkg.Name -> pkg.core.Name)."""
    if seen is None:
        seen = set()
    if dotted in seen or depth > 6:  # seen breaks re-export cycles
        return []
    seen = seen | {dotted}
    rows = _api_by_qualname(con, dotted, kind)
    if rows:
        return rows
    parts = dotted.split(".")
    for i in range(len(parts) - 1, 0, -1):
        mod, local, rest = ".".join(parts[:i]), parts[i], parts[i + 1:]
        imp = con.execute("SELECT target FROM py_imports WHERE module = ?"
                          " AND name = ?", (mod, local)).fetchone()
        if imp and imp["target"] != dotted:
            return _resolve_dotted(con, ".".join([imp["target"], *rest]),
                                   kind, depth + 1, seen)
        for star in con.execute("SELECT target FROM py_imports WHERE module = ?"
                                " AND name = '*'", (mod,)).fetchall():
            hit = _resolve_dotted(con, ".".join([star["target"], local, *rest]),
                                  kind, depth + 1, seen)
            if hit:
                return hit
    return []


def _api_hit(entry, root: Path, r) -> dict:
    out = {"codebase": entry.id, "name": r["name"], "kind": r["kind"],
           "path": str(root / r["path"]), "line": r["line"],
           "language": "Python", "signature": r["signature"],
           "qualname": r["qualname"], "summary": _summary(r["doc"])}
    bases = json.loads(r["bases"] or "[]")
    if bases:
        out["bases"] = bases
    decos = json.loads(r["decorators"] or "[]")
    if decos:
        out["decorators"] = decos
    if r["value"]:
        out["value"] = r["value"]
    return out


def _dotted_symbols(entry, root: Path, name: str, kind: str | None,
                    limit: int) -> list[dict] | None:
    """Dotted lookup (`pkg.mod.Class.meth`, `Class.meth`); None if no py index."""
    con = _py_con(entry)
    if con is None:
        return None
    try:
        rows = _resolve_dotted(con, name, kind)
        if not rows:  # suffix match: "MCMC.NewScan" -> bsmart.scans.MCMC.NewScan
            kfilter = " AND kind = ?" if kind else ""
            rows = con.execute(
                f"SELECT {_API_COLS} FROM py_api WHERE qualname LIKE ?{kfilter}"
                f" ORDER BY path, line LIMIT ?",
                ["%." + name] + ([kind] if kind else []) + [limit]).fetchall()
        return [_api_hit(entry, root, r) for r in rows[:limit]]
    finally:
        con.close()


def find_symbol_impl(name: str, codebase: str | None = None,
                     kind: str | None = None, max_results: int = 50) -> list[dict]:
    results: list[dict] = []
    for e in registry.resolve(codebase):
        if len(results) >= max_results:
            break
        root = Path(e.path)
        if not root.is_dir():
            continue
        if "." in name:
            hits = _dotted_symbols(e, root, name, kind, max_results - len(results))
            if hits:
                results.extend(hits)
                continue
        rows = _db_symbols(root, e, name, kind, max_results - len(results))
        if rows is not None:
            con = _py_con(e)
            try:
                for sym_name, sym_kind, rel, line, language, signature in rows:
                    api = None
                    if con is not None and language == "Python":
                        api = con.execute(
                            f"SELECT {_API_COLS} FROM py_api WHERE path = ? AND"
                            " line = ? AND name = ? AND kind != 'module'",
                            (rel, line, sym_name)).fetchone()
                    if api is not None:
                        results.append(_api_hit(e, root, api))
                        continue
                    results.append({
                        "codebase": e.id,
                        "name": sym_name,
                        "kind": sym_kind,
                        "path": str(root / rel),
                        "line": line,
                        "language": language,
                        "signature": signature,
                    })
            finally:
                if con is not None:
                    con.close()
        else:
            # no index.db or empty symbols table: rg word-search fallback
            for path, line_no, text in _rg_word_search(
                    root, name, max_results - len(results)):
                results.append({
                    "codebase": e.id, "path": path, "line_no": line_no, "text": text,
                })
    return results


def _member(r) -> dict:
    m = {"name": r["name"], "kind": r["kind"], "line": r["line"],
         "signature": r["signature"], "summary": _summary(r["doc"])}
    bases = json.loads(r["bases"] or "[]")
    if bases:
        m["bases"] = bases
    decos = json.loads(r["decorators"] or "[]")
    if decos:
        m["decorators"] = decos
    if r["value"]:
        m["value"] = r["value"]
    return m


def _subclasses(con, qualname: str, name: str, limit: int = 100) -> list[dict]:
    """Classes whose bases name this class (name-based; may include homonyms)."""
    out = []
    for r in con.execute(f"SELECT {_API_COLS} FROM py_api WHERE kind = 'class'"
                         " AND bases LIKE ? ORDER BY qualname", (f"%{name}%",)):
        bases = json.loads(r["bases"] or "[]")
        if any(b.split("[", 1)[0].rsplit(".", 1)[-1] == name for b in bases):
            out.append({"qualname": r["qualname"], "path": r["path"],
                        "line": r["line"], "summary": _summary(r["doc"])})
            if len(out) >= limit:
                break
    return [s for s in out if s["qualname"] != qualname]


def _outline_one(entry, root: Path, con, target: str, include_private: bool,
                 max_members: int) -> dict | None:
    rows = _resolve_dotted(con, target)
    rows = [r for r in rows if r["kind"] in ("module", "class")] or rows
    if not rows:  # a file path relative to the root
        mod = con.execute("SELECT module FROM py_modules WHERE path = ?",
                          (target.removeprefix("./"),)).fetchone()
        if mod:
            rows = _api_by_qualname(con, mod["module"], "module")
    if not rows:  # unique qualname suffix: "MCMC" -> bsmart.scans.MCMC
        cand = con.execute(f"SELECT {_API_COLS} FROM py_api WHERE qualname LIKE ?"
                           " AND kind IN ('module', 'class') LIMIT 2",
                           ("%." + target,)).fetchall()
        if len(cand) == 1:
            rows = cand
    if not rows:
        return None
    r = rows[0]
    out = {"codebase": entry.id, "qualname": r["qualname"], "kind": r["kind"],
           "path": str(root / r["path"]), "line": r["line"],
           "signature": r["signature"], "doc": r["doc"]}
    if len(rows) > 1:
        out["also_defined_at"] = [f"{x['path']}:{x['line']}" for x in rows[1:]]
    bases = json.loads(r["bases"] or "[]")
    if bases:
        out["bases"] = bases
    if r["kind"] == "class" and r["decorators"] != "[]":
        out["decorators"] = json.loads(r["decorators"])

    all_names = None
    if r["kind"] == "module":
        m = con.execute("SELECT all_names FROM py_modules WHERE module = ?"
                        " AND path = ?", (r["qualname"], r["path"])).fetchone()
        all_names = json.loads(m["all_names"]) if m and m["all_names"] else None
        if all_names is not None:
            out["__all__"] = all_names

    def visible(name: str) -> bool:
        if include_private:
            return True
        if all_names is not None:
            return name in all_names
        return not _is_private(name)

    members: list[dict] = []
    seen: dict[str, dict] = {}  # name defined in several try/if branches
    for m in con.execute(
            f"SELECT {_API_COLS} FROM py_api WHERE parent = ? AND path = ?"
            " AND kind != 'module' ORDER BY line", (r["qualname"], r["path"])):
        if not visible(m["name"]):
            continue
        if m["name"] in seen:
            seen[m["name"]].setdefault("redefined_at", []).append(m["line"])
            continue
        seen[m["name"]] = _member(m)
        members.append(seen[m["name"]])
    out["members"] = members[:max_members]
    if len(members) > max_members:
        out["members_truncated"] = len(members) - max_members

    if r["kind"] == "module":
        if r["path"].endswith("__init__.py"):
            prefix = r["qualname"] + "."
            subs = [x["module"] for x in con.execute(
                "SELECT DISTINCT module FROM py_modules WHERE module LIKE ?"
                " ORDER BY module", (prefix + "%",))
                if "." not in x["module"][len(prefix):]]
            out["submodules"] = [
                {"module": sm, "summary": _summary(
                    (_api_by_qualname(con, sm, "module") or [{"doc": ""}])[0]["doc"])}
                for sm in subs]
        reexports = []
        for imp in con.execute("SELECT name, target FROM py_imports WHERE"
                               " module = ? ORDER BY line", (r["qualname"],)):
            if imp["name"] == "*" or not visible(imp["name"]):
                continue
            if all_names is None and not r["path"].endswith("__init__.py"):
                continue  # plain module imports are dependencies, not API
            tgt = _resolve_dotted(con, imp["target"])
            reexports.append({"name": imp["name"], "target": imp["target"],
                              **({"kind": tgt[0]["kind"],
                                  "signature": tgt[0]["signature"],
                                  "summary": _summary(tgt[0]["doc"])}
                                 if tgt else {})})
        if reexports:
            out["reexports"] = reexports
        out["imports"] = sorted({i["target"] for i in con.execute(
            "SELECT target FROM py_imports WHERE module = ?", (r["qualname"],))})
    else:
        subs = _subclasses(con, r["qualname"], r["name"])
        if subs:
            out["subclasses"] = subs
    return out


def outline_impl(target: str, codebase: str | None = None,
                 include_private: bool = False, max_members: int = 200) -> list[dict]:
    """Structured API outline of a Python module/package/class (no bodies)."""
    results = []
    for e in registry.resolve(codebase):
        root = Path(e.path)
        if not root.is_dir():
            continue
        con = _py_con(e)
        if con is None:
            continue
        try:
            o = _outline_one(e, root, con, target, include_private, max_members)
        finally:
            con.close()
        if o is not None:
            results.append(o)
    if not results:
        raise KeyError(f"no Python module/class {target!r} in "
                       f"{codebase or 'any codebase'} (try find_symbol, or "
                       f"reindex if this index predates the ast layer)")
    return results


def _has_table(con, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table'"
                       " AND name=?", (name,)).fetchone() is not None


def _seg_match(pattern: list[str], keys: list[str]) -> bool:
    """Same length; a "*" in the pattern matches any key."""
    return len(pattern) == len(keys) and all(
        p == "*" or p == k for p, k in zip(pattern, keys))


def _prefix_match(want: list[str], keys: list[str]) -> bool:
    """keys starts with want; "*" on either side matches any key, so a
    concrete prefix (Codes/SPheno) also selects code patterns (Codes/*/Run)."""
    return len(keys) >= len(want) and all(
        w == "*" or k == "*" or w == k for w, k in zip(want, keys))


def _data_key_agg(con, root: Path, entry, want: list[str],
                  roots: set[str] | None) -> dict[str, dict]:
    """Aggregate data_keys rows across files: keystr -> {files, types, values}."""
    agg: dict[str, dict] = {}
    if not _has_table(con, "data_keys"):
        return agg
    for r in con.execute("SELECT * FROM data_keys ORDER BY path"):
        keys = json.loads(r["keys"])
        if roots is not None and keys[0] not in roots:
            continue
        if not _prefix_match(want, keys):
            continue
        a = agg.setdefault(r["keys"], {"keys": keys, "n_files": 0, "files": [],
                                       "types": [], "values": []})
        a["n_files"] += 1
        if len(a["files"]) < 3:
            a["files"].append(str(root / r["path"]))
        for t in json.loads(r["types"]):
            if t not in a["types"]:
                a["types"].append(t)
        for v in json.loads(r["samples"]):
            if len(a["values"]) < 5 and v not in a["values"]:
                a["values"].append(v)
    return agg


def config_keys_impl(base: str | None = None, codebase: str | None = None,
                     prefix: str | None = None, include_data: bool = True,
                     data_prefix: str | None = None,
                     max_results: int = 200) -> list[dict]:
    """Key schema: code lookups (py_keys) merged with data files (data_keys).

    data_prefix mounts the code keys of `base` under a data key path, for a
    dict handed across calls (bsmart: tool `settings` = inputs["Codes"][name]).
    """
    want = [k for k in prefix.split("/") if k] if prefix else []
    mount = [k for k in data_prefix.split("/") if k] if data_prefix else []
    if base is not None:
        base = base.removeprefix("self.").removeprefix("cls.")
    results: list[dict] = []
    for e in registry.resolve(codebase):
        root = Path(e.path)
        con = _py_con(e)
        if con is None:
            continue
        try:
            if base is None and want:  # data-only schema under a key prefix
                for a in sorted(_data_key_agg(con, root, e, want, None).values(),
                                key=lambda a: a["keys"]):
                    results.append({"codebase": e.id, "keys": a["keys"],
                                    "data": {k: v for k, v in a.items()
                                             if k != "keys"}})
                continue
            if not _has_table(con, "py_keys"):
                continue
            if base is None:  # discovery: which receivers are key-indexed most
                for r in con.execute(
                        "SELECT base, COUNT(*) AS n, COUNT(DISTINCT keys) AS nk,"
                        " GROUP_CONCAT(DISTINCT raw_base) AS raw FROM py_keys"
                        " GROUP BY base ORDER BY n DESC LIMIT ?", (max_results,)):
                    results.append({"codebase": e.id, "base": r["base"],
                                    "n_uses": r["n"], "n_key_paths": r["nk"],
                                    "written_as": sorted(r["raw"].split(","))})
                continue
            agg: dict[str, dict] = {}
            for r in con.execute("SELECT * FROM py_keys WHERE base = ?"
                                 " ORDER BY path, line", (base,)):
                keys = json.loads(r["keys"])
                if not _prefix_match(want, keys):
                    continue
                a = agg.setdefault(r["keys"], {
                    "codebase": e.id, "keys": keys, "accesses": {},
                    "defaults": [], "n_uses": 0, "locations": []})
                a["n_uses"] += 1
                a["accesses"][r["access"]] = a["accesses"].get(r["access"], 0) + 1
                if r["dflt"] and r["dflt"] not in a["defaults"]:
                    a["defaults"].append(r["dflt"])
                if len(a["locations"]) < 3:
                    a["locations"].append(
                        f"{root / r['path']}:{r['line']} ({r['scope']})")
            if include_data and agg:
                if mount:  # data rows under the mount, re-keyed relative to it
                    raw = _data_key_agg(con, root, e, mount + want, None)
                    dagg: dict[str, dict] = {}
                    for d in raw.values():
                        rel = d["keys"][len(mount):]
                        if not rel:
                            continue
                        m = dagg.setdefault(json.dumps(rel), {
                            "keys": rel, "n_files": 0, "files": [],
                            "types": [], "values": []})
                        m["n_files"] += d["n_files"]
                        for f in d["files"]:
                            if f not in m["files"] and len(m["files"]) < 3:
                                m["files"].append(f)
                        for t in d["types"]:
                            if t not in m["types"]:
                                m["types"].append(t)
                        for v in d["values"]:
                            if v not in m["values"] and len(m["values"]) < 5:
                                m["values"].append(v)
                else:
                    code_roots = {a["keys"][0] for a in agg.values()
                                  if a["keys"][0] != "*"}
                    dagg = _data_key_agg(con, root, e, want, code_roots)
                code_keys = [a["keys"] for a in agg.values()]
                for kstr, d in dagg.items():
                    data = {k: v for k, v in d.items() if k != "keys"}
                    if kstr in agg:
                        agg[kstr]["data"] = data
                        continue
                    # read if a code path matches it, reads beneath it,
                    # reads the list holding it (settings["Higgs"] covers
                    # Higgs/*), or reads an entry by variable key
                    # (obs[name] consumes obs/<name>/...). Iterating a dict
                    # (cfg["Codes"]) does not cover its keys.
                    dk = d["keys"]
                    via = max((p for p in code_keys if _seg_match(
                        p[:len(dk)], dk[:len(p)]) and (
                            p[-1] == "*" or all(k == "*" for k in dk[len(p):]))),
                        key=lambda p: (min(len(p), len(dk)), -p.count("*")),
                        default=None)
                    agg[kstr] = {"codebase": e.id, "keys": d["keys"],
                                 "accesses": {}, "defaults": [], "n_uses": 0,
                                 "locations": [], "data": data,
                                 **({"read_via": via} if via else {})}
                for a in agg.values():
                    if a["n_uses"] and "data" in a:
                        a["status"] = "read+set"
                    elif a["n_uses"]:
                        a["status"] = ("pattern" if "*" in a["keys"]
                                       else "read_only")
                    else:
                        a["status"] = "read+set" if "read_via" in a else "set_only"
            results.extend(sorted(agg.values(), key=lambda a: a["keys"]))
        finally:
            con.close()
    return results[:max_results]


def data_files_impl(codebase: str | None = None, glob: str | None = None,
                    has_key: str | None = None, max_results: int = 100) -> list[dict]:
    """List indexed JSON/YAML/TOML files, optionally those containing a key path."""
    import fnmatch
    want = [k for k in has_key.split("/") if k] if has_key else []
    out: list[dict] = []
    for e in registry.resolve(codebase):
        con = _py_con(e)
        if con is None:
            continue
        try:
            if not _has_table(con, "data_files"):
                continue
            with_key = None
            if want:
                with_key = {r["path"] for r in con.execute(
                    "SELECT path, keys FROM data_keys")
                    if _prefix_match(want, json.loads(r["keys"]))}
            for r in con.execute("SELECT path, format, size, top_keys, truncated,"
                                 " content IS NOT NULL AS stored FROM data_files"
                                 " ORDER BY path"):
                if glob and not (fnmatch.fnmatch(r["path"], glob) or
                                 fnmatch.fnmatch(Path(r["path"]).name, glob)):
                    continue
                if with_key is not None and r["path"] not in with_key:
                    continue
                out.append({"codebase": e.id,
                            "path": str(Path(e.path) / r["path"]),
                            "rel_path": r["path"], "format": r["format"],
                            "size": r["size"], "stored": bool(r["stored"]),
                            "top_keys": json.loads(r["top_keys"]),
                            **({"truncated": True} if r["truncated"] else {})})
                if len(out) >= max_results:
                    return out
        finally:
            con.close()
    return out


def call_graph_impl(name: str, codebase: str | None = None,
                    direction: str = "both", max_results: int = 50) -> list[dict]:
    """Static callees / callers of a Python function, method or class."""
    if direction not in ("both", "calls", "callers"):
        raise ValueError("direction must be 'both', 'calls' or 'callers'")
    if max_results < 0:  # a negative LIMIT means unlimited in sqlite
        max_results = 50
    out: list[dict] = []
    for e in registry.resolve(codebase):
        root = Path(e.path)
        con = _py_con(e)
        if con is None:
            continue
        try:
            if not _has_table(con, "py_calls"):
                continue
            if "." in name:
                rows = _resolve_dotted(con, name)
                if not rows:
                    rows = con.execute(
                        f"SELECT {_API_COLS} FROM py_api WHERE qualname LIKE ?"
                        " ORDER BY path, line LIMIT 10", ("%." + name,)).fetchall()
            else:
                rows = con.execute(
                    f"SELECT {_API_COLS} FROM py_api WHERE name = ? AND kind IN"
                    " ('function', 'method', 'class', 'module') ORDER BY path, line"
                    " LIMIT 10", (name,)).fetchall()
            for r in rows:
                q = r["qualname"]
                res = {"codebase": e.id, "qualname": q, "kind": r["kind"],
                       "path": str(root / r["path"]), "line": r["line"],
                       "signature": r["signature"]}
                if direction in ("both", "calls"):
                    callees: dict[str, dict] = {}
                    for c in con.execute("SELECT callee, target, line FROM"
                                         " py_calls WHERE caller = ? ORDER BY line",
                                         (q,)):
                        key = c["target"] or c["callee"]
                        if key in callees:
                            callees[key]["n"] += 1
                            continue
                        callees[key] = {"callee": c["callee"], "line": c["line"],
                                        "n": 1, **({"target": c["target"]}
                                                   if c["target"] else {})}
                    res["calls"] = list(callees.values())[:max_results]
                if direction in ("both", "callers"):
                    res["called_by"] = [
                        {"caller": c["caller"], "callee": c["callee"],
                         "path": str(root / c["path"]), "line": c["line"]}
                        for c in con.execute(
                            "SELECT * FROM py_calls WHERE target = ? ORDER BY"
                            " caller, line LIMIT ?", (q, max_results))]
                    if r["kind"] == "method":  # x.meth() with unknown x
                        poss = con.execute(
                            "SELECT * FROM py_calls WHERE name = ? AND target != ?"
                            " AND callee LIKE ? AND (target = '' OR target NOT IN"
                            " (SELECT qualname FROM py_api)) ORDER BY caller, line",
                            (r["name"], q, "%." + r["name"])).fetchall()
                        if poss:
                            res["n_possible_callers"] = len(poss)
                            res["possible_callers"] = [
                                {"caller": c["caller"], "callee": c["callee"],
                                 "path": str(root / c["path"]), "line": c["line"]}
                                for c in poss[:max_results]]
                out.append(res)
        finally:
            con.close()
    if not out:
        raise KeyError(f"no Python function/method/class {name!r} in "
                       f"{codebase or 'any codebase'} (try find_symbol, or "
                       f"reindex if this index predates the call graph)")
    return out


def _stored_file(path: str) -> tuple[registry.CodebaseEntry, str, str] | None:
    """(entry, rel, content) for a data file stored in some index, else None."""
    p = Path(path)
    for e in registry.load_registry():
        if p.is_absolute():
            if not p.is_relative_to(e.path):
                continue
            rel = p.relative_to(e.path).as_posix()
        else:
            rel = p.as_posix().removeprefix("./")
        con = _py_con(e)
        if con is None:
            continue
        try:
            if not _has_table(con, "data_files"):
                continue
            r = con.execute("SELECT content FROM data_files WHERE path = ?"
                            " AND content IS NOT NULL", (rel,)).fetchone()
        finally:
            con.close()
        if r is not None:
            root = Path(e.path).resolve()
            if (root / rel).resolve().is_relative_to(root):
                return e, rel, r["content"]
    return None


def _registered_roots() -> list[tuple[registry.CodebaseEntry, Path]]:
    return [(e, Path(e.path)) for e in registry.load_registry() if Path(e.path).is_dir()]


def _numbered(lines: list[str], offset: int, limit: int) -> list[str]:
    return [f"{n}: {lines[n - 1]}"
            for n in range(offset, min(offset + limit, len(lines) + 1))]


def read_file_impl(path: str, offset: int = 1, limit: int = 200,
                   center: int | None = None, before: int = 10,
                   after: int = 10) -> dict:
    """Read from disk; if the file is not there (no checkout), fall back to a
    data file whose content is stored in the index (source="index")."""
    try:
        return _read_disk(path, offset, limit, center, before, after)
    except (FileNotFoundError, ValueError) as err:
        stored = _stored_file(path)
        if stored is None:
            raise err
    e, rel, content = stored
    if center is not None:
        center = max(1, int(center))
        offset = max(1, center - max(0, int(before)))
        limit = max(0, int(before)) + max(0, int(after)) + 1
    offset = max(1, offset)
    limit = min(max(limit, 0), _MAX_READ_LINES)
    lines = content.splitlines()
    return {"codebase": e.id, "rel_path": rel, "offset": offset,
            "total_lines": len(lines), "content": _numbered(lines, offset, limit),
            "source": "index"}


def _read_disk(path: str, offset: int = 1, limit: int = 200,
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
            selected = _numbered(lines, offset, limit)
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
        """Look up a class/function/variable symbol via the symbol index.

        `name` is matched exactly first, then as a substring if nothing
        matched exactly. A dotted name ("pkg.mod.Class.method",
        "Class.method", or a re-export like "pkg.Name") is resolved against
        Python qualified names, following imports. `codebase` is an
        optional id or bare name (omit to search all); `kind` filters by
        kind: Python uses "module", "class", "function", "method",
        "variable", "attribute", "instance_attribute" (self.x set in a
        method); other languages use ctags kinds (e.g.
        "class", "function", "member"). Returns {codebase, name, kind, path,
        line, language, signature}; Python hits also carry qualname,
        summary (docstring first paragraph), and bases/decorators/value
        (full literal constant) when present. If a codebase has no index yet, falls back to a whole-word
        ripgrep and returns grep-shaped hits {codebase, path, line_no, text}.

        Example: find_symbol("Kinematics", codebase="atlas", kind="class") ->
            [{"codebase": "atlas@1.0", "name": "Kinematics",
              "kind": "class", "path": "/srv/atlas/kine.py", "line": 3, ...}]

        If unsure which codebases are indexed, call list_codebases first; selectors are 'name' (latest) or 'name@version'.
        """
        return find_symbol_impl(name, codebase, kind, max_results)

    @mcp.tool()
    def read_file(path: str, offset: int = 1, limit: int = 200,
                  center: int | None = None, before: int = 10,
                  after: int = 10) -> dict:
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
        Data files stored in the index (see data_files) are served from it
        when the checkout is absent; the result then has source="index".

        If unsure which codebases are indexed, call list_codebases first; selectors are 'name' (latest) or 'name@version'.
        """
        return read_file_impl(path, offset, limit, center, before, after)

    @mcp.tool()
    def outline(target: str, codebase: str | None = None,
                include_private: bool = False,
                max_members: int = 200) -> list[dict]:
        """API outline of a Python package, module, or class, without reading source.

        `target` is a dotted name ("bsmart", "bsmart.scans.MCMC",
        "bsmart.scans.MCMC.NewScan"), a unique dotted suffix ("MCMC.NewScan"),
        a re-exported name ("pkg.Name" resolved through imports), or a file
        path relative to the codebase root. Returns one dict per matching
        codebase: {codebase, qualname, kind, path, line, signature, doc,
        members[{name, kind, line, signature, summary, bases?, decorators?,
        value?}]} — `value` is the full source of a long literal constant
        (e.g. a plugin's settings/metadata dict) that the signature truncates;
        plus, for modules: imports, __all__ (if declared), reexports
        (package/`__all__` names with their resolved target), and for
        packages submodules[{module, summary}]; for classes: bases and
        subclasses (classes naming it as a base — e.g. every plugin
        implementing an interface). A class's signature is its constructor
        signature (from __init__ or dataclass fields). Private (_x) members
        are hidden unless include_private=True; __all__ restricts module
        members when declared.

        Example: outline("bsmart.scans.MCMC.NewScan") ->
            [{"qualname": "bsmart.scans.MCMC.NewScan", "kind": "class",
              "bases": ["Scan"], "signature": "(scan_config, ...)",
              "members": [{"name": "run", "kind": "method", ...}], ...}]

        Use read_file(path, center=line) for a body. If unsure which codebases are
        indexed, call list_codebases first; selectors are 'name' (latest) or
        'name@version'.
        """
        return outline_impl(target, codebase, include_private, max_members)

    @mcp.tool()
    def call_graph(name: str, codebase: str | None = None,
                   direction: str = "both", max_results: int = 50) -> list[dict]:
        """Static call graph of a Python function, method or class: what it calls
        and who calls it. Use it to see how an API is driven in practice.

        `name` is a qualified/dotted name ("bsmart.HEPRun.HEPRun.run_batch",
        "core.Scan.run") or a bare name (all definitions, max 10).
        `direction` is "both" (default), "calls" or "callers". Returns one
        dict per definition: {codebase, qualname, kind, path, line,
        signature, calls[{callee, target?, line, n}], called_by[{caller,
        callee, path, line}]} — `target` is the resolved definition
        (imports, re-exports, self.method() through base classes; external
        ones like "numpy.array" kept). Calling a class = constructing it.
        For methods, possible_callers lists `x.meth()` calls whose receiver
        type is unknown statically (e.g. self.RunManager.run_batch) — likely
        but unverified, n_possible_callers gives the total.

        Example: call_graph("run_batch", codebase="bsmart", direction="callers")
            -> [{"qualname": "bsmart.HEPRun.HEPRun.run_batch", "called_by": [],
                 "possible_callers": [{"caller": "bsmart.scans.AffineMC.NewScan.
                 run_batch", "callee": "self.RunManager.run_batch", ...}]}]

        If unsure which codebases are indexed, call list_codebases first;
        selectors are 'name' (latest) or 'name@version'.
        """
        return call_graph_impl(name, codebase, direction, max_results)

    @mcp.tool()
    def config_keys(base: str | None = None, codebase: str | None = None,
                    prefix: str | None = None, include_data: bool = True,
                    data_prefix: str | None = None,
                    max_results: int = 200) -> list[dict]:
        """Which string keys Python code reads from a config/dict, with defaults.

        Built statically from every lookup chain like cfg["Setup"]["Cores"],
        cfg["Setup"].get("Resume", "False"), "SLHA_Output" in cfg["Setup"],
        or a write cfg["A"]["B"] = .... For config-driven codes this lists the
        valid input-file keys, their defaults, and where each is consumed.

        Call with no `base` first to discover receivers: returns
        [{codebase, base, n_uses, n_key_paths, written_as}] ranked by use
        ("self." is stripped, so `inputs` covers self.inputs too). Then pass
        `base` (e.g. "inputs", "os.environ") and optionally `prefix` — a
        "/"-separated key path such as "Setup" or "Codes/*" ("*" = a
        non-constant key, e.g. a loop variable) — to get one row per key path:
        {codebase, keys, accesses{index|get|in|set|del: n}, defaults,
        n_uses, locations[<=3 "path:line (scope)"]}.

        With include_data (default), key paths found in the codebase's
        JSON/YAML/TOML files (example inputs, templates) are merged in when
        their top-level key is one the code reads: rows gain
        data{n_files, files[<=3], types, values[<=5 samples]} and a status:
        "read+set" (read by code and set in examples), "read_only" (code
        reads it, no example sets it: optional/defaulted), "set_only" (in
        data files but never read via this base: dead option, typo, or read
        through an alias), "pattern" (code path with "*", matched by
        concrete data rows carrying read_via; read_via is also set when
        code reads keys beneath a data container, reads the list holding a
        data element, or reads an entry by a variable key, which consumes
        everything nested in it). With base omitted but
        `prefix` given, returns the data-file schema alone.

        Aliases: within a function, s = cfg["Setup"]; s["Cores"] is reported
        as cfg/Setup/Cores. A dict handed across calls can't be traced
        statically — use `data_prefix` to mount its data, e.g.
        config_keys("settings", data_prefix="Codes/*") matches a tool's
        settings["Command"] against Codes/<tool>/Command in example inputs.

        Example: config_keys("inputs", codebase="bsmart", prefix="Setup") ->
            [{"keys": ["Setup", "Resume"], "accesses": {"get": 3},
              "defaults": ["'False'"], ...}, ...]

        If unsure which codebases are indexed, call list_codebases first;
        selectors are 'name' (latest) or 'name@version'.
        """
        return config_keys_impl(base, codebase, prefix, include_data,
                                data_prefix, max_results)

    @mcp.tool()
    def data_files(codebase: str | None = None, glob: str | None = None,
                   has_key: str | None = None,
                   max_results: int = 100) -> list[dict]:
        """List JSON/YAML/TOML files (example inputs, templates, configs).

        `glob` filters by path or file name (e.g. "*MCMC*.json",
        "*/InputExamples/*"); `has_key` keeps files containing a "/"-separated
        key path, "*" matching any key (e.g. "Codes/SModelS" -> every example
        input that configures SModelS). Returns {codebase, path, rel_path,
        format, size, stored, top_keys, truncated?}. stored=True means the
        whole file is in the index: read_file works on it even without the
        checkout. For the merged key schema use config_keys.

        Example: data_files(codebase="bsmart", has_key="Codes/SModelS") ->
            [{"rel_path": "src/bsmart/data/InputExamples/SMSQQ/SMSQQ.json",
              "format": "json", "stored": true, "top_keys": ["Setup", ...]}]

        If unsure which codebases are indexed, call list_codebases first;
        selectors are 'name' (latest) or 'name@version'.
        """
        return data_files_impl(codebase, glob, has_key, max_results)

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
