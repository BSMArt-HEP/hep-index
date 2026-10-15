"""Tests for the indexer module (real Universal Ctags, no network)."""
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from hep_index.indexer import DEFAULT_EXCLUDES, IndexStats, build_index
from hep_index.registry import CodebaseEntry, index_dir


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HEP_INDEX_CONFIG", str(tmp_path / "reg.toml"))
    monkeypatch.setenv("HEP_INDEX_CACHE", str(tmp_path / "cache"))
    return tmp_path


def make_tree(tmp_path):
    """Small polyglot fixture tree, including stuff that must be excluded."""
    root = tmp_path / "src"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__pycache__").mkdir()
    (root / "build").mkdir()
    (root / "pkg" / "mod.py").write_text(
        "def alpha():\n    pass\n\n\nclass Beta:\n    pass\n")
    (root / "kernel.cpp").write_text(
        "void simulate() {}\n")
    (root / "kernel.h").write_text(
        "int readout(int n) { return n; }\n")
    (root / "pkg" / "junk.pyc").write_bytes(b"\x00")
    (root / "build" / "gen.py").write_text("def generated(): pass\n")
    (root / "pkg" / "__pycache__" / "mod.cpython-311.pyc").write_bytes(b"\x00")
    (root / "vendor_blob.o").write_bytes(b"\x00")
    return root


@pytest.fixture
def entry(env):
    root = make_tree(env)
    return CodebaseEntry(name="toy", version="1.0", path=str(root),
                         exclude=["vendor*"])


def _db(entry):
    return sqlite3.connect(index_dir(entry) / "index.db")


def test_index_files_schema_symbols_excludes(entry, env):
    stats = build_index(entry)
    out = index_dir(entry)
    assert (out / "index.db").is_file()
    assert (out / "meta.json").is_file()

    # exact schema
    con = _db(entry)
    tables = dict(con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall())
    assert set(tables) == {"symbols", "files", "py_api", "py_modules",
                           "py_imports", "py_keys", "py_calls", "data_files",
                           "data_keys"}
    cols = {t: [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
            for t in tables}
    assert cols["symbols"] == ["name", "kind", "path", "line", "language",
                               "signature"]
    assert cols["files"] == ["path", "size", "language"]
    indexes = {r[1] for r in con.execute(
        "SELECT * FROM sqlite_master WHERE type='index'")}
    idx_cols = {ix: [r[2] for r in con.execute(f"PRAGMA index_info({ix})")]
                for ix in indexes}
    assert sorted(idx_cols.get("idx_symbols_name", [])) == ["name"]
    assert sorted(idx_cols.get("idx_symbols_path", [])) == ["path"]

    # symbols extracted by real ctags
    syms = {(r[0], r[1], r[2], r[4]) for r in
            con.execute("SELECT name, kind, path, line, language FROM symbols")}
    assert ("alpha", "function", "pkg/mod.py", "Python") in syms
    assert ("Beta", "class", "pkg/mod.py", "Python") in syms
    assert ("simulate", "function", "kernel.cpp", "C++") in syms
    assert ("readout", "function", "kernel.h", "C++") in syms

    # excludes honored: nothing from build/, __pycache__/, *.pyc, *.o
    files = [r[0] for r in con.execute("SELECT path FROM files")]
    assert sorted(files) == ["kernel.cpp", "kernel.h", "pkg/mod.py"]
    for p in files:
        assert not p.startswith("/")          # relative
        assert "\\" not in p                   # posix separators
    size, lang = con.execute("SELECT size, language FROM files"
                             " WHERE path='pkg/mod.py'").fetchone()
    assert size > 0 and lang == "Python"
    con.close()

    assert stats.n_files == 3
    assert stats.n_symbols == 4


def test_degraded_mode_missing_ctags(entry, env):
    stats = build_index(entry, ctags_bin="/nonexistent/ctags")
    assert stats.ctags_used is False
    # no C++ symbols, but Python still comes from the ast pass
    assert stats.n_symbols == 2
    con = _db(entry)
    assert {r[0] for r in con.execute("SELECT name FROM symbols")} == \
        {"alpha", "Beta"}
    assert con.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 3
    con.close()
    meta = json.loads((index_dir(entry) / "meta.json").read_text())
    assert meta["ctags_used"] is False
    assert meta["n_symbols"] == 2


def test_stats_fields_git(entry, env):
    stats = build_index(entry)
    assert isinstance(stats, IndexStats)
    assert stats.ctags_used is True
    assert stats.git_head is None          # not a git repo
    assert stats.git_dirty is False
    assert stats.indexed_at                # ISO-8601 UTC string

    # real git repo fixture: head non-null, clean -> not dirty
    subprocess.run(["git", "init", "-q"], cwd=entry.path, check=True)
    subprocess.run(["git", "-C", entry.path, "add", "-A"], check=True)
    subprocess.run(["git", "-C", entry.path, "-c", "user.name=t",
                    "-c", "user.email=t@t", "commit", "-qm", "init"], check=True)
    stats = build_index(entry)
    assert stats.git_head
    assert stats.git_dirty is False
    (Path(entry.path) / "dirty.txt").write_text("")
    stats = build_index(entry)
    assert stats.git_dirty is True
    assert stats.n_files == 4  # dirty.txt is now indexed too

    # meta.json = IndexStats fields + entry_id
    meta = json.loads((index_dir(entry) / "meta.json").read_text())
    assert meta["entry_id"] == "toy@1.0"
    assert set(meta) == {"n_files", "n_symbols", "ctags_used", "git_head",
                         "git_dirty", "indexed_at", "entry_id"}
    assert meta["git_head"] == stats.git_head


def test_rerun_wipes_cleanly(entry, env):
    build_index(entry)
    out = index_dir(entry)
    (out / "stale-artifact.txt").write_text("junk")
    con = _db(entry)
    with con:
        con.execute("INSERT INTO files VALUES ('ghost.py', 1, 'Python')")
    con.close()
    stats = build_index(entry)
    assert not (out / "stale-artifact.txt").exists()
    con = _db(entry)
    assert con.execute("SELECT COUNT(*) FROM files"
                       " WHERE path='ghost.py'").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 3
    assert con.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == \
        stats.n_symbols
    con.close()


def test_default_excludes_constant():
    assert DEFAULT_EXCLUDES == [".git", "__pycache__", "*.pyc", "node_modules",
                                "*.o", "*.so", "*.a", "build", "dist"]


def test_ctags_skips_data_languages(env):
    root = env / "data"
    root.mkdir()
    (root / "cfg.json").write_text('{"Setup": {"Points": 10, "Cores": 2}}\n')
    (root / "notes.md").write_text("# Heading\n\n## Section\n")
    (root / "model.m").write_text("f[x_] := x^2;\n")       # Mathematica
    (root / "k.cpp").write_text("void kernel() {}\n")
    entry = CodebaseEntry(name="data", version="1", path=str(root))
    build_index(entry)
    con = _db(entry)
    langs = {r[0] for r in con.execute("SELECT DISTINCT language FROM symbols")}
    con.close()
    assert langs == {"C++"}
