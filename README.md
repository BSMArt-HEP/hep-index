# hep-index

A multi-codebase code index for HEP software, served to AI agents over MCP.

HEP tools are notoriously hard to navigate — sparse docs, heterogeneous APIs,
moving upstreams. hep-index lets an agent *read the source* instead of guessing:
you register codebases (local checkouts, or fetched from a curated catalog of
pinned upstream sources), and any MCP-capable harness (Claude Code, Codex, pi,
Cursor, …) gets `search_code` / `find_symbol` / `read_file` tools over the whole
stack at once.

It is deliberately **not** RAG: no embeddings, no vector store — ripgrep +
ctags/sqlite symbol indexes over the real trees, live-read. Symbol-level lookup
works across C++, Python, Fortran and (via search) Mathematica. Python is
indexed with the stdlib `ast` module (static, nothing imported), giving
qualified names, full signatures, docstrings, inheritance, re-exports,
`self.x` instance attributes and config-key lookups; files that don't parse
(e.g. Python 2) fall back to ctags. ctags is not run on data/markup formats
(JSON, YAML, XML, Markdown, …) or on `.m` files (Mathematica in HEP; ctags
would misparse them as MatLab/Objective-C). JSON/YAML/TOML files are instead
flattened into key paths with value types and samples.

## Install (consumers)

Zero-install, straight from the git remote (pin a tag for reproducibility — SSH
key required for private repos):

```bash
# one-shot use
uvx --from git+ssh://git@github.com/BSMArt-HEP/hep-index.git@v0.3.0 hep-index list

# or install persistently (isolated venv, `hep-index` on PATH)
uv tool install git+ssh://git@github.com/BSMArt-HEP/hep-index.git@v0.3.0
hep-index list
```

Requirements: `uv`, Python ≥ 3.11, `ripgrep` (required for search),
`universal-ctags` (optional — without it you get degraded manifest-only indexes).
Updates: `uv tool upgrade hep-index`.

## Quickstart

```bash
# fetch + index a curated package (MadAnalysis 5, pinned upstream)
hep-index fetch madanalysis

# or index something already on disk, e.g. your project's MG5 install
hep-index add ~/recast/read/madgraph --name madgraph --version 3.7.0 --recipe madgraph

hep-index list          # what's indexed, staleness, git heads
hep-index catalog       # 29 curated sources w/ categories + gotcha notes
```

Serve it to an agent harness (stdio MCP):

```bash
hep-index serve
```

MCP wiring (any MCP-JSON client; adjust syntax to your harness). Preferred —
zero-install via uvx, pinned tag:

```json
{"mcpServers": {"hep-index": {
  "command": "uvx", "args": ["--from", "git+ssh://git@github.com/BSMArt-HEP/hep-index.git@v0.3.0",
                             "hep-index", "serve"]
}}}
```

Dev alternative (runs the live checkout): `"command": "uv", "args": ["run",
"--project", "/path/to/hep-index", "hep-index", "serve"]`.

## Tools exposed

| Tool | What it does |
|---|---|
| `list_codebases()` | registered codebases, counts, git heads, staleness |
| `search_code(query, codebase?, glob?, max?)` | ripgrep (regex) across all/selected codebases, labeled hits |
| `find_symbol(name, codebase?, kind?)` | symbol lookup → definitions w/ file:line; Python hits carry qualname, signature, docstring summary, bases; dotted names (`pkg.mod.Class.meth`, re-exports like `pkg.Name`) resolve through imports |
| `call_graph(name, codebase?, direction?)` | static Python call graph: what a function/method/class calls and who calls it, targets resolved through imports, re-exports, base classes and `self.attr = Ctor()` attribute types (so `self.RunManager.run_batch()` → `HEPRun.run_batch`); unresolvable `x.meth()` calls listed separately as possible callers |
| `config_keys(base?, codebase?, prefix?, data_prefix?)` | input-key schema: every `cfg["A"]["B"]` / `.get("B", default)` / `"B" in cfg["A"]` chain in the Python, merged with the key paths of the codebase's JSON/YAML/TOML example inputs — per key: defaults, consuming functions, example values, and status `read+set` / `read_only` / `set_only` (likely dead option or typo) |
| `data_files(codebase?, glob?, has_key?)` | list JSON/YAML/TOML files (example inputs, templates) with top-level keys; `has_key="Codes/SModelS"` finds every example configuring SModelS. Files ≤64 kB are stored whole, so `read_file` serves them even without the checkout |
| `outline(target, codebase?, include_private?)` | Python package/module/class API without reading source: members + signatures + summaries, submodules, re-exports, `__all__`, subclasses, full literal settings dicts |
| `read_file(path, offset?, limit?)` | numbered lines; or `center=/before=/after=` context window |
| `index_codebase(path, name, version)` | agent may index a **local** dir (no network) |
| `fetch_codebase(name, version?)` | agent may fetch a **catalog** package (curated URLs only) |

Without MCP (shell-only agents, scripts, skills), the same read-only tools run
from the CLI and print JSON:

```bash
hep-index query                                    # list tools + signatures
hep-index query outline --doc                      # full tool description
hep-index query outline bsmart.core.Scan           # positionals fill required params
hep-index query config_keys inputs prefix=Setup    # param=value, JSON-parsed
hep-index query call_graph run_batch direction=callers codebase=bsmart
```

Wrong selector names self-correct: `KeyError: not registered: 'madgrap' (available: …)`.

## Example session (agent's view)

> **Q: does `RecLeptonFormat` have `d0sig()`?**
> `search_code(r"\bd0sig\b", codebase="madanalysis")` → `[]` — no such method.
> `find_symbol("d0error")` → `tools/SampleAnalyzer/Commons/DataFormat/RecLeptonFormat.h:202`.
> `read_file(that path, center=202, before=10, after=5)` → the accessor + comment.

Every fact rediscovered from source in three calls, with file:line citations —
no hand-maintained API notes to rot.

## Layout & state

```
~/.config/hep-index/codebases.toml   # registry (machine-local, hand-editable)
~/.cache/hep-index/<name>-<version>/ # per-codebase sqlite index (rebuildable)
src/hep_index/data/catalog.toml      # curated source pins (shareable data)
```

Env overrides: `HEP_INDEX_CONFIG`, `HEP_INDEX_CACHE`, `HEP_INDEX_CATALOG`,
`HEP_INDEX_ROOT` (fetch destination, default `~/hep-codebases`).

Catalog = **pins-as-data**: canonical upstream URLs, known-good versions, and
gotchas (dead tags, launchpad series-path quirks, Anubis walls) as commented
TOML — contributions welcome via PR. Codebases themselves are never bundled or
redistributed; each machine fetches from upstream.



## Extending the catalog

The catalog is just commented TOML (`src/hep_index/data/catalog.toml`) — pins,
not code. To propose a new package:

**1. Add the entry** (category from the existing set, `versions` with latest
LAST — never a beta/pre-release):

```toml
[mytool]
category = "model-builder"          # me-generator | parton-shower | detector-sim |
                                    # analysis-framework | recast-engine | spectrum-calc |
                                    # model-builder | dark-matter | stat-interpretation |
                                    # validation | pdf | global-fit | symbolic-toolkit
type = "git"                         # or "tarball" (tar and zip both supported)
url = "https://github.com/<org>/mytool.git"
versions = ["v1.2.3"]
notes = "tag scheme vX.Y.Z; PyPI 'mytool' exists but source is canonical for navigation"
```

Extra fields when needed: `recipe` (preset exclude globs), `extract_root`
(tarball top-level dir — leave unset to auto-detect; flat archives extract
into the dest dir), `urls` (per-version URL overrides, e.g. launchpad series
paths that aren't mechanical).

**2. Verify before you PR — nothing enters unverified:**

```bash
# git entries: exact tag string must exist
git ls-remote --tags --refs https://github.com/<org>/mytool.git

# tarball entries: direct URL must return 200 (Anubis-walled *pages* are fine,
# the file URLs usually still fetch)
curl -sIL -o /dev/null -w "%{http_code}\n" <tarball-url>
```

Hard-won lessons encoded in existing notes — read a few entries first: canonical
upstream only (personal mirrors rot: `restrepo/*`, `HEPcodes/*`); claimed
versions sometimes don't exist (SoftSUSY "4.1.24" didn't); dead release lines
lurk (MadAnalysis `v2.0.4_beta`, frozen 2022); moving endpoints are allowed but
must be flagged (FeynMaster's php `latest` stream, BSMArt pre-tag `main`).

**3. Test the fetch in a scratch registry** (never your real one):

```bash
HEP_INDEX_CONFIG=/tmp/c.toml HEP_INDEX_CACHE=/tmp/c HEP_INDEX_ROOT=/tmp/r \
  uv run hep-index fetch mytool
```

**4. PR checklist:** entry parses (`uv run hep-index catalog`), fetch works in
scratch, version is latest-LAST stable, notes name the hosting gotcha, and
`uv run pytest` stays green (bump the entry-count assertion in
`tests/test_catalog.py`).

## Development

```bash
git clone git@github.com:BSMArt-HEP/hep-index.git && cd hep-index
uv sync
uv run pytest        # 91 tests, offline (file:// fixtures)
uv run hep-index …   # CLI from the live checkout
```

Architecture and binding interface contracts live in `CONTRACT.md`; the
full HEP-software landscape map (incl. Tier-2/3 packages not yet catalogued)
in `docs/HEP_SOFTWARE_MAP.md`.

## AI-assistance disclaimer

This codebase was developed with substantial AI assistance: implementation,
tests, and the HEP-software landscape research were produced by LLM agents
(GLM models, orchestrated via the pi coding agent) working from
human-authored interface contracts, with human review of every change. Upstream
packages referenced in the catalog are the work of their respective authors and
are only pinned, never redistributed.
## License

MIT — Copyright (c) 2026 Miguel Crispim Romão. Catalog entries pin upstream
software by other authors; their licenses apply to their code, which is never
redistributed here.
