# TBI Knowledge Graph — literature knowledge base

A literature knowledge base for blood-biomarker research in traumatic brain injury (TBI), centred on
the biology of quinone reductase 2 (QR2, gene *NQO2*). It collects PubMed and bioRxiv papers in topic
clusters, tags them with biomarker, pathway and drug entities, and links the entities in a
provenance-labelled graph that can be explored from the command line or a web app. New PubMed papers
are added daily.

> **Looking for the knowledge graph?** The standards-based successor, **TBI-BiomarkerKG**
> (Biolink-compliant, 175,948 edges from curated databases, published TBI omics and text-mined
> literature, with a time-split benchmark), is in its own repository:
> **[github.com/Lipskerov/tbi-biomarker-kg](https://github.com/Lipskerov/tbi-biomarker-kg)**.

Developed in the Rosenblum laboratory (Sagol Department of Neurobiology, University of Haifa) in
collaboration with the Liraz-Zaltsman laboratory (Sheba Medical Center).

---

## At a glance

| | |
|---|---|
| Papers | **7,248**: 6,923 PubMed, 325 bioRxiv (1951–2026) |
| Entities | **115**: 52 drugs, 37 proteins, 7 RNAs, 7 metabolites, 7 diseases, 4 pathways, 1 process |
| Graph edges | **1,040**: 947 co-occurrence, 13 curated mechanism, 40 ChEMBL inhibitor potency, 40 OmniPath signed interactions |
| Topic clusters | 14 (a paper can belong to several) |
| Interfaces | Command-line queries, a password-protected web app, a static HTML graph |

Counts measured on 6 Oct 2026; the daily sync changes them.

## Topic clusters

| Cluster | Papers | Topic |
|---|---|---|
| `aging_neuro` | 1,862 | Brain aging and age-related neurodegeneration |
| `tbi_mild_blood` | 1,341 | Mild TBI and blood biomarkers |
| `nfl_tau` | 1,087 | Neurofilament light and tau in TBI |
| `ppcs_prognosis` | 1,078 | Persistent post-concussion symptoms and prognosis |
| `gfap_uchl1` | 937 | GFAP and UCH-L1 as TBI blood diagnostics |
| `tbi_proteomics` | 905 | TBI proteomics and metabolomics |
| `exosomal_rna` | 424 | Extracellular-vesicle RNA in TBI |
| `nqo2` | 384 | NQO2/QR2 biology, without a disease filter |
| `tbi_panel_poc` | 317 | Multi-marker panels and point-of-care TBI tests |
| `qr2_structure_kinetics` | 303 | QR2 structure and enzyme kinetics |
| `qr2_inhibitors` | 254 | QR2 inhibitor pharmacology |
| `qr2_melatonin_mt3` | 68 | QR2 as the MT3 melatonin binding site |
| `qr2_flavonoids` | 66 | Flavonoid QR2 inhibitors |
| `qr2_antimalarials` | 27 | Antimalarial QR2 inhibitors |

## Graph edges

| Kind | Meaning | Count |
|---|---|---|
| `cooccur` | Two entities mentioned in the same paper; weight = number of shared papers | 947 |
| `curated` | Hand-curated, directed mechanism edges from the QR2 literature | 13 |
| `chembl` | Compound → NQO2 inhibition with potency (IC50, Ki or Kd; pChEMBL) from ChEMBL | 40 |
| `omnipath` | Signed, directed protein interactions from OmniPath | 40 |

Co-occurrence edges show that two entities are discussed together, not that one affects the other.

## QR2 biology in the graph

QR2 is a flavoenzyme that reduces quinones using dihydronicotinamide riboside (NRH) as co-substrate and
generates reactive oxygen species. The curated edges encode the pathway described by the Rosenblum
laboratory: dopamine → DRD1 → cAMP/PKA → miR-182 ⊣ QR2, and QR2 → ROS → Kv2.1 oxidation in
interneurons, which makes QR2 a removable constraint on memory formation.

- Gould NL et al. Dopamine-dependent QR2 pathway activation in CA1 interneurons enhances novel memory
  formation. *J Neurosci* 2020;40:8698–8714. [doi:10.1523/JNEUROSCI.1243-20.2020](https://doi.org/10.1523/JNEUROSCI.1243-20.2020)
- Gould NL et al. Somatostatin interneurons of the insula mediate QR2-dependent novel taste memory
  enhancement. *eNeuro* 2021;8:ENEURO.0152-21.2021. [doi:10.1523/ENEURO.0152-21.2021](https://doi.org/10.1523/ENEURO.0152-21.2021)
- Gould NL et al. Specific quinone reductase 2 inhibitors reduce metabolic burden and reverse
  Alzheimer's disease phenotype in mice. *J Clin Invest* 2023;133:e162120. [doi:10.1172/JCI162120](https://doi.org/10.1172/JCI162120)

An evidence-graded map of what lies downstream of QR2 is in
[`05_analysis/exports/QR2_downstream_map.md`](05_analysis/exports/QR2_downstream_map.md); the directed
pathway is in [`data/qr2_pathway.json`](data/qr2_pathway.json).

---

## Query from the command line

```bash
pip install -r requirements.txt
python kb/query_kb.py --stats
python kb/query_kb.py --q "NQO2 blood biomarker"
python kb/query_kb.py --entity NQO2 --show-papers
python kb/query_kb.py --related NQO2           # co-occurring entities
python kb/query_kb.py --cluster gfap_uchl1 --year-min 2022
python kb/query_kb.py --pmid 37561584          # full record for one paper
python kb/query_kb.py --export-context         # compact JSON summary
```

## Web app

A FastAPI + SQLite FTS5 application with an interactive graph (vis.js) whose edges are coloured by
kind, per-entity paper lists, full-text search over abstracts and filters for cluster, entity type and
year. Access is protected by a shared password.

```bash
python -m app.auth set-password      # writes a git-ignored .env with the password hash and session secret
docker compose up --build -d         # http://localhost:8000
```

Read-only API (session cookie from `/login` required):

| Method | Path | Returns |
|---|---|---|
| GET | `/api/stats` | Counts of papers, entities, edges by kind, clusters |
| GET | `/api/graph` | Nodes and edges; filters `min_papers`, `min_edge`, `types`, `clusters`, `disease`, `q`, `year_min`, `year_max` |
| GET | `/api/node/{id}/papers` | Papers for an entity |
| GET | `/api/entity/{id}` | Entity aliases, mechanism links and top co-occurring entities |
| GET | `/api/search` | Full-text search over abstracts |

The app serves plain HTTP. Put it behind an HTTPS reverse proxy and set `TBI_HTTPS_ONLY=1` before
exposing it beyond a trusted network.

## Static graph

```bash
python visualize_graph.py                          # full graph → data/tbi_graph.html
python visualize_graph.py --min-papers 5 --min-edge 3
python visualize_graph.py --cluster nqo2
```

## Rebuild and extend

```bash
python build_kb.py                   # fetch new PubMed papers for every cluster, rebuild the graph
python build_kb.py --api-key KEY     # NCBI API key: 10 instead of 3 requests per second
python build_kb.py --skip-fetch      # rebuild the graph only
python build_kb.py --cluster nqo2    # refresh one cluster
python build_kb.py --source biorxiv  # bioRxiv preprints via Europe PMC
python build_kb.py --chembl          # ChEMBL NQO2 inhibitor potencies
python build_kb.py --omnipath        # OmniPath signed interactions
```

Add a cluster by editing `CLUSTERS` in `kb/fetch_papers.py`; add entities or curated edges in
`kb/build_graph.py` (`ENTITY_SEEDS`, `PATHWAY_EDGES`).

## Repository layout

```
kb/             fetchers (PubMed, bioRxiv, ChEMBL, OmniPath), graph builder, CLI
app/            FastAPI web app
data/           SQLite database and exports, updated daily
05_analysis/    biomarker-panel analyses
04_reference/   build specifications
.github/        daily PubMed sync workflow
```

## Data sources

PubMed (NCBI E-utilities); bioRxiv via Europe PMC; ChEMBL (CC BY-SA 3.0); OmniPath and the resources it
aggregates (per-resource licences). Abstracts remain the copyright of their publishers.

## Version history

See [`CHANGELOG.md`](CHANGELOG.md).
