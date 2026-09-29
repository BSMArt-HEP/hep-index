# HEP software landscape map — hep-index catalog research

Generated 2026-09-30 by three parallel researcher agents (lanes A/B/C), then
machine-verified by the maintainer (curl HEAD / git ls-remote): every URL, tag
and version in catalog.toml was confirmed live. Discrepancies found and fixed:
SoftSUSY tags stop at v4.1.22 (claimed 4.1.24 does not exist); Herwig git is
auth-walled (tarball canonical); micrOMEGAs tarballs actually live on
micromegasdm.github.io/downloadarea. Tier-1 = catalogued (22 entries).
Tier-2/3 below remain map-only until someone needs them.

# LANE A — BSM model building, spectra, dark matter (16 seeds + 1 added sibling)

Catalog date context: verified Sep/Oct 2026. HEPForge (spheno/softsusy/sarah/darksusy/lilith) sits behind an Anubis anti-bot wall (HTTP 403 to scripted clients; fine in a human browser) — flagged per package below. Versions below were confirmed from GitHub/GitLab release APIs, author pages, or package recipes wherever the primary page was blocked.

### SPheno
category: spectrum-calc
role: SUSY/general-BSM spectrum and decay calculator (SLHA in/out); the workhorse generator behind SARAH→SPheno chains, feeds micrOMEGAs/HiggsBounds/HiggsSignals.
source: https://spheno.hepforge.org/downloads/?f=SPheno-4.0.7.tar.gz (type: tarball)
latest_stable: 4.0.7 — upstream release date NOT verifiable (hepforge blocked); exists on hepforge (conda-forge recipe pulls exactly that URL, first packaged 2026-05); previous 4.0.5 was 2022.
version_scheme: tarball named SPheno-X.Y.Z.tar.gz from https://spheno.hepforge.org/downloads/?f=... (no git tags upstream)
hosting_notes: hepforge site behind Anubis (403 to bots); no official git repo (github.com/restrepo/SPheno is an unofficial, stale mirror, latest v4.0.5/2022); tarball is pure Fortran source tree, moderate size.
language: Fortran (F90)
license: BSD-4-Clause (LICENSE file in tarball, as parsed by conda-forge recipe; Gentoo says "all-rights-reserved" — treat tarball LICENSE as authoritative)
pip_conda: yes — conda-forge `spheno` (+ `spheno-atlas` variant); source checkout still worth indexing (SLHA parsing, model files, RGE routines needed for navigation).
priority: high — default spectrum engine in SARAH/FlexibleSUSY workflows; every recast chain touches its output blocks.

### SARAH
category: model-builder
role: Mathematica model builder: derives Feynman rules/RGEs for (not only) SUSY models and auto-generates SPheno, FlexibleSUSY, FeynArts, UFO, CalcHEP output.
source: https://sarah.hepforge.org/downloads/ (tarball SARAH-4.15.2.tar.gz) (type: tarball)
latest_stable: 4.15.2 (default pinned by FlexibleSUSY's `install-sarah`, Apr 2025); note: tracked mirror's SARAH.m shows 4.15.4 — hepforge changelog unreachable (Anubis), so 4.15.2 vs 4.15.4 ambiguity unresolved; FlexibleSUSY's pin is the strongest signal for the last known-good stable.
version_scheme: tarball named SARAH-X.Y.Z.tar.gz from sarah.hepforge.org/downloads/; sources are a plain .m/.wl text tree (fully indexable); no official git tags.
hosting_notes: hepforge behind Anubis; github.com/restrepo/SARAH is an unofficial mirror (28 releases, tags v4.14.15/2022, master tracks tarballs) — useful for browsing, NOT canonical; github.com/staub86/SARAH does not exist (404).
language: Mathematica (plus embedded Fortran/C++ code-generation templates)
license: GPL-3 (per SARAH documentation; site unreachable to re-verify)
pip_conda: no
priority: high — the single entry point for defining new BSM models that flow into SPheno/micrOMEGAs/CalcHEP/MadGraph; an agent must read its generated-code templates.

### FeynRules
category: model-builder
role: Mathematica package computing Feynman rules from a Lagrangian and exporting UFO (MadGraph/MadDM), CalcHEP, FeynArts, Sherpa, Whizard model files.
source: https://github.com/FeynRules/FeynRules.git (type: git) — official author org; tarball alias: http://feynrules.irmp.ucl.ac.be/downloads/feynrules-current.tar.gz
latest_stable: 2.3.49 — tag `fr-2.3.49`, published 2024-03-28 (code's internal version date 2021-09-29).
version_scheme: git tags `fr-X.Y.Z` on branch `feynrules-current`; website tarball is unversioned name `feynrules-current.tar.gz`.
hosting_notes: Trac wiki at feynrules.irmp.ucl.ac.be (feynrules.phys.ucl.ac.be resolves to same); repo is a plain .m text tree (indexable) with some C/C++ in Interfaces/; github.com/HEPcodes/FeynRules is a secondary mirror.
language: Mathematica
license: GPL-3 (LICENSE = full GPLv3 text, verified via GitHub API)
pip_conda: no
priority: high — UFO production line for MadDM/MG5 recasting; model-file format knowledge lives here.

### FeynArts
category: model-builder
role: Mathematica Feynman-diagram and amplitude generator (generic/class/particle levels); model-file backend for FormCalc and FeynRules interface.
source: https://feynarts.de/FeynArts-3.12.tar.gz (type: tarball)
latest_stable: 3.12 (10 Aug 2026 — mini-change over 3.11; 3.11 was 25 Mar 2022)
version_scheme: tarball named FeynArts-X.Y.tar.gz from feynarts.de (two-part version numbers; no git)
hosting_notes: author site (Thomas Hahn, MPP Munich), no official git; github.com/FeynCalc/feynarts-mirror is third-party; installer script `FeynInstall` fetches FeynArts+FormCalc+LoopTools; plain .m text tree.
language: Mathematica
license: LGPL (site: "GNU Lesser General Public License")
pip_conda: no
priority: medium — needed to navigate SARAH/FeynRules→FeynArts pipelines and model files, but less central than the UFO/CalcHEP path for collider recasting.

### FormCalc
category: model-builder
role: Mathematica package that reduces FeynArts one-loop diagrams to Fortran/C code (amplitudes, cross sections); ships LoopTools numerical loop library interface.
source: https://feynarts.de/formcalc/FormCalc-9.10.tar.gz (type: tarball)
latest_stable: 9.10 (11 Oct 2024)
version_scheme: tarball named FormCalc-X.Y.tar.gz from feynarts.de/formcalc/ (no git)
hosting_notes: tarball is 51 MB (bundles FORM binaries + demos); companion LoopTools-2.16 tarball separate; no official git.
language: Mathematica + Fortran/C (codegen)
license: LGPL
pip_conda: no
priority: low — precision one-loop niche; recast chains rarely enter it (MadGraph_aMC@NLO/CalcHEP cover the agent's needs).

### FlexibleSUSY
category: spectrum-calc
role: Mathematica/C++ meta-code spectrum generator (any SARAH model; EFT/hybrid via FlexibleEFTHiggs, FlexibleDecay for decays, GM2Calc/NPointFunctions observables).
source: https://github.com/FlexibleSUSY/FlexibleSUSY.git (type: git)
latest_stable: v2.9.0 (6 Apr 2025)
version_scheme: vX.Y.Z git tags + GitHub releases (attached model tarballs); expects SARAH-X.Y.Z tarball at configure time.
hosting_notes: clean GitHub hosting; C++17 + Mathematica meta layer; optional deps via Conan (Eigen, GM2Calc, COLLIER, Himalaya); links to HiggsTools and Lilith for validation.
language: C++ (generated) + Mathematica (meta)
license: GPL-3
pip_conda: no (not packaged; deps like GM2Calc partially on conda-forge)
priority: high — actively maintained, most extensible non-SUSY/SUSY spectrum engine; an agent modifying model code will live in its templates.

### SoftSUSY
category: spectrum-calc
role: MSSM (incl. flavour/CP/RPV) and NMSSM spectrum+decay calculator; supplies loop library used by other tools; SLHA standard output.
source: https://github.com/BAllanach/softsusy.git (type: git)
latest_stable: 4.1.24 (9 Sep 2026)
version_scheme: git tags vX.Y.Z; release tarballs also stored inside the repo at tags/softsusy-X.Y.Z.tar.gz (raw.githubusercontent.com/BAllanach/softsusy/master/tags/...); hepforge tarballs ≤4.1.13.
hosting_notes: hosting MOVED hepforge → author GitHub (hepforge archive behind Anubis); repo bundles Himalaya-1.0.0 and NMSSMTools_4.2.1.tgz in-tree; version history in README.
language: C++
license: GPL-3
pip_conda: yes — conda-forge `softsusy` (may lag git master; source checkout still valuable)
priority: high — reference MSSM spectrum calculator, cross-check standard; its SLHA dialect is what many downstream tools parse.

### micrOMEGAs
category: dark-matter
role: relic density (incl. multi-component/freeze-in/co-scattering), direct+indirect detection rates for generic BSM models; ships CalcHEP-based model compiler and many built-in models.
source: https://lapth.cnrs.fr/micromegas/ → "Download and Install" (v7.1/install_7.1.html), tarball `micromegas_7.X.tgz` (type: tarball)
latest_stable: 7.1 (site's current line; no release date printed — 7.1 adds modified-cosmology scenarios; micrOMEGAs 6.0 (CPC 299 (2025) 109133) archived on Zenodo 2025-11-13 as micromegas_6.0.tgz)
version_scheme: tarball named micromegas_X.Y(.Z).tgz (micromegas_6.0.tgz ~22 MB packed / ~100 MB unpacked; 5.x-era names like micromegas_5.3.41.tgz); per-version doc dirs v7.1/ on the site.
hosting_notes: domain moved lapth.in2p3.fr → lapth.cnrs.fr (old domain dead); site is a 1990s frameset (fetch-hostile but plain HTML); new GitHub org MicrOMEGAsDM (created 2026-06) hosts only the website mirror; github.com/restrepo/micromegas is a third-party mirror.
language: C (+ Fortran bits; bundles CalcHEP_src)
license: custom academic — free-use terms in tarball; Zenodo record metadata says CC-BY-4.0 for the *record*, not the code
pip_conda: no
priority: high — the default Ωh²/DD/ID engine called from SPheno/FlexibleSUSY workflows; agent must navigate main.c calcOmega/calcSpectrum APIs.

### DarkSUSY
category: dark-matter
role: modular DM framework (Fortran library): relic density, direct/indirect detection, freeze-in, out-of-equilibrium freeze-out, custom particle-physics modules (MSSM, singlet scalar, vdSIDM, …).
source: https://darksusy.hepforge.org/download.html → darksusy-6.4.1.tgz (type: tarball)
latest_stable: 6.4.1 (26 Aug 2024)
version_scheme: tarball named darksusy-X.Y.Z.tgz in tars/ (darksusy-6.1.0.tar.gz …); development via phab.hepforge.org (source/DS_releases/) — also bot-blocked.
hosting_notes: hepforge Anubis wall (403 to scripted download); tarball is HUGE (~460 MB download / ~2.5 GB unpacked — bundles galprop & co); Stockholm mirror staff.fysik.su.se/~edsjo/darksusy/ is stale (stops at 6.1.0/2018) — do not use for versions.
language: Fortran
license: academic free-use terms in tarball (hepforge page unreachable to verify exact wording)
pip_conda: no
priority: medium — capable but heavyweight; micrOMEGAs/MadDM dominate automated chains; index mainly for module API navigation.

### MadDM
category: dark-matter
role: MadGraph5_aMC@NLO plugin: Ωh², direct/directional/indirect detection and likelihoods computed directly from UFO models (loop-induced via NLOCT output supported).
source: https://github.com/maddmhep/maddm.git (type: git)
latest_stable: v3.2.13 (16 Jul 2023) — GitHub release + `version` file in repo; MadDM 3.3.x is explicitly beta/rc (branch `rc`, "now in beta" per collaboration talks 2025/2026), docs site maddmhep.github.io/maddm is the 3.3.0-dev docs.
version_scheme: vX.Y.Z git tags + GitHub releases (asset maddm.tar.gz); version also in plain-text file `version` at repo root.
hosting_notes: moved OFF Launchpad (deprecated for MadDM); requires MG5_aMC ≥2.9 (LTS 2.9.x recommended; MG5 itself from launchpad.net/mg5amcnlo, tarballs at madgraph.phys.ucl.ac.be/Downloads); Python 3, numpy/scipy, gfortran.
language: Python (+ Fortran templates)
license: none stated in repo (no LICENSE file; inherits MG5_aMC ecosystem academic-use terms)
pip_conda: no (install into MG5 via `install maddm` or git clone into PLUGIN/)
priority: high — the UFO-native DM engine; the natural DM leg of any MG5-based recast pipeline, and small enough to index whole.

### CalcHEP
category: me-generator
role: Lagrangian→cross sections/distributions: symbolic model compiler + numerical ME integrator (also the calculation kernel bundled inside micrOMEGAs; interactive numeric session).
source: https://theory.sinp.msu.ru/~pukhov/CALCHEP/calchep_3.9.2.tgz (type: tarball)
latest_stable: 3.9.2 (5 Mar 2025 — page states "Current version 3.9.2, updated 05.03.2025")
version_scheme: tarball named calchep_X.Y.Z.tgz from theory.sinp.msu.ru/~pukhov/CALCHEP/ (dd.mm.yyyy dates on page); BSM models distributed as separate tarballs (e.g. MSSM_10.14.tgz).
hosting_notes: author's personal MSU page (Alexander Pukhov; Belyaev/Christensen co-authors); no official git (github.com/restrepo/calchep is third-party, near-dead); Launchpad only hosts Q&A/bug tracker.
language: C
license: GPL-3 (page links gnu.org/licenses/gpl.html)
pip_conda: no
priority: high — model-file format (.mdl) and the engine under micrOMEGAs; agents recasting need to read/write its model files.

### FeynHiggs
category: spectrum-calc
role: MSSM Higgs-sector masses, mixings, couplings, EWPO and uncertainties (diagrammatic fixed-order + EFT + hybrid), with SLHA I/O for HB/HS.
source: https://wwwth.mpp.mpg.de/members/heinemey/feynhiggs/newversion/FeynHiggs-2.18.1.tar.gz (type: tarball)
latest_stable: 2.18.1 (1 Jul 2021) — newest offered on the page is 2.19.0-**beta** (6 Oct 2022); per catalog rules the stable line is 2.18.1.
version_scheme: tarball named FeynHiggs-X.Y.Z.tar.gz under .../newversion/ (no git); static executables also provided per version.
hosting_notes: canonical pages under wwwth.mpp.mpg.de/members/heinemey/feynhiggs/ (history.html, cFeynHiggs.html); the feynhiggs.de vanity domain did not respond to my fetch — use the MPP URL for automation.
language: Fortran
license: free academic use (usage/citation terms on the page; license text in tarball; not OSI)
pip_conda: no
priority: medium — the MSSM-Higgs precision reference; used inside DarkSUSY/SuperIso Relic builds rather than standalone in recast chains.

### HiggsBounds
category: validation
role: applies LEP/Tevatron/LHC Higgs search limits (cross-section upper limits) to arbitrary BSM Higgs sectors; standard SLHA-driven exclusion engine.
source: https://gitlab.com/higgsbounds/higgsbounds.git (type: git)
latest_stable: 5.10.2 (13 Dec 2021) — standalone Fortran line frozen since; active development moved to HiggsTools.
version_scheme: plain X.Y.Z git tags (no "v" prefix); GitLab release assets higgsbounds-5.10.2.tar.gz/.zip.
hosting_notes: hosting MOVED hepforge → GitLab (gitlab.com/higgsbounds/*); docs at higgsbounds.gitlab.io; Fortran95+cmake; test suite needs pytest/numpy/pandas.
language: Fortran
license: GPL-3
pip_conda: no
priority: medium — the HB5 library/SLHA interface is still embedded in current chains (FlexibleSUSY, micrOMEGAs links), but new constraint logic lives in HiggsTools.

### HiggsSignals
category: validation
role: χ² statistical test of predicted Higgs signal rates/masses against Tevatron+LHC measurements (Run-2 era database).
source: https://gitlab.com/higgsbounds/higgssignals.git (type: git)
latest_stable: 2.6.2 (28 Sep 2021) — frozen; successor = HiggsTools (same collaboration).
version_scheme: plain X.Y.Z git tags; GitLab release tarballs higgssignals-2.6.2.tar.gz.
hosting_notes: builds on top of a compiled HiggsBounds (found via CMake / HiggsBounds_DIR); depends on HB ≥5.9 for current database; documentation higgsbounds.gitlab.io/higgssignals.
language: Fortran
license: GPL-3
pip_conda: no
priority: medium — historical χ² interface still referenced by global-fit tools; for new work navigate HiggsTools instead.

### Lilith
category: validation
role: likelihood of a light Higgs from measured signal strengths/mass (Run-1 + partial Run-2 databases in .list format); commonly chained after SPheno/FeynHiggs.
source: https://github.com/sabinekraml/Lilith-2.git (type: git)
latest_stable: v2.1db22.01 (tag; commit dated 2022-01-28 — code 2.1 with database 22.01)
version_scheme: tags v2.XdbYY.MM (code version + database version concatenated, e.g. v2.0.0db19.09, v2.1db22.01); betas tagged -beta.1.
hosting_notes: repo maintained by the Lilith-2 authors' group (Kraml et al.); FlexibleSUSY links it directly (--with-lilith); lilith.hepforge.org is the legacy page (Anubis-blocked).
language: Python
license: GPL-3
pip_conda: no
priority: medium — lightweight, easily embedded likelihood step; smaller codebase, cheap to index.

### SuperIso
category: stat-interpretation
role: flavour-observables calculator (b→sγ, B→K(*)ℓℓ, Bs→μμ, kaons, g-2 …) for SM/2HDM/MSSM/NMSSM from SLHA; companion SuperIso Relic adds relic density/BBN; automatic theory-error/correlation (χ²) machinery.
source: https://superiso.in2p3.fr/download/ → POST form (download1.php) delivering `superiso_v5.0.tgz` (type: tarball)
latest_stable: v5.0 (23 Nov 2025); companion SuperIso Relic latest 4.1 (4 Nov 2020, `superiso_relic_v4.1.tar.bz2`) — relic line lags (still bundles FeynHiggs 2.16.1).
version_scheme: tarball named superiso_vX.Y.tgz; relic named superiso_relic_vX.Y.tar.bz2 — served via POST form, filenames confirmed in page HTML.
hosting_notes: plain static site, no git, no CDN; download1.html and download.html URLs are broken (500) — use /download/; relic flavour embeds FeynHiggs/HDECAY/AlterBBN copies (slow static build pre-2.8 merged).
language: C (Relic: C+Fortran)
license: not stated on site — free academic use, terms in tarball
pip_conda: no
priority: medium — the flavour-constraint leg of BSM global scans (GAMBIT FlavBit lineage); index the Wilson-coefficient core.

### HiggsTools
category: validation
role: active successor combining HiggsBounds + HiggsSignals + HiggsPredictions (+ SusHi): unified C++/Python framework applying Higgs searches, signal-strength χ² and XS/BR predictions to arbitrary scalar sectors.
source: https://gitlab.com/higgsbounds/higgstools.git (type: git)
latest_stable: v1.3 (17 Sep 2026; prior v1.2 8 May 2024)
version_scheme: vX.Y git tags (+ vX.Y.Z point tags for fixes, e.g. v1.1.4); GitLab release archives higgstools-v1.3.tar.gz.
hosting_notes: GitLab group higgsbounds; same team as HB/HS; FlexibleSUSY 2.9 links it natively; C++ core with Python interface (SLHA/HB5-style input), Fortran interface supported.
language: C++ (+ Python interface)
license: GPL-3
pip_conda: no PyPI/conda package found — build from source (cmake)
priority: high — where all new Higgs-constraint development happens; an agent doing 2026-era recasting should navigate this, not frozen HB5/HS2.

---

## Lane summary (Tier-1 picks)
1. SARAH + SPheno (paired) — the model→spectrum backbone of nearly every BSM chain; plain-text .m + Fortran trees, both indexable, both Anubis-walled on hepforge (need direct tarball ingestion).
2. FeynRules — UFO generation for MadGraph/MadDM; small plain-.m repo with clean `fr-X.Y.Z` tags; highest navigability per unit of recast value.
3. micrOMEGAs — default DM observables engine (7.1 current); API-level navigation (calcOmega etc.) is what recast agents actually call.
4. MadDM — UFO-native DM plugin with tidy vX.Y.Z GitHub tags; smallest barrier to automated pipeline integration of the DM leg.
5. HiggsTools — actively maintained constraint successor (v1.3, Sep 2026); index it instead of investing further in frozen HiggsBounds-5/HiggsSignals-2.

Notable lane facts: SoftSUSY moved to GitHub (4.1.24, Sep 2026); micrOMEGAs jumped to 7.1; SuperIso hit v5.0 (Nov 2025); FeynArts 3.12 released Aug 2026; CalcHEP 3.9.2 (Mar 2025) still tarball-only on a personal MSU page; FeynHiggs's "newest" is a beta so 2.18.1 remains the stable pin.

## Contradictions / unresolved
- SARAH latest: 4.15.2 (FlexibleSUSY pin, Apr 2025) vs 4.15.4 (mirror SARAH.m) — unresolved, hepforge changelog bot-blocked.
- SPheno 4.0.7 upstream release date unverifiable (Anubis); conda-forge packaged it 2026-05.
- SPheno license: BSD-4-Clause (tarball LICENSE via conda recipe) vs Gentoo "all-rights-reserved" label.
- DarkSUSY 6.4.1 details (date 2024-08-26, sizes) from cached search snippets of the blocked hepforge page, not read directly.
# Research: LANE B — Matrix-element generators, parton showers, hadronization (hep-index catalog map)

## Summary
12 entries: the seed packages plus the obviously-missing sibling MadGraph5_aMC@NLO (the LO/NLO automation workhorse that hosts MadSpin/ALOHA) and one-loop ME providers (OpenLoops, GoSam, Recola2). Two big hosting facts dominate the lane: POWHEG-BOX migrated from anonymous SVN to GitLab submodules (SVN frozen read-only end of June 2025), and Sherpa now releases from GitLab (3.0.5, Jul 2026) with Herwig/MCFM/VBFNLO quirks noted per entry. All Hepforge download pages sit behind an anti-bot (Anubis) wall that blocks scripted fetches but not browsers — noted where it prevented direct verification.

---

### Sherpa
category: me-generator
role: Multi-leg LO/NLO ME + parton shower (Dire-based) + cluster hadronization event generator with ME merging, used widely for DM/BSM and recast backgrounds
source: https://gitlab.com/sherpa-team/sherpa.git (type: git)
latest_stable: 3.0.5 — released 2026-07-22 (GitLab tag v3.0.5)
version_scheme: vX.Y.Z git tags (e.g. v3.0.5); source tarball attached to each GitLab release page; also `rel-a-b-c` release branches carrying backported fixes
hosting_notes: Canonical hosting moved to GitLab (sherpa-team/sherpa); legacy sherpa.hepforge.org. Docs at sherpa-team.gitlab.io (changelog.html lists all 3.0.x). Large C++ codebase (~thousands of files). GitLab releases also provide the tarball, so `git clone -b rel-3.0.5` and release tarball both work.
language: C++
license: GPL-3.0
pip_conda: no official package — IMPORTANT: PyPI `sherpa` is a completely different package (CIAO statistics/fitting); do not index that as this project. Source checkout is the only option.
priority: high — standard generator for merged MEPS samples, DM EFT signals and backgrounds in recast workflows; Dire shower ships inside (no separate entry needed)

### Herwig 7
category: me-generator
role: Angular-ordered (and dipole) parton shower + cluster hadronization event generator with NLO matching (POWHEG/Matchbox), now with EW showers and dark-sector hadronization
source: https://gitlab.com/herwig/herwig.git (type: git); tarballs at https://herwig.hepforge.org/downloads
latest_stable: 7.3.0 — released 2023-12-11 (NEWS entry; 7.3 release note EPJC s10052-024-13211-9, Oct 2024; no 7.3.1 found as of this research, Dec 2025 write-up arXiv:2512.16645 still says current = 7.3)
version_scheme: tarball named Herwig-7.X.Y.tar.gz from herwig.hepforge.org/downloads; GitLab tags exist but exact tag string not verified — hepforge page is behind an Anubis anti-bot wall that blocked scripted fetch
hosting_notes: herwig.hepforge.org is Anubis-walled (scripted fetch returns a bot challenge) — use a real browser or the GitLab repo. github.com/hep-mirrors/herwig is a THIRD-PARTY mirror (useful to read NEWS, not canonical — do not index). Repo is large (C++ + ThePEG dependency stack).
language: C++
license: GPL-3.0
pip_conda: no
priority: high — cluster hadronization + BSM decays and Matchbox NLO machinery make it the complement to Pythia/Sherpa for recast systematics

### MadGraph5_aMC@NLO (incl. MadSpin and ALOHA)
category: me-generator
role: Automated LO/NLO event generation for any UFO Lagrangian, FKS/MLM matching to showers; MadSpin (spin-correlated decays) and ALOHA (analytic helicity amplitude output) ship INSIDE this codebase — not standalone packages
source: https://github.com/mg5amcnlo/mg5amcnlo.git -b 3.x (type: git; the project itself links this repo from its Launchpad page); tarballs at https://launchpad.net/mg5amcnlo/+download
latest_stable: 3.8.0 "Density" — series 3.8.x released 2026-09-14; LTS line is 3.5.x, current tarball MG5_aMC_v3.5.16.tar.gz
version_scheme: tarball named MG5_aMC_vX.Y.Z.tar.gz (LTS files named MG5_aMC_v3.5.x.tar.gz) from launchpad.net/mg5amcnlo/+download; git branch `3.x` (tag scheme unverified). MadGraph7 is separately listed as MG7_v0.2.0.tar.gz (alpha — do not catalog as stable).
hosting_notes: Registration wall exists ONLY on the historical UCL portal (madgraph.phys.ucl.ac.be Register/download.cgi); anonymous download works fine via Launchpad files and the GitHub mirror-repo. Bugs tracked on Launchpad. Tarball is large. Version line moved fast: 3.7.x (Jan 2026) → 3.8.x (Sep 2026).
language: Python / Fortran / C++
license: UoI-NCSA (per Launchpad project info)
pip_conda: no; source checkout essential — code navigation covers MadSpin/ALOHA/MadGraph4 GPU attempts in-repo
priority: high — THE BSM workhorse (UFO models, reweighting, MadSpin decays); every recast pipeline touches it

### POWHEG-BOX (V1/V2/RES)
category: me-generator
role: NLO+PS matched generators (POWHEG method) for a curated process library incl. many BSM/EFT processes (DM monojet, SMEFT, weakinos, leptoquarks), matched to Pythia/Herwig showers
source: https://gitlab.com/POWHEG-BOX/V2/POWHEG-BOX-V2.git (type: git; RES: https://gitlab.com/POWHEG-BOX/RES/POWHEG-BOX-RES.git); legacy anonymous SVN: svn://powhegbox.mib.infn.it/trunk/POWHEG-BOX-V2 (username/password `anonymous`)
latest_stable: No tagged releases at all — never had them. Identified by SVN revision (latest referenced: rev 4079, Sep 2024, per homepage notes on ggHH_SMEFT) / Git default branch + submodule pins. RES is now the recommended line; V2 still developed.
version_scheme: none — SVN revision numbers historically; now Git default branch of each V1/V2/RES repo with each process as a separate Git submodule (`git submodule update --remote`)
hosting_notes: MAJOR MOVE: SVN frozen read-only since end of June 2025; development now on gitlab.com/POWHEG-BOX/* (V1, V2, RES + per-process repos as submodules; migration tool at gitlab.com/powheg-testing/powheg2git). Anonymous download EXISTS for both legacy SVN (anonymous/anonymous) and GitLab — never a registration-walled tarball despite lore; the historical pain was the enormous SVN checkout (fixed by NoUserProcesses dir, then by modular Git). Issues tracked at gitlab.com/groups/POWHEG-BOX/-/issues.
language: Fortran
license: POWHEG-BOX license (see powhegbox.mib.infn.it/AAAREADME-LICENSE) under MCnet Guidelines — custom, not plain GPL
pip_conda: no
priority: high — recast-standard for ttbar/V+jets/Higgs NLO+PS signal modeling; the SVN→Git move means catalogs must update their fetch recipe now

### WHIZARD
category: me-generator
role: ME generator/fragmentation-free event generator for multi-leg processes at LO/NLO (incl. beam spectra), main tool for e+e- (ILC/CLIC/FCC-ee) and BSM studies there
source: https://gitlab.tp.nt.uni-siegen.de/whizard/public.git (type: git; self-hosted GitLab)
latest_stable: 3.1.8 — released 2026-03-03 (tag v3.1.8; Launchpad series table)
version_scheme: vX.Y.Z git tags at the self-hosted GitLab; tarball named whizard-X.Y.Z.tar.gz (e.g. whizard-3.1.8.tar.gz) from launchpad.net/whizard/+download; hepforge mirrors
hosting_notes: Split hosting: code on a SELF-HOSTED GitLab (gitlab.tp.nt.uni-siegen.de/whizard/public — unusual, not gitlab.com), releases/tarballs on Launchpad, legacy site whizard.hepforge.org (Anubis-walled for scripts). 3.2.x is the development focus. Fortran+OCaml toolchain makes builds nontrivial.
language: Fortran 2008 + OCaml
license: GPL-3.0 (per Launchpad project info)
pip_conda: no
priority: medium — indispensable for e+e- BSM phenomenology; lower priority for LHC-centric recast lanes

### Pythia 8 (hosting update — already catalogued at 8.3.17)
category: me-generator
role: String-fragmentation hadronization + pT/dipole showers event generator, the universal shower/hadronization backend for MG5/POWHEG/Herwig recast chains
source: https://gitlab.com/Pythia8/releases.git (type: git, branch pythia8XXX per release); tarball pythia83XX.tgz from https://pythia.org/releases/
latest_stable: pythia.org/releases/ (cached) says 8.317 (2026-01-20), BUT official PyPI package `pythia8mc` is at 8.318.2 referencing pythia.org/download/pythia83/pythia8318.tgz → 8.318 has shipped; catalogued 8.3.17 is one patch behind — verify 8.318 date directly on pythia.org (site 403-blocks scripted fetch)
version_scheme: tarball named pythia83XX.tgz (no dots: pythia8317.tgz) from pythia.org; GitLab repo `Pythia8/releases` with per-release branches named pythia8XXX
hosting_notes: Moved off hepforge to own domain pythia.org; official PyPI package `pythia8mc` (new, semver 8.318.x) is the notable 2025/26 addition — pip now viable, still worth a source checkout for code navigation
language: C++
license: GPL-2.0-or-later (per PyPI metadata COPYING)
pip_conda: yes — `pip install pythia8mc` (official team package); source checkout still worth indexing for Vincia/Dire plugin navigation
priority: high — hadronization + shower ground truth for every recast; update catalog entry to 8.318 if confirmed

### Vincia
category: parton-shower
role: Antenna-shower formalism (QCD+QED/EW, helicity-dependent, with uncertainties) originally a standalone Pythia 8 plugin, now shipped INSIDE the Pythia 8.3 source tree
source: none current — ships inside https://gitlab.com/Pythia8/releases.git (Pythia ≥8.300); historical standalone tarballs from https://vincia.hepforge.org (type: tarball, legacy)
latest_stable: No active standalone line — incorporated into Pythia 8.3 since version 8.300 (per pythia.org VINCIA manual: "incorporated into the Pythia 8 source code since Pythia version 8.300"). Last standalone series distributed via hepforge: 2.2.x (e.g. 2.2.04, the version LCG ships) for Pythia 8.2.
version_scheme: standalone: vincia-X.Y.ZZ tarballs (e.g. vincia-2.2.04) from vincia.hepforge.org; current: version rides the pythia83XX tarball (Vincia.h inside include/Pythia8/)
hosting_notes: vincia.hepforge.org is Anubis-walled (scripted fetch blocked). Do NOT create a separate Vincia checkout for navigation — index Pythia 8.3 and you have Vincia. Standalone 2.2.04 remains what LCG/cvmfs pins.
language: C++
license: GPL-2.0-or-later + MCnet guidelines
pip_conda: via pythia8mc (Vincia included in Pythia source)
priority: low-medium — fully covered by the Pythia 8 catalog entry; only catalog separately if you want the legacy 2.2.x line

### MCFM
category: me-generator
role: Parton-level NLO/NNLO(N3LO) generator for benchmark collider processes (V+jets, diboson, ttbar, HH with full mt and SMEFT, Higgs EFT ops)
source: https://gitlab.com/mcfm-team/releases.git (type: git); official tarball MCFM-10.3.tar.gz from https://mcfm.fnal.gov
latest_stable: 10.3 — January 2023 (per mcfm.fnal.gov "MCFM-10.3.tar.gz (January 2023)")
version_scheme: git tags MCFM-X.Y.Z (e.g. MCFM-10.2.1); tarball MCFM-X.Y.tar.gz (note: no patch component, MCFM-10.3.tar.gz) from mcfm.fnal.gov
hosting_notes: QUIRK: the GitLab repo's master/last tag stops at MCFM-10.2.1 (2022-06-24) while the website distributes MCFM-10.3 (Jan 2023) — 10.3 exists as tarball only, not visibly tagged in the repo. Don't assume git HEAD == released code. Repo moderate size.
language: Fortran / C++
license: GPL-3.0 (LICENSE file in repo)
pip_conda: no
priority: medium — precise SM/HH/EFT references for validating recast assumptions, not an event-record generator

### OpenLoops
category: me-generator
role: One-loop (NLO virtual) amplitude library providing the V-part to Sherpa/Herwig/WHIZARD/POWHEG NLO runs; loop-induced processes (gg→HH/VV)
source: https://gitlab.com/openloops/OpenLoops.git (type: git — recommended route)
latest_stable: 2.1.5 — released 2025-09-19 (GitLab tag OpenLoops-2.1.5)
version_scheme: git tags OpenLoops-X.Y.Z (OpenLoops-2.1.5); tarball OpenLoops-X.Y.Z.tar.gz from openloops.hepforge.org/downloads (hepforge list still showed 2.1.4 at fetch time — slight lag vs GitLab)
hosting_notes: git clone is the recommended install because process libraries are downloaded separately at install time (`./openloops libinstall ...`) — the source repo alone does NOT contain the physics process code. openloops.hepforge.org is Anubis-walled for scripts.
language: C++ / Fortran
license: GPL-3.0 (per project repo — verify in LICENSE on clone)
pip_conda: no
priority: medium — the default loop provider behind most Sherpa/Herwig NLO recast samples; index for navigation of the BLHA interface

### GoSam
category: me-generator
role: Automated one-loop amplitude generator (Python codegen → Fortran process libraries) used as BLHA OLP by Sherpa/POWHEG/WHIZARD; strong EFT support
source: https://github.com/gudrunhe/gosam.git (type: git)
latest_stable: 3.0.3 (latest tag; 3.0.0 major rewrite released Jul 2025, arXiv:2507.23549; 3.0.1–3.0.3 are patches, 3.0.3 adds Apple M-series support — its exact date is not shown on the releases page)
version_scheme: vX.Y.Z git tags at github.com/gudrunhe/gosam (v3.0.0…v3.0.3); releases page attaches archives like gosam-3.0.3; installer script gosam_installer.py
hosting_notes: Project moved from hepforge (gosam.hepforge.org, now Anubis-walled) to GitHub (gudrunhe/gosam) incl. the gosam-contrib integral libraries. Integral libraries (gosam-contrib) are a separate install.
language: Python / Fortran
license: GPL-3.0-or-later (README wording "version 3 ... any later version")
pip_conda: no pip package; the installer script fetches deps
priority: low-medium — alternative to OpenLoops/Recola; only needed when a specific loop-induced/EFT process is unavailable elsewhere

### Recola2
category: me-generator
role: One-loop (and tree) amplitude generator with strong resonance-aware NLO EW/QCD support, used via BLHA by Sherpa/Herwig/WHIZARD/POWHEG-RES
source: https://gitlab.com/recola/recola2.git (type: git)
latest_stable: 2.3.0 — tag dated 2026-01-19 (GitLab release 2.3.0)
version_scheme: plain X.Y.Z git tags (2.3.0); standalone tarball recola2-2.3.0.tar.gz listed on recola.hepforge.org/downloads; docs at recola.gitlab.io
hosting_notes: Recola2 needs COLLIER and separate Recola2 model files (recola2-2.x.y modelfiles) as external tarballs — repo alone is not buildable. recola.hepforge.org is Anubis-walled for scripts. License NOT stated on the GitLab tags page — check AAAREADME/LICENSE inside the tarball before asserting (unverified here).
language: Fortran
license: unverified — per-package license text inside distribution (not shown on GitLab page fetched)
pip_conda: no
priority: low-medium — matters for NLO-EW precision (WZjj/VBS-type recasts), niche for a general BSM lane

### VBFNLO
category: me-generator
role: NLO parton-level generator specialized in electroweak boson-fusion/vector-boson-scattering processes with anomalous-coupling/EFT parameter scans
source: https://github.com/vbfnlo/vbfnlo.git (type: git)
latest_stable: 3.0 — tag v3.0 dated 2024-06-20 (repo README states release 27 May 2024; both are 2024)
version_scheme: vX.Y git tags (v3.0; betas were v3.0.0betaN); historical tarball VBFNLO-2.7.1.tgz naming; current release downloads at ific.uv.es/vbfnlo/downloads.html
hosting_notes: Hosting MOVED: from KIT (itp.kit.edu/vbfnlo wiki) to github.com/vbfnlo with a new site at ific.uv.es/vbfnlo. Effectively one stable release since 2024 after 6 years of betas — treat as low-activity. GPL statement is on the project docs; exact version string not re-verified (repo LICENSE filename not fetched).
language: Fortran
license: GNU GPL (per project docs; version not pinned on pages fetched)
pip_conda: no
priority: low — superseded for most BSM work by MG5/WHIZARD VBS implementations; keep only for legacy anomalous-coupling studies

---

## Contradictions
- **Pythia 8.317 vs 8.318**: pythia.org/releases (cached snippet) lists 8.317 (2026-01-20) as latest, while the official PyPI `pythia8mc` package is at 8.318.2 pointing at pythia.org/download/pythia83/pythia8318.tgz. Direct fetch of pythia.org is bot-blocked (403), so 8.318's release date is unverified. — sources: pythia.org/releases, pypi.org/project/pythia8mc/8.318.2
- **MCFM 10.3 vs repo**: website distributes MCFM-10.3.tar.gz (Jan 2023) but gitlab mcfm-team/releases master and tags stop at MCFM-10.2.1 (Jun 2022). — sources: mcfm.fnal.gov/OverviewofMCFM.html, gitlab.com/mcfm-team/releases/-/tags
- **VBFNLO 3.0 dates**: README "27 May 2024" vs git tag v3.0 "Jun 20, 2024". — sources: github.com/vbfnlo/vbfnlo, tags page

## Missing evidence
- Herwig exact git tag string and tarball filename for 7.3.0 (Anubis wall blocked hepforge downloads page; no 7.3.1 found but not disproven).
- Pythia 8.318 official release date (pythia.org 403 for scripts).
- Recola2 license text (not visible on GitLab; inside tarball).
- GoSam 3.0.3 exact release date (releases page shows no dates for 3.0.x).
- POWHEG "latest" revision — no tag exists; newest process (VBF_HH, arXiv:2502.09112, Feb 2025) postdates the highest cited revision number 4079; current Git HEAD is the only truth.
- MadGraph5_aMC git tag naming scheme (branch 3.x confirmed; whether tags like 3.8.0 exist on the GitHub repo not checked).

## Sources
- Kept: GitLab sherpa-team tags/releases (version+dates), sherpa-team.gitlab.io changelog — Sherpa 3.0.5/2026-07-22
- Kept: hep-mirrors/herwig NEWS + arXiv:2312.05175 + EPJC 7.3 note — Herwig 7.3.0/2023-12-11 (mirror used only as evidence, not as canonical source)
- Kept: launchpad.net/mg5amcnlo (+download, bugs) — MG5 3.8.0/2026-09-14, LTS 3.5.16, UoI-NCSA license, github mg5amcnlo/mg5amcnlo
- Kept: powhegbox.mib.infn.it (full homepage fetch) — SVN frozen Jun 2025, GitLab migration, anonymous access, license link
- Kept: launchpad.net/whizard (+download, series page) + gitlab.tp.nt.uni-siegen.de/whizard/public tags — WHIZARD 3.1.8/2026-03-03, GPL-3
- Kept: pythia.org/releases + pypi.org/project/pythia8mc — 8.317/8.318 conflict, PyPI package, GitLab releases repo
- Kept: pythia.org VINCIA manual — Vincia incorporated since Pythia 8.300; LCG info vincia 2.2.04
- Kept: mcfm.fnal.gov + gitlab mcfm-team releases tags/branches — MCFM 10.3/10.2.1 discrepancy
- Kept: gitlab.com/openloops/OpenLoops tags + openloops.hepforge.org/downloads — 2.1.5/2025-09-19
- Kept: github.com/gudrunhe/gosam releases + Readme — GoSam 3.0.3, hepforge→github move
- Kept: gitlab.com/recola/recola2 tags + recola.gitlab.io — Recola2 2.3.0/2026-01-19
- Kept: github.com/vbfnlo/vbfnlo tags + ific.uv.es/vbfnlo — VBFNLO 3.0/2024, hosting move
- Rejected: coinmarketcap/coingecko "Pythia" crypto pages — name collision noise
- Rejected: Tracxn "Dr. Herwig" company pages — name collision noise
- Rejected: github.com/hep-mirrors/herwig as a source field — unofficial mirror; used only to read NEWS

## Lane summary (Tier-1 priorities)
1. **MadGraph5_aMC@NLO** — highest traffic for BSM/recast agents; UFO-in, events-out; covers MadSpin/ALOHA so no separate entries; catalog both 3.8.0 and LTS 3.5.16.
2. **Sherpa 3.0.5** — recast-standard merging generator; new GitLab-native hosting with clean vX.Y.Z tags makes indexing cheap.
3. **POWHEG-BOX** — required for NLO+PS signal modeling; the 2025 SVN→GitLab move means any existing SVN-based recipe is dead — index the new V2/RES Git repos + submodule scheme.
4. **Pythia 8.318 (update)** — already catalogued but one patch behind and now pip-installable (pythia8mc); update entry, Vincia rides along inside it.
5. **Herwig 7.3.0** — second hadronization model + EW shower/dark-hadronization options; Tier-1 for shower-systematics navigation; note the Anubis wall on its hepforge downloads.
# Lane C — Detector sim, analysis/validation frameworks, recast engines, statistics

Researched 2026 (all versions verified against upstream GitLab/GitHub release APIs unless noted). 15 entries = 14 seeds + Delphes (obvious missing sibling for detector-sim). MadAnalysis 5 skipped per instructions (already catalogued v1.11.1; no new hosting facts found — canonical repo remains github.com/MadAnalysis/madanalysis5).

Hosting-migration headline: the entire "Cedar" suite (Rivet, YODA, Contur, LHAPDF, Professor) moved from HepForge SVN to **gitlab.com/hepcedar**; HepForge sites remain as front doors (several now behind Anubis anti-bot walls). SModelS, CheckMATE, HistFitter, Delphes live on GitHub. GAMBIT distributes via GitHub org with **per-major-version repos** (unusual). xFitter's primary repo is on CERN GitLab with a gitlab.com public mirror. fastNLO dev repo is on KIT GitLab (web UI returns 403 to bots; git clone should still work).

### Rivet
category: validation
role: Generator-independent validation & detector-level analysis framework; the de-facto library of implemented LHC/LEP/Belle measurements for MC validation and reinterpretation.
source: https://gitlab.com/hepcedar/rivet.git (type: git)
latest_stable: 4.1.4 (2026-09-10, release "v4.1.4", tag `rivet-4.1.4`)
version_scheme: git tags named `rivet-X.Y.Z`; tarballs `Rivet-4.1.4.tar.gz` from rivet.hepforge.org downloads (Anubis-walled) — pin by GitLab tag.
hosting_notes: Canonical: gitlab.com/hepcedar/rivet. Migrated from HepForge SVN (old rivet.hepforge.org is legacy front door). Medium-large repo (~100 MB order); releases carry long changelogs. No auth wall on GitLab.
language: C++ (Python bindings)
license: GPL-3.0
pip_conda: conda-forge yes (rivet), pip no; source checkout still worth indexing — analysis routines (`src/Analyses/`) are the physics payload and only fully present in git.
priority: high — the analysis-routine corpus is exactly what a recast agent must read to map BSM signals onto published measurements.

### YODA
category: analysis-framework
role: Histogramming/profile/statistics library underlying Rivet & Contur (and others); persistent object model for binned observables.
source: https://gitlab.com/hepcedar/yoda.git (type: git)
latest_stable: 2.1.4 (2026-09-10, tag `yoda-2.1.4`)
version_scheme: git tags named `yoda-X.Y.Z`; tarballs `yoda-2.1.4.tar.gz`.
hosting_notes: Same hepcedar GitLab group as Rivet; released in lockstep with Rivet 4.1.x (YODA 2.x series broke API vs YODA 1.x — keep major version pinned to Rivet's requirement). Small-to-medium repo, no walls.
language: C++ (Python bindings)
license: GPL-3.0
pip_conda: conda-forge yes (yoda), pip no; checkout useful mainly as reference for Contur/Rivet data formats — index second-tier.
priority: medium — library plumbing for the lane; navigate when extending binning/statistics behavior, not usually first stop for recasting.

### Contur
category: recast-engine
role: Reinterprets Rivet-implemented measurements to constrain BSM models via likelihoods over normalized distributions (runs MadGraph+Pythia+Rivet internally).
source: https://gitlab.com/hepcedar/contur.git (type: git)
latest_stable: 3.1.5 (2026-09-25, tag `contur-3.1.5`)
version_scheme: git tags named `contur-X.Y.Z` (releases also named, e.g. 3.1.4 "Lunga"); tarballs via releases page.
hosting_notes: gitlab.com/hepcedar/contur; docs at hepcedar.gitlab.io/contur. Requires matching Rivet/YODA versions (3.1.4 ↔ Rivet 4.1.3/YODA 2.1.3). Python codebase, moderate size, no walls.
language: Python
license: GPL-3.0 (stated; LICENSE not found at repo-root paths checked — unverified)
pip_conda: yes — `pip install contur` and conda-forge; source checkout still worth indexing for run-config templates and the pool of analysis-to-observable mappings.
priority: high — direct BSM-constraint engine that chains the rest of the lane (MG5+Pythia+Rivet+Spey); agent must read its config/rivet mapping layer.

### Delphes
category: detector-sim
role: Fast parametric multipurpose detector simulation (jets, isolation, MET, b/τ-tagging via cards) — the standard engine underneath recast tools.
source: https://github.com/delphes/delphes.git (type: git)
latest_stable: 3.5.1 (2026-02-04, tag `3.5.1`; a 3.5.2pre01 pre-release exists — ignore)
version_scheme: plain `X.Y.Z` git tags (no `v` prefix); tarballs `delphes-3.5.1.tar.gz` linked from delphes.github.io/releases.
hosting_notes: GitHub org delphes (canonical since the HepForge era ended). Small repo (~23 MB git size), no walls. GitHub language stats say "Tcl" (build system noise) — code is C++.
language: C++ (Tcl build)
license: GPL-3.0 (repo shows non-SPDX; COPYING is GPLv3)
pip_conda: conda-forge yes, pip no; checkout worth indexing — detector cards and modules are where recast fidelity lives.
priority: high — every CheckMATE/MA5-style recast flows through Delphes cards and modules; agents tune cards constantly.

### CheckMATE
category: recast-engine
role: Reinterprets simulated BSM events against reimplemented ATLAS/CMS searches (Delphes-based detector sim + SR likelihoods r-values).
source: https://github.com/CheckMATE2/checkmate2.git (type: git)
latest_stable: v2.5.4 (published 2026-04-01 per GitHub release metadata; adds pyhf-json/HS3 statistical models, ONNX NN searches)
version_scheme: `vX.Y.Z` git tags + GitHub Releases; legacy tarballs from checkmate.hepforge.org (stale — prefer GitHub).
hosting_notes: GitHub org CheckMATE2; large-ish repo (~290 MB git size) because bundled analysis data. Legacy hepforge site effectively dead. Beware unrelated GitHub project "Checkmate v3.9.2" (bluewave-labs monitoring tool) — not this CheckMATE. Separate LLP repo: CheckMATE2/checkmate2-LLP.
language: C++ (Python drivers)
license: GPL-2.0
pip_conda: no
priority: high — one of the two workhorse collider-recast engines; agent must read analysis/validation code (SR definitions, likelihood handling).

### SModelS
category: recast-engine
role: Decomposes BSM spectra into simplified-model topologies and confronts them with a database of ATLAS/CMS limits (efficiency-map or likelihood).
source: https://github.com/SModelS/smodels.git (type: git)
latest_stable: 3.2.0 (2026-09-02, release "v3.2.0", tag `3.2.0`; first NN-surrogate/ONNX statistical-model support, breaks database format compat)
version_scheme: tags named `X.Y.Z` (no `v` prefix in tag, release name carries v); tarballs from smodels.hepforge.org/downloads.
hosting_notes: GitHub org SModelS (canonical dev); smodels.github.io docs; smodels.hepforge.org legacy. Medium repo (~350 MB git size — includes database bits). Python.
language: Python
license: GPL-3.0 (per project docs; LICENSE not detected in repo root by GitHub API — flag for verification)
pip_conda: pip yes (`pip install smodels`); source checkout still worth indexing — theory/particle database parsers and likelihood interface (`.nlls` since 3.2.0) live only fully in git.
priority: high — complementary recast engine to CheckMATE (simplified-model limit maps); agent must navigate decomposition + database formats.

### pyhf
category: stat-interpretation
role: Pure-Python HistFactory likelihood construction and inference (CLs, asymptotics), the exchange format for publishing experimental statistical models.
source: https://github.com/scikit-hep/pyhf.git (type: git)
latest_stable: v0.7.6 (2024-01-05 — no newer non-prerelease as of 2026-09; release cadence has slowed but v0.7.6 remains API-stable)
version_scheme: `vX.Y.Z` tags + GitHub Releases; PyPI `pyhf`.
hosting_notes: GitHub scikit-hep org (canonical); tiny repo (~8 MB), no walls.
language: Python
license: MIT
pip_conda: yes (pip + conda-forge); checkout marginally useful — the docs/tutorials cover most needs — but indexing gives access to `pyhf/src/pyhf/` likelihood kernels for debugging JSON models.
priority: high — every modern recast consumes pyhf JSON; agent must understand spec schema and optimizer backends to reproduce limits.

### Spey
category: stat-interpretation
role: Smooth-likelihood inference library for reinterpretation (pyhf-style and covariance-matrix models) used inside Contur; multi-POI fits, CLs/likelihood contours.
source: https://github.com/SpeysideHEP/spey.git (type: git)
latest_stable: v0.2.7 (2026-07-28, tag `v0.2.7`; adds multi-POI fitting)
version_scheme: `vX.Y.Z` tags + GitHub Releases; PyPI `spey`. (Docs site lags: readthedocs showed 0.2.6 — trust GitHub.)
hosting_notes: GitHub SpeysideHEP org (canonical). Tiny repo (~8 MB).
language: Python
license: MIT
pip_conda: pip yes; source checkout small and cheap to index if you also index Contur, whose fitting it powers.
priority: medium — the statistical backend for Contur; index alongside Contur for likelihood-reproduction debugging.

### GAMBIT
category: global-fit
role: Modular global-fit framework for BSM theories (Bayesian likelihoods over observables incl. collider, DM, flavor) with scanner, prior and backend management.
source: https://github.com/GambitBSM/gambit_2.5.git (type: git; default branch `release_2.5`)
latest_stable: v2.5.1 (tag; repo last push 2024-07-18 — treat as current stable line; no newer GitHub release objects exist)
version_scheme: `vX.Y.Z` tags inside per-major-version repos (`gambit_2.0`, `gambit_2.2`, `gambit_2.5`); release tarballs historically from gambit.hepforge.org (Anubis-walled).
hosting_notes: Unusual hosting: one GitHub repo per major version under org GambitBSM; `gambit_2.0` repo is a dormant 2021 snapshot (~608 MB), `gambit_2.5` is the live one (~842 MB — big; shallow clone recommended). gambit.hepforge.org remains the website. License not auto-detectable (no LICENSE/COPYING at repo root checked) — verify before redistribution.
language: C++ (CMake, some Fortran backends)
license: unverified (not detected; project distributes under its own terms — check repo/docs)
pip_conda: no
priority: medium — heavyweight but central to BSM global fits; index `Models/` and `Likelihoods/` dirs via shallow clone.

### HistFitter
category: stat-interpretation
role: ATLAS-style statistical analysis framework on ROOT HistFactory (shape+control-region fits, CLs limit setting) used for SUSY/exotics-style results and recasts.
source: https://github.com/histfitter/histfitter.git (type: git)
latest_stable: v1.4.1 (2026-03-03 per Zenodo record; tag `v1.4.1`, ROOT-version compatibility updates)
version_scheme: `vX.Y.Z` git tags; recommended install is clone + checkout of a tag (docs say so explicitly).
hosting_notes: GitHub org histfitter (moved off CERN-internal SVN/Git to GitHub years ago). Tiny repo (~5 MB). conda-forge package exists (BSD-2-Clause per conda metadata; repo license file is a custom ATLAS-style notice).
language: Python (C++ via ROOT PyROOT)
license: BSD-2-Clause-style (per conda-forge; repo license text is custom — flag)
pip_conda: conda-forge yes; source checkout still the recommended route — index it.
priority: medium — the reference implementation of ATLAS analysis-level statistics; agent reads config classes to emulate published fit setups.

### Professor
category: validation
role: MC-generator parameter tuning by polynomial-response-function interpolation of bin observables (prof2-tune etc., Rivet-compatible).
source: https://gitlab.com/hepcedar/professor.git (type: git)
latest_stable: 2.5.9 (2026-08-14, tag `professor-2.5.9` with GitLab release notes)
version_scheme: git tags named `professor-X.Y.Z`.
hosting_notes: Migrated to hepcedar GitLab (Cedar group); professor.hepforge.org legacy (Anubis-walled). Active again after a dormant spell (2.5.x patch releases in 2026). Small repo. Successor project "Apprentice" exists but Professor is the maintained line.
language: Python (C++ roots in interpolation core)
license: GPL-3.0 (verified from repo LICENSE)
pip_conda: no PyPI; conda availability unverified — build from source.
priority: low — tuning is niche for recast agents; raise if lane covers generator-tuning workflows.

### LHAPDF
category: pdf
role: The standard PDF interpolation/lookup library consuming .lhgrid/.LHpdf sets; used by every ME/shower code in the catalog.
source: https://gitlab.com/hepcedar/lhapdf.git (type: git)
latest_stable: 6.5.6 (2026-02-20, tag `lhapdf-6.5.6`)
version_scheme: git tags named `lhapdf-X.Y.Z`; tarballs `LHAPDF-6.5.6.tar.gz` from lhapdf.org / hepforge.
hosting_notes: gitlab.com/hepcedar/lhapdf (canonical since 6.x moved to GitLab); lhapdf.org website. Python interface now requires Python 3. PDF set data (the big part, GBs) is downloaded separately by `lhapdf install` — git repo itself is small. Do NOT mirror the PDF data dir.
language: C++ (Python bindings; legacy Fortran wrappers)
license: GPL-3.0
pip_conda: conda-forge yes; pip no. Checkout worth indexing lightly — agents mostly need the CLI + set metadata, not deep code.
priority: medium — universal dependency but small API surface; index for version/set-management quirks, not daily navigation.

### fastNLO
category: pdf
role: Fast NLO cross-section interpolation code for hadron-collider observables used in PDF fits (and theory-data comparisons).
source: https://gitlab.etp.kit.edu/qcd-public/fastNLO.git (type: git)
latest_stable: 2.6.0 (tag "Release tag for 2.6.0" dated 2025-03-07 on KIT GitLab) — caveat: repo README still references `fastNLO_toolkit-2.5.1-3034.tar.gz`, and distros ship 2.5.0/2.5.1; 2.6.0 is the newest tagged release.
version_scheme: mixed: version-release tags plus numeric internal tags (e.g. `3055`, `3065`); tarballs named `fastNLO_toolkit-X.Y.Z-NNNN.tar.gz` (NNNN = internal rev, e.g. `-3034`) from fastnlo.hepforge.org.
hosting_notes: fastnlo.hepforge.org is Anubis-walled (blocked to bots); dev repo on KIT GitLab `qcd-public/fastNLO` — web UI returned HTTP 403 to this agent, but anonymous git clone is expected to work; note as access risk. Small-to-medium repo.
language: C++ (Fortran-era heritage in docs)
license: GPL (exact version unverified — site walled)
pip_conda: conda-forge has `fastnlo-toolkit`; pip no.
priority: low — niche unless lane covers precision QCD/PDF-fit machinery.

### xFitter
category: global-fit
role: Open-source QCD fit framework for extracting PDFs from HERA/LHC data (apfel/QCDNUM evolution backends).
source: https://gitlab.cern.ch/fitters/xfitter.git (primary; public mirror https://gitlab.com/fitters/xfitter.git) (type: git)
latest_stable: 2.2.0 via tag `2.2.0_Future_Freeze` (2022-03-23) — effectively the last stable; repo dormant since 2022.
version_scheme: tags named `X.Y.Z` plus named-release tags (`2.0.1N_Nuclear_Daiquiri`, `2.2.0_Future_Freeze`); tarballs from xfitter.hepforge.org.
hosting_notes: Canonical dev on CERN GitLab `fitters/xfitter` (public read OK; CERN GitLab requires account for issues); gitlab.com/fitters is the public mirror used here for tag verification. Project effectively unmaintained (last tag 2022) — flag staleness. A conda `xfitter-dev` shows 2.2.1 (2026-07 listing) — unconfirmed against any upstream tag; treat 2.2.0 as stable line.
language: C++/Fortran
license: GPL-3.0
pip_conda: no (experimental conda `xfitter-dev` only)
priority: low — dormant; only worth indexing if lane covers PDF global fits (fastNLO+apfel context).

### ROOT
category: analysis-framework
role: The ubiquitous C++ data-analysis framework (I/O, histograms, fitting, RooFit/RooStats, PyROOT) underpinning HistFitter and most HEP analysis stacks.
source: https://github.com/root-project/root.git (type: git; primary development — migrated from CERN GitLab)
latest_stable: 6.40.04 (2026-08-27; 6.40 is the current LTS series; 6.36.14 and 6.38.06 are parallel maintenance branches)
version_scheme: tags `v6-40-04` (dash-separated, `v` prefix); release tarballs `root_v6.40.04.source.tar.gz` from root.cern/downloads.
hosting_notes: SPECIAL CASE — repo is ~1.6 GB bare (GitHub `size` 1,625,963 KB), ~97k commits, full clone is expensive and history-heavy. Feasibility: shallow clone (`git clone --depth 1`, ~0.5 GB working tree) is workable for code navigation; recommended alternative is the release source tarball (~120 MB) pinned per version, or browse via github.dev. Do not full-clone for a catalog mirror.
language: C++ (Python bindings)
license: LGPL-2.1 (with exceptions; GitHub shows non-SPDX "Other")
pip_conda: conda-forge/`root` yes (and PyPI `root` wheels unofficial); pip no (officially). Checkout rarely needed for recast work — index RooFit/RooStats paths only if lane deep-dives statistics.
priority: medium — unavoidable dependency and RooFit math is relevant, but navigation value/byte ratio is poor; tarball pin beats git mirror.

## Lane summary — Tier-1 priorities
1. Rivet — the measurement reimplementation corpus every validation/recast pipeline targets; tag `rivet-4.1.4`, pin gitlab.com/hepcedar.
2. Delphes — detector-sim backbone of all recast workflows; small repo, plain tags, trivial to pin.
3. SModelS — simplified-model limit database engine (3.2.0 adds ONNX surrogates); Python, easy navigation.
4. CheckMATE — reimplemented-search recast engine, now pyhf/HS3-native (v2.5.4); heavy repo, shallow clone.
5. pyhf — the statistical-model interchange format; tiny MIT repo, zero excuse not to pin.
(YODA/Contur/Spey follow as a Tier-2 cluster; ROOT stays tarball-pinned; Professor/fastNLO/xFitter/GAMBIT are Tier-3 by recast-relevance or size.)

## Verification notes & residual risks
- Verified via GitLab release API (gitlab.com/hepcedar): Rivet 4.1.4, YODA 2.1.4, Contur 3.1.5, LHAPDF 6.5.6, Professor 2.5.9 (+ tags + dates). Direct evidence.
- Verified via GitHub release/tag API: Delphes 3.5.1, CheckMATE v2.5.4, pyhf v0.7.6, Spey v0.2.7, SModelS 3.2.0, HistFitter v1.4.1 (tags), GAMBIT tags v2.5.1, ROOT 6.40.04 (root.cern release page). Direct evidence.
- Inferred/stale-risk: fastNLO 2.6.0 date and tag (search-index of KIT GitLab; site 403s to bots). xFitter 2.2.0 stability (last tag 2022; conda 2.2.1 unconfirmed). GAMBIT v2.5.1 exact tag date not extracted (repo push 2024-07-18). Licenses flagged unverified: SModelS (GPL-3 per docs, no LICENSE in root), Contur (GPL-3 claimed, file not found), GAMBIT (unknown), fastNLO (GPL, version unknown), Delphes/HistFitter/ROOT (non-SPDX "Other" on GitHub; conventional readings noted).
