# TBI Knowledge Base — CLAUDE.md

> For Claude Code: full context to pick up work immediately without re-reading the codebase.

## What this project is

A local SQLite + NetworkX knowledge graph of TBI diagnostic literature, built for **Fedor Lipskerov** (biotech founder, molecular biologist). The project centers on **NQO2 (Quinone Reductase 2)** as a novel TBI blood biomarker entry point, embedded in the Rosenblum lab (University of Haifa) × Liraz-Zaltsman lab (Sheba Medical Center) postdoc project.

**Scientific thesis:** NQO2 is overexpressed in aging brain → drives oxidative stress → connects to TBI secondary injury cascade and long-term neurodegeneration risk. The goal is to develop a multi-analyte blood panel (NQO2 pathway + established markers) for TBI diagnostics, ideally with a PPCS (persistent post-concussion syndrome) prognosis angle.

---

## Directory Structure

```
/Users/lipskerov/Desktop/TBI/
├── CLAUDE.md                    ← you are here
├── build_kb.py                  ← main pipeline (run this to rebuild)
├── kb/
│   ├── fetch_papers.py          ← PubMed E-utilities fetcher
│   ├── build_graph.py           ← entity extraction + NetworkX graph
│   └── query_kb.py              ← CLI query interface
├── data/
│   ├── tbi_papers.db            ← SQLite database (~8 MB, 2,679 papers)
│   ├── knowledge_graph.json     ← full graph export
│   ├── paper_summaries.md       ← human-readable paper index (~1.2 MB)
│   └── claude_context.json      ← compact context for Claude (~50 KB)
└── [3 local PDFs — Rosenblum lab papers on QR2]
```

---

## Database Contents (as of May 2026)

| Cluster | Papers | Topic |
|---------|--------|-------|
| `nqo2` | 370 | **All NQO2/QR2 papers** — enzyme biology, inhibitors, cancer, aging, neurodegeneration, no filter |
| `gfap_uchl1` | 300 | GFAP and UCH-L1 as TBI blood diagnostics — the competitive landscape |
| `ppcs_prognosis` | 287 | Post-concussion syndrome prognosis biomarkers — commercial whitespace |
| `exosomal_rna` | 283 | Exosomal / extracellular vesicle RNA in TBI |
| `tbi_mild_blood` | 335 | mTBI/concussion + blood biomarkers 2018–2026 — recent clinical cohort papers |
| `tbi_proteomics` | 471 | TBI + proteomics/metabolomics/mass spectrometry — discovery methods |
| `tbi_panel_poc` | 224 | Multi-marker panels + point-of-care TBI tests — commercial translation angle |
| `nfl_tau` | 217 | NfL and tau in TBI blood diagnosis and prognosis |
| `proteostasis` | 192 | p62/SQSTM1, autophagy, UPS in TBI |

**Total: 2,679 papers, 74 entities, 7,039 paper-entity links, 767 graph edges**
**Year range: 1975–2026**

### Why NQO2 has no tissue/disease filter
All 367 PubMed NQO2 papers are included — enzyme structure, cancer biology, pharmacology, tissue expression, inhibitor chemistry. This is intentional: designing a blood assay requires understanding the full NQO2 biology (substrate specificity, inhibitor selectivity vs NQO1, expression in blood cells vs neurons, release mechanisms on cell damage).

### NQO2 co-occurrence in the graph (top connections)
| Entity | Shared papers | Significance |
|--------|--------------|--------------|
| NQO1 | 113 | Selectivity problem — inhibitors must not hit NQO1 |
| NRH | 87 | NQO2's preferred substrate (not NADPH like NQO1) — key for assay design |
| ROS | 72 | Core mechanism — NQO2 is a ROS source |
| oxidative stress | 55 | Pathway axis connecting NQO2 → TBI secondary injury |
| resveratrol | 32 | Natural polyphenol NQO2 modulator — large pharmacology literature |
| glutathione | 17 | Antioxidant defense, consumed when NQO2-driven ROS rises |
| dopamine | 16 | Upstream trigger (LC → DRD1 → miR-182 → NQO2 suppression) |
| Nrf2 | 14 | Master antioxidant TF — NQO2 modulates Nrf2 activity |
| Alzheimer | 12 | Neurodegeneration bridge (5xFAD mouse model, JCI 2022) |
| S29434 | 11 | Specific Rosenblum lab NQO2 inhibitor compound |
| quercetin | 8 | Natural flavonoid NQO2 inhibitor |
| SOD | 8 | Antioxidant enzyme co-regulated with NQO2 |
| autophagy | 8 | Proteostasis connection (relevant to p62 sub-project) |
| cAMP | 5 | D1R → cAMP/PKA → miR-182 signaling intermediate |
| HO-1 | 4 | Nrf2 target, neuroprotective downstream of antioxidant response |
| p62 | 3 | Direct link to Fedor's PhD biology |
| miR-182 | 3 | Upstream regulator of NQO2 expression |
| Kv2.1 | 3 | Downstream target — oxidized by NQO2-driven ROS to reduce interneuron excitability |
| tau | 2 | TBI→AD prognosis bridge |
| CHOP | 2 | ISR stress TF downstream of eIF2α |
| TBI | 2 | Confirms near-zero direct NQO2 + TBI literature — the whitespace |

### Why the new TBI clusters were added
- **`tbi_proteomics`** (471): Covers discovery-phase methodology — proteomics/metabolomics approaches used in TBI blood studies. Directly relevant for designing the Sheba cohort discovery phase (Olink, Alamar NULISA, Simoa).
- **`tbi_mild_blood`** (335): 2018–2026 mTBI + blood papers only. The most up-to-date clinical cohort literature — performance benchmarks, cohort designs, and comparators for the project.
- **`tbi_panel_poc`** (224): Multi-marker panels and point-of-care TBI tests. Maps directly to the product direction (multi-analyte panel, not single biomarker).

---

## How to Query the Knowledge Base

### Statistics
```bash
cd /Users/lipskerov/Desktop/TBI
python kb/query_kb.py --stats
```

### Keyword search (returns top 10 ranked papers)
```bash
python kb/query_kb.py --q "NQO2 blood TBI biomarker"
python kb/query_kb.py --q "PPCS prognosis 6 months outcome"
python kb/query_kb.py --q "exosomal miRNA concussion"
```

### Entity lookup (biomarker, protein, pathway)
```bash
python kb/query_kb.py --entity NQO2
python kb/query_kb.py --entity GFAP --show-papers
python kb/query_kb.py --entity p62 --show-papers
python kb/query_kb.py --entity "post-concussion syndrome" --show-papers
```

### Entity co-occurrence (what co-appears with a given entity)
```bash
python kb/query_kb.py --related NQO2
python kb/query_kb.py --related GFAP
```

### Browse a cluster
```bash
python kb/query_kb.py --cluster nqo2
python kb/query_kb.py --cluster ppcs_prognosis --year-min 2020
python kb/query_kb.py --cluster gfap_uchl1 --year-min 2022 --limit 20
python kb/query_kb.py --cluster tbi_proteomics --year-min 2020
python kb/query_kb.py --cluster tbi_mild_blood
python kb/query_kb.py --cluster tbi_panel_poc
```

### Full record for a specific paper
```bash
python kb/query_kb.py --pmid 35617003
```

### Refresh Claude context file (after updates)
```bash
python kb/query_kb.py --export-context
```

---

## How to Update / Rebuild

### Re-fetch all clusters from PubMed (only fetches new PMIDs)
```bash
python build_kb.py
```

### Rebuild graph only (papers already fetched)
```bash
python build_kb.py --skip-fetch
```

### Fetch with NCBI API key (10 req/s vs 3 req/s — much faster)
```bash
python build_kb.py --api-key YOUR_KEY
# Get free key at: https://www.ncbi.nlm.nih.gov/account/
```

### Fetch a single cluster
```bash
python build_kb.py --cluster nqo2           # re-check for new NQO2 papers
python build_kb.py --cluster tbi_mild_blood  # refresh recent mTBI blood papers
python build_kb.py --cluster tbi_proteomics
```

### Test with small fetch
```bash
python build_kb.py --limit 20 --cluster gfap_uchl1
```

---

## Key Entities in the Knowledge Graph

74 entities total. Grouped by role in the project:

### TBI diagnostic biomarkers (competitive landscape)
| Entity | Papers | Notes |
|--------|--------|-------|
| GFAP | ~300 | FDA-cleared (Abbott i-STAT TBI) |
| UCH-L1 | ~280 | FDA-cleared (Abbott i-STAT TBI) — Fedor's PhD hook via p62/UPS biology |
| NfL | ~200 | Leading prognostic marker, no FDA-cleared TBI test yet |
| tau / p-tau | ~200 | TBI→AD bridge, strong prognostic signal |
| S100B | ~100 | Oldest TBI marker, poor specificity |
| NSE | ~50 | Neuron-specific enolase — alternative neuronal damage marker |
| MBP | ~30 | Myelin basic protein — axonal injury marker |

### NQO2/QR2 pathway (the novel angle)
| Entity | Papers | Notes |
|--------|--------|-------|
| NQO2 | 370 | Full enzyme biology; ~2 TBI papers — the whitespace |
| NQO1 | ~200 | Selectivity partner — inhibitors must distinguish from NQO2 |
| NRH | ~90 | NQO2's preferred substrate (distinguishes it from NQO1/NADPH) |
| dopamine | ~16 | Upstream trigger of NQO2 suppression pathway |
| DRD1 | ~5 | Dopamine D1 receptor — initiates miR-182 → NQO2 cascade |
| cAMP | ~5 | Signaling intermediate (D1R → cAMP/PKA) |
| miR-182 | ~3 | Suppresses NQO2 expression downstream of DRD1 |
| Kv2.1 | ~3 | Downstream effector — oxidized by NQO2 ROS to tune interneuron firing |
| resveratrol | ~32 | Natural NQO2 modulator, large pharmacology literature |
| quercetin | ~8 | Natural flavonoid NQO2 inhibitor |
| S29434 | ~11 | Rosenblum lab specific NQO2 inhibitor |

### Antioxidant response arm (NQO2 → Nrf2 axis)
| Entity | Papers | Notes |
|--------|--------|-------|
| ROS | ~200 | Core output of NQO2 activity |
| Nrf2 | ~32 | Master antioxidant TF — bidirectional relationship with NQO2 |
| HO-1 | ~20 | Nrf2 target, neuroprotective |
| SOD | ~30 | Antioxidant enzyme co-regulated with NQO2 |
| glutathione | ~50 | Major antioxidant buffer |
| catalase | ~15 | H₂O₂ scavenger |
| 4-HNE | ~20 | Lipid peroxidation product — oxidative stress reporter |

### ISR / translation regulation arm
| Entity | Papers | Notes |
|--------|--------|-------|
| eIF2α | ~30 | Central ISR node — phosphorylated by PKR, PERK, GCN2 |
| PKR | ~20 | dsRNA-activated kinase, Rosenblum lab's ProteKt therapeutic target |
| PERK | ~15 | ER stress kinase — also phosphorylates eIF2α |
| GCN2 | ~5 | Amino acid stress kinase |
| eEF2 | ~10 | Elongation factor — translationally regulated |
| ATF4 | ~15 | ISR downstream TF — drives stress gene expression |
| CHOP | ~10 | Stress TF downstream of eIF2α — apoptosis trigger |
| eIF2B | ~5 | GEF that reverses eIF2α phosphorylation |

### Synaptic plasticity / memory effectors (Rosenblum lab context)
| Entity | Papers | Notes |
|--------|--------|-------|
| CaMKII | ~30 | Key plasticity kinase — TBI disrupts CaMKII signaling |
| Arc | ~15 | Immediate early gene — marker of synaptic consolidation |
| AMPA receptor | ~40 | Synaptic receptor — TBI causes AMPAR trafficking defects |
| NMDA receptor | ~50 | Excitotoxicity receptor — primary TBI acute injury mechanism |
| BDNF | ~30 | Neurotrophin — disrupted in TBI, potential biomarker |

### Proteostasis axis (p62 / autophagy / UPS)
| Entity | Papers | Notes |
|--------|--------|-------|
| p62/SQSTM1 | ~50 | Proteostasis bridge — Fedor's PhD biology, links UPS to autophagy |
| LC3 | ~40 | Autophagosome marker |
| beclin-1 | ~30 | Autophagy initiator |
| ubiquitin | ~150 | Core UPS signal |

### Clinical / disease entities
| Entity | Papers | Notes |
|--------|--------|-------|
| mTBI | ~600 | Primary diagnostic target |
| PPCS | ~280 | Post-concussion syndrome — strongest commercial angle |
| TBI | ~1000 | Broad category |
| CTE | ~30 | Chronic traumatic encephalopathy |
| Alzheimer | ~200 | TBI→AD neurodegeneration bridge |

---

## Local Rosenblum Lab Papers (in DB as `source='local'`, `cluster='nqo2'`)

| PMID | Title | Journal | Year |
|------|-------|---------|------|
| 34493578 | Somatostatin Interneurons of the Insula Mediate QR2-Dependent Novel Taste Memory Enhancement | eNeuro | 2021 |
| 35617003 | Specific quinone reductase 2 inhibitors reduce metabolic burden and reverse Alzheimer's disease phenotype in mice | JCI | 2022 |
| 32948681 | Dopamine-Dependent QR2 Pathway Activation in CA1 Interneurons Enhances Novel Memory Formation | J Neuroscience | 2020 |

> **Note:** PMIDs are pre-filled from known DOIs. If a query returns unexpected results for these, verify PMIDs with `python kb/query_kb.py --pmid 34493578`.

---

## Scientific Context (for grounded answers)

### The NQO2 → TBI blood biomarker hypothesis
- NQO2 is an intracellular flavoenzyme — not normally secreted — but can be released into circulation on neuronal damage (similar mechanism to UCH-L1, NSE)
- In aged brain, NQO2 is overexpressed → excess ROS → Kv2.1 channel dysfunction → impaired inhibitory interneuron activity
- The Rosenblum lab showed QR2 inhibitors reverse AD phenotype in 5xFAD mice (JCI 2022) — implying NQO2 dysregulation precedes or accompanies neurodegeneration
- Hypothesis: acute TBI → neuronal damage → NQO2 release into blood + ROS spike → measurable in plasma

### Project positioning (from investor conversation)
The strongest commercial angle is **PPCS prognosis** (not acute mTBI diagnosis):
- **Clinical action:** early referral to structured neurorehab for high-risk patients at 1–4 weeks
- **Payer:** self-insured employers, workers' comp, Medicare Advantage (chronic-cost-containment buyers)
- **Why:** PPCS patients cost 5–10× more over 12 months; Liraz-Zaltsman's longitudinal Sheba cohort is perfectly suited for this; Rosenblum's translation-regulation biology (PKR, eIF2α) is mechanistically aligned with chronic injury persistence

### Competitive landscape
- **Abbott i-STAT TBI** (GFAP + UCH-L1) — FDA-cleared 2021, whole-blood 2024 — the predicate everything is compared to
- **bioMérieux VIDAS TBI** — cleared 2024
- **Quanterix Simoa** — ultra-sensitive platform, used in research; Fedor should know their GFAP/NfL assays
- **Olink / Alamar NULISA** — high-plex proteomics for discovery phase
- Gap: no FDA-cleared TBI **prognostic** test; NfL is leading candidate but not cleared

---

## Claude Workflow for This Project

When Fedor asks a TBI question, the suggested workflow is:

1. **Check the DB first:** run `python kb/query_kb.py --q "..."` or `--entity` to get relevant papers
2. **Load context file** if doing broad analysis: read `data/claude_context.json`
3. **For deep dives:** read `data/paper_summaries.md` filtered by cluster
4. **For specific papers:** use `--pmid` to get full abstract + entity tags

Claude has permission to:
- Run any `python kb/query_kb.py` command (read-only)
- Run `python build_kb.py --skip-fetch` to rebuild graph
- Run `python build_kb.py` to re-fetch + rebuild
- Edit `kb/build_graph.py` to add new entities to `ENTITY_SEEDS`
- Edit `kb/fetch_papers.py` to add new search clusters to `CLUSTERS`

---

## Adding New Papers / Clusters

### Add a new search cluster
Edit `kb/fetch_papers.py`, add to `CLUSTERS` dict:
```python
"new_cluster": '("your query") AND (additional terms)',
```
Then run `python build_kb.py --cluster new_cluster`.

### Add new entities for keyword extraction
Edit `kb/build_graph.py`, add to `ENTITY_SEEDS` list:
```python
("EntityName", "protein", ["alias1", "alias2", "alias 3"]),
```
Then run `python build_kb.py --skip-fetch` to rebuild the graph.

### Add a paper manually
Insert directly into SQLite:
```python
import sqlite3, json
conn = sqlite3.connect("data/tbi_papers.db")
conn.execute("""
    INSERT OR IGNORE INTO papers (pmid, title, abstract, authors, journal, year,
                                   doi, source, topic_cluster, fetched_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', 'nqo2', datetime('now'))
""", ("PMID", "Title", "Abstract text...", "Author et al.", "Journal", 2025, "10.xxx/xxx"))
conn.commit()
```
Then run `python build_kb.py --skip-fetch`.
