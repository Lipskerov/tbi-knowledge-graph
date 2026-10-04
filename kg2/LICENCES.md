# TBI-BiomarkerKG v2 — licence audit (04.10.2026)

Every source in release `2.0.0-dev`, its licence as stated on the source's own page today, and
whether it can be redistributed in a CC BY 4.0 release. Edge counts are from `out/2.0.0-dev/edges.tsv`.

| Source | Licence (verified) | Edges / use in release | CC BY 4.0 release? |
|---|---|---|---|
| STRING v12 (+ v11.0 for the 2020 arm) | CC BY 4.0 — [string-db.org/cgi/access](https://string-db.org/cgi/access) | 83,810 | Yes, with attribution |
| Reactome | **CC0** — [reactome.org/license](https://reactome.org/license) (registry said CC BY 4.0; corrected) | 48,809 | Yes |
| OmniPath, academic subset | Per resource — [omnipathdb.org/resources](https://omnipathdb.org/resources) | 32,281, of which **1,652 rest only on non-commercial resources** | 30,629 yes; **1,652 no** |
| PubTator3 relations | NCBI data, no restrictions — [NCBI policies](https://www.ncbi.nlm.nih.gov/home/about/policies/) | 7,520 | Yes |
| PubTator3 evidence sentences | Abstract text: "NLM does not claim the copyright on the abstracts … publishers or authors may" | **8,757 evidence rows carry a sentence** | **No (publisher copyright)** |
| MGI homology | CC BY 4.0 — [MGI copyright](https://www.informatics.jax.org/mgihome/other/copyright.shtml) | 1,525 | Yes |
| Mantash 2025 (PMID 40545497) | Article CC BY (Europe PMC) | 1,370 | Yes |
| Thelin 2021 CSF + serum (PMID 33712077) | CC BY | 82 + 31 | Yes |
| Adolescent Olink (PMID 34987469) | CC BY | 81 | Yes |
| CARE SomaScan (PMID 35928129) | CC BY | 74 | Yes |
| PXD035289 (PMID 36482407) | CC BY | 27 | Yes |
| BIO-AX-TBI (PMID 39323289) | **CC BY-NC** | **60** | **No as CC BY**: facts with citation, or a separate NC file |
| ChEMBL | **CC BY-SA 3.0** — [ChEMBL about](https://chembl.gitbook.io/chembl-interface-documentation/about) | **40** | **Share-alike**: only in a separate CC BY-SA file |
| MONDO (MeSH→MONDO SSSOM) | CC BY 4.0 (MONDO ontology licence; the SSSOM file header says "unspecified") | 328 disease-node xrefs | Yes, with attribution |
| RGD rat–human orthologs | CC BY 4.0 (RGD) | 238 ortholog edges (release only) | Yes, with attribution |
| HGNC | CC0 — [genenames.org licence](https://www.genenames.org/about/license/) | IDs, names | Yes |
| GO annotations | CC BY 4.0 — [GO citation policy](https://geneontology.org/docs/go-citation-policy/) | Node features | Yes, with attribution |
| MeSH | NLM terms — [MeSH terms](https://www.nlm.nih.gov/databases/download/terms_and_conditions_mesh.html) | Disease node IDs, names | Yes: credit NLM, state the MeSH version, no implied endorsement |
| Lab omics (private layer) | Unpublished | 7,457 in `out/*/private/` | Never released |

## Non-commercial OmniPath resources that support at least one edge (21)

Baccin2019, Cellinker, DEPOD, HPMR (CC BY-NC 4.0) · Li2012, Wang (CC BY-NC 3.0) · LMPID (CC BY-NC 2.0) ·
PhosphoSite, TRIP, iTALK (CC BY-NC-SA 3.0) · iPTMnet (CC BY-NC-SA 4.0) · Kirouac2010 (CC BY-NC-ND 3.0) ·
DLRP, HINT, KEA, PDZBase (unspecified NC-SA) · ELM, phosphoELM, HPRD, HPRD-phos, PhosphoNetworks (own
academic / non-profit terms). An edge is kept as CC BY when at least one of its supporting resources is
licensed for commercial reuse (OmniPath's own `purpose: commercial` flag).

## Resolution (04.10.2026): `p7_release.py` writes `out/<v>/release/`

| File | Licence | Edges |
|---|---|---|
| `edges.tsv`, `edge_evidence.tsv`, `nodes.tsv`, `graph.nt` | CC BY 4.0 | 173,966 |
| `noncommercial/` | Non-commercial use only; original licence per edge | 1,704 (1,652 OmniPath + 52 BIO-AX-TBI) |
| `chembl_cc-by-sa-3.0/` | CC BY-SA 3.0 | 40 |

- No edge is lost: 175,710 edges in, 175,710 out, each in exactly one file.
- 8 BIO-AX-TBI edges are also reported by Thelin 2021 (CC BY); they are released in the main file under
  Thelin, and their 8 BIO-AX-TBI evidence rows stay in `noncommercial/`.
- Abstract sentences are removed from every release file (8,757 rows); each literature edge keeps its PMID.
- Main-file OmniPath edges carry only PMIDs and resource names from commercially reusable resources.
  4,955 of them are left with no PMID: their papers came only from non-commercial resources.
- Scientific Data accepts this split: CC BY for the dataset, original licences retained for re-used
  third-party data.
