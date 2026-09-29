"""Tests for fetch.py (CONTRACT §D3) — all offline: file:// URLs, local tarballs."""
import re
import subprocess
import tarfile
from pathlib import Path

import pytest

from hep_index import fetch, registry
from hep_index.recipes import RECIPES


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HEP_INDEX_CONFIG", str(tmp_path / "reg.toml"))
    monkeypatch.setenv("HEP_INDEX_CACHE", str(tmp_path / "cache"))
    return tmp_path


def make_git_repo(tmp_path: Path) -> Path:
    """Tiny repo with one commit tagged v1.0; clone source for file:// tests."""
    repo = tmp_path / "srcrepo"
    repo.mkdir()
    (repo / "core.py").write_text("def alpha():\n    pass\n")
    (repo / "notes.txt").write_text("hello\n")
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True)
    git("init", "-q", "-b", "main")
    git("add", "-A")
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t",
                    "-c", "user.email=t@t", "commit", "-qm", "init"],
                   check=True, capture_output=True)
    git("tag", "v1.0")
    return repo


def make_tarball(tmp_path: Path) -> Path:
    """tar.gz with a single top-level dir toy-pkg-1.0/ holding one source file."""
    top = tmp_path / "toy-pkg-1.0"
    top.mkdir()
    (top / "sim.f90").write_text("program simulate\nend program\n")
    tar_path = tmp_path / "toy-pkg-1.0.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(top, arcname="toy-pkg-1.0")
    return tar_path


def test_fetch_git_from_file_url(env):
    repo = make_git_repo(env)
    dest = env / "out" / "toy-v1.0"
    got = fetch.fetch_source(kind="git", url=repo.as_uri(), version="v1.0",
                             dest=dest)
    assert got == dest
    assert (dest / "core.py").is_file()
    assert (dest / ".git").is_dir()
    head = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout
    assert head.strip()


def test_fetch_git_never_prompts_env(env, monkeypatch):
    """The credential-popup prevention env is non-negotiable (CONTRACT)."""
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(fetch.subprocess, "run", fake_run)
    fetch.fetch_source(kind="git", url="https://example.invalid/x", version="v1",
                       dest=env / "d")
    assert seen["cmd"][:6] == ["git", "clone", "--depth", "1",
                               "--branch", "v1"]
    env_vars = seen["kwargs"]["env"]
    assert env_vars["GIT_ASKPASS"] == "/bin/true"
    assert env_vars["GIT_TERMINAL_PROMPT"] == "0"
    assert env_vars["GIT_SSH_COMMAND"] == "ssh -o BatchMode=yes"
    assert env_vars["PATH"]  # rest of os.environ preserved


def test_fetch_tarball_plain_local_path(env):
    tar_path = make_tarball(env)
    dest = env / "out" / "toy-pkg-1.0"
    fetch.fetch_source(kind="tarball", url=str(tar_path), version="1.0",
                       dest=dest, extract_root="toy-pkg-1.0")
    assert (dest / "sim.f90").is_file()
    assert not (dest / "toy-pkg-1.0").exists()  # top dir WAS dest, not nested


def test_fetch_tarball_file_url_auto_top_dir(env):
    tar_path = make_tarball(env)
    dest = env / "out" / "toy-pkg-1.0"
    fetch.fetch_source(kind="tarball", url=tar_path.as_uri(), version="1.0",
                       dest=dest, extract_root=None)
    assert (dest / "sim.f90").is_file()


def test_fetch_git_failure_removes_dest(env):
    repo = make_git_repo(env)
    dest = env / "out" / "toy-v9.9"
    with pytest.raises(RuntimeError, match="fetch failed"):
        fetch.fetch_source(kind="git", url=repo.as_uri(),
                           version="no-such-tag", dest=dest)
    assert not dest.exists()


def test_fetch_tarball_missing_file_fails_clean(env):
    dest = env / "out" / "x"
    with pytest.raises(RuntimeError, match="fetch failed"):
        fetch.fetch_source(kind="tarball", url=str(env / "nope.tar.gz"),
                           version="1", dest=dest, extract_root="x")
    assert not dest.exists()


def test_fetch_unknown_kind(env):
    with pytest.raises(ValueError, match="unknown fetch kind"):
        fetch.fetch_source(kind="ftp", url="x", version="1", dest=env / "d")


def test_fetch_source_refuses_nonempty_dest(env):
    dest = env / "d"
    dest.mkdir()
    (dest / "keep.txt").write_text("x")
    with pytest.raises(ValueError, match="not empty"):
        fetch.fetch_source(kind="git", url="https://example.invalid/x",
                           version="v1", dest=dest)
    assert (dest / "keep.txt").is_file()


def test_fetch_and_register_git_end_to_end(env):
    repo = make_git_repo(env)
    root = env / "codebases"
    out = fetch.fetch_and_register(
        name="toy", version="v1.0", kind="git", url=repo.as_uri(),
        extract_root=None, root=root, recipe="delphes", exclude=["extra*"])

    assert out["codebase"] == "toy@v1.0"
    assert out["path"] == str(root / "toy-v1.0")
    assert out["n_files"] == 2          # core.py + notes.txt (.git excluded)
    assert out["n_symbols"] >= 1        # ctags present in this env
    assert out["ctags_used"] is True
    assert out["git_head"]

    entries = registry.load_registry()
    assert len(entries) == 1
    assert entries[0].id == "toy@v1.0"
    assert entries[0].exclude == RECIPES["delphes"] + ["extra*"]

    cache = Path(registry.default_cache_root())
    assert (cache / "toy-v1.0" / "index.db").is_file()
    assert (cache / "toy-v1.0" / "meta.json").is_file()


def test_fetch_and_register_tarball_end_to_end(env):
    tar_path = make_tarball(env)
    out = fetch.fetch_and_register(
        name="toypkg", version="1.0", kind="tarball", url=str(tar_path),
        extract_root="toy-pkg-1.0", root=env / "codebases")
    assert out["codebase"] == "toypkg@1.0"
    assert out["n_files"] == 1
    assert out["git_head"] is None      # tarball is not a repo


def test_fetch_and_register_reuses_existing_dest(env):
    """Non-empty dest + bogus URL must succeed: fetch is skipped on reuse."""
    dest = env / "codebases" / "toy-v1.0"
    dest.mkdir(parents=True)
    (dest / "sentinel.txt").write_text("already here")
    out = fetch.fetch_and_register(
        name="toy", version="v1.0", kind="git", url="https://example.invalid/x",
        extract_root=None, root=env / "codebases")
    assert (dest / "sentinel.txt").is_file()
    assert out["n_files"] == 1
    assert out["git_head"] is None


def test_fetch_and_register_duplicate_raises(env):
    repo = make_git_repo(env)
    kwargs = dict(name="toy", version="v1.0", kind="git", url=repo.as_uri(),
                  extract_root=None, root=env / "codebases")
    fetch.fetch_and_register(**kwargs)
    with pytest.raises(ValueError, match="already registered: toy@v1.0"):
        fetch.fetch_and_register(**kwargs)
    assert len(registry.load_registry()) == 1


def test_fetch_and_register_unknown_recipe(env, capsys):
    with pytest.raises(ValueError, match="unknown recipe"):
        fetch.fetch_and_register(
            name="toy", version="v1.0", kind="git",
            url="https://example.invalid/x", extract_root=None,
            root=env / "codebases", recipe="nonexistent")
    assert registry.load_registry() == []
    assert not (env / "codebases" / "toy-v1.0").exists()


def test_no_catalog_import():
    """fetch.py is primitives-only: no catalog import, ever (CONTRACT)."""
    assert not re.search(r"^\s*(from|import)\s+.*catalog",
                         Path(fetch.__file__).read_text(), re.M)
