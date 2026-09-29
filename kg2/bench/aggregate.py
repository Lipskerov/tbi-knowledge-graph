"""Aggregate benchmark results (mean ± SD over seeds) + V5 leakage audit on the arm files.

    python3 aggregate.py            # reads bench/results/*.json (pulled from HIVE)
Writes bench/results_summary.tsv and bench/leakage_audit.tsv; prints both.
Heuristic baselines come from out/<v>/benchmarks/timesplit_2020_results.json (p6_timesplit).
"""
import csv
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import OUT, VERSION, write_tsv  # noqa: E402

METRICS = ["AUROC", "AUPRC", "P@50", "P@100"]


def leakage(arm_dir):
    """Test positives must never appear as training triples, forward or reversed."""
    ents = {r["idx"]: r["id"] for r in csv.DictReader(open(arm_dir / "entities.tsv"), delimiter="\t")}
    meta = {r["key"]: r["value"] for r in csv.DictReader(open(arm_dir / "meta.tsv"), delimiter="\t")}
    tgt = meta["target_idx"]
    pos = {r["idx"] for r in csv.DictReader(open(arm_dir / "test_candidates.tsv"), delimiter="\t")
           if r["label"] == "1"}
    fwd = rev = 0
    direct = 0
    for r in csv.DictReader(open(arm_dir / "train.tsv"), delimiter="\t"):
        if r["h"] in pos and r["t"] == tgt:
            fwd += 1
        if r["t"] in pos and r["h"] == tgt:
            rev += 1
        if (r["h"] in pos or r["t"] in pos) and tgt in (r["h"], r["t"]):
            direct += 1
    return {"arm": arm_dir.name, "test_positives": len(pos), "train_triples_gene_to_TBI*": fwd,
            "reversed": rev, "any_relation_gene_TBI*": direct,
            "target_node": ents[tgt]}


def main():
    runs = defaultdict(list)
    for p in sorted((HERE / "results").glob("*.json")):
        r = json.loads(p.read_text())
        runs[(r["arm"], r["model"])].append(r)
    rows = []
    for (arm, model), rs in sorted(runs.items()):
        row = {"arm": arm, "model": model, "n_seeds": len(rs),
               "mean_seconds": round(st.mean(r["seconds"] for r in rs), 1)}
        for m in METRICS:
            v = [r[m] for r in rs]
            row[m] = f"{st.mean(v):.3f} ± {st.stdev(v):.3f}" if len(v) > 1 else f"{v[0]:.3f}"
        rows.append(row)
    base = json.loads((OUT / VERSION / "benchmarks" / "timesplit_2020_results.json").read_text())
    for name, m in base["models"].items():
        rows.append({"arm": "ref_lit+L2 (full graph)", "model": f"heuristic:{name}", "n_seeds": 1,
                     **{k: f"{m[k]:.3f}" for k in METRICS}})
    write_tsv(HERE / "results_summary.tsv", ["arm", "model", "n_seeds"] + METRICS + ["mean_seconds"], rows)
    leaks = [leakage(d) for d in sorted((HERE / "data").iterdir()) if d.is_dir()]
    write_tsv(HERE / "leakage_audit.tsv", list(leaks[0]), leaks)
    print(f"{'arm':24s} {'model':34s} n  " + "  ".join(f"{m:>15s}" for m in METRICS))
    for r in rows:
        print(f"{r['arm']:24s} {r['model']:34s} {r['n_seeds']:<2} " + "  ".join(f"{r[m]:>15s}" for m in METRICS))
    print(f"\nprevalence {base['prevalence']}")
    for l in leaks:
        print("leakage", l)


if __name__ == "__main__":
    main()
