# TBI-BiomarkerKG v2 (`kg2/`)

A rebuild of the TBI knowledge graph to publication standard, modelled on VitaGraph
(Madeddu et al., *Sci Data* 13:1045, 2026): every node on a public ID, every edge with a
source, a method and evidence, measured QC, and a time-sliced benchmark. v1 (`kb/`, `app/`)
is untouched and keeps running.

Plan and rationale: the "TBI Knowledge Graph v2 — Publication Build Plan" doc (claude.ai).

## Run

```bash
cd kg2 && python3 run_all.py      # ~15 s with a warm cache; first run downloads ~150 MB
```
Needs Python ≥3.10, `networkx`, `openpyxl`; network for first download. Outputs land in
`out/<version>/`. `raw/`, `interim/`, `out/` are git-ignored.

## Design

| Layer | What | Source | knowledge_level / agent_type |
| --- | --- | --- | --- |
| L1 | PPI (STRING v12 physical, score ≥ 700), signed regulation (OmniPath core, academic), pathways (Reactome, human genes only), compound→NQO2 (ChEMBL), mouse→human 1:1 orthologs (MGI) | public DBs | knowledge_assertion / automated or manual |
| L2 | gene ↔ condition, increased/decreased, with species, matrix (UBERON), log2FC, p, n per dataset row | panel.db: Mantash 2025 (PMID 40545497) + 6 human cohorts | statistical_association / data_analysis_pipeline |
| L3 | gene/chemical/disease relations with the supporting sentence | PubTator3 on 4,118 in-scope PMIDs | knowledge_assertion / text_mining_agent |
| private | unpublished lab datasets, configured in the git-ignored `private_config.py` | panel.db | `out/*/private/` — never released |

IDs: genes `NCBIGene` (HGNC, UniProt, Ensembl, MGI as xrefs); diseases and chemicals `MESH`;
pathways `REACT`; compounds `CHEMBL.COMPOUND`; project-only nodes `TBIKG`. Predicates are
Biolink. One edge per (subject, predicate, object, direction); evidence rows aggregate in
`edge_evidence.tsv`. Co-occurrence is not an edge type.

Scope: all papers of v1 except those only in `lupus_biomarkers`; bioRxiv preprints (no PMID)
are not in L3 yet.

| Step | Script | Output |
| --- | --- | --- |
| P0 freeze v1, fix scope | `p0_freeze.py` | `interim/baseline_v1/`, `interim/scope_pmids.tsv` |
| P1 ID backbone | `p1_ids.py` | `interim/genes_*.tsv`, `interim/symbol_map.tsv` |
| P2 curated reference (L1) + GO | `p2_reference.py` | `interim/l1_*.tsv`, `interim/features_go.tsv` |
| P3 omics (L2) | `p3_omics.py` | `interim/l2_*.tsv` |
| P4 literature (L3) | `p4_literature.py` | `interim/l3_*.tsv` |
| P5 integrate, QC, export | `p5_integrate.py` | `out/<v>/nodes.tsv, edges.tsv, edge_evidence.tsv, graph.nt, features/, QC.md, stats.json` |
| P6a validation sheets | `p6_validation_sheets.py` | `curation/V2_*.xlsx`, `curation/V3_edge_audit.xlsx` |
| P6b time-split benchmark | `p6_timesplit.py` | `out/<v>/benchmarks/` |
| P6d auto-audit of the 200 L1/L2 rows of V3 (source re-check + swap/flip controls) | `p6_v3_auto.py` | `curation/V3_auto_L1L2.tsv` |
| P7 publishable release split by licence (CC BY main + non-commercial + CC BY-SA) | `p7_release.py` | `out/<v>/release/` |
| P6c score V1–V3 (run after annotation; read-only on `curation/`) | `p6_score.py` (tests: `test_p6_score.py`) | `out/<v>/validation/validation_scores.tsv`, `V2_disagreements_to_adjudicate.tsv` |

## Status — build 2.0.0-dev, 2026-09-29 (numbers from `stats.json`)

- 20,203 nodes; 175,710 edges (L1 166,465 · L2 1,725 · L3 7,520); 13,507 evidence rows (public layers; the private layer is local only).
- QC (`QC.md`): all 7 structural checks pass. The first run failed two (431 viral Reactome genes
  without nodes; 3 STRING/PubTator duplicates) — both fixed at the source.
- L3: 85.9% of 10,197 relations have a sentence mentioning both entities; the rest are flagged `document_level`.
- V6 time split (cutoff 2020; 344 positives / 16,820 candidates): personalised PageRank from TBI
  nodes AUROC 0.712, AUPRC 0.082 (prevalence 0.020); literature count 0.563 / 0.067; random 0.491.

## Benchmark (kg2/bench/, run on HIVE; see SESSION_LOG 2026-09-29 for full detail)

Headline (L1 as of 2020, leakage-free; 10 seeds): R-GAT AUROC 0.725 ± 0.017, RotatE AUPRC
0.090 ± 0.008 vs personalised PageRank 0.705 / 0.065 on the same graph. Current-release L1 gives
R-GAT 0.762, of which ~0.03–0.04 is post-2020 leakage. Co-occurrence arm (v1 method) 0.598 AUROC.
Leakage audit 0 in all arms. Table: `bench/results_summary.tsv`.

## Not done yet / known limits

- **V1–V2 precision and the L3 third of V3 are unmeasured** until the sheets in `curation/` are
  annotated (two annotators, blind). The L1/L2 two-thirds of V3 is automated: 200/200 edges found in
  their source files (`p6_v3_auto.py`).
- **Licences**: see `LICENCES.md`. Publish `out/<v>/release/`, not the working files in `out/<v>/`
  (those keep abstract sentences and non-commercial edges for the benchmark and the gold set). Visible L3 noise exists, e.g. "NQO2 associated_with Actinium".
- Residual time-split leak: genes added to pre-2020 Reactome pathways after 2020 (archive
  releases are not downloadable).
- LLM second extractor (qwen2.5 72B, HIVE array 11874386) ran 29.09: 400/400 items, 0 errors,
  in `bench/llm_preds/` (labels only). Not scored until both annotators finish.
- 244 rat genes from PubTator3 have no ortholog link (MGI file is mouse–human only).
- panel.db symbols unmapped: 16,163, almost all mouse non-coding / Gm genes without homology.
- v1 "curated" edges are not carried: their PMIDs were co-mentions, not the establishing papers.
- MONDO: 328 of 539 MeSH disease nodes carry an exact MONDO xref (327 from MONDO's SSSOM + 1 curated:
  Brain Injuries, Traumatic → MONDO:0858950, which MONDO lists without a MeSH link; `mondo_mesh_additions.tsv`), each verified (name/synonym,
  Disease Ontology cross-check, obsolete status; 17 rejected with reasons in `mondo_mesh_rejects.tsv`,
  full table `mondo_mesh_check.tsv`, re-run with `check_mondo_mapping.py`).
- Validation: `validate_release.py` = KGX 2.6.0 (Biolink 4.4.4) + own checks for what KGX 2.6 does
  not flag (measured: dangling edges, missing primary source, bad knowledge_level/agent_type,
  publications format). Release: 0 problems; allowed exception = the TBIKG prefix (1 node, 74 edges).
  `--selftest` plants 7 errors and requires all to be caught. Run with `KGX_BIN=<venv>/bin/kgx`.
- Rat genes: 238 of 244 linked to human by RGD 1:1 orthologs, each confirmed by HGNC's own rgd_id
  record (release only, so the benchmarked working graph is unchanged). The 6 left: 3 LOC/pseudogenes,
  Cyp2d2, RT1-CE11, and Crnde (RGD's human ID is not an HGNC gene).
- Not yet:
  Zenodo release, licence audit.
