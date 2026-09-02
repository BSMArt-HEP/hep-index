"""Tests for the CLI (real ctags, no network; see CONTRACT.md §cli)."""
import json
import sqlite3

import pytest

from hep_index import registry
from hep_index.cli import main
from hep_index.recipes import RECIPES
from hep_index.registry import index_dir
from hep_index.server import list_codebases_impl


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HEP_INDEX_CONFIG", str(tmp_path / "reg.toml"))
    monkeypatch.setenv("HEP_INDEX_CACHE", str(tmp_path / "cache"))
    return tmp_path


@pytest.fixture
def root(env):
    """Tiny fixture codebase with real Python symbols."""
    src = env / "toy-src"
    src.mkdir()
    (src / "physics.py").write_text(
        "def simulate():\n    pass\n\n\nclass Detector:\n    pass\n")
    return src


def _add(root, *extra):
    return main(["add", str(root), "--name", "toy", "--version", "1.0", *extra])


def test_recipes_have_required_keys():
    assert {"madgraph", "madanalysis", "delphes"} <= set(RECIPES)
    for globs in RECIPES.values():
        assert globs and all(isinstance(g, str) for g in globs)


def test_add_indexes_and_registers(env, root, monkeypatch, capsys):
    monkeypatch.chdir(env)  # relative path must be stored as abspath
    assert main(["add", "toy-src", "--name", "toy", "--version", "1.0"]) == 0
    entries = registry.load_registry()
    assert [e.id for e in entries] == ["toy@1.0"]
    entry = entries[0]
    assert entry.path == str(root)
    assert entry.exclude == []

    out = index_dir(entry)
    assert (out / "index.db").is_file()
    assert (out / "meta.json").is_file()
    meta = json.loads((out / "meta.json").read_text())
    assert meta["entry_id"] == "toy@1.0"

    con = sqlite3.connect(out / "index.db")
    syms = {r[0] for r in con.execute("SELECT name FROM symbols")}
    files = [r[0] for r in con.execute("SELECT path FROM files")]
    con.close()
    assert {"simulate", "Detector"} <= syms  # real ctags ran
    assert files == ["physics.py"]

    line = capsys.readouterr().out.strip()
    assert line.startswith("registered toy@1.0: 1 files, ")
    assert line.endswith(" symbols, head none")  # fixture is not a git repo


def test_add_recipe_extends_exclude(env, root):
    (root / "Events").mkdir()
    (root / "Events" / "run.lhe").write_text("fake events\n")
    rc = main(["add", str(root), "--name", "toy", "--version", "1.0",
               "--exclude", "*.tmp", "--recipe", "madgraph"])
    assert rc == 0
    entry = registry.load_registry()[0]
    assert entry.exclude == ["*.tmp"] + RECIPES["madgraph"]
    con = sqlite3.connect(index_dir(entry) / "index.db")
    files = {r[0] for r in con.execute("SELECT path FROM files")}
    con.close()
    assert "Events/run.lhe" not in files  # recipe glob honored by the indexer
    assert "physics.py" in files


def test_duplicate_add_exits_1(env, root, capsys):
    assert _add(root) == 0
    assert _add(root) == 1
    assert capsys.readouterr().err.startswith("error:")
    assert len(registry.load_registry()) == 1


def test_add_missing_path_exits_1(env, capsys):
    assert main(["add", str(env / "missing"), "--name", "x",
                 "--version", "1"]) == 1
    assert capsys.readouterr().err.startswith("error:")
    assert registry.load_registry() == []


def test_usage_errors_exit_1(env, root, capsys):
    assert main(["frobnicate"]) == 1
    assert main(["add"]) == 1  # missing required args
    assert main(["add", str(root), "--name", "t", "--version", "1",
                 "--recipe", "nope"]) == 1
    assert "error:" in capsys.readouterr().err


def test_remove_unregisters_and_deletes_index_dirs(env, root):
    assert _add(root) == 0
    assert main(["add", str(root), "--name", "toy", "--version", "2.0"]) == 0
    dirs = [index_dir(e) for e in registry.load_registry()]
    assert all(d.is_dir() for d in dirs)
    assert main(["remove", "toy"]) == 0  # bare name -> all versions
    assert registry.load_registry() == []
    assert not any(d.exists() for d in dirs)


def test_remove_selective_version(env, root):
    assert _add(root) == 0
    assert main(["add", str(root), "--name", "toy", "--version", "2.0"]) == 0
    assert main(["remove", "toy@1.0"]) == 0
    assert [e.id for e in registry.load_registry()] == ["toy@2.0"]
    assert index_dir(registry.resolve("toy")[0]).is_dir()  # 2.0 index kept


def test_remove_unknown_exits_2(env, capsys):
    assert main(["remove", "ghost"]) == 2
    assert capsys.readouterr().err.startswith("error:")


def test_list_json_matches_impl(env, root, capsys):
    assert _add(root) == 0
    capsys.readouterr()  # drain the add output
    assert main(["list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == list_codebases_impl()
    assert len(data) == 1
    row = data[0]
    assert row["id"] == "toy@1.0"
    assert row["ok"] is True
    assert row["n_files"] == 1
    assert row["n_symbols"] >= 2
    assert row["stale"] is False


def test_list_human_table(env, root, capsys):
    assert _add(root) == 0
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "toy@1.0" in out
    assert str(root) in out
    assert "stale" in out


def test_list_empty(env, capsys):
    assert main(["list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_reindex_rebuilds(env, root, capsys):
    assert _add(root) == 0
    entry = registry.load_registry()[0]
    (root / "extra.py").write_text("def fresh_symbol():\n    pass\n")
    # trash the old index; reindex must recreate it from scratch
    (index_dir(entry) / "index.db").write_bytes(b"garbage")
    assert main(["reindex", "toy"]) == 0
    meta = json.loads((index_dir(entry) / "meta.json").read_text())
    assert meta["n_files"] == 2
    con = sqlite3.connect(index_dir(entry) / "index.db")
    n = con.execute("SELECT COUNT(*) FROM symbols"
                    " WHERE name = 'fresh_symbol'").fetchone()[0]
    con.close()
    assert n == 1
    assert "reindexed toy@1.0" in capsys.readouterr().out


def test_reindex_unknown_exits_2(env, capsys):
    assert main(["reindex", "ghost"]) == 2
    assert capsys.readouterr().err.startswith("error:")
