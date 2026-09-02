# hep-index Smoke Report — MadAnalysis5 acceptance run

Date: 2026-09-02 · Working dir: `/home/mcromao/tmp/hep-codebases/hep-index`

## Environment

| Item | Value |
|---|---|
| MadAnalysis5 tag | `v2.0.4_beta` (latest tag on GitHub at run time; clone HEAD `fe98722745428dbefb93cac5e8c609deaeb90be8`) |
| Clone path | `/home/mcromao/tmp/hep-codebases/madanalysis5` (shallow, depth 1) |
| Universal Ctags | 6.2.1 |
| mcp | 2.1.1 (MCPServer branch of server.py) |
| Python | 3.14.7 (uv-managed venv) |
| Registration | Default user config `~/.config/hep-index/codebases.toml` (not tmp), cache in `~/.cache/hep-index` |

## Full test suite

`uv sync -q && uv run pytest -q` → **46 passed**, 0 failed, 0 skipped.

## Registration

```
$ uv run hep-index add /home/mcromao/tmp/hep-codebases/madanalysis5 \
    --name madanalysis --version v2.0.4_beta --recipe madanalysis
registered madanalysis@v2.0.4_beta: 554 files, 5798 symbols, head fe98722
```

## Eval queries (expected vs actual)

Queries run via `python -c` importing `hep_index.server` impl functions against
the real user registration.

| # | Query | Expected | Actual | Verdict |
|---|---|---|---|---|
| Q1 | `find_symbol_impl("RecLeptonFormat")` | class definition under `tools/SampleAnalyzer/*/DataFormat/` | class at `/…/madanalysis5/tools/SampleAnalyzer/Commons/DataFormat/RecLeptonFormat.h:50` (kind=class, lang=C++; 3 sibling ctor-like function hits in same file) | **PASS** (subdir is `Commons/`, not `Interfaces/` as guessed — see notes) |
| Q2a | `search_code_impl(r"\bd0sig\b", codebase="madanalysis")` | 0 hits | `[]` (0 hits) | **PASS** |
| Q2b | `search_code_impl("d0error", codebase="madanalysis")` | ≥1 hit in `RecLeptonFormat.h` | 7 hits, incl. `RecLeptonFormat.h:202` — `MAfloat32 d0error() const { return d0error_; }` | **PASS** |
| Q3 | `find_symbol_impl("AddRegionSelection")` | definition in SampleAnalyzer RegionSelectionManager | `tools/SampleAnalyzer/Process/RegionSelection/RegionSelectionManager.h:124` (kind=function) + `Process/Counter/MultiRegionCounter.h:74` | **PASS** |
| Q4a | `search_code_impl("DeltaPhi", codebase="madanalysis", glob="*MALorentzVector*")` | hits in `MALorentzVector.h` | 3 hits, top at `tools/SampleAnalyzer/Commons/Vector/MALorentzVector.h:243` | **PASS** |
| Q4b | `read_file_impl(path, offset=233, limit=40)` on Q4a path | signature takes `MALorentzVector`, not `TVector3` | line 243: `inline MAdouble64 DeltaPhi(const MALorentzVector& q) const` — takes `MALorentzVector` ✓ (total_lines=331, offset numbering correct) | **PASS** |
| Q5 | `list_codebases_impl()` | ok=True, stale=False, n_files>1000 | ok=True, stale=False, n_files=**554**, n_symbols=5798, head matches live HEAD | **PARTIAL** — ok/stale PASS; `n_files>1000` FAIL, but the index is *correct* (see notes) |

**Overall: 6/7 sub-expectations pass. The single miss (Q5 n_files) is a wrong
expectation for this tag, not an indexing bug — verified against the clone.**

## Notes / surprising findings

1. **Q5 n_files=554, not >1000.** Ground truth on disk:
   `find . -type f -not -path './.git/*' | wc -l` → 557; after recipe/DEFAULT
   excludes (`Build/*`, `Output/*`, `__pycache__`) → 554, exactly what the index
   reports. The `v2.0.4_beta` tag of madanalysis5 simply has a smaller tree than
   the >1000 guess assumed (no vendored/build trees present in this tag). The
   indexer is faithful to the clone; only the expectation was miscalibrated.
   If a >1000-file corpus is required, a different/larger codebase must be
   registered — not a code change.
2. **Q1 directory layout.** In this tag, `RecLeptonFormat.h` lives under
   `tools/SampleAnalyzer/Commons/DataFormat/`, not `…/Interfaces/DataFormat/`.
   The semantic expectation (class definition in SampleAnalyzer DataFormat)
   holds; the literal path in the task was a guess for the wrong subtree.
3. `find_symbol_impl` returns empty `signature` fields for C++ records — ctags
   6.2.1 emits no `signature` for these class/function declarations. Cosmetic;
   contract makes signature optional passthrough.
4. No suspect bugs found in `registry.py` / `indexer.py` / `server.py` during
   the run; all tools behaved per CONTRACT.md (rg exit-1-as-no-hits, absolute
   paths, registry re-read per call).

## Artifacts left in place (as instructed)

- Clone: `/home/mcromao/tmp/hep-codebases/madanalysis5` @ `v2.0.4_beta`
- Registration: `madanalysis@v2.0.4_beta` in default user config + index cache
