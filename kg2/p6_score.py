"""P6c — score the human validation sheets made by p6_validation_sheets.py. Read-only on curation/.

    python3 p6_score.py                     # scores whatever is annotated so far
    python3 p6_score.py --curation DIR --out DIR --preds 'bench/llm_preds/*.jsonl'

V1 entity normalisation  a_correct / b_correct in the V2 sheets: share of IDs judged correct.
V2 relation extraction   two blind annotators -> consensus truth (an optional
                         curation/V2_gold_set_adjudication.xlsx, columns item + relation, settles
                         disagreements). Scored: inter-annotator Cohen's kappa; PubTator3 (the key)
                         and every LLM prediction file: binary relation-vs-none P/R/F1, type accuracy.
                         PubTator3 precision per predicate stratum and weighted by stratum size in
                         the release (the 300 extractor items were sampled with fixed quotas, not
                         in proportion). The 100 'none' items give the share of unrelated co-mention
                         pairs that in fact state a relation (misses).
V3 edge audit            supported share per layer and source: strict = yes / (yes+no+partly),
                         lenient = (yes+partly) / same; cannot_check is excluded and counted.

Items are scored only where every needed label is filled, so partial annotation gives partial
scores with their n. Proportions carry Wilson 95% CIs; kappa and F1 a seeded bootstrap 95% CI.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import load_workbook

from common import CURATION, KG2, OUT, VERSION, read_tsv, write_tsv

RELATED = ("positive_correlation", "negative_correlation", "association", "binding")
LABELS = RELATED + ("no_relation", "cannot_tell")
PREDICATE_LABEL = {"biolink:associated_with": "association",
                   "biolink:related_to": "association",
                   "biolink:positively_correlated_with": "positive_correlation",
                   "biolink:negatively_correlated_with": "negative_correlation",
                   "biolink:physically_interacts_with": "binding",
                   "none": "no_relation"}
KEY_FILE = "V2_gold_set_KEY_do_not_open_before_annotation.xlsx"
BOOT, SEED, Z = 2000, 20260929, 1.959963984540054


# ---------- statistics ----------
def wilson(k: int, n: int) -> tuple[float, float, float]:
    """Proportion with Wilson score 95% interval; (nan, nan, nan) when n == 0."""
    if n == 0:
        return (math.nan,) * 3
    p = k / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def kappa(a: list, b: list) -> float:
    """Cohen's kappa for two raters over the same items."""
    n = len(a)
    if n == 0:
        return math.nan
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[c] * cb[c] for c in set(a) | set(b)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def boot_ci(stat, rows: list, seed: int = SEED) -> tuple[float, float]:
    """Percentile bootstrap 95% CI of stat(rows); resamples whose stat is nan are dropped."""
    if not rows:
        return math.nan, math.nan
    rng = random.Random(seed)
    vals = sorted(v for v in (stat([rows[rng.randrange(len(rows))] for _ in rows])
                              for _ in range(BOOT)) if not math.isnan(v))
    if not vals:
        return math.nan, math.nan
    return vals[int(0.025 * (len(vals) - 1))], vals[int(0.975 * (len(vals) - 1))]


def prf(pairs: list[tuple[bool, bool]]) -> tuple[int, int, int, float]:
    """pairs of (predicted related, truly related) -> tp, fp, fn, F1."""
    tp = sum(p and t for p, t in pairs)
    fp = sum(p and not t for p, t in pairs)
    fn = sum(t and not p for p, t in pairs)
    return tp, fp, fn, (2 * tp / (2 * tp + fp + fn) if tp + fp + fn else math.nan)


# ---------- reading (never writes to curation/) ----------
def norm(v) -> str:
    return "" if v is None else str(v).strip().lower()


def sheet_rows(path: Path, name: str) -> list[dict]:
    wb = load_workbook(path, read_only=True, data_only=True)
    rows = list(wb[name].values)
    wb.close()
    head = [str(h) for h in rows[0]]
    return [dict(zip(head, r)) for r in rows[1:] if any(v is not None for v in r)]


def read_preds(pattern: str) -> dict[str, dict[str, str]]:
    """model -> item -> label ('' when the model errored or answered outside LABELS)."""
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for f in sorted(glob.glob(pattern)):
        for line in open(f):
            if line.strip():
                r = json.loads(line)
                lab = norm(r.get("relation"))
                out[r["model"]][r["item"]] = lab if lab in LABELS and not r.get("error") else ""
    return dict(out)


def strata_sizes() -> dict[str, int]:
    """L3 evidence rows with a sentence, per predicate: the population each V2 quota sampled."""
    rel = OUT / VERSION
    if not (rel / "edges.tsv").exists():
        return {}
    pred = {e["id"]: e["predicate"] for e in read_tsv(rel / "edges.tsv") if e["layer"] == "L3"}
    n = Counter(pred[r["edge_id"]] for r in read_tsv(rel / "edge_evidence.tsv")
                if r["layer"] == "L3" and r["sentence"] and r["edge_id"] in pred)
    return dict(n)


# ---------- scoring ----------
def row(metric, group, k, n, extra=""):
    p, lo, hi = wilson(k, n)
    return {"metric": metric, "group": group, "k": k, "n": n, "value": p, "ci_low": lo,
            "ci_high": hi, "note": extra}


def consensus(a1: dict, a2: dict, adj: dict) -> tuple[dict, list]:
    """item -> truth label. Adjudication wins; else agreement; cannot_tell is never truth.
    Binary truth survives a type-only disagreement (both related) as the label 'related'."""
    truth, disagree = {}, []
    for it in sorted(set(a1) & set(a2) | set(adj)):
        if it in adj:
            t = adj[it]
        elif a1[it] == a2[it]:
            t = a1[it]
        else:
            disagree.append(it)
            t = "related" if a1[it] in RELATED and a2[it] in RELATED else ""
        if t and t != "cannot_tell":
            truth[it] = t
    return truth, disagree


def score_extractor(name: str, pred: dict, truth: dict, strata: dict | None = None,
                    key: dict | None = None) -> list[dict]:
    out = []
    items = [i for i in truth if pred.get(i, "") not in ("", "cannot_tell")]
    abstain = sum(1 for i in truth if pred.get(i, "") in ("", "cannot_tell"))
    pairs = [(pred[i] in RELATED, truth[i] != "no_relation") for i in items]
    tp, fp, fn, f1 = prf(pairs)
    lo, hi = boot_ci(lambda rs: prf(rs)[3], pairs)
    out.append(row(f"V2 {name} precision (relation vs none)", "all", tp, tp + fp,
                   f"abstained/cannot_tell on {abstain} scored items"))
    out.append(row(f"V2 {name} recall (relation vs none)", "all", tp, tp + fn))
    out.append({"metric": f"V2 {name} F1 (relation vs none)", "group": "all", "k": "", "n": len(pairs),
                "value": f1, "ci_low": lo, "ci_high": hi, "note": "bootstrap CI"})
    typed = [i for i in items if pred[i] in RELATED and truth[i] in RELATED]
    out.append(row(f"V2 {name} type accuracy", "both say related, type agreed by annotators",
                   sum(pred[i] == truth[i] for i in typed), len(typed)))
    if key is not None:  # PubTator3: per sampled stratum, then weighted by stratum size
        by = defaultdict(list)
        for i in truth:
            by[key[i]].append(truth[i] != "no_relation")
        est, var, tot = 0.0, 0.0, 0
        for s in sorted(by):
            k, n = sum(by[s]), len(by[s])
            if s == "none":
                out.append(row("V2 pubtator3 missed relations", "unrelated co-mention pairs", k, n,
                               "share of 'none' items that state a relation"))
                continue
            out.append(row("V2 pubtator3 precision", s, k, n))
            if strata and s in strata:
                p = k / n
                est += strata[s] * p
                var += strata[s] ** 2 * p * (1 - p) / n
                tot += strata[s]
        if tot:
            p, se = est / tot, math.sqrt(var) / tot
            out.append({"metric": "V2 pubtator3 precision, weighted by stratum size", "group": "all",
                        "k": "", "n": sum(len(v) for s, v in by.items() if s != "none"), "value": p,
                        "ci_low": max(0.0, p - Z * se), "ci_high": min(1.0, p + Z * se),
                        "note": f"normal CI; strata {dict(sorted(strata.items()))}"})
    return out


def score(curation: Path, preds_glob: str, strata: dict) -> tuple[list[dict], list[dict], list[str]]:
    msgs = []
    key = {r["item"]: r["pubtator3_label"] for r in sheet_rows(curation / KEY_FILE, "key")}
    ann = [{r["item"]: r for r in sheet_rows(curation / f"V2_gold_set_annotator_{k}.xlsx", "items")}
           for k in (1, 2)]
    for k, a in enumerate(ann, 1):
        bad = Counter(norm(r.get("relation")) for r in a.values()
                      if norm(r.get("relation")) not in LABELS + ("",))
        if bad:
            msgs.append(f"annotator_{k}: labels outside the list ignored: {dict(bad)}")
    rel = [{i: norm(r.get("relation")) for i, r in a.items() if norm(r.get("relation")) in LABELS}
           for a in ann]
    adj = {}
    adj_path = curation / "V2_gold_set_adjudication.xlsx"
    if adj_path.exists():
        adj = {r["item"]: norm(r["relation"]) for r in sheet_rows(adj_path, "items")
               if norm(r.get("relation")) in LABELS}
    out = [row("V2 annotated", f"annotator_{k}", len(r), len(key)) for k, r in enumerate(rel, 1)]

    both = sorted(set(rel[0]) & set(rel[1]))
    lab = [(rel[0][i], rel[1][i]) for i in both]
    binr = [(x in RELATED, y in RELATED) for x, y in lab if "cannot_tell" not in (x, y)]
    for name, data in (("6 labels", lab), ("relation vs none", binr)):
        k_ = kappa([x for x, _ in data], [y for _, y in data])
        lo, hi = boot_ci(lambda rs: kappa([x for x, _ in rs], [y for _, y in rs]), data)
        out.append({"metric": "V2 inter-annotator Cohen's kappa", "group": name, "k": "",
                    "n": len(data), "value": k_, "ci_low": lo, "ci_high": hi, "note": "bootstrap CI"})
        out.append(row("V2 inter-annotator raw agreement", name, sum(x == y for x, y in data),
                       len(data)))

    truth, disagree = consensus(rel[0], rel[1], adj)
    out.append(row("V2 consensus truth", "items with a truth label", len(truth), len(key),
                   f"{len(disagree)} disagreements, {len(adj)} adjudicated"))
    pt = {i: PREDICATE_LABEL[key[i]] for i in key}
    out += score_extractor("pubtator3", pt, truth, strata, key)
    for model, p in sorted(read_preds(preds_glob).items()):
        missing = len(set(key) - set(p))
        if missing:
            msgs.append(f"{model}: {missing} items have no prediction")
        out += score_extractor(model, p, truth)

    # V1: entity IDs (a_correct and b_correct pooled), per annotator and where both agree
    for k, a in enumerate(ann, 1):
        v = [norm(r.get(c)) for r in a.values() for c in ("a_correct", "b_correct")]
        out.append(row("V1 entity ID correct", f"annotator_{k}", v.count("yes"),
                       v.count("yes") + v.count("no"), f"unsure {v.count('unsure')}"))
    pairs = [(norm(ann[0][i].get(c)), norm(ann[1][i].get(c))) for i in ann[0] if i in ann[1]
             for c in ("a_correct", "b_correct")]
    pairs = [(x, y) for x, y in pairs if x in ("yes", "no") and y in ("yes", "no")]
    out.append({"metric": "V1 inter-annotator Cohen's kappa", "group": "yes/no", "k": "",
                "n": len(pairs), "value": kappa(*zip(*pairs)) if pairs else math.nan,
                "ci_low": "", "ci_high": "", "note": ""})
    agreed = [x for x, y in pairs if x == y]
    out.append(row("V1 entity ID correct", "both annotators agree", agreed.count("yes"), len(agreed)))

    # V3: edge audit
    audit = sheet_rows(curation / "V3_edge_audit.xlsx", "edges")
    for field in ("layer", "source"):
        by = defaultdict(Counter)
        for r in audit:
            by[r[field]][norm(r.get("supported"))] += 1
        for g in sorted(by):
            c = by[g]
            n = c["yes"] + c["no"] + c["partly"]
            extra = f"cannot_check {c['cannot_check']}, blank {c['']} of {sum(c.values())}"
            out.append(row(f"V3 supported (strict) by {field}", g, c["yes"], n, extra))
            out.append(row(f"V3 supported (lenient) by {field}", g, c["yes"] + c["partly"], n))

    dis = [{"item": i, "pmid": ann[0][i].get("pmid"), "sentence": ann[0][i].get("sentence"),
            "entity_a": ann[0][i].get("entity_a"), "entity_b": ann[0][i].get("entity_b"),
            "annotator_1": rel[0][i], "annotator_2": rel[1][i]} for i in disagree if i not in adj]
    return out, dis, msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--curation", type=Path, default=CURATION)
    ap.add_argument("--preds", default=str(KG2 / "bench" / "llm_preds" / "*.jsonl"))
    ap.add_argument("--out", type=Path, default=OUT / VERSION / "validation")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    rows, dis, msgs = score(a.curation, a.preds, strata_sizes())
    cols = ["metric", "group", "k", "n", "value", "ci_low", "ci_high", "note"]
    for r in rows:
        for c in ("value", "ci_low", "ci_high"):
            if isinstance(r[c], float):
                r[c] = "" if math.isnan(r[c]) else round(r[c], 4)
    write_tsv(a.out / "validation_scores.tsv", cols, rows)
    write_tsv(a.out / "V2_disagreements_to_adjudicate.tsv",
              ["item", "pmid", "sentence", "entity_a", "entity_b", "annotator_1", "annotator_2"], dis)
    for m in msgs:
        print("WARN", m)
    for r in rows:
        if r["n"]:
            print(f"{r['metric']:<58} {str(r['group'])[:40]:<40} {r['k']!s:>4}/{r['n']:<4} "
                  f"{r['value']!s:<7} [{r['ci_low']}, {r['ci_high']}]")
    print(f"P6c: {len(rows)} metrics -> {a.out / 'validation_scores.tsv'}; "
          f"{len(dis)} disagreements to adjudicate")


if __name__ == "__main__":
    main()
