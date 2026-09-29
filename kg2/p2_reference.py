"""P2 — curated reference layer (L1) + gene features.

Edges
  STRING v12 physical, human, combined score >= 700   physically_interacts_with (undirected)
  OmniPath core (academic licence subset)            regulates (+/-), directed
  Reactome lowest-level pathways, human              participates_in
  ChEMBL (v1 table, NQO2 target, pChEMBL)           directly_physically_interacts_with
Features
  GO (goa_human, NOT-qualified rows dropped)         interim/features_go.tsv (long format)

Outputs: interim/l1_edges.tsv, interim/l1_nodes.tsv, interim/features_go.tsv
"""
from collections import defaultdict

from common import (INTERIM, KB_DB, RAW, SOURCES, db, dumps, fetch, log_source, open_text,
                    read_tsv, write_tsv)

STRING_MIN = 700
EDGE_COLS = ["subject", "predicate", "object", "direction", "layer", "knowledge_level",
             "agent_type", "primary_knowledge_source", "publications", "score", "qualifiers"]


def human_maps():
    genes = read_tsv(INTERIM / "genes_human.tsv")
    by_sym = {g["symbol"].upper(): g["ncbigene"] for g in genes}
    by_uniprot = {}
    for g in genes:
        for u in filter(None, g["uniprot"].split("|")):
            by_uniprot.setdefault(u, g["ncbigene"])
    return genes, by_sym, by_uniprot


def string_edges(by_sym):
    info = fetch("string_info")
    links = fetch("string_links")
    ensp2sym = {}
    with open_text(info) as f:
        next(f)
        for line in f:
            ensp, name = line.split("\t")[:2]
            ensp2sym[ensp] = name
    seen, unmapped = set(), set()
    with open_text(links) as f:
        next(f)
        for line in f:
            a, b, s = line.split()
            if int(s) < STRING_MIN:
                continue
            ga, gb = by_sym.get(ensp2sym.get(a, "").upper()), by_sym.get(ensp2sym.get(b, "").upper())
            if not ga or not gb:
                unmapped.update(x for x, g in ((a, ga), (b, gb)) if not g)
                continue
            if ga == gb:
                continue
            key = tuple(sorted((ga, gb)))  # undirected: canonical sorted pair
            if key in seen:
                continue
            seen.add(key)
            yield {"subject": key[0], "predicate": "biolink:physically_interacts_with",
                   "object": key[1], "layer": "L1", "knowledge_level": "knowledge_assertion",
                   "agent_type": "automated_agent",
                   "primary_knowledge_source": "infores:string", "score": int(s) / 1000}
    print(f"  STRING: {len(seen)} edges >= {STRING_MIN}; {len(unmapped)} ENSP unmapped to NCBIGene")


def omnipath_edges(by_uniprot):
    path = RAW / "omnipath_interactions.tsv"
    if not path.exists():
        fetch("omnipath", "omnipath_interactions.tsv")
    else:
        log_source("omnipath", *SOURCES["omnipath"], path)
    agg = {}
    skipped = 0
    for r in read_tsv(path):
        s, o = by_uniprot.get(r["source"]), by_uniprot.get(r["target"])
        if not s or not o or s == o:
            skipped += 1
            continue
        directed = r["consensus_direction"] == "True"
        stim, inh = r["consensus_stimulation"] == "True", r["consensus_inhibition"] == "True"
        direction = "positive" if stim and not inh else "negative" if inh and not stim else ""
        if not directed:
            s, o = sorted((s, o))
        pm = sorted({x.split(":", 1)[1] for x in r["references"].split(";") if ":" in x})
        k = (s, o, direction, directed)
        e = agg.setdefault(k, {"subject": s, "object": o, "direction": direction,
                               "predicate": "biolink:regulates" if directed
                               else "biolink:interacts_with",
                               "layer": "L1", "knowledge_level": "knowledge_assertion",
                               "agent_type": "manual_agent",
                               "primary_knowledge_source": "infores:omnipath",
                               "pm": set(), "score": 0, "src": set()})
        e["pm"].update(pm)
        e["src"].update(r["sources"].split(";"))
        e["score"] = max(e["score"], int(r["curation_effort"] or 0))
    for e in agg.values():
        e["publications"] = ";".join(sorted(e.pop("pm"), key=int))
        e["qualifiers"] = dumps({"aggregated_sources": sorted(e.pop("src"))})
        yield e
    print(f"  OmniPath: {len(agg)} edges; {skipped} rows skipped (protein complexes, non-HGNC isoforms or self-loops)")


def reactome_edges(nodes, human_ids):
    """Human genes only: Reactome places viral proteins in human pathways (dropped, as VitaGraph
    dropped virus edges)."""
    ncbi = fetch("reactome_ncbi")
    dropped = 0
    names = {}
    with open_text(fetch("reactome_pathways")) as f:
        for line in f:
            pid, name, sp = line.rstrip("\n").split("\t")
            if sp == "Homo sapiens":
                names[pid] = name
    seen = set()
    with open_text(ncbi) as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 6 or p[5] != "Homo sapiens" or p[1] not in names:
                continue
            g, pw = "NCBIGene:" + p[0], "REACT:" + p[1]
            if g not in human_ids:
                dropped += 1
                continue
            if (g, pw) in seen:
                continue
            seen.add((g, pw))
            yield {"subject": g, "predicate": "biolink:participates_in", "object": pw,
                   "layer": "L1", "knowledge_level": "knowledge_assertion",
                   "agent_type": "manual_agent", "primary_knowledge_source": "infores:reactome",
                   "qualifiers": dumps({"evidence_code": p[4]})}
    used = {pw for _, pw in seen}
    for pid in used:
        nodes[pid] = {"id": pid, "category": "biolink:Pathway", "name": names[pid[6:]],
                      "taxon": "NCBITaxon:9606", "provided_by": "infores:reactome"}
    print(f"  Reactome: {len(seen)} gene-pathway edges, {len(used)} pathways; "
          f"{dropped} rows with non-HGNC (mostly viral) genes dropped")


def chembl_edges(nodes):
    con = db(KB_DB)
    n = 0
    for r in con.execute("SELECT * FROM chembl_activities"):
        cid = "CHEMBL.COMPOUND:" + r["molecule_chembl_id"]
        nodes[cid] = {"id": cid, "category": "biolink:SmallMolecule",
                      "name": (r["pref_name"] or r["molecule_chembl_id"]).lower(),
                      "provided_by": "infores:chembl",
                      "xrefs": ""}
        pm = r["evidence_pmids"] or "[]"
        yield {"subject": cid, "predicate": "biolink:directly_physically_interacts_with",
               "object": "NCBIGene:4835", "layer": "L1", "knowledge_level": "knowledge_assertion",
               "agent_type": "manual_agent", "primary_knowledge_source": "infores:chembl",
               "publications": ";".join(x.strip('" ') for x in pm.strip("[]").split(",") if x.strip()),
               "score": r["pchembl_median"],
               "qualifiers": dumps({"activity": r["relation"], "standard_type": r["standard_type"],
                                    "median_nM": r["median_nm"], "n_activities": r["n_acts"],
                                    "target": r["target_chembl_id"]})}
        n += 1
    print(f"  ChEMBL: {n} compound -> NQO2 edges (carried from v1 fetch)")


def go_features(by_uniprot):
    path = fetch("goa_human")
    rows, seen = [], set()
    with open_text(path) as f:
        for line in f:
            if line.startswith("!"):
                continue
            p = line.split("\t")
            if "NOT" in p[3] or p[0] != "UniProtKB":
                continue
            g = by_uniprot.get(p[1])
            if g and (g, p[4]) not in seen:
                seen.add((g, p[4]))
                rows.append({"ncbigene": g, "go_id": p[4], "aspect": p[8], "evidence": p[6]})
    write_tsv(INTERIM / "features_go.tsv", ["ncbigene", "go_id", "aspect", "evidence"], rows)
    print(f"  GO features: {len(rows)} gene-term pairs, {len({r['go_id'] for r in rows})} terms, "
          f"{len({r['ncbigene'] for r in rows})} genes")


def main():
    genes, by_sym, by_uniprot = human_maps()
    nodes = {}
    edges = []
    edges += list(string_edges(by_sym))
    edges += list(omnipath_edges(by_uniprot))
    edges += list(reactome_edges(nodes, {g['ncbigene'] for g in genes}))
    edges += list(chembl_edges(nodes))
    n = write_tsv(INTERIM / "l1_edges.tsv", EDGE_COLS, edges)
    write_tsv(INTERIM / "l1_nodes.tsv", ["id", "category", "name", "taxon", "xrefs", "provided_by"],
              nodes.values())
    go_features(by_uniprot)
    by_src = defaultdict(int)
    for e in edges:
        by_src[e["primary_knowledge_source"]] += 1
    print(f"P2: L1 edges {n} ({dict(by_src)}); extra nodes {len(nodes)}")


if __name__ == "__main__":
    main()
