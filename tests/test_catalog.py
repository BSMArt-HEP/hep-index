"""Tests for the catalog module (CONTRACT.md §D2). No network."""
from pathlib import Path

import pytest

from hep_index.catalog import (CatalogEntry, default_catalog_path, latest,
                               load_catalog, render_extract_root, render_url)

EXPECTED_URLS = {
    "madgraph": "https://launchpad.net/mg5amcnlo/3.0/3.6.x/+download/MG5_aMC_v3.7.0.tar.gz",
    "madanalysis": "https://github.com/MadAnalysis/madanalysis5",
    "pythia8": "https://pythia.org/releases/pythia83/pythia8317.tgz",
    "delphes": "https://github.com/delphes/delphes",
}


@pytest.fixture
def packaged(monkeypatch):
    monkeypatch.delenv("HEP_INDEX_CATALOG", raising=False)
    return load_catalog()


def test_packaged_catalog_has_four_entries(packaged):
    assert set(packaged) == {"madgraph", "madanalysis", "pythia8", "delphes"}
    assert packaged["madgraph"].versions == ["3.7.0", "3.7.3"]
    assert packaged["madanalysis"].type == "git"
    assert packaged["pythia8"].recipe is None
    assert packaged["delphes"].notes == "plain X.Y.Z tags"


def test_default_path_env_override(tmp_path, monkeypatch):
    fake = tmp_path / "my-catalog.toml"
    fake.write_text("[x]\ntype='git'\nurl='file:///repo'\nversions=['1']\n")
    monkeypatch.setenv("HEP_INDEX_CATALOG", str(fake))
    assert default_catalog_path() == fake
    catalog = load_catalog()
    assert set(catalog) == {"x"}
    assert catalog["x"].name == "x"


def test_default_path_packaged(monkeypatch):
    monkeypatch.delenv("HEP_INDEX_CATALOG", raising=False)
    p = default_catalog_path()
    assert p.is_file()
    assert p.name == "catalog.toml"
    assert "data" in p.parts


def test_render_url_all_four_entries(packaged):
    for name, expected in EXPECTED_URLS.items():
        assert render_url(packaged[name], packaged[name].versions[0]) == expected


def test_render_url_template_fields(tmp_path):
    entry = CatalogEntry(
        name="t", type="tarball",
        url="https://x/{version}/{version_nodot}/{version_underscore}.tgz",
        versions=["3.7.0"],
    )
    assert render_url(entry, "3.7.0") == "https://x/3.7.0/370/3_7_0.tgz"


def test_render_extract_root(packaged):
    assert render_extract_root(packaged["madgraph"], "3.7.3") == "MG5_aMC_v3_7_3"
    assert render_extract_root(packaged["pythia8"], "8.3.17") == "pythia8317"
    assert render_extract_root(packaged["madanalysis"], "v1.11.1") is None
    assert render_extract_root(packaged["delphes"], "3.5.1") is None


def test_latest(packaged):
    assert latest(packaged["madgraph"]) == "3.7.3"
    assert latest(packaged["pythia8"]) == "8.3.17"


def test_unknown_version_error(packaged):
    with pytest.raises(ValueError, match="unknown version: madgraph@9.9.9"):
        render_url(packaged["madgraph"], "9.9.9")
    with pytest.raises(ValueError, match=r"available: 3\.7\.0, 3\.7\.3"):
        render_extract_root(packaged["madgraph"], "9.9.9")


def test_unknown_entry_error(packaged):
    with pytest.raises(KeyError):
        packaged["nobody"]


def test_render_url_override():
    cat = load_catalog()
    u0 = render_url(cat["madgraph"], "3.7.0")
    u3 = render_url(cat["madgraph"], "3.7.3")
    assert "/3.6.x/+download/MG5_aMC_v3.7.0.tar.gz" in u0
    assert "/3.7.x/+download/MG5_aMC_v3.7.3.tar.gz" in u3
