"""Build the ablation arms for the GNN / KGE benchmark (runs locally, stdlib only).

Task (same as p6_timesplit V6): rank human genes by their chance of a FIRST link to TBI
after CUTOFF, using only evidence dated <= CUTOFF.

All TBI-family disease nodes are merged into one target node `TBI*`; every gene<->TBI-family
edge dated <= CUTOFF becomes relation `tbi_link` (the supervision). Supervision, validation
and test labels are IDENTICAL across arms; arms differ only in the context graph:

  cooc       PubTator3 entities joined by abstract co-occurrence (<= CUTOFF): the v1 method
  lit        typed L3 relations (<= CUTOFF)
  ref_lit    L1 curated reference + L3 (<= CUTOFF)
  ref_lit_feat  ref_lit + node features (GO terms with >= 20 genes, panel.db annotations)

L2 omics edges are all dated > CUTOFF (Mantash 2025, cohorts 2021-24), so under this split they
are TEST LABELS, never context; a separate `full` arm would be identical to ref_lit.
No validation set: only ~150 human supervision genes exist, so hyperparameters are fixed a
priori (see train.py) and all tbi_link genes train. Output: kg2/bench/data/<arm>/.
"""
import random
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import INTERIM, OUT, VERSION, read_tsv, write_tsv  # noqa: E402

CUTOFF = 2020
SEED = 20260929
REL = OUT / VERSION
DATA = Path(__file__).resolve().parent / "data"
TBI_RX = re.compile(r"brain injur|concussion|head injur|traumatic encephalopath|diffuse axonal|"
                    r"craniocerebral trauma", re.I)
TARGET = "TBI*"
GO_MIN_GENES = 20


def rel_name(e):
    p = e["predicate"].split(":")[-1]
    return f"{e['layer']}:{p}" + (f":{e['direction']}" if e.get("direction") else "")


def main():
    rng = random.Random(SEED)
    nodes = {n["id"]: n for n in read_tsv(REL / "nodes.tsv")}
    edges = read_tsv(REL / "edges.tsv")
    tbi = {k for k, n in nodes.items() if n["category"] == "biolink:Disease" and TBI_RX.search(n["name"])}
    human = {k for k, n in nodes.items() if n.get("taxon") == "NCBITaxon:9606"}
    tmap = lambda x: TARGET if x in tbi else x  # noqa: E731
    genes = {k for k, n in nodes.items() if n["category"] == "biolink:Gene"}

    def dated_ok(e):
        return e["layer"] == "L1" or (e["first_year"].isdigit() and int(e["first_year"]) <= CUTOFF)

    # supervision / labels (identical across arms)
    early, late = set(), set()
    context = defaultdict(list)  # layer -> triples
    for e in edges:
        s, o = tmap(e["subject"]), tmap(e["object"])
        if s == o:
            continue
        is_link = TARGET in (s, o) and ({s, o} - {TARGET}) <= genes
        g = next(iter({s, o} - {TARGET})) if is_link else None
        if dated_ok(e):
            if is_link:
                early.add(g)
            else:
                context[e["layer"]].append((s, rel_name(e), o))
        elif is_link and e["first_year"].isdigit():
            late.add(g)
    early_h = sorted(early & human)
    val = set()  # no validation split (see docstring)
    sup = [(g, "tbi_link", TARGET) for g in sorted(early - val)]
    positives = (late & human) - early

    # co-occurrence context from PubTator3 mentions (<= CUTOFF)
    years = {r["pmid"]: r["year"] for r in read_tsv(INTERIM / "scope_pmids.tsv")}
    by_pmid = defaultdict(set)
    for r in read_tsv(INTERIM / "l3_mentions.tsv"):
        y = years.get(r["pmid"], "")
        if y.isdigit() and int(y) <= CUTOFF:
            by_pmid[r["pmid"]].add(tmap(r["id"]))
    cooc = set()
    for ids in by_pmid.values():
        for a, b in combinations(sorted(ids), 2):
            if TARGET not in (a, b):  # target links come only from supervision
                cooc.add((a, "cooc:co_occurs", b))

    arms = {
        "cooc": sorted(cooc),
        "lit": context["L3"],
        "ref_lit": context["L1"] + context["L3"],
    }
    assert not [t for t in context["L2"]], "an L2 edge is dated <= CUTOFF: revisit arm design"
    arms["ref_lit_feat"] = arms["ref_lit"]
    # L1 as of 2020 (p2b_reference_2020.py): STRING v11.0 exp+db, Reactome pathways released
    # <= 2020, OmniPath/ChEMBL with a PMID <= 2020; MGI orthologs kept (not TBI knowledge).
    l1_2020 = INTERIM / "l1_edges_2020.tsv"
    if l1_2020.exists():
        orth = [t for t in context["L1"] if t[1] == "L1:orthologous_to"]
        old = [(tmap(e["subject"]), rel_name(e), tmap(e["object"])) for e in read_tsv(l1_2020)]
        arms["ref_lit_2020"] = old + orth + context["L3"]

    # features (only written for full_feat)
    go = defaultdict(set)
    for r in read_tsv(INTERIM / "features_go.tsv"):
        go[r["go_id"]].add(r["ncbigene"])
    go_terms = sorted(t for t, gs in go.items() if len(gs) >= GO_MIN_GENES)
    ann_keys = Counter()
    ann = []
    for r in read_tsv(REL / "features" / "protein_annotations.tsv"):
        if r["value_num"] not in ("", None):
            k = f"{r['category']}:{r['metric_key']}"
            ann_keys[k] += 1
            ann.append((r["ncbigene"], k, float(r["value_num"])))

    # ONE candidate set and ONE validation sample for every arm (= p6_timesplit candidates:
    # human genes present in the full context graph with no tbi_link <= CUTOFF)
    full_nodes = {x for h, _, t in arms["ref_lit"] + sup for x in (h, t)}
    cands = sorted(g for g in human if g in full_nodes and g not in early)

    summary = []
    for arm, ctx in arms.items():
        d = DATA / arm
        d.mkdir(parents=True, exist_ok=True)
        triples = sorted(set(ctx)) + sup
        ents = sorted({x for h, _, t in triples for x in (h, t)} | {TARGET} | val | set(cands))
        eid = {x: i for i, x in enumerate(ents)}
        rels = sorted({r for _, r, _ in triples})
        rid = {r: i for i, r in enumerate(rels)}
        write_tsv(d / "entities.tsv", ["idx", "id", "name"],
                  ({"idx": i, "id": x, "name": nodes.get(x, {}).get("name", x)} for i, x in enumerate(ents)))
        write_tsv(d / "relations.tsv", ["idx", "relation"], ({"idx": i, "relation": r} for i, r in enumerate(rels)))
        write_tsv(d / "train.tsv", ["h", "r", "t"],
                  ({"h": eid[h], "r": rid[r], "t": eid[t]} for h, r, t in triples))
        write_tsv(d / "test_candidates.tsv", ["idx", "label"],
                  ({"idx": eid[g], "label": int(g in positives)} for g in cands))
        (d / "meta.tsv").write_text(f"key\tvalue\ntarget_idx\t{eid[TARGET]}\ntbi_link_rel\t{rid['tbi_link']}\n"
                                    f"cutoff\t{CUTOFF}\n")
        if arm == "ref_lit_feat":
            fid = {t: i for i, t in enumerate(go_terms)}
            kid = {k: len(go_terms) + i for i, k in enumerate(sorted(ann_keys))}
            rows = [{"node": eid[g], "feat": fid[t], "value": 1}
                    for t in go_terms for g in go[t] if g in eid]
            # annotations: min-max scaled per key
            lo, hi = defaultdict(lambda: float("inf")), defaultdict(lambda: float("-inf"))
            for _, k, v in ann:
                lo[k], hi[k] = min(lo[k], v), max(hi[k], v)
            rows += [{"node": eid[g], "feat": kid[k],
                      "value": round((v - lo[k]) / (hi[k] - lo[k]), 6) if hi[k] > lo[k] else 0}
                     for g, k, v in ann if g in eid]
            rows.sort(key=lambda r: (r["node"], r["feat"]))  # deterministic order (set iteration)
            write_tsv(d / "features.tsv", ["node", "feat", "value"], rows)
            (d / "meta.tsv").write_text((d / "meta.tsv").read_text() + f"n_features\t{len(go_terms) + len(kid)}\n")
        summary.append((arm, len(ents), len(rels), len(triples), sum(r == 1 for r in
                        [int(g in positives) for g in cands]), len(cands)))
    print("arm        entities relations triples  test_pos/candidates")
    for a, ne, nr, nt, npos, nc in summary:
        print(f"{a:10s} {ne:8d} {nr:9d} {nt:8d}  {npos}/{nc}")
    print(f"supervision tbi_link {len(sup)} ({len(early_h)} human); GO terms {len(go_terms)}; "
          f"annotation keys {len(ann_keys)}")


if __name__ == "__main__":
    main()
