"""Tests for hep_index.datafiles (JSON/YAML/TOML key-path flattening)."""
import json

from hep_index import datafiles
from hep_index.datafiles import extract_data_file, flatten


def by_path(keys):
    return {"/".join(k.keys): k for k in keys}


def test_flatten_nested_lists_types_samples():
    data = {"Setup": {"Cores": 4, "Resume": "False", "Neurons": [50, 25]},
            "Codes": {"SPheno": {"Run": True, "Obs": [{"SLHA": ["MASS", 25]}]}}}
    keys, truncated = flatten(data)
    assert not truncated
    p = by_path(keys)
    assert p["Setup"].types == ["object"] and p["Setup"].samples == ["{3 keys}"]
    assert p["Setup/Cores"].types == ["int"] and p["Setup/Cores"].samples == ["4"]
    assert p["Setup/Resume"].samples == ['"False"']
    assert p["Setup/Neurons"].samples == ["[2 items]"]
    assert p["Setup/Neurons/*"].samples == ["50", "25"]       # merged per path
    assert p["Codes/SPheno/Run"].types == ["bool"]
    assert p["Codes/SPheno/Obs/*/SLHA/*"].types == ["str", "int"]


def test_flatten_caps_paths(monkeypatch):
    monkeypatch.setattr(datafiles, "MAX_PATHS", 3)
    keys, truncated = flatten({str(i): i for i in range(10)})
    assert len(keys) == 3 and truncated


def test_extract_formats_and_storage(tmp_path, monkeypatch):
    (tmp_path / "a.json").write_text(json.dumps({"Setup": {"Points": 10}}))
    (tmp_path / "b.yaml").write_text("Setup:\n  Points: 10\n  Tags: [x, y]\n")
    (tmp_path / "c.toml").write_text("[Setup]\nPoints = 10\n")
    (tmp_path / "bad.json").write_text("{not json")
    (tmp_path / "d.txt").write_text("{}")
    for rel, fmt in (("a.json", "json"), ("b.yaml", "yaml"), ("c.toml", "toml")):
        size = (tmp_path / rel).stat().st_size
        info = extract_data_file(tmp_path, rel, size)
        assert info.format == fmt
        assert info.top_keys == ["Setup"]
        assert "Setup/Points" in by_path(info.keys)
        assert info.content == (tmp_path / rel).read_text()
    assert "Setup/Tags/*" in by_path(
        extract_data_file(tmp_path, "b.yaml", 30).keys)
    assert extract_data_file(tmp_path, "bad.json", 9) is None
    assert extract_data_file(tmp_path, "d.txt", 2) is None
    # big files: keys kept, content not stored; huge: skipped entirely
    monkeypatch.setattr(datafiles, "MAX_STORE_BYTES", 5)
    info = extract_data_file(tmp_path, "a.json", 25)
    assert info.content is None and info.keys
    monkeypatch.setattr(datafiles, "MAX_PARSE_BYTES", 5)
    assert extract_data_file(tmp_path, "a.json", 25) is None


def test_extract_yaml_alias_cycle_returns_none(tmp_path):
    p = tmp_path / "cyc.yaml"
    p.write_text("a: &x\n  b: *x\n")
    assert extract_data_file(tmp_path, "cyc.yaml", p.stat().st_size) is None
