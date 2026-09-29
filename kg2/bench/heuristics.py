"""Heuristic baselines computed on EACH arm's own training graph (same edges the models see).

Scores for every test candidate: personalised PageRank from TBI*, Adamic-Adar to TBI*
neighbours, degree, random. Writes results/<arm>__heur_<name>__s0.json (same schema as
train.py), so aggregate.py tabulates them next to the learned models.
"""
import csv
import json
import math
import random
from pathlib import Path

import networkx as nx

HERE = Path(__file__).resolve().parent


def auroc(scores, labels):
    pairs = sorted(zip(scores, labels))
    ranks, i = [0.0] * len(pairs), 0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        for k in range(i, j):
            ranks[k] = (i + j + 1) / 2
        i = j
    npos = sum(labels)
    rpos = sum(r for r, (_, l) in zip(ranks, pairs) if l)
    return (rpos - npos * (npos + 1) / 2) / (npos * (len(labels) - npos))


def auprc(scores, labels):
    tp, ap = 0, 0.0
    for k, (_, l) in enumerate(sorted(zip(scores, labels), key=lambda x: -x[0]), 1):
        if l:
            tp += 1
            ap += tp / k
    return ap / sum(labels)


def p_at(scores, labels, k):
    return sum(l for _, l in sorted(zip(scores, labels), key=lambda x: -x[0])[:k]) / k


def main():
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    for d in sorted(p for p in (HERE / "data").iterdir() if p.is_dir()):
        rd = lambda f: list(csv.DictReader(open(d / f), delimiter="\t"))  # noqa: E731
        meta = {r["key"]: r["value"] for r in rd("meta.tsv")}
        tgt = int(meta["target_idx"])
        G = nx.Graph()
        G.add_edges_from((int(r["h"]), int(r["t"])) for r in rd("train.tsv"))
        cand = rd("test_candidates.tsv")
        idx = [int(c["idx"]) for c in cand]
        labels = [int(c["label"]) for c in cand]
        ppr = nx.pagerank(G, personalization={tgt: 1}, alpha=0.85)
        nb = set(G[tgt])
        rng = random.Random(0)
        scorers = {
            "ppr": lambda g: ppr.get(g, 0.0),
            "adamic_adar": lambda g: sum(1 / math.log(G.degree(z)) for z in set(G[g]) & nb
                                         if G.degree(z) > 1) if g in G else 0.0,
            "degree": lambda g: G.degree(g) if g in G else 0,
            "random": lambda g: rng.random(),
        }
        for name, f in scorers.items():
            s = [f(g) for g in idx]
            res = {"arm": d.name, "model": f"heur_{name}", "seed": 0, "seconds": 0,
                   "AUROC": auroc(s, labels), "AUPRC": auprc(s, labels),
                   "P@50": p_at(s, labels, 50), "P@100": p_at(s, labels, 100), "P@500": p_at(s, labels, 500)}
            (out / f"{d.name}__heur_{name}__s0.json").write_text(json.dumps(res, indent=1))
        print(d.name, "PPR AUROC %.3f AUPRC %.3f" % (auroc([ppr.get(g, 0) for g in idx], labels),
                                                      auprc([ppr.get(g, 0) for g in idx], labels)))


if __name__ == "__main__":
    main()
