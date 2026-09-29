"""P3 — omics measurement layer (L2) from 05_analysis/panel.db.

One edge per (gene, predicate, condition); every contributing row of panel.db becomes one
evidence row. Predicates: biolink:positively_correlated_with (higher in condition) /
biolink:negatively_correlated_with (lower), knowledge_level = statistical_association.

PUBLIC (published data only)
  mantash_mouse_de        Mantash 2025 (PMID 40545497), mouse brain, rows already padj<0.05
  extC_* cohorts          dataset_evidence, human biofluids, stats as reported by the papers
PRIVATE (local only -> out/private/, never released)
  datasets, nodes and settings live in kg2/private_config.py, which is git-ignored; without that
  file the private layer is simply empty and the public build is unchanged.

Not converted: mantash_mouse_anova (no direction), gene lists, tissue expression
(-> node features in P5). Protein groups ("A;B") are dropped, not split.
"""
import re
from collections import defaultdict

from common import (INTERIM, MESH_CONCUSSION, MESH_TBI, PANEL_DB, UBERON, db, dumps,
                    read_tsv, write_tsv)

PMID_MANTASH = "40545497"
RECOVERY = "TBIKG:prolonged_recovery_after_concussion"
try:
    from private_config import PRIVATE_DATASETS, PRIVATE_NODES
except ImportError:
    PRIVATE_DATASETS, PRIVATE_NODES = {}, []

COHORT_OBJECT = {  # dataset -> (condition node, population note, exploratory?)
    "extC_BIOAXTBI": (MESH_TBI, "moderate-severe TBI vs controls", False),
    "extC_PXD035289": (MESH_TBI, "severe TBI vs controls; paper-named hits, no stats table", False),
    "extC_thelin_csf": (MESH_TBI, "severe TBI vs controls", False),
    "extC_thelin_serum": (MESH_TBI, "severe TBI vs controls", False),
    "extC_adolescent_olink": (MESH_CONCUSSION, "concussion vs controls; nominal p only", True),
    "extC_CARE_somascan": (RECOVERY, "recovery >=14 d vs <14 d after concussion (prognosis)", False),
}
EXTRA_NODES = [
    {"id": RECOVERY, "category": "biolink:PhenotypicFeature",
     "name": "prolonged recovery after concussion (return to sport >= 14 d)",
     "xrefs": "related:MESH:D038223", "provided_by": "infores:tbikg"},
]
EDGE_COLS = ["key", "subject", "predicate", "object", "direction", "layer", "knowledge_level",
             "agent_type", "primary_knowledge_source", "public"]
EVID_COLS = ["key", "source", "pmid", "dataset_id", "contrast", "species", "matrix",
             "log2fc", "effect", "pvalue", "padj", "n", "note"]


def maps():
    human = {r["gene"]: r["human_ncbigene"] for r in read_tsv(INTERIM / "symbol_map.tsv")}
    mouse = {r["symbol"].upper(): r["ncbigene"] for r in read_tsv(INTERIM / "genes_mouse.tsv")}
    return human, mouse


def pmid_of(con, ds):
    row = con.execute("SELECT citation, url, notes FROM datasets WHERE dataset_id=?", (ds,)).fetchone()
    m = re.search(r"PMID:?\s*(\d{6,9})", " ".join(x or "" for x in row)) if row else None
    return m.group(1) if m else ""


class Layer:
    def __init__(self):
        self.edges, self.evid = {}, []

    def add(self, subj, obj, up, public, source, ev, predicate=None):
        pred = predicate or ("biolink:positively_correlated_with" if up
                             else "biolink:negatively_correlated_with")
        direction = "increased" if up else "decreased"
        key = f"{subj}|{pred}|{obj}|{direction}"
        self.edges.setdefault(key, {
            "key": key, "subject": subj, "predicate": pred, "object": obj,
            "direction": direction, "layer": "L2", "knowledge_level": "statistical_association",
            "agent_type": "data_analysis_pipeline", "primary_knowledge_source": source,
            "public": int(public)})
        self.evid.append({"key": key, "source": source, **ev})


def mantash(con, L, mouse, stats):
    rx = re.compile(r"(Cortex|Hippo)-(ipsi|contra) (\d)hits? ?_(48h|1w) vs Sham")
    for r in con.execute("""SELECT raw_symbol, gene, contrast, direction, log2fc, pvalue, padj
                            FROM measurements WHERE dataset_id='mantash_mouse_de'"""):
        sym = (r["raw_symbol"] or r["gene"]).upper()
        if ";" in sym:
            stats["mantash_group_dropped"] += 1
            continue
        g = mouse.get(sym)
        if not g:
            stats["mantash_unmapped"] += 1
            continue
        m = rx.match(r["contrast"])
        region, side, hits, tp = m.groups() if m else ("", "", "", "")
        L.add(g, MESH_TBI, r["direction"] == "up", True, "infores:mantash2025", {
            "pmid": PMID_MANTASH, "dataset_id": "mantash_mouse_de", "contrast": r["contrast"],
            "species": "NCBITaxon:10090",
            "matrix": UBERON["cortex" if region == "Cortex" else "hippocampus"],
            "log2fc": r["log2fc"], "pvalue": r["pvalue"], "padj": r["padj"],
            "note": f"{hits} hit(s), {tp}, {side}lateral"})
        stats["mantash_rows"] += 1


def cohorts(con, L, human, stats):
    for r in con.execute("SELECT * FROM dataset_evidence"):
        ds = r["dataset_id"]
        if ds not in COHORT_OBJECT or r["direction"] not in ("up", "down"):
            stats[f"cohort_skipped_{ds}"] += 1
            continue
        g = human.get(r["gene"])
        if not g:
            stats["cohort_unmapped"] += 1
            continue
        obj, pop, exploratory = COHORT_OBJECT[ds]
        m = (r["matrix"] or "").lower()
        matrix = next((UBERON[k] for k in ("plasma", "serum", "csf") if k in m), "")
        L.add(g, obj, r["direction"] == "up", True, "infores:" + ds.lower(), {
            "pmid": pmid_of(con, ds), "dataset_id": ds, "contrast": pop,
            "species": "NCBITaxon:9606", "matrix": matrix, "log2fc": r["logfc"],
            "effect": r["effect_size"], "pvalue": r["pval"], "padj": r["padj"], "n": r["n"],
            "note": ("EXPLORATORY (nominal p). " if exploratory else "") + (r["note"] or "")[:300]})
        stats[f"cohort_rows_{ds}"] += 1


def private(con, L, human, mouse, stats):
    for ds, cfg in PRIVATE_DATASETS.items():
        q = f"SELECT * FROM measurements WHERE dataset_id=? AND {cfg['filter']}"
        args = [ds]
        if cfg["contrast"]:
            q += " AND contrast=?"
            args.append(cfg["contrast"])
        for r in con.execute(q, args):
            sym = (r["raw_symbol"] or r["gene"]).upper()
            g = human.get(r["gene"]) if cfg["species"] == "human" else mouse.get(sym)
            if ";" in sym or not g:
                stats[f"private_unmapped_{ds}"] += 1
                continue
            up = (r["direction"] == "up") if r["direction"] in ("up", "down") else (r["log2fc"] or 0) > 0
            ev = {"dataset_id": ds, "contrast": r["contrast"],
                  "species": "NCBITaxon:9606" if cfg["species"] == "human" else "NCBITaxon:10090",
                  "matrix": UBERON.get(cfg["matrix"], ""), "log2fc": r["log2fc"], "pvalue": r["pvalue"],
                  "padj": r["padj"], "note": "unpublished lab data"}
            if cfg["role"] == "condition":
                L.add(g, cfg["node"], up, False, "infores:tbikg-lab", ev)
            else:
                L.add(cfg["node"], g, up, False, "infores:tbikg-lab", ev, predicate="biolink:affects")
            stats[f"private_rows_{ds}"] += 1


def main():
    human, mouse = maps()
    con = db(PANEL_DB)
    L, stats = Layer(), defaultdict(int)
    mantash(con, L, mouse, stats)
    cohorts(con, L, human, stats)
    private(con, L, human, mouse, stats)
    write_tsv(INTERIM / "l2_edges.tsv", EDGE_COLS, L.edges.values())
    write_tsv(INTERIM / "l2_evidence.tsv", EVID_COLS, L.evid)
    write_tsv(INTERIM / "l2_nodes.tsv", ["id", "category", "name", "xrefs", "provided_by"],
              EXTRA_NODES + PRIVATE_NODES)
    pub = sum(e["public"] for e in L.edges.values())
    print(f"P3: L2 edges {len(L.edges)} (public {pub}, private {len(L.edges) - pub}); "
          f"evidence rows {len(L.evid)}")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
