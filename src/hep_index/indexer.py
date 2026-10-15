"""Codebase indexer: ctags + Python-ast symbol extraction + file manifest into sqlite.

Contract (CONTRACT.md §indexer):
  build_index(entry, cache_root=None, ctags_bin="ctags") -> IndexStats
Wipes and recreates index_dir(entry, cache_root) holding index.db + meta.json.
Python files that parse are indexed by `pyast` (replacing their ctags rows);
unparseable ones keep ctags rows.
JSON/YAML/TOML files are flattened to key paths by `datafiles` (small ones
stored whole).
Degraded mode: missing ctags binary -> only ast symbols, ctags_used=False, no raise.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import sqlite3
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from hep_index import datafiles, pyast
from hep_index.registry import CodebaseEntry, index_dir

DEFAULT_EXCLUDES = [".git", "__pycache__", "*.pyc", "node_modules",
                    "*.o", "*.so", "*.a", "build", "dist"]

_MAX_PY_BYTES = 2_000_000  # skip ast on huge (generated) python files

_SUFFIX_LANG = {".py": "Python", ".cpp": "C++", ".h": "C++", ".cc": "C++",
                ".hpp": "C++", ".f90": "Fortran", ".f": "Fortran",
                ".m": "Mathematica", ".json": "JSON", ".yaml": "YAML",
                ".yml": "YAML", ".toml": "TOML"}


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


# ctags parsers for data/markup formats: their "symbols" are keys, headings and
# array indices that drown real code symbols (bsmart: 2161 JSON vs 1004 Python).
# MatLab and ObjectiveC are here because HEP `.m` files are Mathematica, which
# both misparse (disabling only MatLab hands .m to the ObjectiveC parser).
CTAGS_SKIP_LANGUAGES = [
    "JSON", "Yaml", "XML", "SVG", "HTML", "CSS", "SCSS", "Markdown",
    "ReStructuredText", "Asciidoc", "Org", "Txt2tags", "Man", "Tex",
    "TeXBeamer", "BibTeX", "BibLaTeX", "Iniconf", "JavaProperties", "PlistXML",
    "DTD", "RelaxNG", "XSLT", "OpenAPI", "FrontMatter", "RMarkdown", "Quarto",
    "Diff", "Passwd", "MatLab", "ObjectiveC"]


def _ctags_language_flags(ctags_bin: str) -> list[str]:
    """--languages=-X for each skip language this ctags build knows (an
    unknown name makes ctags abort, so filter against --list-languages)."""
    try:
        r = subprocess.run([ctags_bin, "--list-languages"], capture_output=True,
                           text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    known = {ln.split()[0] for ln in r.stdout.splitlines() if ln.strip()}
    skip = [lang for lang in CTAGS_SKIP_LANGUAGES if lang in known]
    return ["--languages=" + ",".join("-" + lang for lang in skip)] if skip else []


def _run_ctags(root: Path, ctags_bin: str, patterns: list[str]):
    """Yield parsed ctags JSON tag records; [] if the binary is missing."""
    if shutil.which(ctags_bin) is None:
        return []
    cmd = [ctags_bin, "-R", "--output-format=json", "--fields=+n+k+s+l",
           "--extras=-F", *_ctags_language_flags(ctags_bin),
           *(f"--exclude={p}" for p in patterns), "."]
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


def _canonical_calls(api_rows, mod_rows, imp_rows, calls_raw) -> list[tuple]:
    """Resolve call targets across files: re-exports (pkg.Name -> pkg.core.Name),
    constructors stay on the class, self.m() climbs resolved base classes."""
    quals = {r[0] for r in api_rows}
    kinds = {r[0]: r[2] for r in api_rows}
    imports = {(m, n): t for m, n, t, _ in imp_rows if n != "*"}
    path_mod = {path: m for m, path, _ in mod_rows}
    cls_mod = {r[0]: path_mod.get(r[3], "") for r in api_rows if r[2] == "class"}
    cls_bases_raw = {r[0]: json.loads(r[9]) for r in api_rows if r[2] == "class"}

    def canon(t: str, depth: int = 0) -> str:
        if not t or t in quals or depth > 6:
            return t
        parts = t.split(".")
        for i in range(len(parts) - 1, 0, -1):
            mod, name, rest = ".".join(parts[:i]), parts[i], parts[i + 1:]
            nxt = imports.get((mod, name))
            if nxt and nxt != t:
                return canon(".".join([nxt, *rest]), depth + 1)
        return t

    bases: dict[str, list[str]] = {}
    for cq, raw in cls_bases_raw.items():
        mod = cls_mod[cq]
        out = []
        for b in raw:
            if "=" in b:
                continue  # metaclass=...
            head, _, rest = b.split("[", 1)[0].partition(".")
            tgt = imports.get((mod, head)) or (
                f"{mod}.{head}" if f"{mod}.{head}" in quals else head)
            out.append(canon(tgt + (f".{rest}" if rest else "")))
        bases[cq] = out

    attr_sig = {r[0]: r[7] for r in api_rows
                if r[2] in ("attribute", "instance_attribute")}

    def attr_type(cq: str, attr: str, depth: int = 0) -> str | None:
        """Class of self.attr from its recorded `= Ctor(...)` value (or a base's)."""
        sig = attr_sig.get(f"{cq}.{attr}")
        if sig is not None:
            m = re.match(r"(?::[^=]*)?\s*=\s*([A-Za-z_][\w.]*)\(", sig)
            if not m:
                return None
            head, _, rest = m.group(1).partition(".")
            mod = cls_mod.get(cq, "")
            tgt = imports.get((mod, head)) or (
                f"{mod}.{head}" if f"{mod}.{head}" in quals else None)
            if tgt is None:
                return None
            t = canon(tgt + (f".{rest}" if rest else ""))
            return t if kinds.get(t) == "class" else None
        if depth > 8:
            return None
        for b in bases.get(cq, []):
            hit = attr_type(b, attr, depth + 1)
            if hit:
                return hit
        return None

    def method(cq: str, m: str, depth: int = 0) -> str | None:
        if f"{cq}.{m}" in quals:
            return f"{cq}.{m}"
        if depth > 8:
            return None
        for b in bases.get(cq, []):
            hit = method(b, m, depth + 1)
            if hit:
                return hit
        return None

    rows = []
    for caller, callee, name, target, path, line in calls_raw:
        if "#" in target:  # self.attr.meth()
            cq, _, am = target.partition("#")
            attr, _, m = am.partition(".")
            typ = attr_type(cq, attr)
            t = (method(typ, m) or f"{typ}.{m}") if typ else ""
            rows.append((caller, callee, name, t, path, line))
            continue
        t = canon(target)
        if t and t not in quals:
            cq, _, m = t.rpartition(".")
            if kinds.get(cq) == "class":
                t = method(cq, m) or t
        rows.append((caller, callee, name, t, path, line))
    return rows


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

    # python: ast replaces ctags rows for every file that parses
    api_rows, mod_rows, imp_rows, key_rows = [], [], [], []  # py_* tables
    calls_raw: list[tuple] = []
    parsed: set[str] = set()
    for rel, size, lang in file_rows:
        if lang != "Python" or not rel.endswith(".py") or size > _MAX_PY_BYTES:
            continue
        info = pyast.extract_file(root, rel)
        if info is None:
            continue
        parsed.add(rel)
        api_rows.extend(r.as_tuple() for r in info.rows)
        mod_rows.append((info.module, rel, json.dumps(info.all_names)))
        imp_rows.extend((info.module, n, t, ln) for n, t, ln in info.imports)
        key_rows.extend(k.as_tuple() for k in info.keys)
        calls_raw.extend(c.as_tuple() for c in info.calls)
    call_rows = _canonical_calls(api_rows, mod_rows, imp_rows, calls_raw)

    # structured data files: key paths (+ whole content when small)
    df_rows, dk_rows = [], []  # data_files / data_keys
    for rel, size, _ in file_rows:
        dinfo = datafiles.extract_data_file(root, rel, size)
        if dinfo is None:
            continue
        df_rows.append((rel, dinfo.format, size, json.dumps(dinfo.top_keys),
                        int(dinfo.truncated), dinfo.content))
        dk_rows.extend(k.as_tuple(rel) for k in dinfo.keys)

    sym_rows = [r for r in sym_rows if r[2] not in parsed]
    sym_rows.extend((r[1], r[2], r[3], r[4], "Python", r[7])
                    for r in api_rows if r[2] != "module")

    # deterministic sorted inserts
    file_rows.sort()
    sym_rows.sort()
    api_rows.sort()
    mod_rows.sort()
    imp_rows.sort()
    key_rows.sort()
    call_rows.sort()
    df_rows.sort()
    dk_rows.sort()

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
            con.execute("CREATE TABLE py_api(qualname TEXT, name TEXT, kind TEXT,"
                        " path TEXT, line INTEGER, end_line INTEGER, parent TEXT,"
                        " signature TEXT, doc TEXT, bases TEXT, decorators TEXT,"
                        " value TEXT)")
            con.execute("CREATE INDEX idx_py_api_qualname ON py_api(qualname)")
            con.execute("CREATE INDEX idx_py_api_parent ON py_api(parent)")
            con.execute("CREATE INDEX idx_py_api_loc ON py_api(path, line)")
            con.execute("CREATE TABLE py_modules(module TEXT, path TEXT,"
                        " all_names TEXT)")
            con.execute("CREATE INDEX idx_py_modules_module ON py_modules(module)")
            con.execute("CREATE TABLE py_imports(module TEXT, name TEXT,"
                        " target TEXT, line INTEGER)")
            con.execute("CREATE INDEX idx_py_imports ON py_imports(module, name)")
            con.executemany("INSERT INTO py_api VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            api_rows)
            con.executemany("INSERT INTO py_modules VALUES (?,?,?)", mod_rows)
            con.executemany("INSERT INTO py_imports VALUES (?,?,?,?)", imp_rows)
            con.execute("CREATE TABLE py_keys(base TEXT, raw_base TEXT, keys TEXT,"
                        " access TEXT, dflt TEXT, scope TEXT, path TEXT,"
                        " line INTEGER)")
            con.execute("CREATE INDEX idx_py_keys_base ON py_keys(base)")
            con.executemany("INSERT INTO py_keys VALUES (?,?,?,?,?,?,?,?)",
                            key_rows)
            con.execute("CREATE TABLE py_calls(caller TEXT, callee TEXT,"
                        " name TEXT, target TEXT, path TEXT, line INTEGER)")
            con.execute("CREATE INDEX idx_py_calls_caller ON py_calls(caller)")
            con.execute("CREATE INDEX idx_py_calls_target ON py_calls(target)")
            con.execute("CREATE INDEX idx_py_calls_name ON py_calls(name)")
            con.executemany("INSERT INTO py_calls VALUES (?,?,?,?,?,?)",
                            call_rows)
            con.execute("CREATE TABLE data_files(path TEXT, format TEXT,"
                        " size INTEGER, top_keys TEXT, truncated INTEGER,"
                        " content TEXT)")
            con.execute("CREATE INDEX idx_data_files_path ON data_files(path)")
            con.execute("CREATE TABLE data_keys(path TEXT, keys TEXT,"
                        " types TEXT, samples TEXT)")
            con.execute("CREATE INDEX idx_data_keys_path ON data_keys(path)")
            con.executemany("INSERT INTO data_files VALUES (?,?,?,?,?,?)",
                            df_rows)
            con.executemany("INSERT INTO data_keys VALUES (?,?,?,?)", dk_rows)
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
