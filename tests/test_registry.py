"""Tests for the registry module."""
from pathlib import Path

import pytest

from hep_index.registry import (CodebaseEntry, add_entry, default_cache_root,
                                default_registry_path, index_dir, load_registry,
                                remove_entry, resolve)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HEP_INDEX_CONFIG", str(tmp_path / "reg.toml"))
    monkeypatch.setenv("HEP_INDEX_CACHE", str(tmp_path / "cache"))
    return tmp_path


def _entry(tmp_path, name="madanalysis", version="1.11.1"):
    p = tmp_path / name
    p.mkdir(exist_ok=True)
    return CodebaseEntry(name=name, version=version, path=str(p))


def test_roundtrip_and_defaults(env):
    e = _entry(env)
    add_entry(e)
    loaded = load_registry()
    assert len(loaded) == 1
    assert loaded[0].id == "madanalysis@1.11.1"
    assert loaded[0].added_at  # stamped automatically
    assert index_dir(loaded[0]) == Path(default_cache_root()) / "madanalysis-1.11.1"


def test_duplicate_rejected(env):
    add_entry(_entry(env))
    with pytest.raises(ValueError):
        add_entry(_entry(env))


def test_bad_path_rejected(env, tmp_path):
    with pytest.raises(FileNotFoundError):
        add_entry(CodebaseEntry(name="x", version="1", path=str(tmp_path / "nope")))


def test_resolve_semantics(env):
    add_entry(_entry(env, version="1.9"))
    add_entry(_entry(env, version="1.10"))
    add_entry(_entry(env, name="madgraph", version="3.7.0"))
    assert len(resolve(None)) == 3
    assert resolve("madanalysis@1.9") == [resolve("madanalysis@1.9")[0]]
    # bare name -> latest, numeric-aware (1.10 > 1.9, not string sort)
    assert resolve("madanalysis")[0].version == "1.10"
    with pytest.raises(KeyError):
        resolve("unknown")


def test_remove(env):
    add_entry(_entry(env, version="1.9"))
    add_entry(_entry(env, version="1.10"))
    removed = remove_entry("madanalysis", version="1.9")
    assert [e.version for e in removed] == ["1.9"]
    assert [e.version for e in load_registry()] == ["1.10"]
    removed = remove_entry("madanalysis")
    assert len(removed) == 1
    assert load_registry() == []
    with pytest.raises(KeyError):
        remove_entry("madanalysis")


def test_resolve_error_lists_available(env):
    add_entry(_entry(env, name="madanalysis", version="1.11.1"))
    add_entry(_entry(env, name="delphes", version="3.5.1"))
    # name@version branch
    with pytest.raises(KeyError, match="available:") as exc:
        resolve("madgraph@3.7.0")
    assert "not registered: 'madgraph@3.7.0'" in str(exc.value)
    assert "available: delphes@3.5.1, madanalysis@1.11.1" in str(exc.value)  # sorted
    # bare-name branch
    with pytest.raises(KeyError, match="available:") as exc:
        resolve("madgraph")
    assert "not registered: 'madgraph'" in str(exc.value)
    assert "available: delphes@3.5.1, madanalysis@1.11.1" in str(exc.value)


def test_resolve_error_empty_registry(env):
    with pytest.raises(KeyError, match=r"\(available: none\)"):
        resolve("madgraph")
