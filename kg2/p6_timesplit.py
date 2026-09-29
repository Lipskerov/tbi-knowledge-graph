"""P6b — V6 time-sliced benchmark (baselines; GNNs plug into the same split later).

Question: using only evidence dated <= CUTOFF, how well do simple graph scores rank the human
genes whose FIRST link to a TBI-family disease appears after CUTOFF?

  train graph  = L1 (undated reference DBs; caveat: current releases may encode post-cutoff
                 knowledge) + L2/L3 edges with first_year <= CUTOFF + orthologs
  positives    = human genes with a TBI-family edge first_year > CUTOFF and none <= CUTOFF
  candidates   = every human gene in the train graph with no TBI-family edge <= CUTOFF
Scores: random, literature count (papers <= CUTOFF), degree, common neighbours with the TBI
node set, Adamic-Adar, personalised PageRank from the TBI node set.
Split files are written to out/<VERSION>/benchmarks/ so others can reproduce them.
"""
import json
import math
import random
import re
from collections import Counter

import networkx as nx

from common import OUT, VERSION, read_tsv, write_tsv

CUTOFF = 2020
REL = OUT / VERSION
TBI_RX = re.compile(r"brain injur|concussion|head injur|traumatic encephalopath|diffuse axonal|"
                    r"craniocerebral trauma", re.I)


def auroc(scores, labels):
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    order = sorted(set(scores))
    rank = {}
    ranked = sorted(scores)
    i = 0
    for v in order:  # average ranks for ties
        j = i
        while j < len(ranked) and ranked[j] == v:
            j += 1
        rank[v] = (i + j + 1) / 2
        i = j
    r_pos = sum(rank[s] for s in pos)
    return (r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def auprc(scores, labels):
    pairs = sorted(zip(scores, labels), key=lambda x: -x[0])
    tp = 0
    ap = 0.0
    n_pos = sum(labels)
    for k, (_, l) in enumerate(pairs, 1):
        if l:
            tp += 1
            ap += tp / k
    return ap / n_pos


def prec_at(scores, labels, k):
    return sum(l for _, l in sorted(zip(scores, labels), key=lambda x: -x[0])[:k]) / k


def main():
    nodes = {n["id"]: n for n in read_tsv(REL / "nodes.tsv")}
    edges = read_tsv(REL / "edges.tsv")
    tbi = {k for k, n in nodes.items() if n["category"] == "biolink:Disease" and TBI_RX.search(n["name"])}
    human = {k for k, n in nodes.items() if n.get("taxon") == "NCBITaxon:9606"}

    def year(e):
        return int(e["first_year"]) if e["first_year"].isdigit() else None

    train, early_tbi, late_tbi = [], set(), set()
    for e in edges:
        y = year(e)
        pair = {e["subject"], e["object"]}
        is_tbi = bool(pair & tbi)
        gene = next(iter(pair - tbi), None) if is_tbi else None
        if e["layer"] == "L1" or (y is not None and y <= CUTOFF):
            train.append(e)
            if is_tbi and gene in human:
                early_tbi.add(gene)
        elif is_tbi and gene in human and y is not None:
            late_tbi.add(gene)
    positives = late_tbi - early_tbi

    G = nx.Graph()
    G.add_edges_from((e["subject"], e["object"]) for e in train)
    tbi_in = [t for t in tbi if t in G]
    cands = sorted(g for g in human if g in G and g not in early_tbi)
    labels = [int(g in positives) for g in cands]

    lit = Counter()
    for e in train:
        if e["layer"] == "L3":
            for x in (e["subject"], e["object"]):
                lit[x] += int(e["n_evidence"])
    tbi_nb = set().union(*(set(G[t]) for t in tbi_in))
    ppr = nx.pagerank(G, personalization={t: 1 for t in tbi_in}, alpha=0.85)
    rng = random.Random(0)
    scorers = {
        "random": lambda g: rng.random(),
        "literature_count": lambda g: lit[g],
        "degree": lambda g: G.degree(g),
        "common_neighbours_TBI": lambda g: len(set(G[g]) & tbi_nb),
        "adamic_adar_TBI": lambda g: sum(1 / math.log(G.degree(z)) for z in set(G[g]) & tbi_nb
                                         if G.degree(z) > 1),
        "personalised_pagerank_TBI": lambda g: ppr.get(g, 0.0),
    }
    res = {"cutoff": CUTOFF, "tbi_nodes": sorted(tbi_in), "train_edges": len(train),
           "candidates": len(cands), "positives": sum(labels),
           "prevalence": round(sum(labels) / len(cands), 5), "models": {}}
    for name, f in scorers.items():
        s = [f(g) for g in cands]
        res["models"][name] = {"AUROC": round(auroc(s, labels), 4), "AUPRC": round(auprc(s, labels), 4),
                               "P@50": prec_at(s, labels, 50), "P@100": prec_at(s, labels, 100)}
    bdir = REL / "benchmarks"
    bdir.mkdir(exist_ok=True)
    write_tsv(bdir / f"timesplit_{CUTOFF}_candidates.tsv", ["id", "name", "label"],
              ({"id": g, "name": nodes[g]["name"], "label": l} for g, l in zip(cands, labels)))
    (bdir / f"timesplit_{CUTOFF}_results.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "tbi_nodes"}, indent=1))


if __name__ == "__main__":
    main()
