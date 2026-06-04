"""
OmniPath signed/directed interaction fetcher for the TBI Knowledge Base (v2.2)
==============================================================================
Adds **curated, directed, signed** protein-protein interactions (who activates /
inhibits whom) among the knowledge-graph entities, pulled from OmniPath -- a
meta-resource that aggregates SIGNOR, SignaLink, Reactome, SPIKE and ~100 other
curated sources into one signed causal network.

Why this exists (grounded in a coverage probe, 2026-06-04):
  * NQO2 itself is barely present in curated interaction DBs (2 edges total), so
    OmniPath does **not** supply the novel NQO2 mechanism -- that stays in the
    hand-curated PATHWAY_EDGES (the project's unique contribution).
  * But the *surrounding* biology is well covered: ~42 directed / ~34 signed
    edges exist among the existing entities (the ISR/eIF2alpha arm, the Nrf2
    antioxidant arm, the neuroinflammation cytokine arm, plasticity). OmniPath
    makes that context rigorous and directional, with literature references.

Pipeline (mirrors kb/fetch_chembl.py):
  1. Map entity names -> official HGNC gene symbols.
  2. Query OmniPath for interactions among that gene set (directed network).
  3. Keep edges whose *both* partners are entities we have; resolve back to
     entity ids; classify relation (activates / inhibits / regulates / interacts).
  4. Normalise: add the gene symbol as an alias on each mapped entity.
  5. Write an `omnipath_interactions` table (source of truth). Edges are emitted
     into the graph by kb/build_graph.py::add_omnipath_edges on every build.

Usage:
    python kb/fetch_omnipath.py [--dry-run] [--db PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "https://omnipathdb.org/interactions"
HEADERS = {"User-Agent": "TBI-KnowledgeBase/2.2 (research; fedorlipskerov@gmail.com)"}
DATASETS = "omnipath,pathwayextra,kinaseextra"

# Entity name (as stored in the DB) -> official HGNC gene symbol.
# Only proteins that OmniPath could plausibly carry; lncRNA/miRNA are omitted
# (OmniPath's causal protein network does not contain them).
ENTITY_TO_GENE = {
    "NQO2": "NQO2", "NQO1": "NQO1", "Nrf2": "NFE2L2", "HO-1": "HMOX1", "SOD": "SOD1",
    "catalase": "CAT", "GFAP": "GFAP", "UCH-L1": "UCHL1", "NfL": "NEFL", "NfH": "NEFH",
    "tau": "MAPT", "p-tau": "MAPT", "Kv2.1": "KCNB1", "DRD1": "DRD1", "ATF4": "ATF4",
    "CHOP": "DDIT3", "CaMKII": "CAMK2A", "Arc": "ARC", "GCN2": "EIF2AK4", "PERK": "EIF2AK3",
    "PKR": "EIF2AK2", "eEF2": "EEF2", "eIF2B": "EIF2B5", "eIF2α": "EIF2S1", "BDNF": "BDNF",
    "IL-1β": "IL1B", "IL-6": "IL6", "TNF-α": "TNF", "Iba1": "AIF1", "MBP": "MBP",
    "NSE": "ENO2", "S100B": "S100B", "VILIP-1": "VSNL1", "Aβ42": "APP",
    "AMPA receptor": "GRIA1", "NMDA receptor": "GRIN1",
}


def _lst(v) -> list[str]:
    """OmniPath list-ish fields arrive as a list or a ';'-joined string."""
    if isinstance(v, list):
        return [x for x in v if x]
    return [x for x in v.split(";") if x] if v else []


def _pmids(refs) -> list[str]:
    """Extract PubMed ids from OmniPath 'references' (e.g. 'SIGNOR:12345678')."""
    out = []
    for r in _lst(refs):
        m = re.search(r"(\d{6,})", str(r))
        if m:
            out.append(m.group(1))
    return sorted(set(out))


def _relation(e: dict) -> tuple[str, int]:
    """Map an OmniPath edge to (relation, directed)."""
    directed = 1 if e.get("is_directed") else 0
    stim, inhib = e.get("is_stimulation"), e.get("is_inhibition")
    if stim and not inhib:
        return "activates", directed
    if inhib and not stim:
        return "inhibits", directed
    if directed:
        return "regulates", 1
    return "interacts", 0


def fetch_interactions(genes: list[str]) -> list[dict]:
    params = {
        "partners": ",".join(genes),
        "genesymbols": "1",
        "fields": "sources,references,curation_effort",
        "datasets": DATASETS,
        "format": "json",
    }
    for attempt in range(4):
        try:
            r = requests.get(BASE, params=params, headers=HEADERS, timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 3:
                print(f"  OmniPath request failed: {e}")
                return []
            time.sleep(2 ** attempt)
    return []


CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS omnipath_interactions (
    source_entity_id INTEGER,
    target_entity_id INTEGER,
    relation         TEXT,
    directed         INTEGER,
    sources          TEXT,
    references_pmids TEXT,
    curation_effort  INTEGER,
    fetched_at       TEXT,
    PRIMARY KEY (source_entity_id, target_entity_id, relation),
    FOREIGN KEY (source_entity_id) REFERENCES entities(id),
    FOREIGN KEY (target_entity_id) REFERENCES entities(id)
)
"""


def _name_to_id(conn: sqlite3.Connection) -> dict[str, int]:
    return {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM entities")}


def _add_alias(conn: sqlite3.Connection, entity_id: int, symbol: str):
    """Normalisation: record the HGNC gene symbol as an alias on the entity."""
    row = conn.execute("SELECT aliases FROM entities WHERE id=?", (entity_id,)).fetchone()
    aliases = json.loads(row["aliases"] or "[]")
    if symbol not in aliases:
        aliases.append(symbol)
        conn.execute("UPDATE entities SET aliases=? WHERE id=?",
                     (json.dumps(aliases), entity_id))


def run(db_path: str, dry_run: bool = False) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    name_to_id = _name_to_id(conn)

    # Build gene-symbol set + symbol -> entity id (first entity wins on collision,
    # e.g. MAPT maps to 'tau' rather than 'p-tau').
    sym_to_eid: dict[str, int] = {}
    for name, sym in ENTITY_TO_GENE.items():
        eid = name_to_id.get(name)
        if eid is not None and sym not in sym_to_eid:
            sym_to_eid[sym] = eid
    genes = sorted(sym_to_eid)
    print(f"[omnipath] {len(genes)} entity genes mapped; querying OmniPath...")

    raw = fetch_interactions(genes)
    inset = set(genes)
    # keep only edges whose both partners are in our entity set
    edges = [e for e in raw
             if e.get("source_genesymbol") in inset and e.get("target_genesymbol") in inset]
    print(f"  OmniPath returned {len(raw)} edges; {len(edges)} are intra-set")

    # dedup by (src_id, tgt_id, relation), keeping the best-supported
    best: dict[tuple, dict] = {}
    for e in edges:
        s_id = sym_to_eid[e["source_genesymbol"]]
        t_id = sym_to_eid[e["target_genesymbol"]]
        if s_id == t_id:
            continue
        relation, directed = _relation(e)
        rec = {
            "src": s_id, "tgt": t_id, "relation": relation, "directed": directed,
            "sources": sorted({s.split("_")[0] for s in _lst(e.get("sources"))}),
            "pmids": _pmids(e.get("references")),
            "effort": int(e.get("curation_effort") or 0),
        }
        key = (s_id, t_id, relation)
        if key not in best or rec["effort"] > best[key]["effort"]:
            best[key] = rec

    records = list(best.values())
    signed = sum(1 for r in records if r["relation"] in ("activates", "inhibits"))
    print(f"  {len(records)} unique edges ({signed} signed activates/inhibits)")

    if dry_run:
        id_to_name = {v: k for k, v in name_to_id.items()}
        print("\n  -- sample edges --")
        for r in sorted(records, key=lambda x: -x["effort"])[:20]:
            print(f"   {id_to_name.get(r['src'])} -{r['relation']}-> {id_to_name.get(r['tgt'])}"
                  f"  [{','.join(r['sources'][:3])}] refs={len(r['pmids'])}")
        conn.close()
        return 0

    conn.execute(CREATE_TABLE)
    conn.execute("DELETE FROM omnipath_interactions")
    now = datetime.utcnow().isoformat()
    for r in records:
        conn.execute("""
            INSERT OR REPLACE INTO omnipath_interactions
                (source_entity_id, target_entity_id, relation, directed,
                 sources, references_pmids, curation_effort, fetched_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (r["src"], r["tgt"], r["relation"], r["directed"],
              ";".join(r["sources"]), json.dumps(r["pmids"]), r["effort"], now))
    # normalisation: stamp gene symbols onto entities as aliases
    for sym, eid in sym_to_eid.items():
        _add_alias(conn, eid, sym)
    conn.commit()
    conn.close()
    print(f"  wrote {len(records)} edges to omnipath_interactions (+ gene-symbol aliases). "
          f"Run build_kb.py --skip-fetch to emit graph edges.")
    return len(records)


def main():
    ap = argparse.ArgumentParser(description="Fetch signed/directed interactions from OmniPath")
    ap.add_argument("--db", default="data/tbi_papers.db")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    db_path = Path(__file__).resolve().parent.parent / args.db
    run(str(db_path), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
