"""Tests for hep_index.server: impl functions + MCP tool wiring.

Fixture codebases are built directly on disk; their index.db/meta.json are
pre-created per the CONTRACT.md schema (indexer.build_index is out of scope
here). No network: rg/git run locally against tmp_path fixtures; fetch_codebase
tests use a file:// git fixture behind a fixture catalog (CONTRACT.md §D4).
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from hep_index import registry, server
from hep_index.recipes import RECIPES
from hep_index.server import (create_mcp_server, fetch_codebase_impl,
                              find_symbol_impl, index_codebase_impl,
                              call_graph_impl, config_keys_impl,
                              data_files_impl,
                              list_codebases_impl,
                              outline_impl,
                              read_file_impl, search_code_impl)

ATLAS_FILES = {
    "physics/kine.py": (
        "import math\n"
        "\n"
        "class Kinematics:\n"
        "    def pt(self, p):\n"
        "        return math.hypot(p[0], p[1])\n"
        "\n"
        "    def rapidity(self, p):\n"
        "        return 0.5 * math.log(p[3] + p[0])\n"
    ),
    "util/helpers.h": (
        "#pragma once\n"
        "class Helper {\n"
        "public:\n"
        "    void doThing();\n"
        "};\n"
    ),
}
MA5_FILES = {
    "sample.py": (
        "def analyze(events):\n"
        "    total = 0\n"
        "    for e in events:\n"
        "        total += e\n"
        "    return total\n"
    ),
}

ATLAS_SYMBOLS = [
    ("Kinematics", "class", "physics/kine.py", 3, "Python", "class Kinematics:"),
    ("pt", "member", "physics/kine.py", 4, "Python", "def pt(self, p):"),
    ("rapidity", "member", "physics/kine.py", 7, "Python", "def rapidity(self, p):"),
    ("Helper", "class", "util/helpers.h", 2, "C++", "class Helper {"),
]
MA5_SYMBOLS = [
    ("analyze", "function", "sample.py", 1, "Python", "def analyze(events):"),
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HEP_INDEX_CONFIG", str(tmp_path / "reg.toml"))
    monkeypatch.setenv("HEP_INDEX_CACHE", str(tmp_path / "cache"))
    return tmp_path


def make_codebase(tmp_path, name, version, files):
    root = tmp_path / name
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    return registry.CodebaseEntry(name=name, version=version, path=str(root))


def write_index(entry, symbols, n_files=2, git_head=None):
    """Pre-create index.db + meta.json per the contract schema (wipes first)."""
    d = registry.index_dir(entry)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(d / "index.db")
    db.execute("CREATE TABLE symbols(name TEXT, kind TEXT, path TEXT, "
               "line INTEGER, language TEXT, signature TEXT)")
    db.execute("CREATE INDEX symbols_name ON symbols(name)")
    db.execute("CREATE INDEX symbols_path ON symbols(path)")
    db.execute("CREATE TABLE files(path TEXT, size INTEGER, language TEXT)")
    db.executemany("INSERT INTO symbols VALUES (?,?,?,?,?,?)", symbols)
    db.commit()
    db.close()
    meta = {"n_files": n_files, "n_symbols": len(symbols), "ctags_used": True,
            "git_head": git_head, "git_dirty": False,
            "indexed_at": "2026-01-01T00:00:00+00:00", "entry_id": entry.id}
    (d / "meta.json").write_text(json.dumps(meta))


@pytest.fixture
def two_codebases(env):
    atlas = make_codebase(env, "atlas", "1.0", ATLAS_FILES)
    ma5 = make_codebase(env, "ma5", "1.1", MA5_FILES)
    registry.add_entry(atlas)
    registry.add_entry(ma5)
    write_index(atlas, ATLAS_SYMBOLS)
    write_index(ma5, MA5_SYMBOLS, n_files=1)
    return atlas, ma5


def _git_head_of(path: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "init"],
                   cwd=path, check=True)
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, check=True,
                         capture_output=True, text=True)
    return out.stdout.strip()


# ---------------------------------------------------------------- list_codebases

def test_list_codebases_ok_and_counts(two_codebases):
    rows = {r["id"]: r for r in list_codebases_impl()}
    assert set(rows) == {"atlas@1.0", "ma5@1.1"}
    atlas = rows["atlas@1.0"]
    assert atlas["ok"] is True
    assert atlas["n_files"] == 2
    assert atlas["n_symbols"] == 4
    assert atlas["name"] == "atlas" and atlas["version"] == "1.0"
    assert atlas["path"] == str(two_codebases[0].path)
    assert atlas["git_head"] is None
    assert atlas["stale"] is False
    assert rows["ma5@1.1"]["n_symbols"] == 1


def test_list_codebases_missing_path_and_missing_index(env):
    ghost = make_codebase(env, "ghost", "1.0", ATLAS_FILES)
    registry.add_entry(ghost)
    shutil.rmtree(ghost.path)  # registered checkout deleted, never indexed
    bare = make_codebase(env, "bare", "1.0", MA5_FILES)  # no index ever written
    registry.add_entry(bare)
    rows = {r["id"]: r for r in list_codebases_impl()}
    assert rows["ghost@1.0"]["ok"] is False
    assert rows["ghost@1.0"]["n_files"] == 0
    assert rows["ghost@1.0"]["n_symbols"] == 0
    assert rows["ghost@1.0"]["stale"] is False
    assert rows["bare@1.0"]["ok"] is False
    assert rows["bare@1.0"]["n_symbols"] == 0


def test_list_codebases_stale(env):
    entry = make_codebase(env, "repo", "1.0", ATLAS_FILES)
    registry.add_entry(entry)
    head = _git_head_of(Path(entry.path))
    write_index(entry, ATLAS_SYMBOLS, git_head=head)
    assert list_codebases_impl()[0]["stale"] is False
    write_index(entry, ATLAS_SYMBOLS, git_head="b" * 40)
    row = list_codebases_impl()[0]
    assert row["stale"] is True
    assert row["git_head"] == "b" * 40
    # no git repo at all -> live head unavailable -> never stale
    entry2 = make_codebase(env, "norepo", "1.0", ATLAS_FILES)
    registry.add_entry(entry2)
    write_index(entry2, ATLAS_SYMBOLS, git_head="c" * 40)
    by_id = {r["id"]: r for r in list_codebases_impl()}
    assert by_id["norepo@1.0"]["stale"] is False


# ------------------------------------------------------------------- search_code

def test_search_hit_shape(two_codebases):
    hits = search_code_impl(r"def \w+\(self", codebase="atlas")
    assert len(hits) == 2
    for hit in hits:
        assert set(hit) == {"codebase", "path", "line_no", "text"}
        assert hit["codebase"] == "atlas@1.0"
        assert Path(hit["path"]).is_absolute()
        assert isinstance(hit["line_no"], int)
    assert hits[0]["text"].endswith("def pt(self, p):")
    assert hits[0]["line_no"] == 4


def test_search_regex_alternation_and_selector(two_codebases):
    atlas, _ = two_codebases
    hits = search_code_impl("rapidity|analyze", codebase="ma5")
    assert [h["line_no"] for h in hits] == [1]
    assert all(h["codebase"] == "ma5@1.1" for h in hits)
    hits = search_code_impl("rapidity|analyze", codebase="atlas")
    assert [h["line_no"] for h in hits] == [7]
    # bare name resolves to latest version
    hits = search_code_impl("rapidity|analyze", codebase="ma5@1.1")
    assert hits[0]["path"].startswith(str(Path(atlas.path).parent / "ma5"))


def test_search_across_codebases_labeled(two_codebases):
    hits = search_code_impl("return")
    labels = {h["codebase"] for h in hits}
    assert labels == {"atlas@1.0", "ma5@1.1"}


def test_search_glob(two_codebases):
    hits = search_code_impl("class", glob="*.h")
    assert len(hits) == 1
    assert hits[0]["path"].endswith("util/helpers.h")


def test_search_missing_path_codebase_skipped(two_codebases):
    _, ma5 = two_codebases
    shutil.rmtree(ma5.path)
    hits = search_code_impl("return")  # must not raise on the gone checkout
    assert {h["codebase"] for h in hits} == {"atlas@1.0"}


def test_search_max_results(two_codebases):
    assert len(search_code_impl("return", max_results=2)) == 2


def test_search_bad_regex_raises(two_codebases):
    with pytest.raises(ValueError):
        search_code_impl("[")


def test_search_query_never_parsed_as_rg_options(two_codebases):
    # an rg-looking query is a regex, not an option: no raise, and no pattern
    # file is read (the -e form pins it as the pattern)
    assert search_code_impl("--hostname-bin=/bin/true") == []
    assert search_code_impl("-f/etc/hostname") == []
    assert search_code_impl("-f/no/such/pattern/file") == []


# ------------------------------------------------------------------ find_symbol

def test_find_symbol_exact(two_codebases):
    hits = find_symbol_impl("Kinematics", codebase="atlas")
    assert len(hits) == 1
    hit = hits[0]
    assert set(hit) == {"codebase", "name", "kind", "path", "line",
                        "language", "signature"}
    assert hit["codebase"] == "atlas@1.0"
    assert hit["kind"] == "class"
    assert hit["path"] == str(Path(two_codebases[0].path) / "physics/kine.py")
    assert hit["line"] == 3
    assert hit["language"] == "Python"


def test_find_symbol_substring_when_no_exact(two_codebases):
    hits = find_symbol_impl("Kinem", codebase="atlas")
    assert [h["name"] for h in hits] == ["Kinematics"]
    hits = find_symbol_impl("rapid", codebase="atlas")
    assert [h["name"] for h in hits] == ["rapidity"]
    # exact wins over substring: "pt" must not return rapidity etc.
    hits = find_symbol_impl("pt", codebase="atlas")
    assert [h["name"] for h in hits] == ["pt"]


def test_find_symbol_kind_filter(two_codebases):
    hits = find_symbol_impl("Helper", codebase="atlas", kind="class")
    assert [h["name"] for h in hits] == ["Helper"]
    # indexed codebase + kind filter with no match -> [], NOT rg fallback
    assert find_symbol_impl("Helper", codebase="atlas", kind="function") == []


def test_find_symbol_fallback_without_index(env):
    entry = make_codebase(env, "raw", "1.0", MA5_FILES)
    registry.add_entry(entry)  # no index.db at all
    hits = find_symbol_impl("analyze", codebase="raw")
    assert len(hits) == 1
    hit = hits[0]
    assert set(hit) == {"codebase", "path", "line_no", "text"}
    assert hit["codebase"] == "raw@1.0"
    assert hit["line_no"] == 1
    assert "def analyze" in hit["text"]
    # word search: "total" must not match the substring inside... it exists,
    # but "tota" (partial word) must not match at all
    assert find_symbol_impl("tota", codebase="raw") == []


def test_find_symbol_fallback_empty_symbols_table(env):
    entry = make_codebase(env, "empty", "1.0", MA5_FILES)
    registry.add_entry(entry)
    write_index(entry, [])  # index.db exists but n_symbols == 0
    hits = find_symbol_impl("analyze", codebase="empty")
    assert len(hits) == 1
    assert "line_no" in hits[0]


def test_find_symbol_no_match_with_index(two_codebases):
    assert find_symbol_impl("zzz_no_such_symbol") == []


# -------------------------------------------------------------------- read_file

def test_read_file_relative_with_offset_limit(two_codebases):
    out = read_file_impl("physics/kine.py", offset=4, limit=2)
    assert set(out) == {"codebase", "rel_path", "offset", "total_lines", "content"}
    assert out["codebase"] == "atlas@1.0"
    assert out["rel_path"] == "physics/kine.py"
    assert out["offset"] == 4
    assert out["total_lines"] == 8
    assert out["content"] == [
        "4:     def pt(self, p):",
        "5:         return math.hypot(p[0], p[1])",
    ]


def test_read_file_full_and_absolute(two_codebases):
    atlas, ma5 = two_codebases
    out = read_file_impl("sample.py")
    assert out["codebase"] == "ma5@1.1"
    assert out["content"][0] == "1: def analyze(events):"
    assert len(out["content"]) == out["total_lines"] == 5
    # absolute path, same result
    abs_out = read_file_impl(str(Path(atlas.path) / "physics/kine.py"))
    assert abs_out["rel_path"] == "physics/kine.py"
    assert abs_out["content"][0] == "1: import math"


def test_read_file_limit_clamped_to_1000(two_codebases, tmp_path):
    big = tmp_path / "ma5" / "big.py"
    big.write_text("\n".join(f"line {i}" for i in range(1, 1101)) + "\n")
    out = read_file_impl("big.py", limit=5000)
    assert len(out["content"]) == 1000
    assert out["total_lines"] == 1100
    assert out["content"][-1] == "1000: line 1000"


def test_read_file_traversal_rejected(two_codebases, tmp_path):
    (tmp_path / "secret.txt").write_text("nope")
    with pytest.raises(ValueError):
        read_file_impl("../secret.txt")
    with pytest.raises(ValueError):
        read_file_impl(str(tmp_path / "secret.txt"))  # absolute, outside roots
    with pytest.raises(ValueError):
        read_file_impl("../../etc/passwd")


def test_read_file_missing(two_codebases):
    with pytest.raises(FileNotFoundError):
        read_file_impl("physics/nope.py")  # relative, inside atlas root
    with pytest.raises(FileNotFoundError):
        read_file_impl(str(Path(two_codebases[0].path) / "missing.cxx"))


# --------------------------------------------------------------- MCP server wiring

def test_create_mcp_server_registers_ten_tools():
    srv = create_mcp_server()
    tools = {t.name: t for t in srv._tool_manager.list_tools()}
    assert set(tools) == {"list_codebases", "search_code", "find_symbol",
                          "read_file", "outline", "call_graph", "config_keys",
                          "data_files", "index_codebase", "fetch_codebase"}
    for tool in tools.values():
        assert tool.description, f"missing LLM-facing description on {tool.name}"
    assert "regex" in tools["search_code"].description.lower()
    assert "example" in tools["read_file"].description.lower()
    # contract docstrings for the two D4 tools
    assert "No network" in tools["index_codebase"].description
    assert "prefer fetch_codebase" in tools["index_codebase"].description
    assert "no arbitrary URLs" in tools["fetch_codebase"].description
    # discoverability hint appended to every pre-existing tool docstring
    hint = "list_codebases first; selectors are 'name' (latest) or 'name@version'"
    for name in ("list_codebases", "search_code", "find_symbol", "read_file"):
        assert hint in tools[name].description, f"hint missing on {name}"
    # the MCP wrapper must expose read_file's context-window parameters
    props = tools["read_file"].parameters["properties"]
    assert {"center", "before", "after"} <= set(props)


def test_read_file_context_window(two_codebases):
    out = read_file_impl("physics/kine.py", center=4, before=1, after=1)
    assert out["offset"] == 3
    assert [l.split(":")[0] for l in out["content"]] == ["3", "4", "5"]


def test_read_file_context_clamps_low(two_codebases):
    out = read_file_impl("physics/kine.py", center=1, before=5, after=2)
    assert out["offset"] == 1
    assert len(out["content"]) <= 8


# -------------------------------------------------------------- index_codebase (D4)

def test_index_codebase_real_ctags(env):
    src = env / "mysrc"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "mod.py").write_text(
        "class Collider:\n"
        "    def run(self):\n"
        "        return 42\n"
    )
    (src / "README").write_text("docs\n")

    out = index_codebase_impl(str(src), "mysrc", "0.1")
    assert set(out) == {"codebase", "path", "n_files", "n_symbols",
                        "ctags_used", "git_head"}
    assert out["codebase"] == "mysrc@0.1"
    assert out["path"] == str(src)
    assert out["n_files"] == 2
    assert out["n_symbols"] >= 1        # ctags present in this env
    assert out["ctags_used"] is True
    assert out["git_head"] is None      # not a git repo

    entries = registry.load_registry()
    assert [e.id for e in entries] == ["mysrc@0.1"]
    assert entries[0].path == str(src)
    cache = Path(registry.default_cache_root())
    assert (cache / "mysrc-0.1" / "index.db").is_file()
    # indexed through the real pipeline: symbol is findable like any other
    hits = find_symbol_impl("Collider", codebase="mysrc")
    assert [(h["name"], h["kind"]) for h in hits] == [("Collider", "class")]


def test_index_codebase_recipe_extends_exclude(env):
    src = env / "rsrc"
    src.mkdir()
    (src / "a.py").write_text("x = 1\n")
    index_codebase_impl(str(src), "rsrc", "1.0",
                        recipe="delphes", exclude=["extra*"])
    [entry] = registry.load_registry()
    assert entry.exclude == RECIPES["delphes"] + ["extra*"]


def test_index_codebase_duplicate_refused_mentions_reindex(env):
    src = env / "dsrc"
    src.mkdir()
    (src / "a.py").write_text("x = 1\n")
    index_codebase_impl(str(src), "dup", "1.0")
    with pytest.raises(ValueError, match=r"already registered: dup@1.0.*reindex"):
        index_codebase_impl(str(src), "dup", "1.0")
    assert len(registry.load_registry()) == 1


def test_index_codebase_unknown_recipe_and_missing_dir(env, tmp_path):
    with pytest.raises(ValueError, match="unknown recipe"):
        index_codebase_impl(str(tmp_path), "x", "1", recipe="nonexistent")
    with pytest.raises(FileNotFoundError, match="not a directory"):
        index_codebase_impl(str(tmp_path / "gone"), "x", "1")
    assert registry.load_registry() == []


# -------------------------------------------------------------- fetch_codebase (D4)

def make_git_repo_with_tags(path: Path, tags: list[str]) -> Path:
    """Offline clone source: tiny repo, one commit, tagged per arg."""
    path.mkdir(parents=True)
    (path / "core.py").write_text("def ignite():\n    pass\n")
    def git(*args):
        subprocess.run(["git", "-C", str(path), *args], check=True,
                       capture_output=True)
    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    for tag in tags:
        git("tag", tag)
    return path


@pytest.fixture
def catalog_env(env, monkeypatch):
    """Fixture catalog whose git url is a file:// repo; HEP_INDEX_ROOT set."""
    repo = make_git_repo_with_tags(env / "upstream", ["v1.0", "v2.0"])
    cat = env / "catalog.toml"
    cat.write_text(
        "[toygit]\n"
        'type = "git"\n'
        f'url = "{repo.as_uri()}"\n'
        'versions = ["v1.0", "v2.0"]\n'
        'recipe = "delphes"\n'
        'notes = "offline fixture"\n')
    monkeypatch.setenv("HEP_INDEX_CATALOG", str(cat))
    monkeypatch.setenv("HEP_INDEX_ROOT", str(env / "root"))
    return env


def test_fetch_codebase_end_to_end_latest_version(catalog_env):
    out = fetch_codebase_impl("toygit")  # version omitted -> catalog latest
    assert set(out) == {"codebase", "path", "n_files", "n_symbols",
                        "ctags_used", "git_head"}
    assert out["codebase"] == "toygit@v2.0"
    assert out["path"] == str(Path(os.environ["HEP_INDEX_ROOT"]) / "toygit-v2.0")
    assert out["n_files"] == 1          # core.py (.git excluded)
    assert out["n_symbols"] >= 1
    assert out["ctags_used"] is True
    assert out["git_head"]
    [entry] = registry.load_registry()
    assert entry.exclude == RECIPES["delphes"]   # recipe from catalog entry
    assert (Path(registry.default_cache_root()) / "toygit-v2.0"
            / "index.db").is_file()


def test_fetch_codebase_explicit_version_and_custom_root(catalog_env, tmp_path):
    out = fetch_codebase_impl("toygit", version="v1.0",
                              root=str(tmp_path / "custom"))
    assert out["codebase"] == "toygit@v1.0"
    assert out["path"] == str(tmp_path / "custom" / "toygit-v1.0")
    assert (tmp_path / "custom" / "toygit-v1.0" / "core.py").is_file()


def test_fetch_codebase_not_in_catalog(catalog_env):
    with pytest.raises(ValueError,
                       match="not in catalog: ghost.*CLI add for local paths"):
        fetch_codebase_impl("ghost")


def test_fetch_codebase_bad_version(catalog_env):
    with pytest.raises(ValueError, match="unknown version: toygit@9.9"):
        fetch_codebase_impl("toygit", version="9.9")


# ------------------------------------------------------- python ast layer (outline)

PYPKG_FILES = {
    "src/pkg/__init__.py": '"""Toy package."""\nfrom .core import Scan\n',
    "src/pkg/core.py": (
        '"""Core module.\n\n-----\nBanner."""\n'
        "class Scan:\n"
        '    """Parent scan class."""\n'
        "    def __init__(self, inputs, log=None):\n"
        "        self.inputs = inputs\n"
        "    def run(self, n: int = 10) -> None:\n"
        '        """Run the scan."""\n'
        "    def _private(self): ...\n"
    ),
    "src/pkg/scans/__init__.py": "",
    "src/pkg/scans/mcmc.py": (
        "from pkg.core import Scan\n"
        "__meta__ = {'name': 'MCMC', 'settings': {'Points': 'Int',"
        " 'Valid Points': 'Int', 'Merge Results': 'Boolean'}}\n"
        "class NewScan(Scan):\n"
        '    """MCMC scan."""\n'
        "    def run(self): ...\n"
    ),
    "src/pkg/scans/grid.py": (
        "from ..core import Scan\n"
        "class NewScan(Scan):\n"
        '    """Grid scan."""\n'
        "    def initialise(self):\n"
        "        n = self.inputs['Setup']['Points']\n"
        "        r = self.inputs['Setup'].get('Resume', 'False')\n"
        "        if 'Seed' in self.inputs['Setup']:\n"
        "            pass\n"
        "        for c in self.inputs['Codes']:\n"
        "            self.inputs['Codes'][c]['Run'] = 'True'\n"
    ),
    "src/pkg/tool.py": (
        "class Tool:\n"
        "    def __init__(self, settings):\n"
        "        self.settings = settings\n"
        "        cmd = self.settings['Command']\n"
        "        lst = self.settings['Higgs']\n"
    ),
    "examples/mcmc.json": (
        '{"Setup": {"Points": 100, "Resume": "True", "Typo Key": 1},'
        ' "Codes": {"SPheno": {"Run": "True", "Command": "SPheno",'
        ' "Unused": 2, "Higgs": [1, 2]}},'
        ' "Plotting": {"Plots": []}}'
    ),
    "examples/grid.yaml": "Setup:\n  Points: 5\nCodes:\n  SModelS:\n    Run: 'False'\n",
}


@pytest.fixture
def pypkg(env):
    src = env / "pypkg"
    for rel, text in PYPKG_FILES.items():
        f = src / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    index_codebase_impl(str(src), "pypkg", "1.0")
    return src


def test_find_symbol_python_enriched(pypkg):
    hits = find_symbol_impl("NewScan", codebase="pypkg")
    assert {h["qualname"] for h in hits} == {"pkg.scans.mcmc.NewScan",
                                             "pkg.scans.grid.NewScan"}
    mcmc = next(h for h in hits if h["qualname"].endswith("mcmc.NewScan"))
    assert mcmc["kind"] == "class"
    assert mcmc["bases"] == ["Scan"]
    assert mcmc["summary"] == "MCMC scan."
    assert mcmc["path"] == str(pypkg / "src/pkg/scans/mcmc.py")
    run = find_symbol_impl("run", codebase="pypkg", kind="method")
    assert "pkg.core.Scan.run" in {h["qualname"] for h in run}


def test_find_symbol_dotted(pypkg):
    [hit] = find_symbol_impl("pkg.core.Scan.run", codebase="pypkg")
    assert hit["signature"] == "(self, n: int = 10) -> None"
    assert hit["summary"] == "Run the scan."
    # re-export resolution: pkg.Scan -> pkg.core.Scan
    [hit] = find_symbol_impl("pkg.Scan", codebase="pypkg")
    assert hit["qualname"] == "pkg.core.Scan"
    assert hit["signature"] == "(inputs, log=None)"
    # dotted suffix
    [hit] = find_symbol_impl("mcmc.NewScan", codebase="pypkg")
    assert hit["qualname"] == "pkg.scans.mcmc.NewScan"
    # literal value surfaced
    [meta] = find_symbol_impl("pkg.scans.mcmc.__meta__", codebase="pypkg")
    assert "'Merge Results': 'Boolean'" in meta["value"]


def test_dotted_lookup_star_import_cycle_terminates(env, monkeypatch):
    # Six star-imports that each star-import back: the re-export walk revisits
    # pkg.no_such_name along every path, and the depth cap bounds the rest.
    src = env / "starpkg"
    (src / "pkg").mkdir(parents=True)
    mods = [f"m{i}" for i in range(6)]
    (src / "pkg" / "__init__.py").write_text(
        "".join(f"from .{m} import *\n" for m in mods))
    for m in mods:
        (src / "pkg" / f"{m}.py").write_text("from pkg import *\n")
    index_codebase_impl(str(src), "star", "1.0")
    lookups: list[str] = []
    real = server._api_by_qualname
    monkeypatch.setattr(server, "_api_by_qualname",
                        lambda con, q, kind=None: (lookups.append(q),
                                                   real(con, q, kind))[1])
    assert find_symbol_impl("pkg.no_such_name", codebase="star") == []
    # bounded by the depth-6 cap (6^6 paths), not unbounded recursion
    assert len(lookups) < 6 ** 7


def test_outline_package(pypkg):
    [o] = outline_impl("pkg", codebase="pypkg")
    assert o["kind"] == "module"
    assert o["doc"] == "Toy package."
    assert [s["module"] for s in o["submodules"]] == ["pkg.core", "pkg.scans",
                                                      "pkg.tool"]
    core = next(s for s in o["submodules"] if s["module"] == "pkg.core")
    assert core["summary"] == "Core module."          # banner rule dropped
    [rex] = o["reexports"]
    assert rex["name"] == "Scan" and rex["target"] == "pkg.core.Scan"
    assert rex["kind"] == "class" and rex["signature"] == "(inputs, log=None)"


def test_outline_class_members_and_subclasses(pypkg):
    [o] = outline_impl("pkg.core.Scan", codebase="pypkg")
    assert o["kind"] == "class"
    assert o["signature"] == "(inputs, log=None)"
    names = [m["name"] for m in o["members"]]
    assert names == ["__init__", "inputs", "run"]     # by line; _private hidden
    inputs = o["members"][1]
    assert inputs["kind"] == "instance_attribute"
    assert inputs["signature"] == " = inputs"
    assert inputs["summary"] == "Set in __init__()."
    assert {s["qualname"] for s in o["subclasses"]} == {
        "pkg.scans.mcmc.NewScan", "pkg.scans.grid.NewScan"}
    [o] = outline_impl("pkg.core.Scan", codebase="pypkg", include_private=True)
    assert "_private" in [m["name"] for m in o["members"]]
    # re-exported name and dotted suffix resolve to the same class
    assert outline_impl("pkg.Scan", codebase="pypkg")[0]["qualname"] == \
        "pkg.core.Scan"
    assert outline_impl("mcmc.NewScan")[0]["bases"] == ["Scan"]


def test_outline_module_by_path_and_value(pypkg):
    [o] = outline_impl("src/pkg/scans/mcmc.py", codebase="pypkg")
    assert o["qualname"] == "pkg.scans.mcmc"
    assert "pkg.core.Scan" in o["imports"]
    meta = next(m for m in o["members"] if m["name"] == "__meta__")
    assert "'Valid Points': 'Int'" in meta["value"]
    assert "reexports" not in o                       # plain module imports


def test_outline_unknown_and_legacy_index(pypkg, two_codebases):
    with pytest.raises(KeyError):
        outline_impl("pkg.nope", codebase="pypkg")
    # atlas index was written without py_api tables -> skipped, not crashed
    with pytest.raises(KeyError):
        outline_impl("Kinematics", codebase="atlas")


def test_config_keys(pypkg):
    [top] = [r for r in config_keys_impl(codebase="pypkg") if r["base"] == "inputs"]
    assert top["written_as"] == ["self.inputs"]
    assert top["n_uses"] == 5
    rows = config_keys_impl("self.inputs", codebase="pypkg", prefix="Setup",
                            include_data=False)
    by = {"/".join(r["keys"]): r for r in rows}
    assert set(by) == {"Setup/Points", "Setup/Resume", "Setup/Seed"}
    assert by["Setup/Resume"]["accesses"] == {"get": 1}
    assert by["Setup/Resume"]["defaults"] == ["'False'"]
    assert by["Setup/Seed"]["accesses"] == {"in": 1}
    loc = by["Setup/Points"]["locations"][0]
    assert loc.endswith("grid.py:5 (pkg.scans.grid.NewScan.initialise)")
    [codes] = config_keys_impl("inputs", codebase="pypkg", prefix="Codes/*",
                               include_data=False)
    assert codes["keys"] == ["Codes", "*", "Run"]
    assert codes["accesses"] == {"set": 1}
    assert config_keys_impl("nope", codebase="pypkg") == []


def test_config_keys_merged_with_data(pypkg):
    rows = config_keys_impl("inputs", codebase="pypkg", prefix="Setup")
    by = {"/".join(r["keys"]): r for r in rows}
    assert by["Setup/Points"]["status"] == "read+set"
    assert by["Setup/Points"]["data"]["n_files"] == 2
    assert by["Setup/Points"]["data"]["values"] == ["5", "100"]
    assert by["Setup/Seed"]["status"] == "read_only"
    assert by["Setup/Typo Key"]["status"] == "set_only"
    assert by["Setup/Typo Key"]["n_uses"] == 0
    assert by["Setup"]["status"] == "read+set"     # container read beneath
    # Plotting is never read via inputs -> its data is not merged at all
    assert not any(r["keys"][0] == "Plotting" for r in
                   config_keys_impl("inputs", codebase="pypkg"))
    # wildcard code path Codes/*/Run covers concrete data rows
    codes = {"/".join(r["keys"]): r for r in
             config_keys_impl("inputs", codebase="pypkg", prefix="Codes")}
    assert codes["Codes/*/Run"]["status"] == "pattern"
    assert codes["Codes/SPheno/Run"]["read_via"] == ["Codes", "*", "Run"]
    assert codes["Codes/SPheno/Run"]["status"] == "read+set"
    # iterating cfg["Codes"] does not cover keys inside each entry
    assert codes["Codes/SPheno/Unused"]["status"] == "set_only"
    # code-only view
    assert all("data" not in r for r in config_keys_impl(
        "inputs", codebase="pypkg", include_data=False))


def test_config_keys_data_prefix_mount(pypkg):
    by = {"/".join(r["keys"]): r for r in config_keys_impl(
        "settings", codebase="pypkg", data_prefix="Codes/*")}
    assert by["Command"]["status"] == "read+set"
    assert by["Command"]["data"]["values"] == ['"SPheno"']
    assert by["Higgs/*"]["status"] == "read+set"     # inside a read container
    assert by["Unused"]["status"] == "set_only"
    # a variable-key read (Codes/*) consumes the nested entry
    nested = {"/".join(r["keys"]): r for r in config_keys_impl(
        "inputs", codebase="pypkg", prefix="Codes/SPheno")}
    assert "Codes/SPheno/Higgs/*" in nested


def test_config_keys_data_only_schema(pypkg):
    rows = config_keys_impl(codebase="pypkg", prefix="Plotting")
    assert [r["keys"] for r in rows] == [["Plotting"], ["Plotting", "Plots"]]
    assert rows[1]["data"]["values"] == ["[0 items]"]


def test_data_files_listing(pypkg):
    files = data_files_impl(codebase="pypkg")
    assert [f["rel_path"] for f in files] == ["examples/grid.yaml",
                                              "examples/mcmc.json"]
    assert files[1]["top_keys"] == ["Setup", "Codes", "Plotting"]
    assert all(f["stored"] for f in files)
    assert [f["rel_path"] for f in data_files_impl(
        codebase="pypkg", has_key="Codes/SModelS")] == ["examples/grid.yaml"]
    assert len(data_files_impl(codebase="pypkg", has_key="Codes/*/Run")) == 2
    assert [f["format"] for f in data_files_impl(
        codebase="pypkg", glob="*.json")] == ["json"]


def test_read_file_falls_back_to_index_without_checkout(pypkg):
    on_disk = read_file_impl("examples/mcmc.json")
    assert "source" not in on_disk
    shutil.rmtree(pypkg)                             # checkout gone
    out = read_file_impl("examples/mcmc.json")
    assert out["source"] == "index"
    assert out["content"] == on_disk["content"]
    out = read_file_impl(str(pypkg / "examples/grid.yaml"), center=2,
                         before=0, after=0)
    assert out["content"] == ["2:   Points: 5"]
    with pytest.raises((FileNotFoundError, ValueError)):
        read_file_impl("src/pkg/core.py")            # source is not stored


def test_stored_file_symlink_escape_serves_nothing(env, tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text('{"Setup": {"Points": 4}}')
    src = env / "linkpkg"
    src.mkdir()
    (src / "real.py").write_text("def f():\n    pass\n")
    (src / "leak.json").symlink_to(outside)
    index_codebase_impl(str(src), "link", "1.0")
    with pytest.raises((FileNotFoundError, ValueError)):
        read_file_impl("leak.json")   # symlink resolves outside every root


CALLS_FILES = {
    "src/app/__init__.py": "from .runner import Runner\n",
    "src/app/runner.py": (
        "class Runner:\n"
        "    def run_batch(self, pts):\n"
        "        return [p for p in pts]\n"
    ),
    "src/app/base.py": (
        "from app import Runner\n"
        "import numpy as np\n"
        "class Base:\n"
        "    def __init__(self):\n"
        "        self.RunManager = Runner()\n"
        "    def make_dirs(self):\n"
        "        np.zeros(2)\n"
    ),
    "src/app/scan.py": (
        "from .base import Base\n"
        "class NewScan(Base):\n"
        "    def run(self):\n"
        "        self.make_dirs()\n"
        "        self.RunManager.run_batch([1])\n"
        "        self.other.run_batch([2])\n"
    ),
}


@pytest.fixture
def callpkg(env):
    src = env / "callpkg"
    for rel, text in CALLS_FILES.items():
        f = src / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    index_codebase_impl(str(src), "callpkg", "1.0")
    return src


def test_call_graph_resolution(callpkg):
    [run] = call_graph_impl("app.scan.NewScan.run", codebase="callpkg",
                            direction="calls")
    targets = {c["callee"]: c.get("target") for c in run["calls"]}
    assert targets["self.make_dirs"] == "app.base.Base.make_dirs"  # inherited
    # typed via Base.__init__'s self.RunManager = Runner(), re-exported by app
    assert targets["self.RunManager.run_batch"] == "app.runner.Runner.run_batch"
    assert targets["self.other.run_batch"] is None
    assert "called_by" not in run
    [init] = call_graph_impl("app.base.Base.__init__", direction="calls")
    assert init["calls"][0]["target"] == "app.runner.Runner"   # constructor
    [mk] = call_graph_impl("app.base.Base.make_dirs", direction="calls")
    assert mk["calls"][0]["target"] == "numpy.zeros"


def test_call_graph_callers(callpkg):
    [rb] = call_graph_impl("Runner.run_batch", codebase="callpkg",
                           direction="callers")
    assert [c["caller"] for c in rb["called_by"]] == ["app.scan.NewScan.run"]
    assert rb["n_possible_callers"] == 1                # self.other.run_batch
    assert rb["possible_callers"][0]["callee"] == "self.other.run_batch"
    [runner] = call_graph_impl("app.Runner", direction="callers")
    assert [c["caller"] for c in runner["called_by"]] == ["app.base.Base.__init__"]
    assert len(call_graph_impl("run_batch", codebase="callpkg")) == 1  # bare name
    with pytest.raises(KeyError):
        call_graph_impl("nope", codebase="callpkg")
    with pytest.raises(ValueError):
        call_graph_impl("run", direction="sideways")


def test_call_graph_negative_max_results_clamped(env):
    # LIMIT -1 means "unlimited" in sqlite; a negative max must fall back to 50
    src = env / "callmany"
    src.mkdir()
    (src / "m.py").write_text(
        "".join(f"def f{i}():\n    target()\n" for i in range(60))
        + "def target():\n    pass\n")
    index_codebase_impl(str(src), "callmany", "1.0")
    [res] = call_graph_impl("target", codebase="callmany",
                            direction="callers", max_results=-1)
    assert 0 < len(res["called_by"]) <= 50
