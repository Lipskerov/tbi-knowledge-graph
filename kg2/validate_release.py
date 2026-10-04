"""Validate out/<v>/release/ against the Biolink Model: KGX validator + the checks KGX 2.6 skips.

    KGX_BIN=/path/to/venv/bin/kgx python3 validate_release.py      # full (KGX + own checks)
    python3 validate_release.py                                    # own checks only
    python3 validate_release.py --selftest                         # plant errors, all must be caught

KGX checks categories, predicates and CURIE prefixes. Measured on 04.10.2026 with planted errors,
KGX 2.6.0 does NOT flag an edge to a missing node, a missing primary_knowledge_source or an invalid
knowledge_level, so those are checked here, with the agent_type enum and the publications format.
Allowed exception: the project prefix TBIKG (one node, no standard term), documented in README.
Exit code 0 = valid.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common import OUT, VERSION, read_tsv

REL = OUT / VERSION / "release"
ALLOWED_PREFIXES = {"TBIKG"}
# Biolink 4.4.4 enums (read with bmt on 04.10.2026)
KNOWLEDGE_LEVEL = {"knowledge_assertion", "logical_entailment", "not_provided", "observation",
                   "prediction", "statistical_association", "text_co_occurrence"}
AGENT_TYPE = {"automated_agent", "computational_model", "data_analysis_pipeline",
              "image_processing_agent", "manual_agent", "manual_validation_of_automated_agent",
              "not_provided", "text_mining_agent"}
PUBS = re.compile(r"PMID:\d+(\|PMID:\d+)*")
EDGE_FILES = ["edges.tsv", "noncommercial/edges.tsv", "chembl_cc-by-sa-3.0/edges.tsv"]


def own_checks(rel):
    problems = []
    nodes = read_tsv(rel / "nodes.tsv")
    ids = {n["id"] for n in nodes}
    if len(ids) != len(nodes):
        problems.append(f"duplicate node ids: {len(nodes) - len(ids)}")
    seen = set()
    for f in EDGE_FILES:
        for e in read_tsv(rel / f):
            tag = f"{f}:{e['id']}"
            if e["id"] in seen:
                problems.append(f"{tag} duplicate edge id")
            seen.add(e["id"])
            for end in ("subject", "object"):
                if e[end] not in ids:
                    problems.append(f"{tag} {end} {e[end]} is not a node")
            for field in ("primary_knowledge_source", "knowledge_level", "agent_type", "predicate"):
                if not e.get(field):
                    problems.append(f"{tag} missing {field}")
            if e.get("knowledge_level") and e["knowledge_level"] not in KNOWLEDGE_LEVEL:
                problems.append(f"{tag} knowledge_level '{e['knowledge_level']}' not in Biolink enum")
            if e.get("agent_type") and e["agent_type"] not in AGENT_TYPE:
                problems.append(f"{tag} agent_type '{e['agent_type']}' not in Biolink enum")
            if e.get("publications") and not PUBS.fullmatch(e["publications"]):
                problems.append(f"{tag} publications not a '|' list of PMID CURIEs: {e['publications'][:40]}")
    return problems


def kgx_checks(rel, kgx):
    """Run KGX on nodes + every edge file; return (problems, allowed) from its ERROR section."""
    problems, allowed = [], []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shutil.copy(rel / "nodes.tsv", tmp / "rel_nodes.tsv")
        with open(tmp / "rel_edges.tsv", "w") as out:
            cols = None
            for f in EDGE_FILES:  # side files carry an extra `licence` column; drop it for KGX
                rows = read_tsv(rel / f)
                if not rows:
                    continue
                cols = cols or [c for c in rows[0] if c != "licence"]
                if out.tell() == 0:
                    out.write("\t".join(cols) + "\n")
                for r in rows:
                    out.write("\t".join(r[c] for c in cols) + "\n")
        res = subprocess.run([kgx, "validate", "-i", "tsv", "rel_nodes.tsv", "rel_edges.tsv"],
                             cwd=tmp, capture_output=True, text=True)
        text = res.stdout + res.stderr
        start = text.find("{")
        if start < 0:  # KGX prints {} when clean; no JSON at all means it crashed
            return [f"KGX produced no report (exit {res.returncode}): {text.strip()[-200:]}"], []
        report = json.loads(text[start:text.rfind("}") + 1])
    for level in ("ERROR",):
        for kind, msgs in report.get(level, {}).items():
            for msg, examples in msgs.items():
                m = re.search(r"CURIE prefix '([^']+)'", msg)
                (allowed if m and m.group(1) in ALLOWED_PREFIXES else problems).append(
                    f"KGX {kind}: {msg} (e.g. {examples[:2]})")
    return problems, allowed


def validate(rel, kgx):
    problems = own_checks(rel)
    allowed = []
    if kgx:
        p, allowed = kgx_checks(rel, kgx)
        problems += p
    return problems, allowed


def selftest(kgx):
    """Copy the release, plant one error per check, and require every one to be reported."""
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "release"
        shutil.copytree(REL, bad)
        lines = (bad / "edges.tsv").read_text().splitlines()
        head = lines[0].split("\t")
        base = dict(zip(head, lines[1].split("\t")))
        planted = {
            "P1": dict(base, id="P1", object="NCBIGene:999999999"),          # missing node
            "P2": dict(base, id="P2", primary_knowledge_source=""),          # missing source
            "P3": dict(base, id="P3", knowledge_level="made_up_level"),      # bad enum
            "P4": dict(base, id="P4", agent_type="robot"),                   # bad enum
            "P5": dict(base, id="P5", publications="12345;67890"),           # old format
            "P6": dict(base, id="P6", predicate="biolink:not_a_predicate"),  # KGX
            "P7": dict(base, id="P7", subject="FOO:1"),                       # KGX prefix (+ own)
        }
        with open(bad / "edges.tsv", "a") as f:
            for r in planted.values():
                f.write("\t".join(r[c] for c in head) + "\n")
        problems, _ = validate(bad, kgx)
        text = "\n".join(problems)
        expect = {"P1": "P1 object", "P2": "P2 missing primary", "P3": "P3 knowledge_level",
                  "P4": "P4 agent_type", "P5": "P5 publications", "P7": "P7 subject"}
        if kgx:
            expect["P6"] = "not_a_predicate"
        if kgx:  # a KGX run that produces no report (crash) must fail, never pass
            crash, _ = kgx_checks(REL, shutil.which("false"))
            text += "\n" + "\n".join(crash)
            expect["CRASH"] = "KGX produced no report"
        missed = [k for k, needle in expect.items() if needle not in text]
        print(f"selftest: {len(expect) - len(missed)}/{len(expect)} planted errors caught"
              + (f"; MISSED {missed}" if missed else ""))
        return not missed


def main():
    kgx = os.environ.get("KGX_BIN")
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest(kgx) else 1)
    problems, allowed = validate(REL, kgx)
    for a in allowed:
        print("ALLOWED", a)
    for p in problems[:50]:
        print("FAIL", p)
    print(f"validate_release: {'KGX ' + kgx if kgx else 'KGX not run'}; "
          f"{len(problems)} problems, {len(allowed)} allowed exceptions")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
