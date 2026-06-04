# TBI Knowledge Graph — v2.0 Build Spec (DEV)

> **Purpose:** self-contained build document. Hand this to Claude Code (or a dev) on any machine to build v2.0 from the v1.0 repo. Everything needed — repo links, exact queries, schema DDL, API surface, Docker config, verification — is here.

---

## 0. Source repo (v1.0) & how to start

- **GitHub:** https://github.com/Lipskerov/tbi-knowledge-graph
- **Clone:** `git clone https://github.com/Lipskerov/tbi-knowledge-graph.git`
- **Branch:** `main` (last v1.0 commit `0465b82`). Has a daily PubMed sync GitHub Action (`.github/workflows/daily_sync.yml`).
- **v2.0 strategy:** branch off main → `git checkout -b v2-app`. Keep v1.0 (`kb/`, `query_kb.py`, static HTML, the daily-sync Action) fully working — v2.0 is purely additive. Merge to `main` when stable, or keep `v2-app` as the deployable branch.

### Prerequisites on the target machine
- Docker + Docker Compose (primary runtime).
- Python 3.11+ only if rebuilding the DB locally outside the container.
- Optional NCBI API key (free, 10 req/s vs 3) for fetching: https://www.ncbi.nlm.nih.gov/account/
- The repo already vendors `lib/vis-9.1.2/` (graph), `lib/tom-select/` (multi-select), `lib/bindings/utils.js` (neighbourhood highlight) — **reuse, do not re-download.**

---

## 1. Context / why v2.0

v1.0 = 2,679 papers, 74 entities, 767 co-occurrence edges in SQLite (`data/tbi_papers.db`), with a static PyVis `data/tbi_graph.html` and a CLI (`kb/query_kb.py`). Three limits drive v2.0:

1. **Static viz, no drill-down.** The HTML filter sidebar works, but you **can't click a node to see its papers** and there's **no full-text search** of abstracts. `lib/tom-select` + `lib/bindings/utils.js` were vendored for this but never wired.
2. **Co-occurrence only.** The NQO2 mechanism (dopamine→miR-182→NQO2→ROS→Kv2.1 + inhibitors) lives only in the README. `entity_relations.relation` is hard-coded `'co-occurs'`; `paper_entity.relation` is computed but unused.
3. **Thin QR2 inhibitor coverage + single-cluster tagging.** One `nqo2` cluster pulls all NQO2 papers, but inhibitor pharmacology isn't retrieved on its own terms, and `papers.topic_cluster` is a single value, so a paper can't be both `nqo2` and `qr2_inhibitors` (blocks faceting).

**v2.0 = containerized web app** (FastAPI + SQLite FTS5 + Docker): multi-param search over all abstracts, **click node → publication list** (DOI/PubMed links), typed mechanism edges, expanded QR2-inhibitor DB. Run anywhere with `docker compose up`.

---

## 2. Architecture overview

```
┌─ Browser (localhost:8000) ─────────────────────────────┐
│  top: [ multi-param search bar ]  [year range][facets] │
│  ┌─ facet rail ─┐ ┌─ vis.js graph ─┐ ┌─ detail panel ─┐│
│  │ types  (ms)  │ │  (NQO2)●─▶●ROS  │ │ click NQO2 →   ││
│  │ clusters(ms) │ │    ▲            │ │ • papers list  ││
│  │ disease      │ │ S29434●        │ │   +DOI +PubMed ││
│  │ min-papers   │ │                │ │ • mechanism    ││
│  │ min-edge     │ └────────────────┘ │   edges (typed)││
│  └──────────────┘                    └────────────────┘│
└────────────────────────────────────────────────────────┘
        │ HTTP /api/*                 (ms)=tom-select multi
┌───────▼──────────── FastAPI (app/) ────────────────────┐
│ /api/graph  /api/search(FTS5)  /api/node/{id}/papers   │
│ /api/entity/{id}  /api/stats   + StaticFiles(app/static,│
│                                  lib/)                  │
└───────┬────────────────────────────────────────────────┘
        │ read-only sqlite3
┌───────▼─ data/tbi_papers.db ───────────────────────────┐
│ papers · entities · paper_entity · entity_relations    │
│ + paper_clusters (NEW m2m) · papers_fts (NEW FTS5)     │
│ entity_relations + edge_kind/directed (NEW typed edges)│
└────────────────────────────────────────────────────────┘
Docker: web service, port 8000, bind-mount ./data:/app/data
```

---

## 3. Part A — Database expansion: QR2 inhibitor space

### A1. Five new clusters — add to `CLUSTERS` in `kb/fetch_papers.py`

```python
# --- QR2 / NQO2 inhibitor space (v2.0) ---
"qr2_inhibitors": (
    '(NQO2 OR "quinone reductase 2" OR QR2 OR "NRH:quinone oxidoreductase 2") '
    'AND (inhibitor OR inhibition OR antagonist OR "small molecule" OR pharmacolog* '
    'OR IC50 OR Ki OR potency OR "drug discovery")'
),
"qr2_melatonin_mt3": (
    '("quinone reductase 2" OR NQO2 OR QR2) '
    'AND (melatonin OR "MT3 binding" OR "melatonin binding site" OR "2-iodomelatonin" '
    'OR prazosin OR "N-acetylserotonin")'
),
"qr2_antimalarials": (
    '(NQO2 OR QR2 OR "quinone reductase 2") '
    'AND (chloroquine OR primaquine OR quinacrine OR antimalarial OR imatinib OR mefloquine)'
),
"qr2_flavonoids": (
    '(NQO2 OR QR2 OR "quinone reductase 2") '
    'AND (quercetin OR resveratrol OR flavonoid OR casimiroin OR polyphenol '
    'OR genistein OR curcumin OR apigenin OR kaempferol)'
),
"qr2_structure_kinetics": (
    '(NQO2 OR QR2 OR "quinone reductase 2") '
    'AND (crystal OR structure OR "X-ray" OR kinetics OR "active site" '
    'OR "structure-activity" OR cofactor OR FAD OR NRH OR mechanism OR substrate)'
),
```
In `CLUSTER_CAPS` set all five to `None` (fetch all — small corpora; the NQO2 universe is ~370 papers).

> Rationale: many PMIDs already exist under `topic_cluster='nqo2'`. Added value = (a) melatonin/antimalarial/flavonoid papers where NQO2 is *not* the lead term, (b) faceting — which needs A3.

### A2. New entities — add to `ENTITY_SEEDS` in `kb/build_graph.py`

```python
("melatonin",   "drug",       ["melatonin", "N-acetyl-5-methoxytryptamine"]),
("MT3",         "protein",    ["MT3", "melatonin binding site MT3", "ML2"]),
("chloroquine", "drug",       ["chloroquine", "hydroxychloroquine"]),
("primaquine",  "drug",       ["primaquine"]),
("quinacrine",  "drug",       ["quinacrine", "mepacrine"]),
("casimiroin",  "drug",       ["casimiroin"]),
("prazosin",    "drug",       ["prazosin"]),
("imatinib",    "drug",       ["imatinib", "Gleevec"]),
("FAD",         "metabolite", ["FAD", "flavin adenine dinucleotide"]),
```
(S29434, quercetin, resveratrol, NRH already exist. Also add `cAMP/PKA`, `PPCS`, `GOS-E` if Part B references them and they're missing.)

### A3. Many-to-many cluster tagging — `kb/fetch_papers.py: init_schema()`

```sql
CREATE TABLE IF NOT EXISTS paper_clusters (
    pmid    TEXT,
    cluster TEXT,
    PRIMARY KEY (pmid, cluster),
    FOREIGN KEY (pmid) REFERENCES papers(pmid)
);
CREATE INDEX IF NOT EXISTS idx_pc_cluster ON paper_clusters(cluster);
```
- Keep legacy `papers.topic_cluster` (back-compat for `query_kb.py`).
- In `upsert_papers()` (~L307) also `INSERT OR IGNORE INTO paper_clusters(pmid, cluster)` for **every** cluster a PMID is fetched under.
- One-time backfill in `build_kb.py`: `INSERT OR IGNORE INTO paper_clusters SELECT pmid, topic_cluster FROM papers WHERE topic_cluster IS NOT NULL;`

---

## 4. Part B — Typed / directed mechanism edges

### B1. `PATHWAY_EDGES` — new constant in `kb/build_graph.py`

```python
PATHWAY_EDGES = [
    # (source, target, relation, directed)
    ("dopamine",  "DRD1",    "activates",       True),
    ("DRD1",      "cAMP/PKA","signals_via",     True),
    ("cAMP/PKA",  "miR-182", "upregulates",     True),
    ("miR-182",   "NQO2",    "suppresses",      True),
    ("NQO2",      "ROS",     "generates",       True),
    ("ROS",       "Kv2.1",   "oxidizes",        True),
    ("ROS",       "Nrf2",    "activates",       True),
    ("NQO2",      "NRH",     "uses_substrate",  True),
    ("S29434",    "NQO2",    "inhibits",        True),
    ("melatonin", "NQO2",    "binds",           True),
    ("quercetin", "NQO2",    "inhibits",        True),
    ("resveratrol","NQO2",   "inhibits",        True),
    ("chloroquine","NQO2",   "binds",           True),
    ("casimiroin","NQO2",    "inhibits",        True),
    ("GFAP",      "PPCS",    "predicts",        True),
    ("NfL",       "GOS-E",   "correlates_with", True),
]
```

### B2. Store typed edges — extend `entity_relations` + `build_entity_relations()`

- Add columns: `edge_kind TEXT DEFAULT 'cooccur'`, `directed INTEGER DEFAULT 0`.
- Co-occurrence pass unchanged (`edge_kind='cooccur'`, `directed=0`).
- New pass resolves each `PATHWAY_EDGES` name→entity id and writes `edge_kind='curated'`, `directed=1`, `relation=<type>`. Curated + cooccur edges may coexist for the same pair.
- `export_graph_json()` (~L289): include `relation`, `edge_kind`, `directed` on each edge so the frontend draws arrowheads + labels for curated edges.

---

## 5. Part C — Full-text search (SQLite FTS5, no new dependency)

In `init_schema()`:
```sql
CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    pmid UNINDEXED, title, abstract, authors,
    content='papers', content_rowid='rowid'
);
```
Build step in `build_kb.py` (after fetch, before graph export):
```python
conn.execute("INSERT INTO papers_fts(papers_fts) VALUES('rebuild');")
```
Queried by `/api/search` via `MATCH` + `bm25()` ranking. FTS5 ships with stdlib `sqlite3`.

---

## 6. Part D — Containerized web app (`app/` — new)

### D1. Backend — `app/main.py` (FastAPI) + `app/db.py` (read-only SQLite helpers)

All filters AND-combined. Multi-value params (`types`, `clusters`) accept comma lists.

| Endpoint | Returns |
|---|---|
| `GET /api/stats` | counts (papers, entities, edges, clusters) — port `query_kb.cmd_stats` |
| `GET /api/graph?min_papers=&min_edge=&types=&clusters=&disease=&q=` | filtered nodes + edges; each edge carries `relation`,`edge_kind`,`directed` |
| `GET /api/node/{id}/papers?year_min=&year_max=&cluster=&limit=` | **publication list** — join `paper_entity`→`papers`, year desc; fields: pmid, title, authors, journal, year, doi, relation, clusters |
| `GET /api/entity/{id}` | aliases, paper_count, **typed mechanism links** (in/out curated edges), top co-occurring entities |
| `GET /api/search?q=&clusters=&types=&year_min=&year_max=` | **multi-param FTS** (`papers_fts MATCH` + facet WHERE); returns papers + set of entity node-ids they hit (for graph highlight) |

Serve frontend via `StaticFiles`: mount `app/static/` at `/` and `lib/` at `/lib`.

### D2. Frontend — `app/static/{index.html, app.js, styles.css}`

Two-pane (graph left, detail panel right) + top search bar + left facet rail. Port v1.0 `applyFilters` as the base, then add:

- **Graph** from `/api/graph`, rendered with local `lib/vis-9.1.2/vis-network.min.js`. Curated edges = directed arrowheads + relation label; cooccur edges = thin grey.
- **Multi-param facets** with vendored `lib/tom-select`: node-type (multi), cluster (multi — now real via `paper_clusters`), disease dropdown, min-papers / min-edge sliders, year range. Facet change → re-query `/api/graph` (sliders can filter client-side).
- **Search bar → `/api/search`:** highlight matching nodes + list matching papers in the panel (this is the combined text+facet search surface).
- **Click node → `/api/node/{id}/papers`:** panel lists papers with **DOI** (`https://doi.org/<doi>`) and **PubMed** (`https://pubmed.ncbi.nlm.nih.gov/<pmid>`) links, plus typed mechanism links from `/api/entity/{id}`.
- Reuse `lib/bindings/utils.js` `neighbourhoodHighlight()` for click-to-focus.

### D3. Containerization — repo root (new files)

`requirements.txt`
```
fastapi
uvicorn[standard]
requests
networkx
pyvis
```
`Dockerfile`
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY kb/ ./kb/
COPY lib/ ./lib/
COPY build_kb.py visualize_graph.py ./
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
`docker-compose.yml`
```yaml
services:
  web:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data      # live DB; keeps image small
```
`.dockerignore`: `*.pdf`, `*.docx`, `.git`, `data/*.png`, `__pycache__/`

---

## 7. File map

**New:** `app/main.py`, `app/db.py`, `app/static/index.html`, `app/static/app.js`, `app/static/styles.css`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `.dockerignore`

**Modify:**
- `kb/fetch_papers.py` — 5 clusters; `paper_clusters` + `papers_fts` in `init_schema`; junction insert in `upsert_papers`.
- `kb/build_graph.py` — new entities; `PATHWAY_EDGES` + typed-edge pass; `entity_relations` columns; edge fields in `export_graph_json`.
- `build_kb.py` — backfill `paper_clusters`; FTS5 rebuild step; run new passes on `--skip-fetch`.
- `README.md` — document app, `docker compose up`, new clusters, typed edges.

**Reuse unchanged:** `lib/vis-9.1.2/`, `lib/tom-select/`, `lib/bindings/utils.js`, `kb/query_kb.py`, `.github/workflows/daily_sync.yml`.

---

## 8. Build & run (on a fresh machine)

```bash
# 1. Clone v1.0 and branch
git clone https://github.com/Lipskerov/tbi-knowledge-graph.git
cd tbi-knowledge-graph
git checkout -b v2-app

# 2. (Implement Parts A–D per this spec.)

# 3. Rebuild DB from existing data — NO network needed (adds junction, FTS, typed edges)
python build_kb.py --skip-fetch

# 4. (Optional) fetch the new QR2 clusters
python build_kb.py --cluster qr2_inhibitors      --api-key <KEY>
python build_kb.py --cluster qr2_melatonin_mt3   --api-key <KEY>
python build_kb.py --cluster qr2_antimalarials   --api-key <KEY>
python build_kb.py --cluster qr2_flavonoids      --api-key <KEY>
python build_kb.py --cluster qr2_structure_kinetics --api-key <KEY>

# 5. Run the app
docker compose up --build      # → http://localhost:8000
```

---

## 9. Verification

1. **Rebuild (offline):** `python build_kb.py --skip-fetch`, then
   `sqlite3 data/tbi_papers.db "SELECT count(*) FROM paper_clusters; SELECT count(*) FROM entity_relations WHERE edge_kind='curated'; SELECT count(*) FROM papers_fts;"` — all non-zero.
2. **New cluster fetch:** run one `--cluster qr2_*`; confirm new PMIDs + multi-cluster rows.
3. **App up:** `docker compose up --build` → `http://localhost:8000` loads the graph.
4. **API smoke (curl):**
   - `curl 'localhost:8000/api/search?q=melatonin+quinone+reductase'` → papers + node ids.
   - `curl 'localhost:8000/api/node/<NQO2_id>/papers'` → publication list with DOIs.
   - `curl 'localhost:8000/api/graph?clusters=qr2_inhibitors,qr2_melatonin_mt3&types=drug,protein'` → filtered subgraph.
5. **UI:** click NQO2 → papers panel + working DOI/PubMed links; `S29434 —inhibits→ NQO2` renders as a directed arrow; multi-selecting two clusters narrows the graph; typing in search highlights nodes.
6. **Back-compat:** `python kb/query_kb.py --stats` and `--entity NQO2 --show-papers` still work; `python visualize_graph.py` still emits the static HTML; daily-sync Action unaffected.

---

## 10. Out of scope (tracked elsewhere)

The BIKO-inspired data-annotation track (LLM extraction of AUC / time-point / phase / study-design into a `biomarker_data` table) is in `potential_improvement.md`. v2.0 leaves a `phase` facet slot ready in the UI but does **not** require that pipeline. Build it as a later pass on top of v2.0.

---

## 11. Where this doc lives

On approval, save this spec into the repo as `docs/V2_BUILD_SPEC.md` (or `DEV_V2.md`) and commit it to the `v2-app` branch so it syncs to GitHub and is available on any machine that clones the repo.
