"""Tests for p6_score.py on synthetic sheets with known answers. Never touches curation/.

    cd kg2 && python3 -m pytest -q test_p6_score.py
The fixture reuses only the item IDs and PubTator3 labels of the real key (the item mix the
scorer will meet); every annotator, LLM and audit label is synthetic.
"""
import json
import math
import random

import pytest
from openpyxl import Workbook
from sklearn.metrics import cohen_kappa_score
from statsmodels.stats.proportion import proportion_confint

import p6_score as S
from common import CURATION


def write_sheet(path, name, cols, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = name
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c) for c in cols])
    wb.save(path)


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    d = tmp_path_factory.mktemp("curation")
    key = {r["item"]: r["pubtator3_label"] for r in S.sheet_rows(CURATION / S.KEY_FILE, "key")}
    write_sheet(d / S.KEY_FILE, "key", ["item", "pubtator3_label"],
                [{"item": i, "pubtator3_label": k} for i, k in key.items()])
    pos = sorted(i for i in key if key[i] != "none")
    neg = sorted(i for i in key if key[i] == "none")
    assoc = [i for i in pos if S.PREDICATE_LABEL[key[i]] == "association"]
    g = {"flip_to_none": pos[:30], "flip_to_rel": neg[:20], "disagree": pos[30:70],
         "cannot_tell": neg[20:25]}
    g["type_disagree"] = [i for i in assoc if i not in pos[:70]][:10]
    a1 = {i: S.PREDICATE_LABEL[key[i]] for i in key}
    for i in g["flip_to_none"]:
        a1[i] = "no_relation"
    for i in g["flip_to_rel"]:
        a1[i] = "association"
    for i in g["cannot_tell"]:
        a1[i] = "cannot_tell"
    a2 = dict(a1)
    for i in g["disagree"]:
        a2[i] = "no_relation"
    for i in g["type_disagree"]:
        a2[i] = "binding"
    cols = ["item", "pmid", "sentence", "entity_a", "entity_b", "relation", "a_correct", "b_correct"]
    wrong_b = set(sorted(key)[:10])
    for k, lab in ((1, a1), (2, a2)):
        write_sheet(d / f"V2_gold_set_annotator_{k}.xlsx", "items", cols,
                    [{"item": i, "pmid": "1", "sentence": "s", "entity_a": "A", "entity_b": "B",
                      "relation": lab[i].upper() if i == pos[0] else lab[i],  # case is normalised
                      "a_correct": "yes", "b_correct": "no" if i in wrong_b else "yes"}
                     for i in key])
    audit = ["yes"] * 60 + ["no"] * 20 + ["partly"] * 10 + ["cannot_check"] * 10
    write_sheet(d / "V3_edge_audit.xlsx", "edges", ["edge_id", "layer", "source", "supported"],
                [{"edge_id": f"e{n}", "layer": "L1", "source": "infores:x", "supported": s}
                 for n, s in enumerate(audit)])
    llm_abstain = g["flip_to_rel"][0]
    with open(d / "preds.jsonl", "w") as f:
        for i in key:
            err = "invalid label: ''" if i == llm_abstain else ""
            f.write(json.dumps({"item": i, "model": "m", "relation": "" if err else "association",
                                "error": err}) + "\n")
    strata = {"biolink:associated_with": 1000, "biolink:positively_correlated_with": 500,
              "biolink:negatively_correlated_with": 300, "biolink:physically_interacts_with": 50,
              "biolink:related_to": 20}
    rows, dis, msgs = S.score(d, str(d / "preds.jsonl"), strata)
    return {"rows": rows, "dis": dis, "key": key, "g": g, "a1": a1, "a2": a2, "strata": strata,
            "pos": pos, "neg": neg}


def get(rows, metric, group="all"):
    hit = [r for r in rows if r["metric"] == metric and r["group"] == group]
    assert len(hit) == 1, (metric, group, len(hit))
    return hit[0]


def test_wilson_matches_statsmodels():
    for k, n in [(0, 10), (3, 10), (10, 10), (230, 260), (1, 400)]:
        p, lo, hi = S.wilson(k, n)
        elo, ehi = proportion_confint(k, n, alpha=0.05, method="wilson")
        assert p == k / n and lo == pytest.approx(elo, abs=1e-9) and hi == pytest.approx(ehi, abs=1e-9)
    assert all(math.isnan(x) for x in S.wilson(0, 0))


def test_kappa_matches_sklearn():
    rng = random.Random(1)
    for _ in range(50):
        a = [rng.choice("abcd") for _ in range(60)]
        b = [x if rng.random() < 0.6 else rng.choice("abcd") for x in a]
        assert S.kappa(a, b) == pytest.approx(cohen_kappa_score(a, b), abs=1e-12)


def test_consensus_counts(fx):
    g = fx["g"]
    assert len(fx["dis"]) == 50  # 40 relation-vs-none + 10 type-only disagreements
    r = get(fx["rows"], "V2 consensus truth", "items with a truth label")
    assert r["k"] == 400 - 40 - 5  # disagreements out, cannot_tell out, type-only kept
    assert {d["item"] for d in fx["dis"]} == set(g["disagree"]) | set(g["type_disagree"])


def test_iaa_kappa(fx):
    a1, a2 = fx["a1"], fx["a2"]
    items = sorted(fx["key"])
    r = get(fx["rows"], "V2 inter-annotator Cohen's kappa", "6 labels")
    assert r["n"] == 400
    assert r["value"] == pytest.approx(cohen_kappa_score([a1[i] for i in items], [a2[i] for i in items]))
    assert r["ci_low"] <= r["value"] <= r["ci_high"]


def test_pubtator3_binary(fx):
    # truth items: 260 extractor positives (30 truly none), 95 'none' items (20 truly related)
    p = get(fx["rows"], "V2 pubtator3 precision (relation vs none)")
    rc = get(fx["rows"], "V2 pubtator3 recall (relation vs none)")
    f1 = get(fx["rows"], "V2 pubtator3 F1 (relation vs none)")
    assert (p["k"], p["n"]) == (230, 260)
    assert (rc["k"], rc["n"]) == (230, 250)
    assert f1["value"] == pytest.approx(2 * 230 / (2 * 230 + 30 + 20))
    assert get(fx["rows"], "V2 pubtator3 type accuracy",
               "both say related, type agreed by annotators")["k"] == 220
    m = get(fx["rows"], "V2 pubtator3 missed relations", "unrelated co-mention pairs")
    assert (m["k"], m["n"]) == (20, 95)


def test_pubtator3_weighted_precision(fx):
    key, g, strata = fx["key"], fx["g"], fx["strata"]
    out = set(g["disagree"])
    est = tot = 0
    for s, N in strata.items():
        items = [i for i in key if key[i] == s and i not in out]
        k = sum(i not in g["flip_to_none"] for i in items)
        assert get(fx["rows"], "V2 pubtator3 precision", s)["n"] == len(items)
        est += N * k / len(items)
        tot += N
    w = get(fx["rows"], "V2 pubtator3 precision, weighted by stratum size")
    assert w["value"] == pytest.approx(est / tot)
    assert w["ci_low"] < w["value"] < w["ci_high"]


def test_llm_scored_with_abstention(fx):
    # predicts 'association' everywhere except one errored item (a truly related 'none' item)
    p = get(fx["rows"], "V2 m precision (relation vs none)")
    rc = get(fx["rows"], "V2 m recall (relation vs none)")
    assert (p["k"], p["n"]) == (249, 354) and (rc["k"], rc["n"]) == (249, 249)
    assert "abstained/cannot_tell on 1" in p["note"]
    key, a1, out = fx["key"], fx["a1"], set(fx["g"]["disagree"]) | set(fx["g"]["type_disagree"])
    typed = [i for i in key if i not in out and a1[i] in S.RELATED and i != fx["g"]["flip_to_rel"][0]]
    t = get(fx["rows"], "V2 m type accuracy", "both say related, type agreed by annotators")
    assert (t["k"], t["n"]) == (sum(a1[i] == "association" for i in typed), len(typed))


def test_v1_and_v3(fx):
    r = get(fx["rows"], "V1 entity ID correct", "annotator_1")
    assert (r["k"], r["n"]) == (790, 800)
    assert get(fx["rows"], "V1 inter-annotator Cohen's kappa", "yes/no")["value"] == 1.0
    s = get(fx["rows"], "V3 supported (strict) by layer", "L1")
    lz = get(fx["rows"], "V3 supported (lenient) by layer", "L1")
    assert (s["k"], s["n"], lz["k"]) == (60, 90, 70)
    assert "cannot_check 10" in s["note"]


def test_partial_annotation_scores_only_filled(tmp_path, fx):
    """One annotator blank -> no truth, no extractor scores, no crash."""
    d = tmp_path
    key = fx["key"]
    write_sheet(d / S.KEY_FILE, "key", ["item", "pubtator3_label"],
                [{"item": i, "pubtator3_label": k} for i, k in key.items()])
    cols = ["item", "relation", "a_correct", "b_correct"]
    write_sheet(d / "V2_gold_set_annotator_1.xlsx", "items", cols,
                [{"item": i, "relation": "binding" if n < 3 else None} for n, i in enumerate(key)])
    write_sheet(d / "V2_gold_set_annotator_2.xlsx", "items", cols, [{"item": i} for i in key])
    write_sheet(d / "V3_edge_audit.xlsx", "edges", ["edge_id", "layer", "source", "supported"],
                [{"edge_id": "e", "layer": "L1", "source": "x"}])
    rows, dis, _ = S.score(d, str(d / "none*.jsonl"), {})
    assert get(rows, "V2 annotated", "annotator_1")["k"] == 3
    assert get(rows, "V2 consensus truth", "items with a truth label")["k"] == 0
    assert get(rows, "V2 pubtator3 precision (relation vs none)")["n"] == 0
