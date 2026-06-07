# Changelog

All notable changes to the **TBI Knowledge Graph** project are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Dates are ISO-8601 (`YYYY-MM-DD`). Paper counts reflect the database at each release.

---

## [Unreleased]

### Added — Click an edge to see shared papers (paged)
- New `GET /api/edge/{a}/{b}/papers`: papers in which the two endpoint entities
  **co-occur**, newest first, year-scoped (`year_min`/`year_max`) and **paged**
  (`limit`/`offset`, returns `total`). Clicking any connection in the graph opens the
  shared-paper list in the detail panel with a **Load more** button.
- Frontend: edge-click handler + `openEdge()` paging; `renderPapers` refactored to share
  a `papersItems()` helper for appends (`app/static/app.js`).

### Added — GitHub link in the main app UI
- The header now carries an explicit **GitHub ↗** link (previously the project link was
  only on the version badge and the login screen).

### Added — Year-range graph filtering
- The **min/max year** controls now filter the **graph itself**, not just full-text
  search. `/api/graph` gained `year_min` / `year_max`: a node appears only if it has
  ≥1 paper in the window, and **co-occurrence edges are recomputed within that span**
  (from `paper_entity` × `papers.year`) so a connection is only drawn when papers from
  those years actually support it. Mechanism edges (curated / ChEMBL / OmniPath) are
  shown between in-range nodes. All-time behaviour is unchanged when no year is set.
- Frontend: the topbar year inputs reload the graph on change/Enter and are included in
  the sidebar **Apply filters** / **Reset** flow (`app/static/app.js`).

### Added — OmniPath signed/directed interactions (data enrichment, v2.2)
- New `kb/fetch_omnipath.py`: pulls **curated, signed, directed** protein–protein
  interactions (who *activates* / *inhibits* whom) among the graph's entities from
  **OmniPath** (which aggregates SIGNOR, Reactome, SignaLink, SPIKE, … ~100 sources).
- Adds **40 directed mechanism edges** (`edge_kind='omnipath'`, 28 signed
  activates/inhibits) across the well-studied arms *around* NQO2 — the ISR/eIF2α axis
  (`PERK/PKR/GCN2 → eIF2α → ATF4 → CHOP`), the Nrf2 antioxidant arm (`Nrf2 → NQO1/HO-1`),
  neuroinflammation cytokines, and plasticity (`CaMKII → AMPA/MAPT`). Each edge carries
  its **source databases + PubMed references** (annotation, hover/detail panel).
- **Decision was grounded by a coverage probe (recorded for honesty):** NQO2 *itself*
  has only **2** interactions in all of OmniPath, and **none** of the novel
  dopamine→DRD1→miR-182→NQO2→ROS→Kv2.1 pathway. So OmniPath deliberately enriches the
  **context**, not the core — the novel NQO2 mechanism stays in the hand-curated
  `PATHWAY_EDGES` (the project's unique contribution no public DB holds).
- **Provenance hierarchy enforced:** an OmniPath edge never overrides a curated or
  ChEMBL edge for the same ordered pair (`add_omnipath_edges` guard).
- **Entity normalization:** mapped 35 entities → HGNC gene symbols (34 had ≥1
  interaction), stamped as aliases — groundwork for future ID-based sources.
- New `omnipath_interactions` table is the source of truth (edges regenerated each
  build by `build_graph.py::add_omnipath_edges`). App: `/api/stats.omnipath_edges`,
  shown as finely-dashed **blue** signed edges; `/api/entity` mechanism panels list them
  with sources. Run `python build_kb.py --omnipath`.
- Result: edges now **13 curated · 40 ChEMBL · 40 OmniPath** · 799 co-occurrence.

### Added — ChEMBL inhibitor bioactivity (data enrichment, v2.1)
- New `kb/fetch_chembl.py`: pulls **quantitative NQO2/QR2 bioactivity** from ChEMBL
  (target `CHEMBL3959`, UniProt P16083) — 463 pChEMBL-scored activities across 378
  compounds — and turns the most informative ones into the graph.
- Adds **40 directed, potency-annotated mechanism edges** `compound —inhibits/binds→
  NQO2` (edge_kind `chembl`), each annotated with median IC50/Ki/Kd, pChEMBL, and n
  measurements (e.g. *melatonin — IC50/Ki ≈ 84 nM · pChEMBL 7.08 · n=9*). This upgrades
  the inhibitor clusters from "papers that mention a compound" to real binding constants.
- **Selection is named-first** (the project's inhibitors — melatonin, prazosin, imatinib,
  furamidine… — are weaker binders than anonymous medchem leads, so a pure-potency rank
  buried them), then tops up with the most potent unnamed leads.
- **Entity dedup**: compounds are matched to existing entities by name/alias before
  creating nodes, so known inhibitors are *enriched* (ChEMBL id added as alias), not
  duplicated. ChEMBL's quantitative edge **supersedes** the redundant hand-curated
  inhibitor edge for the same compound (one richer arrow, not two).
- New `chembl_activities` table is the source of truth; edges are regenerated every
  build by `build_graph.py::add_chembl_edges` (survives the `entity_relations` rebuild).
- Schema: `entity_relations.annotation` column (idempotent migration) holds the potency.
- App: `/api/stats` reports `chembl_edges`; `/api/entity` mechanism panels and `/api/graph`
  include ChEMBL edges (dashed-green in the UI, potency on hover / in the detail panel).
- Build: `python build_kb.py --chembl` (or `kb/fetch_chembl.py` standalone). NCBI API key
  stored in `.env` (`NCBI_API_KEY`, gitignored) for fuller PubMed re-fetches.
- Result: entities **80 → 115** (52 drug nodes), edges include **40 ChEMBL** + 13 curated.

### Added — Authentication (shared-password login)
- The web app is now **gated behind a single shared lab password** (`app/auth.py`,
  `app/static/login.html`). Unauthenticated requests get **401** on `/api/*` and a
  **303 redirect to `/login`** for everything else. New routes: `GET /login`,
  `POST /login`, `GET /logout`, `GET /healthz` (public).
- Password is **never stored in clear** — only a salted **PBKDF2-HMAC-SHA256**
  hash (600k iterations). Session is a signed **HttpOnly**, `SameSite=Lax` cookie
  (Starlette `SessionMiddleware` + `itsdangerous`), 8-hour lifetime.
- **Brute-force lockout**: 5 failed attempts → temporary `429` with exponential
  backoff (30 s → 15 min cap).
- Secrets live in a **gitignored `.env`** (`TBI_AUTH_PASSWORD_HASH`,
  `TBI_SESSION_SECRET`), injected via compose `env_file`; never baked into the image.
  Set/rotate with `python -m app.auth set-password`.
- Hash uses a `:` delimiter (not `$`) **on purpose** — docker-compose interprets
  `$` in `.env` as variable interpolation and would corrupt the hash.
- Tested end-to-end against the container: 11/11 checks pass (gate blocks, login
  issues cookie, authed API works, logout clears, lockout fires).

#### Known limitations
- **No TLS yet** — the password crosses the network in cleartext. Mitigated for now
  by the `/24` firewall restriction; add HTTPS (Caddy reverse proxy) before any
  wider exposure, then set `TBI_HTTPS_ONLY=1` to add the `Secure` cookie flag.
- **Lockout is global, not per-user** — Docker's port proxy makes all clients
  appear as `172.18.0.1`, so the per-IP throttle shares one bucket. Fix alongside
  the reverse proxy by honoring `X-Forwarded-For`.

### Deployment
- **Docker container deployment verified end-to-end (2026-06-04).** Docker Desktop
  was reinstalled from scratch (the prior install's Linux engine hung — no WSL2
  backend distro had been provisioned). After reinstall the `docker-desktop` WSL2
  distro registers and the engine runs (29.5.2). `docker compose up --build -d`
  builds and serves the app on `0.0.0.0:8000`; all 5 endpoints + vendored assets
  return 200 (`/api/stats` → 3,368 papers / 80 entities / 783 edges).
- Docker Desktop set to **start on login** so the container (`restart: unless-stopped`)
  comes back automatically after a reboot.

### Server access (2026-06-04)
- The lab server now serves the graph on the local network via a Windows firewall
  rule (**"TBI KG 8000"**: inbound TCP 8000, Allow, **Private** profile) that is
  **restricted to the lab subnet** rather than left open. Host address, subnet, and
  the widen/rotate commands are kept out of version control (operational config).
- Access is deliberately limited to the lab subnet because the app currently has no
  TLS; for off-campus access prefer a private mesh (e.g. Tailscale) over widening
  the firewall. Add an HTTPS reverse proxy before any broader exposure.

### Pending
- (none) — v2.0 is built, containerized, deployed, and serving on the lab subnet.

---

## [2.0.0] — 2026-06-04

First containerized release. Adds a FastAPI + SQLite-FTS5 web app on top of the
existing v1 database. **Purely additive** — the v1 CLI (`kb/query_kb.py`), the
static `visualize_graph.py` export, and the daily-sync GitHub Action are unchanged.

Database at release: **3,368 papers** (3,043 PubMed + 325 bioRxiv), 80 nodes, ~783 edges.

### Added
- **Web app** (`app/`): FastAPI server with two-pane vis.js UI, tom-select facets,
  node-click → papers, and FTS search. Endpoints: `/api/stats`, `/api/graph`,
  `/api/node/{id}/papers`, `/api/entity/{id}`, `/api/search`.
- **Containerization**: `Dockerfile`, `docker-compose.yml` (binds `0.0.0.0:8000`,
  `restart: unless-stopped`), `.dockerignore`, and `scripts/vendor_lib.py` to
  generate the vendored `lib/` (vis-network etc.) from pyvis at build time.
- **Typed, directed mechanism edges** — `PATHWAY_EDGES` curated pass
  (dopamine → … → NQO2 → ROS → Kv2.1, plus inhibitors); new `edge_kind` /
  `directed` columns with migration (e.g. `S29434 —inhibits→ NQO2`).
- **SQLite FTS5** full-text search over all abstracts (`papers_fts` virtual table
  + rebuild step in `build_kb.py`).
- **Multi-cluster faceting** via a `paper_clusters` many-to-many junction table
  with backfill (a paper can belong to many clusters; 4,460 rows at release).
- **bioRxiv / preprint ingestion** (`kb/fetch_preprints.py`): Europe PMC keyword
  search → `api.biorxiv.org` enrich; `--source pubmed|biorxiv|both`. Tagged
  `source='biorxiv'`.
- **5 new QR2/NQO2 inhibitor clusters** + 11 new entity seeds.
- `docs/V2_BUILD_SPEC.md` (full build spec) and `.gitattributes` (locks LF on
  source/Docker files).

### Notes
- QR2 PubMed fetch ran keyless (3 req/s) — no NCBI API key was provided.
- Preprint set is Europe PMC `SRC:PPR` filtered to `10.1101` DOIs, so it includes
  a few medRxiv (sibling CSH server) preprints alongside bioRxiv. All DOI links work.
- A safety backup of the pre-v2 DB is kept at `data/tbi_papers.db.bak` (gitignored).

---

## [1.2.0] — 2026-05-27

### Added
- Aging cluster, disease selector, and **498 new papers** (total: 3,025).

---

## [1.1.0] — 2026-05-19

### Added
- GitHub Actions **daily PubMed sync** workflow (auto-commits new papers).
- Interactive PyVis graph: filter panel + orbital rotation controls.

### Changed
- Removed the proteostasis / p62 axis from the knowledge graph.

### Fixed
- Daily sync now `pull --rebase` before push and opts into Node.js 24.
- Pull latest DB before build to prevent binary rebase conflicts.

### Daily sync history (paper totals)
- 2026-05-20 → 2,512 · 2026-05-22 → 2,513 · 2026-05-23 → 2,514 · 2026-05-24 → 2,517
- 2026-05-25 → 2,520 · 2026-05-27 → 2,527 · 2026-05-28 → 3,026 · 2026-05-30 → 3,030

---

## [1.0.0] — Initial

### Added
- Initial TBI knowledge graph and literature database: SQLite store, entity/relation
  graph, paper-summary index, Claude-context export, and a pre-built interactive
  HTML graph. Organised around the NQO2 (Quinone Reductase 2) pathway as a novel
  blood-biomarker entry point.

---

[Unreleased]: https://github.com/
[2.0.0]: https://github.com/
[1.2.0]: https://github.com/
[1.1.0]: https://github.com/
[1.0.0]: https://github.com/
