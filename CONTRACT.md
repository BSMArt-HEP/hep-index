# hep-index internal contracts (v0.1) — BINDING for all modules

Project: multi-codebase index for HEP software, served over MCP (stdio).
Read this file fully before writing code. `src/hep_index/registry.py` is already
implemented — import it, do not rewrite it (report bugs in your output instead).

## Environment / config

- `HEP_INDEX_CONFIG` — registry TOML path. Default `~/.config/hep-index/codebases.toml`
- `HEP_INDEX_CACHE`  — index store root.  Default `~/.cache/hep-index`
- Tests MUST use `monkeypatch.setenv` with `tmp_path`; never touch real user dirs.

## Module contracts

### indexer.py — `build_index(entry, cache_root=None, ctags_bin="ctags") -> IndexStats`

```python
@dataclass
class IndexStats:
    n_files: int
    n_symbols: int
    ctags_used: bool        # False when ctags binary is missing (degraded mode)
    git_head: str | None    # `git -C path rev-parse HEAD`, None if not a repo
    git_dirty: bool         # `git status --porcelain` non-empty; False if not a repo
    indexed_at: str         # ISO-8601 UTC

DEFAULT_EXCLUDES = [".git", "__pycache__", "*.pyc", "node_modules",
                    "*.o", "*.so", "*.a", "build", "dist"]
```

Behavior:
- Wipes and recreates `index_dir(entry, cache_root)` containing:
  - `index.db` (sqlite3) with EXACT schema:
    - `symbols(name TEXT, kind TEXT, path TEXT, line INTEGER, language TEXT, signature TEXT)`
      + index on `name`, index on `path`
    - `files(path TEXT, size INTEGER, language TEXT)`
      (`path` values are RELATIVE to entry.path, posix separators)
  - `meta.json` = IndexStats fields (snake_case keys) + `"entry_id": "<name>@<version>"`
- File manifest via `os.walk` honoring DEFAULT_EXCLUDES + `entry.exclude`
  (fnmatch-style globs matched against paths relative to root, and against
  directory/file names).
- Symbols via Universal Ctags run from the tree root:
  `ctags -R --output-format=json --fields=+n+k+s+l --extras=-F --exclude=<glob>`
  (pass DEFAULT_EXCLUDES + entry.exclude as repeatable --exclude).
  ctags `path` field → relative posix path; `line`, `kind`, `language`, `name`,
  `signature` straight from the JSON records. If `ctags` binary is missing
  (FileNotFoundError / shutil.which fails): symbols table empty, `ctags_used=False`,
  no exception.
- Insert rows sorted (deterministic). Language for files table: suffix map
  (.py→Python, .cpp/.h/.cc/.hpp→C++, .f90/.f→Fortran, .m→Mathematica, else "").

### server.py — `create_mcp_server() -> FastMCP` + plain impl functions

Use `from mcp.server.fastmcp import FastMCP`. Register 4 tools via `@mcp.tool()`
that delegate to module-level PLAIN functions (so tests can call them directly):

```python
def list_codebases_impl() -> list[dict]
def search_code_impl(query: str, codebase: str | None = None,
                     glob: str | None = None, max_results: int = 50) -> list[dict]
def find_symbol_impl(name: str, codebase: str | None = None,
                     kind: str | None = None, max_results: int = 50) -> list[dict]
def read_file_impl(path: str, offset: int = 1, limit: int = 200) -> dict
```

- Registry is re-read (registry.load_registry) on EVERY tool call — no startup caching.
- `list_codebases_impl()` → per entry:
  `{name, version, id, path, ok, n_files, n_symbols, git_head, stale}`
  `ok` = entry.path is a dir AND its index.db exists.
  `stale` = live `git -C path rev-parse HEAD` != indexed git_head (False if either
  side unavailable). n_files/n_symbols from meta.json/index.db (0 if missing).
- `search_code_impl` — regex via `rg --no-heading -n --max-count 5 QUERY` per
  resolved root (rg exit code 1 = no hits, NOT an error; 2 = raise ValueError).
  `codebase` selector uses `registry.resolve` (None → ALL codebases). `glob`
  passed to rg via `-g`. Hit: `{codebase, path (absolute), line_no, text}`.
  Skip codebases whose path is missing (don't fail the whole call).
- `find_symbol_impl` — per resolved entry: open its index.db; exact `name = ?`
  first, then substring `name LIKE '%..%'` if no exact hits; optional `kind`
  filter. Result `{codebase, name, kind, path (absolute), line, language, signature}`.
  Fallback when index.db missing or n_symbols == 0: rg word search
  `\b<name>\b` and return hits as `{codebase, path (absolute), line_no, text}`.
- `read_file_impl` — `path` absolute, or relative (resolved against each
  registered root, first match wins). MUST be inside a registered root
  (`Path.resolve()` + `is_relative_to`) else ValueError (path traversal guard).
  `offset` 1-based, `limit` clamped to 1000.
  → `{codebase, rel_path, offset, total_lines, content}` where content lines are
  `"N: text"` numbered. Missing file → FileNotFoundError.
- Tool docstrings are the MCP tool descriptions: write them for an LLM agent
  (what it does, that `query` is a regex, defaults, one example).

### cli.py — `main(argv=None) -> int` (argparse, stdlib only)

```
hep-index add <path> --name NAME --version VER [--exclude GLOB ...] [--recipe NAME]
hep-index remove <name>[@version]
hep-index list [--json]
hep-index reindex <name>[@version]
hep-index serve
```

- `add`: abspath, merge recipe excludes (recipe glob list EXTENDS --exclude),
  registry.add_entry, indexer.build_index; print one-line stats
  (`registered madanalysis@1.11.1: 4231 files, 31290 symbols, head abc1234`).
- `remove`: registry.remove_entry + `shutil.rmtree` the index dirs.
- `list`: human table (id, path, n_files, stale) or `--json` (= list_codebases_impl output).
- `reindex`: build_index for resolved entries.
- `serve`: `create_mcp_server().run()` (stdio).
- Exit codes: 0 ok, 1 usage/ValueError/FileNotFoundError, 2 KeyError (not found).
  Print `error: <msg>` to stderr.

### recipes.py

```python
RECIPES: dict[str, list[str]] = {  # preset exclude-glob lists, extendable data
    "madgraph": ["PROC_*", "madevent*", "MCatNLO_*", "Events/*", "*.lhe", "*.hepmc.gz"],
    "madanalysis": ["ME5_debug*", "Build/*", "Output/*"],
    "delphes": ["*_t*", "*.root"],
}
```
Exact glob choices are yours to refine (comment each with why); keys stay these 3.

## Rules for all agents

- Own ONLY your assigned files. Never edit pyproject.toml, CONTRACT.md, or
  another agent's files. Shared foundation `registry.py` is done — import it.
- No new dependencies (stdlib + mcp + tomli-w only).
- Tests: pytest, `tmp_path` + `monkeypatch.setenv("HEP_INDEX_CONFIG"/"HEP_INDEX_CACHE")`.
  Unit tests never touch the network. Build tiny fixture codebases on disk.
- Finish when `uv run pytest tests/test_<yours>.py -q` is green, then
  `git add <your files> && git commit -m "<conventional msg>"`.

---

# v0.2 additions — BINDING for round-2 tasks (parent-maintained)

Round-2 rules identical to v0.1 (own only your files, no new deps, no network in
tests, green tests then commit only your files). Existing modules are stable and
importable; never modify a module owned by another round-2 task.

## New environment variables
- `HEP_INDEX_CATALOG` — catalog TOML path (default: packaged `src/hep_index/data/catalog.toml`)
- `HEP_INDEX_ROOT` — default fetch destination root (default: `~/hep-codebases`)

## D1 — registry.py: discoverable errors (owner: registry agent)
`resolve()` KeyError messages (BOTH the `name@version` branch and the bare
`name` branch) must list what IS registered:
`not registered: 'madgraph' (available: madanalysis@v1.11.1, delphes@3.5.1, ...)`
ids sorted, comma-joined. Empty registry → `(available: none)`.
Tests: assert message via `pytest.raises(KeyError, match="available:")`.

## D2 — catalog.py + data/catalog.toml (owner: catalog agent) — NEW files
`src/hep_index/catalog.py`:
```python
@dataclass
class CatalogEntry:
    name: str; type: str; url: str; versions: list[str]
    recipe: str | None = None; extract_root: str | None = None; notes: str = ""
def default_catalog_path() -> Path   # env HEP_INDEX_CATALOG, else packaged file
def load_catalog(path: Path | None = None) -> dict[str, CatalogEntry]
def render_url(entry: CatalogEntry, version: str) -> str
def render_extract_root(entry: CatalogEntry, version: str) -> str | None
def latest(entry: CatalogEntry) -> str  # entry.versions[-1]
```
- packaged file read via `importlib.resources.files("hep_index").joinpath("data/catalog.toml")`
- template fields: `{version}`, `{version_nodot}` (dots stripped), `{version_underscore}` (dots→_)
- `data/catalog.toml` contains EXACTLY these verified entries (comment each with notes):
  madgraph: type=tarball, url=https://launchpad.net/mg5amcnlo/3.0/3.6.x/+download/MG5_aMC_v{version}.tar.gz, extract_root=MG5_aMC_v{version_underscore}, versions=["3.7.0","3.7.3"], recipe=madgraph, notes="launchpad project is 'mg5amcnlo'; 3.7.x tarballs sit under the 3.6.x series path; no official GitHub mirror"
  madanalysis: type=git, url=https://github.com/MadAnalysis/madanalysis5, versions=["v1.11.1"], recipe=madanalysis, notes="v2.0.4_beta is a dead 2022 beta line — never treat it as latest"
  pythia8: type=tarball, url=https://pythia.org/releases/pythia83/pythia{version_nodot}.tgz, extract_root=pythia{version_nodot}, versions=["8.3.17"], notes="tarball version has no dot; gitlab.com unreachable from some networks"
  delphes: type=git, url=https://github.com/delphes/delphes, versions=["3.5.1"], recipe=delphes, notes="plain X.Y.Z tags"
Tests: env override, render_url for all four real entries (exact expected strings),
unknown version/entry errors. No network.

## D3 — fetch.py (owner: fetch agent) — NEW file
Transport + registration. MUST NOT import catalog (takes primitives only):
```python
def fetch_source(*, kind: str, url: str, version: str, dest: Path,
                 extract_root: str | None = None) -> Path
def fetch_and_register(*, name: str, version: str, kind: str, url: str,
                       extract_root: str | None, root: Path,
                       recipe: str | None = None,
                       exclude: list[str] | None = None) -> dict
```
- kind="git": `git clone --depth 1 --branch <version> <url> <dest>` with env
  `GIT_ASKPASS=/bin/true, GIT_TERMINAL_PROMPT=0, GIT_SSH_COMMAND="ssh -o BatchMode=yes"`
  (prevents credential popups; non-negotiable).
- kind="tarball": urllib.request (timeout 120; supports file:// and plain paths
  for tests) → temp file → tarfile extract → move top-level dir (`extract_root`)
  to `dest`.
- dest = `root/f"{name}-{version}"`; if dest exists non-empty → reuse, skip fetch.
- On failure: remove partial dest, raise RuntimeError with captured stderr.
- fetch_and_register: builds exclude list (recipes.RECIPES[recipe] if recipe else
  [] + (exclude or [])), registry.add_entry, indexer.build_index; returns
  {"codebase", "path", "n_files", "n_symbols", "ctags_used", "git_head"}.
Tests (offline): git fixture via `git init` + commit + tag in tmp, cloned from a
`file://` URL; tarball fixture built in tmp with tarfile; end-to-end
fetch_and_register with monkeypatched HEP_INDEX_CONFIG/HEP_INDEX_CACHE;
duplicate registration raises ValueError; reuse-existing-dest path covered.

## D4 — server.py: two new MCP tools (owner: server agent; runs AFTER D2+D3)
```python
def index_codebase_impl(path: str, name: str, version: str,
                        recipe: str | None = None,
                        exclude: list[str] | None = None) -> dict
def fetch_codebase_impl(name: str, version: str | None = None,
                        root: str | None = None) -> dict
```
- index_codebase: LOCAL PATH ONLY (os.path.abspath; must be an existing dir);
  refuse duplicate name@version with error mentioning CLI `reindex`; unknown
  recipe → ValueError; register + build; return same stats shape as
  fetch_and_register. Tool docstring: "Index a directory tree already on this
  machine. No network. For known HEP packages prefer fetch_codebase."
- fetch_codebase: CATALOG-GATED ONLY. catalog.load_catalog → entry or
  ValueError("not in catalog: X — run hep-index catalog; use CLI add for local
  paths"); version defaults to catalog latest, must be listed in entry.versions;
  url/extract_root via catalog.render_*; root = Path(root) or HEP_INDEX_ROOT
  default; recipe = entry.recipe. Tool docstring: "Fetch a catalog package from
  its pinned upstream source and index it. Only curated catalog entries are
  fetchable — no arbitrary URLs."
- Both registered via @mcp.tool() wrappers delegating to impls.
- Discoverability: append one line to each of the 4 existing tool docstrings:
  "If unsure which codebases are indexed, call list_codebases first; selectors
  are 'name' (latest) or 'name@version'."
Tests: index_codebase on tmp fixture dir (real ctags); duplicate refusal;
fetch_codebase e2e OFFLINE via HEP_INDEX_CATALOG pointing at a fixture catalog
(file:// git fixture), plus not-in-catalog and bad-version errors.

## D5 — cli.py: catalog + fetch commands (owner: cli agent; runs AFTER D2+D3)
- `hep-index catalog` — table: name, type, versions (latest last, marked), notes
  first line. Exit 0.
- `hep-index fetch <name>[@<version>] [--root DIR] [--exclude GLOB ...]` —
  catalog-gated (same errors as D4), auto-recipe from entry, prints the same
  one-line stats as `add`.
- Bare `hep-index` (no subcommand): print help, then a line
  `registered: <id>, <id>, ... (see 'hep-index list')` (errors ignored, exit 0).
Tests: catalog listing output; fetch via fixture catalog (file:// git fixture,
monkeypatched envs + HEP_INDEX_ROOT); not-in-catalog exit 1; no-arg footer.
