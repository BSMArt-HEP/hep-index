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
