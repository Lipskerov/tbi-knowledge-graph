# TBI Knowledge Graph

A local, queryable knowledge base of **2,679 TBI diagnostic papers** organised around the **NQO2 (Quinone Reductase 2) pathway** as a novel blood biomarker entry point.

Built to support a research project on TBI diagnostics at the [Rosenblum Lab](https://neurosenblum.haifa.ac.il) (University of Haifa) × [Liraz-Zaltsman Lab](https://www.sheba.co.il) (Sheba Medical Center).

---

## What's inside

| File | Contents |
|------|----------|
| `data/tbi_papers.db` | SQLite — 2,679 papers, 74 entities, 767 graph edges |
| `data/knowledge_graph.json` | Full entity-relation graph export |
| `data/paper_summaries.md` | Human-readable index of all papers with entity tags |
| `data/claude_context.json` | Compact JSON for loading as Claude context |
| `data/tbi_graph.html` | Pre-built interactive graph — open in any browser |

---

## v2.0 — Containerized web app

v2.0 adds a FastAPI + SQLite-FTS5 web app on top of the same database. See
[`docs/V2_BUILD_SPEC.md`](docs/V2_BUILD_SPEC.md) for the full spec.

```bash
# 1. Rebuild the DB additively (junction table, FTS index, typed edges) — no network
python build_kb.py --skip-fetch

# 2. (optional) fetch new QR2/NQO2 clusters from PubMed and/or bioRxiv
python build_kb.py --cluster qr2_inhibitors --api-key <NCBI_KEY>   # PubMed
python build_kb.py --source biorxiv                                # bioRxiv (Europe PMC + api.biorxiv.org)

# 3. Build & run the app
docker compose up --build      # → http://localhost:8000
```

**What's new**
- **Click a node → its papers** with DOI / PubMed / bioRxiv links (`/api/node/{id}/papers`).
- **Full-text search** over all abstracts via SQLite FTS5 (`/api/search`).
- **Typed, directed mechanism edges** (e.g. `S29434 —inhibits→ NQO2`) alongside co-occurrence edges.
- **Multi-cluster faceting** via a `paper_clusters` junction table (a paper can be in many clusters).
- **bioRxiv preprints** ingested into the same graph (tagged `source='biorxiv'`).
- Endpoints: `/api/stats`, `/api/graph`, `/api/node/{id}/papers`, `/api/entity/{id}`, `/api/search`.

The v1.0 CLI (`kb/query_kb.py`), the static `visualize_graph.py` export, and the daily-sync
GitHub Action are unchanged — v2.0 is purely additive.

---

## Quick start

```bash
# 1. Install dependencies
pip install requests networkx pyvis

# 2. Open the pre-built interactive graph
open data/tbi_graph.html      # macOS
# or just double-click the file in Finder

# 3. Query the database
python kb/query_kb.py --stats
python kb/query_kb.py --q "NQO2 blood TBI biomarker"
python kb/query_kb.py --entity NQO2 --show-papers
python kb/query_kb.py --cluster nqo2

# 4. Rebuild the graph visualization
python visualize_graph.py

# 5. Rebuild the full database (re-fetches PubMed)
python build_kb.py
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

## Paper clusters

| Cluster | Papers | Description |
|---------|--------|-------------|
| `nqo2` | 370 | **All NQO2/QR2 papers** — full enzyme biology, no filter |
| `gfap_uchl1` | 300 | GFAP + UCH-L1 as TBI blood diagnostics |
| `ppcs_prognosis` | 287 | Post-concussion syndrome biomarkers and prognosis |
| `exosomal_rna` | 283 | Exosomal / extracellular vesicle RNA in TBI |
| `tbi_mild_blood` | 335 | mTBI + blood biomarkers 2018–2026 |
| `tbi_proteomics` | 471 | TBI + proteomics / metabolomics |
| `tbi_panel_poc` | 224 | Multi-marker panels + point-of-care TBI tests |
| `nfl_tau` | 217 | NfL and tau in TBI blood diagnosis / prognosis |
| `proteostasis` | 192 | p62/SQSTM1, autophagy, UPS in TBI |

---

## Knowledge graph entities (74 total)

### NQO2/QR2 pathway (amber nodes in the graph)

```
Upstream:    dopamine → DRD1 → cAMP/PKA → miR-182 → NQO2 suppression
Enzyme:      NQO2 (vs NQO1 — selectivity problem; substrate: NRH not NADPH)
Downstream:  NQO2 → ROS → Kv2.1 oxidation → interneuron excitability
Antioxidant: ROS → Nrf2 → HO-1 / SOD / glutathione / catalase
ISR arm:     PKR / PERK / GCN2 → eIF2α-P → eEF2↓ / ATF4↑ / CHOP↑
Inhibitors:  S29434 (Rosenblum lab), quercetin, resveratrol
```

### Established TBI blood biomarkers

`GFAP` · `UCH-L1` · `NfL` · `tau` · `p-tau` · `S100B` · `NSE` · `MBP`

### Proteostasis axis (Fedor's PhD biology)

`p62/SQSTM1` · `LC3` · `beclin-1` · `ubiquitin` · `UPS`

### Neuroinflammation

`Iba1` · `GFAP` · `IL-6` · `TNF-α` · `IL-1β` · `neuroinflammation`

### RNA biomarkers

`VLDLR-AS1` · `MALAT1` · `GAS5` · `NEAT1` · `miR-21` · `miR-182`

---

## Query reference

```bash
# Statistics
python kb/query_kb.py --stats

# Keyword search (ranked by relevance)
python kb/query_kb.py --q "NQO2 blood TBI"
python kb/query_kb.py --q "PPCS prognosis 6 months"
python kb/query_kb.py --q "exosomal miRNA mild TBI"
python kb/query_kb.py --q "multi-marker panel point of care"

# Entity lookup
python kb/query_kb.py --entity NQO2
python kb/query_kb.py --entity GFAP --show-papers
python kb/query_kb.py --entity Nrf2 --show-papers
python kb/query_kb.py --entity p62 --show-papers

# Co-occurrence (what appears alongside an entity)
python kb/query_kb.py --related NQO2
python kb/query_kb.py --related GFAP

# Browse cluster
python kb/query_kb.py --cluster nqo2
python kb/query_kb.py --cluster tbi_mild_blood --year-min 2022
python kb/query_kb.py --cluster ppcs_prognosis --limit 20

# Full record for a paper
python kb/query_kb.py --pmid 35617003

# Export compact JSON for Claude context
python kb/query_kb.py --export-context
```

---

## Visualization

```bash
# Default: full graph, min 2 papers per node, min 2 shared papers per edge
python visualize_graph.py

# Tighter — major hubs only (good for presentations)
python visualize_graph.py --min-papers 5 --min-edge 3

# Highlight entities that appear in NQO2 cluster papers
python visualize_graph.py --cluster nqo2

# Highlight PPCS prognosis cluster
python visualize_graph.py --cluster ppcs_prognosis
```

**Graph legend:**
- **Amber nodes** — NQO2/QR2 pathway
- Blue — protein | Teal — metabolite | Orange — RNA
- Red-orange — pathway/process | Red — disease | Purple — drug/platform
- Node size ∝ paper count · Edge thickness ∝ shared papers

---

## Rebuilding the database

```bash
# Full rebuild (re-queries PubMed, only fetches new PMIDs)
python build_kb.py

# Faster with NCBI API key (10 req/s vs 3 req/s)
# Get a free key at: https://www.ncbi.nlm.nih.gov/account/
python build_kb.py --api-key YOUR_KEY

# Rebuild graph only (skip PubMed fetch)
python build_kb.py --skip-fetch

# Single cluster refresh
python build_kb.py --cluster nqo2
```

---

## Extending the knowledge base

### Add a new search cluster

Edit `kb/fetch_papers.py`, add to `CLUSTERS`:
```python
"new_cluster": '("your query") AND (additional terms)',
```
Add the fetch cap to `CLUSTER_CAPS` (or `None` to fetch all). Then:
```bash
python build_kb.py --cluster new_cluster
```

### Add new entities

Edit `ENTITY_SEEDS` in `kb/build_graph.py`:
```python
("EntityName", "protein", ["alias1", "alias2", "alias 3"]),
```
Then:
```bash
python build_kb.py --skip-fetch
```

### Add a paper manually

```python
import sqlite3
conn = sqlite3.connect("data/tbi_papers.db")
conn.execute("""
    INSERT OR IGNORE INTO papers
        (pmid, title, abstract, authors, journal, year, doi, source, topic_cluster, fetched_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', 'nqo2', datetime('now'))
""", ("PMID", "Title", "Abstract...", "Author et al.", "Journal", 2025, "10.xxx/xxx"))
conn.commit()
```
Then rebuild the graph: `python build_kb.py --skip-fetch`

---

## Project structure

```
.
├── build_kb.py              # Main pipeline: fetch → graph → export
├── visualize_graph.py       # PyVis interactive HTML graph
├── CLAUDE.md                # Claude Code context file
├── kb/
│   ├── fetch_papers.py      # PubMed E-utilities fetcher (9 clusters)
│   ├── build_graph.py       # Entity extraction + NetworkX graph builder
│   └── query_kb.py          # CLI query interface
└── data/
    ├── tbi_papers.db        # SQLite database
    ├── knowledge_graph.json # Full graph (nodes + edges + centrality)
    ├── paper_summaries.md   # All papers with abstracts + entity tags
    ├── claude_context.json  # Compact context for Claude queries
    └── tbi_graph.html       # Interactive graph (open in browser)
```

---

## Dependencies

```bash
pip install requests networkx pyvis
```

Python 3.10+. No other dependencies — uses only `sqlite3` from the standard library.

---

## Data sources

All papers fetched from [PubMed](https://pubmed.ncbi.nlm.nih.gov/) via the NCBI E-utilities API. Three foundational papers from the Rosenblum lab are pre-loaded:

- Gould et al., *eNeuro* 2021 — QR2 in SST interneurons and taste memory
- Gould et al., *JCI* 2022 — QR2 inhibitors reverse AD phenotype in 5xFAD mice
- Gould et al., *J Neuroscience* 2020 — Dopamine-dependent QR2 pathway in CA1
