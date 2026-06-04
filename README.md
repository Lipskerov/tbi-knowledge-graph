# TBI Knowledge Graph

A queryable knowledge base of **3,368 TBI-diagnostic papers** organised around the
**NQO2 (Quinone Reductase 2 / QR2) pathway** as a novel blood-biomarker entry point —
served as a **containerised web app** with an interactive, provenance-labelled graph.

Built to support a research project on TBI diagnostics at the
[Rosenblum Lab](https://neurosenblum.haifa.ac.il) (University of Haifa) ×
[Liraz-Zaltsman Lab](https://www.sheba.co.il) (Sheba Medical Center).

> **Current version: v2.2.** See [`CHANGELOG.md`](CHANGELOG.md) for the full version
> history and [`docs/V2_BUILD_SPEC.md`](docs/V2_BUILD_SPEC.md) for the v2 build spec.

---

## At a glance

| | |
|---|---|
| **Papers** | **3,368** — 3,040 PubMed · 325 bioRxiv · 3 pre-loaded Rosenblum-lab papers |
| **Years** | 1975 – 2026 |
| **Entities (graph nodes)** | **115** — 52 drug · 37 protein · 7 RNA · 7 metabolite · 7 disease · 4 pathway · 1 process |
| **Edges** | **892** — 799 co-occurrence · 13 curated mechanism · 40 ChEMBL inhibitor · 40 OmniPath signed |
| **Clusters** | 14 topic clusters (multi-cluster faceting) |
| **Interfaces** | FastAPI web app (`localhost:8000`) · v1 CLI (`kb/query_kb.py`) · static HTML graph |

---

## What's inside

| File / dir | Contents |
|------------|----------|
| `app/` | FastAPI web app — REST API + two-pane vis.js frontend + shared-password login |
| `kb/` | Fetchers (PubMed, bioRxiv, ChEMBL, OmniPath) + graph builder + CLI |
| `data/tbi_papers.db` | SQLite — papers, entities, typed edges, FTS5 index, ChEMBL & OmniPath tables |
| `data/knowledge_graph.json` | Full entity-relation graph export |
| `data/paper_summaries.md` | Human-readable index of all papers with entity tags |
| `data/claude_context.json` | Compact JSON for loading as Claude context |
| `data/tbi_graph.html` | Pre-built static interactive graph (v1, offline) |
| `Dockerfile`, `docker-compose.yml` | Container build + run |

---

## The web app (v2.2)

A FastAPI + SQLite-FTS5 app on top of the database, gated behind a shared lab password.

```bash
# 1. Set the shared password (writes a gitignored .env with the hash + session secret)
python -m app.auth set-password

# 2. Build & run the container
docker compose up --build -d        # → http://localhost:8000
```

### Capabilities
- **Interactive graph** (vis.js) — nodes sized by paper count, coloured by entity type.
- **Provenance-labelled edges** — every edge is one of four kinds (see below), colour-coded.
- **Click a node → its papers** with DOI / PubMed / bioRxiv links, plus its directed
  mechanism links (curated / ChEMBL / OmniPath) with annotations.
- **Full-text search** over all abstracts (SQLite FTS5).
- **Multi-cluster faceting** — filter by node type, cluster, focus disease, min papers/edge.
- **Physics toggle** — freeze the layout to drag nodes into place and pin them, or
  re-enable auto-arrange.
- **Shared-password login** — `/login`, `/logout`; 8-hour signed HttpOnly session cookie.

### Edge provenance (the four edge kinds)

| Kind | UI style | Meaning | Count |
|------|----------|---------|-------|
| `cooccur` | faint grey | two entities co-mentioned in a paper (weight = shared papers) | 799 |
| `curated` | solid orange, directed | hand-curated mechanism edges — the **novel NQO2 biology** | 13 |
| `chembl` | dashed green, directed | `compound → NQO2` inhibition with potency (IC50/Ki/Kd · pChEMBL · n) | 40 |
| `omnipath` | dashed blue, directed/signed | curated **activates/inhibits** protein interactions (SIGNOR/Reactome/…) | 40 |

The curated edges carry the project's unique knowledge (the dopamine→DRD1→miR-182→NQO2→
ROS→Kv2.1 pathway), which public databases do not contain; ChEMBL and OmniPath enrich the
quantitative inhibitor data and the surrounding signalling context respectively.

### API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/stats` | counts (papers, entities, edges by kind, clusters, sources) |
| GET | `/api/graph` | nodes + edges (filters: `min_papers`, `min_edge`, `types`, `clusters`, `disease`, `q`) |
| GET | `/api/node/{id}/papers` | papers for an entity (filters: `year_min/max`, `cluster`, `limit`) |
| GET | `/api/entity/{id}` | entity detail: aliases, mechanism in/out (with annotations), top co-occurring |
| GET | `/api/search` | FTS5 full-text search over abstracts |
| GET/POST | `/login`, `/logout` | auth flow (public) |
| GET | `/healthz` | health check (public) |

All `/api/*` and the frontend require a valid session; unauthenticated requests get
`401` (API) or a redirect to `/login`.

---

## Quick start (CLI, no container)

```bash
pip install -r requirements.txt

# query the database from the command line (v1 interface, unchanged)
python kb/query_kb.py --stats
python kb/query_kb.py --q "NQO2 blood TBI biomarker"
python kb/query_kb.py --entity NQO2 --show-papers
python kb/query_kb.py --cluster nqo2

# open the pre-built static graph
open data/tbi_graph.html          # macOS (or just double-click the file)
```

---

## The science

### Why NQO2?

NQO2 (NAD(P)H quinone oxidoreductase 2, also called QR2) is an intracellular flavoenzyme that generates ROS as a byproduct of quinone reduction. In the healthy brain:

- Novel experience → dopamine release (locus coeruleus → CA1) → DRD1 activation → cAMP/PKA → miR-182 upregulation → **NQO2 suppression** → reduced ROS → reduced Kv2.1 oxidation → modulated interneuron excitability → memory consolidation

In aged and injured brain:

- miR-182 is underexpressed → **NQO2 is overexpressed** → excess ROS → oxidative stress cascade → neuroinflammation (GFAP↑, Iba1↑) → secondary neurodegeneration

**TBI blood biomarker hypothesis:** acute TBI causes neuronal damage → NQO2 release into circulation (similar mechanism to UCH-L1 and NSE) + ROS spike → measurable in plasma as a novel diagnostic marker.

The Rosenblum lab has shown:
- QR2 inhibitors reverse Alzheimer's disease phenotype in 5xFAD mice, reducing Aβ42, GFAP, and Iba1 ([JCI 2022](https://doi.org/10.1172/JCI162120))
- Dopamine-dependent QR2 pathway in CA1 interneurons drives novel memory formation ([J Neuroscience 2020](https://doi.org/10.1523/JNEUROSCI.0243-20.2020))
- QR2 removal in SST interneurons of the insula enhances taste memory ([eNeuro 2021](https://doi.org/10.1523/ENEURO.0152-21.2021))

### Project positioning

The strongest commercial angle is **PPCS (persistent post-concussion syndrome) prognosis**, not acute mTBI diagnosis:

| Segment | Clinical action | Payer | Status |
|---------|----------------|-------|--------|
| Acute mTBI triage (Abbott territory) | Skip CT scan | Hospital (saves bed-hours) | Crowded, reimbursement-broken |
| **PPCS risk stratification at 1–4 weeks** | Early neurorehab referral | Workers' comp, self-insured employers, Medicare Advantage | **Commercial whitespace** |
| Pediatric mTBI | Avoid head CT in children | Parents + hospital | Whitespace — no strong pediatric label |
| Return-to-play / return-to-duty | Objective clearance or hold | NFL, NCAA, DoD | Direct fee-for-service |

PPCS patients cost **5–10× more** over 12 months than recovered patients — the payer ROI is well-documented. The Liraz-Zaltsman longitudinal Sheba cohort with 6-month GOS-E follow-up is well-suited for this endpoint.

### Competitive landscape

| Platform | Cleared markers | Status |
|----------|----------------|--------|
| Abbott i-STAT TBI | GFAP + UCH-L1 | FDA-cleared 2021; whole-blood 2024 |
| bioMérieux VIDAS TBI | GFAP | FDA-cleared 2024 |
| Quanterix Simoa | GFAP, UCH-L1, NfL, p-tau | Research platform, no cleared TBI indication |
| BrainScope | EEG-based | Return-to-play segment |
| Gap | Prognostic test | **No FDA-cleared TBI prognostic test exists** |

---

## Paper clusters (14)

A paper can belong to multiple clusters (`paper_clusters` junction table), so counts sum to more than the 3,368 unique papers.

| Cluster | Papers | Description |
|---------|--------|-------------|
| `aging_neuro` | 703 | Brain aging / age-related neurodegeneration |
| `tbi_mild_blood` | 533 | mTBI + blood biomarkers |
| `tbi_proteomics` | 533 | TBI + proteomics / metabolomics |
| `nqo2` | 379 | **All NQO2/QR2 papers** — full enzyme biology |
| `nfl_tau` | 363 | NfL and tau in TBI blood diagnosis / prognosis |
| `gfap_uchl1` | 339 | GFAP + UCH-L1 as TBI blood diagnostics |
| `exosomal_rna` | 313 | Exosomal / extracellular-vesicle RNA in TBI |
| `ppcs_prognosis` | 303 | Post-concussion syndrome biomarkers and prognosis |
| `qr2_structure_kinetics` | 297 | QR2 enzyme structure / kinetics |
| `tbi_panel_poc` | 290 | Multi-marker panels + point-of-care TBI tests |
| `qr2_inhibitors` | 249 | QR2 inhibitor pharmacology |
| `qr2_melatonin_mt3` | 68 | Melatonin / MT3 binding site |
| `qr2_flavonoids` | 64 | Flavonoid QR2 inhibitors (quercetin, resveratrol, …) |
| `qr2_antimalarials` | 26 | Antimalarial QR2 inhibitors (chloroquine, primaquine, …) |

---

## Knowledge graph entities (115)

Entities are seeded in `kb/build_graph.py` (`ENTITY_SEEDS`) and extended by the ChEMBL /
OmniPath fetchers. Key arms of the graph:

```
NQO2/QR2 enzyme:  NQO2 · NQO1 · NRH (substrate) · FAD
Upstream signal:  dopamine → DRD1 → cAMP/PKA → miR-182 → NQO2 (suppression)
Downstream:       NQO2 → ROS → Kv2.1 oxidation → interneuron excitability
Antioxidant arm:  ROS → Nrf2 → HO-1 / SOD / glutathione / catalase / 4-HNE
ISR arm:          PKR / PERK / GCN2 → eIF2α → ATF4 / CHOP / eEF2 / eIF2B
Plasticity:       CaMKII · Arc · AMPA receptor · NMDA receptor
Inhibitors:       S29434, melatonin, quercetin, resveratrol, chloroquine, imatinib,
                  prazosin … + 40 ChEMBL compounds with measured potencies
```

**Established TBI blood biomarkers:** `GFAP` · `UCH-L1` · `NfL` · `NfH` · `tau` · `p-tau` · `S100B` · `NSE` · `MBP` · `VILIP-1` · `BDNF`

**Neuroinflammation:** `Iba1` · `IL-6` · `TNF-α` · `IL-1β` · `Aβ42` · `neuroinflammation`

**RNA biomarkers:** `VLDLR-AS1` · `MALAT1` · `GAS5` · `NEAT1` · `miR-21` · `miR-182` · `let-7`

**Clinical / platforms:** `mTBI` · `TBI` · `PPCS` · `CTE` · `Alzheimer` · `aging` · `GOS-E` · `i-STAT TBI` · `Simoa` · `Olink` · `Quanterix`

> Entities mapped to genes carry their **HGNC symbol** as an alias (added by the OmniPath
> normalisation step), e.g. Nrf2→NFE2L2, Kv2.1→KCNB1, UCH-L1→UCHL1.

---

## CLI query reference

```bash
python kb/query_kb.py --stats
python kb/query_kb.py --q "NQO2 blood TBI"
python kb/query_kb.py --q "PPCS prognosis 6 months"
python kb/query_kb.py --entity NQO2 --show-papers
python kb/query_kb.py --entity GFAP --show-papers
python kb/query_kb.py --related NQO2            # co-occurring entities
python kb/query_kb.py --cluster nqo2
python kb/query_kb.py --cluster tbi_mild_blood --year-min 2022
python kb/query_kb.py --pmid 35617003          # full record for a paper
python kb/query_kb.py --export-context         # compact JSON for Claude
```

---

## Rebuilding & extending the database

```bash
# Full rebuild (re-queries PubMed; only fetches new PMIDs)
python build_kb.py
python build_kb.py --api-key YOUR_KEY          # NCBI key → 10 req/s vs 3 req/s

# Rebuild graph only (no network) — re-extracts entities, rebuilds all edge kinds + FTS
python build_kb.py --skip-fetch

# Add data sources
python build_kb.py --source biorxiv            # bioRxiv preprints (Europe PMC + api.biorxiv.org)
python build_kb.py --chembl                    # ChEMBL NQO2 inhibitor bioactivity → potency edges
python build_kb.py --omnipath                  # OmniPath signed/directed protein interactions
python build_kb.py --cluster nqo2              # refresh a single cluster
```

The fetchers can also be run standalone: `kb/fetch_papers.py`, `kb/fetch_preprints.py`,
`kb/fetch_chembl.py`, `kb/fetch_omnipath.py`. Each writes to the same DB; the graph build
regenerates edges from the source tables (`PATHWAY_EDGES`, `chembl_activities`,
`omnipath_interactions`) on every run.

**Add a search cluster** — edit `CLUSTERS` in `kb/fetch_papers.py`, then
`python build_kb.py --cluster new_cluster`.
**Add curated entities/edges** — edit `ENTITY_SEEDS` / `PATHWAY_EDGES` in
`kb/build_graph.py`, then `python build_kb.py --skip-fetch`.

---

## Static visualization (v1, offline)

The original PyVis static export still works, independent of the web app:

```bash
python visualize_graph.py                       # full graph → data/tbi_graph.html
python visualize_graph.py --min-papers 5 --min-edge 3   # major hubs only
python visualize_graph.py --cluster nqo2        # highlight a cluster
```

---

## Project structure

```
.
├── build_kb.py              # Main pipeline: schema → fetch → graph → export
├── visualize_graph.py       # PyVis static HTML graph (v1)
├── Dockerfile               # Container image (uvicorn serving app.main)
├── docker-compose.yml       # Service: web (port 8000, .env, data volume)
├── requirements.txt         # fastapi, uvicorn, itsdangerous, requests, networkx, pyvis
├── CHANGELOG.md             # Version history (Keep a Changelog)
├── docs/V2_BUILD_SPEC.md    # v2 build specification
├── app/                     # FastAPI web app
│   ├── main.py              #   routes, auth gate, session middleware
│   ├── db.py                #   read-only SQLite data access
│   ├── auth.py              #   shared-password auth (PBKDF2) + CLI
│   └── static/              #   index.html · app.js · styles.css · login.html
├── kb/
│   ├── fetch_papers.py      # PubMed E-utilities fetcher (14 clusters)
│   ├── fetch_preprints.py   # bioRxiv via Europe PMC + api.biorxiv.org
│   ├── fetch_chembl.py      # ChEMBL NQO2 inhibitor bioactivity → potency edges
│   ├── fetch_omnipath.py    # OmniPath signed/directed protein interactions
│   ├── build_graph.py       # Entity extraction + co-occurrence + curated/ChEMBL/OmniPath edges
│   └── query_kb.py          # CLI query interface
├── scripts/vendor_lib.py    # Materialise vendored vis.js/tom-select libs at build time
├── .github/workflows/daily_sync.yml   # Daily PubMed sync (auto-commits new papers)
└── data/                    # DB + exports (see "What's inside")
```

---

## Dependencies

```bash
pip install -r requirements.txt
# fastapi · uvicorn[standard] · itsdangerous · requests · networkx · pyvis
```

Python 3.10+. The container build also materialises the vis.js / tom-select frontend libs
from the installed `pyvis` package (no CDN download) via `scripts/vendor_lib.py`.

---

## Data sources

Papers are fetched from [PubMed](https://pubmed.ncbi.nlm.nih.gov/) (NCBI E-utilities) and
[bioRxiv](https://www.biorxiv.org/) (via Europe PMC). Quantitative NQO2 inhibitor
bioactivity (IC50/Ki/Kd) comes from [ChEMBL](https://www.ebi.ac.uk/chembl/)
(`kb/fetch_chembl.py`), added as directed, potency-annotated `compound → NQO2` edges.
Curated **signed/directed** protein interactions among the entities come from
[OmniPath](https://omnipathdb.org/) — aggregating SIGNOR, Reactome, SignaLink and others
(`kb/fetch_omnipath.py`). Three foundational Rosenblum-lab papers are pre-loaded:

- Gould et al., *eNeuro* 2021 — QR2 in SST interneurons and taste memory
- Gould et al., *JCI* 2022 — QR2 inhibitors reverse AD phenotype in 5xFAD mice
- Gould et al., *J Neuroscience* 2020 — Dopamine-dependent QR2 pathway in CA1

---

## Security & deployment

The app is gated behind a single shared password (PBKDF2-HMAC-SHA256 hash; signed HttpOnly
session cookie). Secrets live in a **gitignored `.env`** (`TBI_AUTH_PASSWORD_HASH`,
`TBI_SESSION_SECRET`, optional `NCBI_API_KEY`), injected via compose `env_file` — never
committed, never baked into the image. Rotate the password with
`python -m app.auth set-password`.

> ⚠️ **No TLS yet.** Login is served over HTTP, so the password is cleartext on the wire —
> acceptable only on a firewall-restricted trusted subnet. Add an HTTPS reverse proxy
> (e.g. Caddy) and set `TBI_HTTPS_ONLY=1` (adds the `Secure` cookie flag) before any wider
> exposure; for off-subnet access prefer a private mesh (e.g. Tailscale) over opening the
> port. See [`CHANGELOG.md`](CHANGELOG.md) for full security notes.

---

## Version history

See [`CHANGELOG.md`](CHANGELOG.md). Highlights: **v2.0** containerised web app (typed edges,
FTS5, multi-cluster, bioRxiv) · **v2.1** shared-password auth + ChEMBL inhibitor potencies ·
**v2.2** OmniPath signed/directed interactions + entity gene-symbol normalisation +
graph physics toggle.
