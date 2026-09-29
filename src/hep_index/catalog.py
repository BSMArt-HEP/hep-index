"""Curated catalog of fetchable HEP software sources (CONTRACT.md §D2).

The catalog maps name -> CatalogEntry with pinned upstream URLs. Only catalog
entries are fetchable (server.fetch_codebase / `hep-index fetch`); arbitrary
URLs are never accepted. Env override for tests:
  HEP_INDEX_CATALOG  catalog TOML path   (default: packaged data/catalog.toml)
"""
from __future__ import annotations

import importlib.resources
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CatalogEntry:
    name: str                      # e.g. "madgraph"
    type: str                      # "tarball" | "git"
    url: str                       # template URL (see _template_vars)
    versions: list[str]            # known-good versions, latest LAST
    recipe: str | None = None      # recipes.RECIPES key applied on fetch
    extract_root: str | None = None  # tarball top-level dir template (None = git)
    notes: str = ""                # why this source/version was pinned
    urls: dict[str, str] = field(default_factory=dict)
                                  # per-version URL overrides (launchpad series
                                  # paths are NOT mechanical — see madgraph)


def default_catalog_path() -> Path:
    p = os.environ.get("HEP_INDEX_CATALOG")
    if p:
        return Path(p).expanduser()
    return Path(importlib.resources.files("hep_index") / "data" / "catalog.toml")


def load_catalog(path: Path | None = None) -> dict[str, CatalogEntry]:
    """Parse the catalog TOML into entries keyed by name (KeyError on unknown name)."""
    path = path or default_catalog_path()
    data = tomllib.loads(path.read_text())
    return {name: CatalogEntry(name=name, **table) for name, table in data.items()}


def latest(entry: CatalogEntry) -> str:
    return entry.versions[-1]


def _template_vars(version: str) -> dict[str, str]:
    return {
        "version": version,                          # 3.7.0
        "version_nodot": version.replace(".", ""),   # 370
        "version_underscore": version.replace(".", "_"),  # 3_7_0
    }


def _check_version(entry: CatalogEntry, version: str) -> None:
    if version not in entry.versions:
        raise ValueError(
            f"unknown version: {entry.name}@{version} "
            f"(available: {', '.join(entry.versions)})"
        )


def render_url(entry: CatalogEntry, version: str) -> str:
    _check_version(entry, version)
    url = entry.urls.get(version, entry.url)
    return url.format(**_template_vars(version))


def render_extract_root(entry: CatalogEntry, version: str) -> str | None:
    if entry.extract_root is None:
        return None
    _check_version(entry, version)
    return entry.extract_root.format(**_template_vars(version))
