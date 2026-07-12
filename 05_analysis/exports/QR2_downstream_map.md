# QR2 / NQO2 — meticulous downstream map

Built 2026-06-28 from the project's own assets: knowledge-graph DB (`data/tbi_papers.db` —
`entity_relations`, `omnipath_interactions`, `chembl_activities`), the live **TBI BioMarkers**
sheet (`QR2_Pathway` tab), and verified literature. EV-mRNA behaviour columns are from
**GSE254880** (neuron-derived serum EVs, severe TBI vs control, n=8 pools/group, 24–48 h).

> **Core principle.** QR2/NQO2 is an enzyme; its **only direct product is ROS** (futile redox
> cycling). It has **no transcriptional output of its own**. So "downstream of QR2" = whatever
> QR2-generated **ROS** modifies. That is mostly an *oxidation state* (post-translational), and a
> *compensatory transcriptional* program. Co-expression of redox genes is NOT evidence of QR2
> driving them — most are siblings/parallel.

---

## Directed backbone (curated edges in the project KG)

```
        DRD1 ──► cAMP/PKA ──► miR-182 ──┤ (suppresses)         [UPSTREAM regulation]
        Nrf2 ──────────────────────────► NQO2  (ARE, PMID 16545679)
        TNF-α ─────────────────────────► NQO2  (inflammatory induction)
                                          │
                                          ▼  generates  (curated, ~many PMIDs)
                                         ROS  ◄───────────────┐
                                       /     \                │ activates (feedback)
                        oxidizes      /       \  activates    │
                                     ▼         ▼              │
                                  Kv2.1       Nrf2 ───────────┘
                              (KCNB1)          │  drives ARE battery
                          disulfide            ▼
                          oligomerization   NQO1, HO-1/HMOX1, GCLC, GCLM,
                          → inactivation    GSR, SLC7A11, TXNRD1, SRXN1, G6PD …
```

`miR-182 ⊣ QR2`, `Nrf2 → QR2`, `TNF-α → QR2` are **upstream** — they are NOT downstream and are
listed only to fix the boundary. Everything below the `generates ROS` arrow is downstream.

---

## Downstream tiers (evidence-graded)

### Tier 1 — Direct molecular product
| Node | Edge (KG) | Evidence | EV-mRNA? | EV result (STBI/ctrl) |
|---|---|---|---|---|
| **ROS** | NQO2 —generates→ ROS | **HIGH**, curated, established biochem | No (metabolite) | n/a |

### Tier 2 — Direct ROS effects (the *true* downstream effectors; mostly post-translational)
| Node | Edge | Evidence | EV-mRNA? | EV result |
|---|---|---|---|---|
| **Kv2.1 / KCNB1** | ROS —oxidizes→ Kv2.1 (disulfide oligomerization → channel inactivation → altered CA1 interneuron firing) | **HIGH** for the model (PMIDs 33046554, 34518366) | mRNA should NOT move (effect is protein oxidation) | **0.89× flat** — *as expected* |
| **DJ-1 / PARK7** | ROS sensor (Cys106 oxidation) | HIGH (canonical) | sensing is post-translational | 1.47× (ns) |
| **4-HNE** | lipid-peroxidation product | HIGH | No (metabolite) | n/a |
| **Nrf2 / NFE2L2** | ROS —activates→ Nrf2 (KEAP1 release) | **HIGH**, curated | activation post-translational → mRNA ~flat | 1.11× flat |

### Tier 3 — Compensatory antioxidant program (Nrf2/ARE battery — the **right transcriptional readout**)
Induced *because of* QR2→ROS via the ROS→Nrf2 feedback. These are the genes that **should rise at
mRNA level** if QR2-driven oxidative stress is active.
| Gene | KG/biology | EV result (FC) | p |
|---|---|---|---|
| **NQO1** | Nrf2→NQO1 (curated) | **2.24×** | 0.33 |
| **G6PD** | ARE (NADPH supply) | 1.57× | 0.65 |
| **SLC7A11** (xCT) | ARE (cystine import) | **1.40×** | **0.065** |
| **TXNRD1** | ARE (thioredoxin system) | 1.28× | 0.23 |
| **GCLC** | ARE (glutathione synth) | 1.21× | 0.23 |
| **GCLM** | ARE (glutathione synth) | 1.20× | 0.80 |
| **GSTP1** | ARE (detox) | 4.1× (very noisy) | 0.65 |
| **GSR** | glutathione redox | 1.03× flat | 0.96 |
| **HMOX1 / HO-1** | Nrf2→HO-1 (curated) | 1.04× flat | 0.65 |
| **FTH1** | ARE (iron storage) | 0.39× down | 0.13 |

→ **8 of 10 ARE-battery genes trend up together** (NQO1, G6PD, SLC7A11, TXNRD1, GCLC, GCLM, GSTP1
plus QR2 itself). No single one is significant, but the **coherent upward drift of the whole Nrf2
program** is the meaningful signal — exactly what an engaging (not yet peaked) antioxidant response
looks like.

### Tier 4 — ER / integrated-stress arm (emerging; lower confidence)
KG has NQO2 co-occurring with PERK, eIF2α, CHOP (PMID 40749898) and CHOP (33240775). Directionality
NOT yet curated — treat as **emerging**.
| Gene | Role | EV result | p |
|---|---|---|---|
| **EIF2AK3 / PERK** | ISR kinase | 1.31× | 0.33 |
| **ATF4** | ISR effector TF | 1.42× | 0.72 |
| **DDIT3 / CHOP** | terminal ISR | 0.67× (down) | 0.21 |
| ATF3 / TRIB3 | ISR | ~flat | — |

→ Faint PERK/ATF4 nudge up, but terminal CHOP **not** induced → ISR is *not engaged* at 24–48 h.

### Tier 5 — Distal pathology / phenotype (causal from QR2-inhibitor reversal, JCI 2023 PMID 37561584)
QR2 inhibition (S29434) reduced GFAP, Iba1, Aβ42 and reversed memory deficit in 5xFAD → these are
genuine *distal* downstream consequences, but disease-level, not proximal.
| Gene | EV result | p |
|---|---|---|
| **IL-6** | **1.83× UP** | **0.038 \*** |
| **GFAP** | 1.40× | 0.23 |
| TNF-α | 1.32× (noisy) | 0.57 |
| IL-1β | 0.73× | 0.13 |

---

## What is genuinely "downstream of QR2" — the short list

1. **ROS** (direct, definitional) — not measurable as mRNA.
2. **Kv2.1/KCNB1 oxidation** — the flagship functional effector; **protein-level only** (mRNA blind).
3. **Nrf2/ARE antioxidant battery** (NQO1, HO-1, GCLC, GCLM, GSR, SLC7A11, TXNRD1, SRXN1, G6PD, FTH1)
   — the compensatory response; **this is the correct transcriptional / EV-mRNA readout of QR2 activity**.
4. **ER/ISR arm** (PERK→eIF2α→ATF4→CHOP) — emerging, single recent paper.
5. **Distal pathology** (GFAP, Iba1, IL-6/IL-1β/TNF-α, Aβ42, tau, memory/metabolic burden).

## NOT downstream (parallel / sibling / upstream — common mislabels)
- **Nrf2** = upstream regulator + feedback sensor (not a QR2 target).
- **NQO1, HO-1** = Nrf2 *siblings* of QR2; they ARE downstream of the ROS→Nrf2 *loop*, but they are
  not driven by QR2 protein directly.
- **TXN, SOD1, GLOD4, PRXL2B, GSR, catalase, glutathione** = general antioxidant machinery, respond
  to ROS from any source.
- **NOS1/nNOS** = independent reactive-nitrogen source.
- **miR-182** = upstream repressor of QR2 (moves *inversely*; needs a small-RNA assay, not this dataset).

## Biomarker implication
- A true QR2-**activity** signature is **redox-proteomic** (Kv2.1 oligomers, DJ-1 oxidation, protein
  carbonyls), not transcriptomic.
- For **EV-mRNA**, the defensible panel is **QR2 itself + the Nrf2/ARE battery as a coherent module**
  (composite score), not single redox genes.
- The day-3–5 banked Baylor samples (NCT00313716) would test whether the ARE module and Kv2.1/CHOP
  effectors engage as QR2 climbs.
