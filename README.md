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
works across C++, Python, Fortran and (via search) Mathematica.

## Install

```bash
git clone <remote> hep-index && cd hep-index
uv sync
```

Requirements: `uv`, Python ≥ 3.11, `ripgrep` (required for search),
`universal-ctags` (optional — without it you get degraded manifest-only indexes).

## Quickstart

```bash
# fetch + index a curated package (MadAnalysis 5, pinned upstream)
uv run hep-index fetch madanalysis

# or index something already on disk, e.g. your project's MG5 install
uv run hep-index add ~/recast/read/madgraph --name madgraph --version 3.7.0 --recipe madgraph

uv run hep-index list          # what's indexed, staleness, git heads
uv run hep-index catalog       # 29 curated sources w/ categories + gotcha notes
```

Serve it to an agent harness (stdio MCP):

```bash
uv run hep-index serve
```

MCP wiring (any MCP-JSON client; adjust syntax to your harness):

```json
{"mcpServers": {"hep-index": {
  "command": "uv", "args": ["run", "--project", "/path/to/hep-index", "hep-index", "serve"]
}}}
```

## Tools exposed

| Tool | What it does |
|---|---|
| `list_codebases()` | registered codebases, counts, git heads, staleness |
| `search_code(query, codebase?, glob?, max?)` | ripgrep (regex) across all/selected codebases, labeled hits |
| `find_symbol(name, codebase?, kind?)` | ctags/sqlite symbol lookup → definitions w/ file:line |
| `read_file(path, offset?, limit?)` | numbered lines; or `center=/before=/after=` context window |
| `index_codebase(path, name, version)` | agent may index a **local** dir (no network) |
| `fetch_codebase(name, version?)` | agent may fetch a **catalog** package (curated URLs only) |

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

## Development

```bash
uv run pytest        # 91 tests, offline (file:// fixtures)
```

Architecture and binding interface contracts live in `CONTRACT.md`; the
full HEP-software landscape map (incl. Tier-2/3 packages not yet catalogued)
in `docs/HEP_SOFTWARE_MAP.md`.
