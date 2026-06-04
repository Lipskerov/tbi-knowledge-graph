"""
ChEMBL NQO2/QR2 Inhibitor Fetcher for the TBI Knowledge Base (v2.1)
===================================================================
Pulls **quantitative bioactivity** for the NQO2 (QR2) enzyme from ChEMBL and
turns it into directed, potency-annotated mechanism edges in the knowledge graph
(``compound —inhibits(Ki/IC50)→ NQO2``). This upgrades the inhibitor clusters
from "papers that mention a compound" to real binding/inhibition constants.

Pipeline:
  1. Resolve the human NQO2 target in ChEMBL (UniProt P16083 -> CHEMBL3959).
  2. Pull all activities with a pChEMBL value (IC50 / Ki / Kd, normalised to nM).
  3. Aggregate per compound: median potency, n measurements, median pChEMBL,
     evidence documents.
  4. Select the most informative compounds (named and/or most potent), enrich
     names/synonyms from the molecule endpoint, and resolve evidence PubMed IDs.
  5. Write a `chembl_activities` table and create/merge `entities` (type 'drug'),
     deduping against existing entities by name/alias so known inhibitors
     (melatonin, resveratrol, quercetin, S29434, ...) are *enriched*, not duplicated.

The graph edges themselves are (re)generated from `chembl_activities` by
`kb/build_graph.py::add_chembl_edges` on every build -- same pattern as the
curated PATHWAY_EDGES, so they survive the `DELETE FROM entity_relations` rebuild.

Usage:
    python kb/fetch_chembl.py [--max-compounds 40] [--dry-run] [--db PATH]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "https://www.ebi.ac.uk/chembl/api/data"
HEADERS = {"User-Agent": "TBI-KnowledgeBase/2.1 (research; fedorlipskerov@gmail.com)"}
NQO2_UNIPROT = "P16083"
PAGE = 1000
MAX_COMPOUNDS_DEFAULT = 40

# Units -> nanomolar multiplier (defensive; this dataset is already nM).
UNIT_TO_NM = {"pM": 0.001, "nM": 1.0, "uM": 1000.0, "uM2": 1000.0, "mM": 1e6, "M": 1e9}


# -- HTTP helper --------------------------------------------------------------

def _get(path: str, params: dict) -> dict:
    for attempt in range(4):
        try:
            r = requests.get(f"{BASE}/{path}", params={**params, "format": "json"},
                             headers=HEADERS, timeout=40)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 3:
                print(f"  ChEMBL request failed ({path}): {e}")
                return {}
            time.sleep(2 ** attempt)
    return {}


# -- 1. resolve target --------------------------------------------------------

def resolve_nqo2_target() -> str | None:
    data = _get("target", {"target_components__accession": NQO2_UNIPROT, "limit": 20})
    targets = data.get("targets", [])
    human = [t for t in targets
             if t.get("organism") == "Homo sapiens" and t.get("target_type") == "SINGLE PROTEIN"]
    chosen = (human or targets)
    return chosen[0]["target_chembl_id"] if chosen else None


# -- 2. pull activities -------------------------------------------------------

def fetch_activities(target_id: str) -> list[dict]:
    """All pChEMBL-scored activities for the target, paginated."""
    acts, offset = [], 0
    while True:
        data = _get("activity", {
            "target_chembl_id": target_id,
            "pchembl_value__isnull": "false",
            "limit": PAGE, "offset": offset,
        })
        chunk = data.get("activities", [])
        acts.extend(chunk)
        total = data.get("page_meta", {}).get("total_count", len(acts))
        offset += PAGE
        if offset >= total or not chunk:
            break
        time.sleep(0.2)
    return acts


def _to_nm(value, units) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    mult = UNIT_TO_NM.get(units)
    return v * mult if mult else None


# -- 3. aggregate per compound ------------------------------------------------

def aggregate(acts: list[dict]) -> dict[str, dict]:
    by_mol: dict[str, dict] = {}
    for a in acts:
        mid = a.get("molecule_chembl_id")
        if not mid:
            continue
        nm = _to_nm(a.get("standard_value"), a.get("standard_units"))
        rel = a.get("standard_relation") or "="
        agg = by_mol.setdefault(mid, {
            "molecule_chembl_id": mid, "pref_name": a.get("molecule_pref_name"),
            "nm": [], "pchembl": [], "types": set(), "docs": set(),
            "smiles": a.get("canonical_smiles"),
        })
        # only exact-relation values feed the median potency (skip >, < censored)
        if nm is not None and rel == "=":
            agg["nm"].append(nm)
        try:
            agg["pchembl"].append(float(a["pchembl_value"]))
        except (TypeError, ValueError, KeyError):
            pass
        if a.get("standard_type"):
            agg["types"].add(a["standard_type"])
        if a.get("document_chembl_id"):
            agg["docs"].add(a["document_chembl_id"])
        if not agg["pref_name"] and a.get("molecule_pref_name"):
            agg["pref_name"] = a["molecule_pref_name"]

    out = {}
    for mid, agg in by_mol.items():
        if not agg["pchembl"]:
            continue
        out[mid] = {
            "molecule_chembl_id": mid,
            "pref_name":     agg["pref_name"],
            "median_nm":     round(statistics.median(agg["nm"]), 2) if agg["nm"] else None,
            "pchembl_median": round(statistics.median(agg["pchembl"]), 2),
            "n_acts":        len(agg["pchembl"]),
            "types":         sorted(agg["types"]),
            "docs":          sorted(agg["docs"]),
            "smiles":        agg["smiles"],
        }
    return out


# -- 4. selection + enrichment ------------------------------------------------

def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def enrich_names(mids: list[str]) -> dict[str, dict]:
    """Batch-fetch pref_name + synonyms for molecule ids (ChEMBL __in filter)."""
    info: dict[str, dict] = {}
    for chunk in _chunks(mids, 20):
        data = _get("molecule", {"molecule_chembl_id__in": ",".join(chunk), "limit": len(chunk)})
        for m in data.get("molecules", []):
            syns = [s.get("molecule_synonym") for s in (m.get("molecule_synonyms") or [])]
            info[m["molecule_chembl_id"]] = {
                "pref_name": m.get("pref_name"),
                "synonyms": [s for s in syns if s],
            }
        time.sleep(0.2)
    return info


def resolve_pmids(doc_ids: list[str]) -> dict[str, str]:
    """Map ChEMBL document ids -> PubMed ids (batched)."""
    out: dict[str, str] = {}
    for chunk in _chunks(doc_ids, 20):
        data = _get("document", {"document_chembl_id__in": ",".join(chunk), "limit": len(chunk)})
        for d in data.get("documents", []):
            if d.get("pubmed_id"):
                out[d["document_chembl_id"]] = str(d["pubmed_id"])
        time.sleep(0.2)
    return out


def select_compounds(agg: dict[str, dict], max_compounds: int) -> list[dict]:
    """Select compounds for the graph, potency-ranked but **named-first**.

    The project's inhibitors of interest (melatonin, resveratrol, quercetin,
    S29434, chloroquine, ...) are weaker binders than anonymous medchem research
    compounds, so a pure pChEMBL ranking buries them. We therefore resolve names
    across the *whole* compound set, take every named compound first (most potent
    first), then top up with the most potent unnamed "lead" compounds.
    """
    ranked = sorted(agg.values(), key=lambda c: -c["pchembl_median"])
    # resolve names for the full set (bounded) so no named compound is missed
    head = ranked[:300]
    names = enrich_names([c["molecule_chembl_id"] for c in head])
    for c in head:
        ni = names.get(c["molecule_chembl_id"], {})
        c["pref_name"] = c["pref_name"] or ni.get("pref_name")
        c["synonyms"] = ni.get("synonyms", [])
    named   = [c for c in head if c["pref_name"]]
    unnamed = [c for c in head if not c["pref_name"]]
    # all named first (already potency-sorted), then fill with most-potent unnamed
    selected = (named + unnamed)[:max_compounds]
    return selected


# -- 5. persist: chembl_activities + entities ---------------------------------

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS chembl_activities (
    molecule_chembl_id TEXT PRIMARY KEY,
    entity_id          INTEGER,
    pref_name          TEXT,
    relation           TEXT,
    standard_type      TEXT,
    median_nm          REAL,
    pchembl_median     REAL,
    n_acts             INTEGER,
    evidence_pmids     TEXT,
    target_chembl_id   TEXT,
    smiles             TEXT,
    fetched_at         TEXT,
    FOREIGN KEY (entity_id) REFERENCES entities(id)
)
"""


def _load_entity_index(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, name, aliases FROM entities").fetchall()
    idx = []
    for r in rows:
        aliases = json.loads(r["aliases"] or "[]")
        keys = {r["name"].lower()} | {a.lower() for a in aliases}
        idx.append({"id": r["id"], "name": r["name"], "aliases": aliases, "keys": keys})
    return idx


def _resolve_or_create_entity(conn: sqlite3.Connection, idx: list[dict],
                              comp: dict) -> int:
    """Match an existing entity by name/synonym (case-insensitive) or create one."""
    candidates = [comp["pref_name"]] + comp.get("synonyms", []) + [comp["molecule_chembl_id"]]
    candidates = [c for c in candidates if c]
    for cand in candidates:
        cl = cand.lower()
        for e in idx:
            if cl in e["keys"]:
                # enrich existing entity's aliases with the ChEMBL id + name
                new_aliases = e["aliases"][:]
                for extra in (comp["molecule_chembl_id"], comp["pref_name"]):
                    if extra and extra not in new_aliases:
                        new_aliases.append(extra)
                if new_aliases != e["aliases"]:
                    conn.execute("UPDATE entities SET aliases=? WHERE id=?",
                                 (json.dumps(new_aliases), e["id"]))
                    e["aliases"] = new_aliases
                    e["keys"] |= {a.lower() for a in new_aliases}
                return e["id"]
    # create a new drug entity
    name = comp["pref_name"] or comp["molecule_chembl_id"]
    aliases = [name, comp["molecule_chembl_id"]] + comp.get("synonyms", [])
    aliases = list(dict.fromkeys(a for a in aliases if a))
    cur = conn.execute(
        "INSERT OR IGNORE INTO entities (name, type, aliases) VALUES (?, 'drug', ?)",
        (name, json.dumps(aliases)),
    )
    if cur.lastrowid:
        eid = cur.lastrowid
    else:  # name already existed (race / exact dup) -- look it up
        eid = conn.execute("SELECT id FROM entities WHERE name=?", (name,)).fetchone()[0]
    idx.append({"id": eid, "name": name, "aliases": aliases,
                "keys": {a.lower() for a in aliases}})
    return eid


def persist(conn: sqlite3.Connection, compounds: list[dict], doc_pmids: dict[str, str],
            target_id: str) -> int:
    conn.execute(CREATE_TABLE)
    idx = _load_entity_index(conn)
    now = datetime.utcnow().isoformat()
    n = 0
    for c in compounds:
        eid = _resolve_or_create_entity(conn, idx, c)
        pmids = sorted({doc_pmids[d] for d in c["docs"] if d in doc_pmids})
        types = c["types"]
        relation = "binds" if types == ["Kd"] else "inhibits"
        conn.execute("""
            INSERT OR REPLACE INTO chembl_activities
                (molecule_chembl_id, entity_id, pref_name, relation, standard_type,
                 median_nm, pchembl_median, n_acts, evidence_pmids, target_chembl_id,
                 smiles, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            c["molecule_chembl_id"], eid, c["pref_name"], relation, "/".join(types),
            c["median_nm"], c["pchembl_median"], c["n_acts"], json.dumps(pmids),
            target_id, c.get("smiles"), now,
        ))
        n += 1
    conn.commit()
    return n


# -- orchestration ------------------------------------------------------------

def run(db_path: str, max_compounds: int = MAX_COMPOUNDS_DEFAULT, dry_run: bool = False) -> int:
    print("[chembl] Resolving NQO2 target...")
    target_id = resolve_nqo2_target()
    if not target_id:
        print("  ! could not resolve NQO2 target in ChEMBL")
        return 0
    print(f"  target = {target_id}")

    print("[chembl] Fetching activities...")
    acts = fetch_activities(target_id)
    print(f"  {len(acts)} activities with pChEMBL")
    agg = aggregate(acts)
    print(f"  {len(agg)} distinct compounds")

    selected = select_compounds(agg, max_compounds)
    n_named = sum(1 for c in selected if c["pref_name"])
    print(f"  selected {len(selected)} compounds ({n_named} named) for the graph")

    doc_ids = sorted({d for c in selected for d in c["docs"]})
    doc_pmids = resolve_pmids(doc_ids)
    print(f"  resolved {len(doc_pmids)}/{len(doc_ids)} evidence documents -> PubMed")

    if dry_run:
        print("\n  -- dry run: top 15 compounds --")
        for c in selected[:15]:
            pot = f"{c['median_nm']:.0f} nM" if c["median_nm"] else "n/a"
            print(f"   {c['pref_name'] or c['molecule_chembl_id']:<28} "
                  f"{'/'.join(c['types']):<8} {pot:>10}  pChEMBL {c['pchembl_median']}  n={c['n_acts']}")
        return 0

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    n = persist(conn, selected, doc_pmids, target_id)
    conn.close()
    print(f"  wrote {n} compounds to chembl_activities (+ entities). "
          f"Run build_kb.py --skip-fetch to emit graph edges.")
    return n


def main():
    ap = argparse.ArgumentParser(description="Fetch NQO2 inhibitor bioactivity from ChEMBL")
    ap.add_argument("--db", default="data/tbi_papers.db")
    ap.add_argument("--max-compounds", type=int, default=MAX_COMPOUNDS_DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    db_path = Path(__file__).resolve().parent.parent / args.db
    run(str(db_path), max_compounds=args.max_compounds, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
