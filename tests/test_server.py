"""Tests for hep_index.server: impl functions + MCP tool wiring.

Fixture codebases are built directly on disk; their index.db/meta.json are
pre-created per the CONTRACT.md schema (indexer.build_index is out of scope
here). No network: rg/git run locally against tmp_path fixtures.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from hep_index import registry
from hep_index.server import (create_mcp_server, find_symbol_impl,
                              list_codebases_impl, read_file_impl,
                              search_code_impl)

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

def test_create_mcp_server_registers_four_tools():
    srv = create_mcp_server()
    tools = {t.name: t for t in srv._tool_manager.list_tools()}
    assert set(tools) == {"list_codebases", "search_code", "find_symbol",
                          "read_file"}
    for tool in tools.values():
        assert tool.description, f"missing LLM-facing description on {tool.name}"
    assert "regex" in tools["search_code"].description.lower()
    assert "example" in tools["read_file"].description.lower()


def test_read_file_context_window(two_codebases):
    out = read_file_impl("physics/kine.py", center=4, before=1, after=1)
    assert out["offset"] == 3
    assert [l.split(":")[0] for l in out["content"]] == ["3", "4", "5"]


def test_read_file_context_clamps_low(two_codebases):
    out = read_file_impl("physics/kine.py", center=1, before=5, after=2)
    assert out["offset"] == 1
    assert len(out["content"]) <= 8
