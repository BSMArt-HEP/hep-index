"""Tests for the CLI (real ctags, no network; see CONTRACT.md §cli)."""
import json
import os
import subprocess
import sqlite3

import pytest

from hep_index import registry
from hep_index.cli import _query_value, main
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


# ---------------------------------------------------------------- v0.2: catalog/fetch/footer

def test_catalog_listing(env, capsys):
    rc = main(["catalog"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "madgraph" in out and "tarball" in out and "3.7.0" in out
    assert "(latest)" in out and "note:" in out


def test_fetch_not_in_catalog(env, capsys):
    rc = main(["fetch", "nosuchpkg"])
    assert rc == 1
    assert "not in catalog" in capsys.readouterr().err


def _fixture_catalog(tmp_path, git_repo):
    cat = tmp_path / "catalog.toml"
    cat.write_text(
        f'[fixture]\ntype = "git"\nurl = "{git_repo.as_uri()}"\n'
        'versions = ["v1.0"]\nrecipe = "madanalysis"\n')
    return cat


def test_fetch_e2e_offline(env, tmp_path, capsys, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("def hello():\n    return 42\n")
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    subprocess.run(["git", "add", "-A"], cwd=src, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "x"], cwd=src, check=True)
    subprocess.run(["git", "tag", "v1.0"], cwd=src, check=True)
    monkeypatch.setenv("HEP_INDEX_CATALOG", str(_fixture_catalog(tmp_path, src)))
    root = tmp_path / "roots"
    monkeypatch.setenv("HEP_INDEX_ROOT", str(root))
    rc = main(["fetch", "fixture"])
    out = capsys.readouterr().out
    assert rc == 0 and "registered fixture@v1.0" in out
    assert (root / "fixture-v1.0" / "mod.py").exists()
    assert any(e.id == "fixture@v1.0" for e in registry.load_registry())


def test_bare_invocation_footer(env, capsys):
    rc = main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "usage:" in out and "registered:" in out


def test_query_tools(env, tmp_path, capsys):
    src = tmp_path / "qsrc"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "__init__.py").write_text("")
    (src / "pkg" / "core.py").write_text(
        "class Scan:\n    def run(self, n: int = 3):\n        return n\n")
    (src / "ex.json").write_text('{"Setup": {"Points": 4}}')
    assert main(["add", str(src), "--name", "q", "--version", "1"]) == 0
    capsys.readouterr()
    assert main(["query", "outline", "pkg.core.Scan"]) == 0
    [o] = json.loads(capsys.readouterr().out)
    assert o["qualname"] == "pkg.core.Scan"
    assert [m["name"] for m in o["members"]] == ["run"]
    # positional fills required params in order; param=value is JSON-parsed
    assert main(["query", "find_symbol", "run", "kind=method",
                 "max_results=1"]) == 0
    [hit] = json.loads(capsys.readouterr().out)
    assert hit["signature"] == "(self, n: int = 3)"
    assert main(["query", "data_files", "has_key=Setup/Points"]) == 0
    assert [f["rel_path"] for f in json.loads(capsys.readouterr().out)] == \
        ["ex.json"]
    # listing / per-tool docs / errors
    assert main(["query"]) == 0
    out = capsys.readouterr().out
    assert "call_graph(" in out and "index_codebase" not in out
    assert main(["query", "outline", "--doc"]) == 0
    assert "API outline" in capsys.readouterr().out
    assert main(["query", "nope"]) == 1
    assert main(["query", "outline", "pkg.nope"]) == 2       # KeyError
    assert main(["query", "outline", "a", "b", "c", "d", "e"]) == 1


# ------------------------------------------------------------- v0.4: --local mode

def test_local_mode_resolution_and_isolation(tmp_path, monkeypatch, capsys):
    import time
    src = tmp_path / "tool"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "mod.py").write_text("def hello():\n    return 42\n")
    # simulate a populated GLOBAL state that must remain untouched
    gcfg, gcache = tmp_path / "g.toml", tmp_path / "gcache"
    gcfg.write_text("[codebase]\nname='keep'\nversion='1'\npath='/nonexistent'\n")
    gcache.mkdir()
    gcfg_before, gcache_before = gcfg.read_text(), gcache.stat().st_mtime_ns
    monkeypatch.setenv("HEP_INDEX_CONFIG", str(gcfg))
    monkeypatch.setenv("HEP_INDEX_CACHE", str(gcache))
    work = tmp_path / "scan"
    work.mkdir()
    monkeypatch.chdir(work)

    rc = main(["--local", "add", str(src), "--name", "tool", "--version", "1.0"])
    assert rc == 0
    assert (work / ".hep-index" / "codebases.toml").is_file()
    assert (work / ".hep-index" / "cache" / "tool-1.0").is_dir()
    # global registry content untouched; no new entries landed there
    assert gcfg.read_text() == gcfg_before
    assert "tool" not in gcfg.read_text()
    time.sleep(2)  # mtime granularity
    rc = main(["--local", "query", "find_symbol", "hello", "codebase=tool"])
    assert rc == 0 and "mod.py" in capsys.readouterr().out
    rc = main(["--local", "list"])
    assert "tool@1.0" in capsys.readouterr().out
    # isolation of the global cache: unchanged
    assert gcache.stat().st_mtime_ns == gcache_before
    assert list(gcache.iterdir()) == []


def test_query_value_python_literals():
    assert _query_value("True") is True
    assert _query_value("False") is False
    assert _query_value("None") is None
    assert _query_value("true") is True      # JSON spellings still work
    assert _query_value("null") is None
    assert _query_value("Setup") == "Setup"


def test_query_unknown_param_exits_1(env, root, capsys):
    assert _add(root) == 0
    capsys.readouterr()
    assert main(["query", "data_files", "globs=*.py"]) == 1
    assert "error: unknown parameter 'globs'" in capsys.readouterr().err


def test_query_bad_type_is_clean_error(env, root, capsys):
    assert _add(root) == 0
    capsys.readouterr()
    assert main(["query", "read_file", "path=5"]) == 1
    cap = capsys.readouterr()
    assert cap.err.startswith("error:")
    assert "Traceback" not in cap.err and "Traceback" not in cap.out


def test_query_python_bool_literal(env, tmp_path, capsys):
    src = tmp_path / "cfgsrc"
    src.mkdir()
    (src / "cfg.py").write_text("def load(cfg):\n"
                                "    return cfg['Setup']['Points']\n")
    (src / "ex.json").write_text('{"Setup": {"Points": 4}}')
    assert main(["add", str(src), "--name", "cfg", "--version", "1"]) == 0
    capsys.readouterr()
    assert main(["query", "config_keys", "base=cfg", "codebase=cfg"]) == 0
    assert any("data" in r for r in json.loads(capsys.readouterr().out))
    assert main(["query", "config_keys", "base=cfg", "codebase=cfg",
                 "include_data=False"]) == 0
    assert all("data" not in r for r in json.loads(capsys.readouterr().out))


def test_local_fetch_keeps_src_root(env, tmp_path, capsys, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("def hello():\n    return 42\n")
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    subprocess.run(["git", "add", "-A"], cwd=src, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "x"], cwd=src, check=True)
    subprocess.run(["git", "tag", "v1.0"], cwd=src, check=True)
    monkeypatch.setenv("HEP_INDEX_CATALOG", str(_fixture_catalog(tmp_path, src)))
    monkeypatch.setenv("HEP_INDEX_ROOT", "sentinel")
    work = tmp_path / "scan"
    work.mkdir()
    monkeypatch.chdir(work)
    assert main(["--local", "fetch", "fixture"]) == 0
    assert (work / ".hep-index" / "src" / "fixture-v1.0" / "mod.py").exists()
    assert (work / ".hep-index" / "codebases.toml").is_file()
    assert os.environ["HEP_INDEX_ROOT"] == "sentinel"   # restored in finally
