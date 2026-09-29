"""P5 — integrate L1-L3 into one graph, attach features, run QC, export.

Release files (out/<VERSION>/)
  nodes.tsv, edges.tsv            KGX-style TSV (public layers only)
  edge_evidence.tsv               one row per supporting paper / dataset row
  graph.nt                        N-Triples (edges only, Biolink predicates)
  features/go.tsv, features/protein_annotations.tsv
  private/edges.tsv, private/edge_evidence.tsv   unpublished lab data — NOT for release
  stats.json, QC.md
"""
import json
import re
import shutil
import urllib.request
from collections import Counter, defaultdict

import networkx as nx

from common import (EDGE_COLS, EVID_COLS, INTERIM, KB_DB, NODE_COLS, OUT, PANEL_DB, RAW,
                    VERSION, db, dumps, read_tsv, write_tsv)

REL = OUT / VERSION
PREFIX_IRI = {
    "NCBIGene": "http://identifiers.org/ncbigene/",
    "MESH": "http://id.nlm.nih.gov/mesh/",
    "REACT": "https://reactome.org/content/detail/",
    "CHEMBL.COMPOUND": "http://identifiers.org/chembl.compound/",
    "TBIKG": "https://github.com/Lipskerov/tbi-knowledge-graph/kg2#",
    "biolink": "https://w3id.org/biolink/vocab/",
}
FIXED_NAMES = {"MESH:D000070642": ("biolink:Disease", "Brain Injuries, Traumatic"),
               "MESH:D001924": ("biolink:Disease", "Brain Concussion"),
               "MESH:D038223": ("biolink:Disease", "Post-Concussion Syndrome")}


def pub_years(pmids):
    """Year per PMID: KB first, then NCBI esummary (cached)."""
    years = {}
    con = db(KB_DB)
    for pmid, y in con.execute("SELECT pmid, year FROM papers"):
        years[pmid] = str(y or "")
    cache = RAW / "esummary_years.json"
    cached = json.loads(cache.read_text()) if cache.exists() else {}
    need = [p for p in pmids if p and p not in years and p not in cached]
    for i in range(0, len(need), 200):
        url = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id="
               + ",".join(need[i:i + 200]))
        res = json.loads(urllib.request.urlopen(url, timeout=60).read())["result"]
        for p in need[i:i + 200]:
            cached[p] = (res.get(p, {}).get("pubdate") or "")[:4]
    cache.write_text(json.dumps(cached))
    years.update(cached)
    return years


def fill_gene_taxa(nodes):
    """NCBI Gene esummary for gene nodes with no taxon (non-human/mouse PubTator3 genes)."""
    cache = RAW / "esummary_gene_taxa.json"
    cached = json.loads(cache.read_text()) if cache.exists() else {}
    ids = [n["id"].split(":")[1] for n in nodes.values()
           if n["category"] == "biolink:Gene" and not n.get("taxon")]
    need = [i for i in ids if i not in cached]
    for i in range(0, len(need), 200):
        url = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=gene&retmode=json&id="
               + ",".join(need[i:i + 200]))
        res = json.loads(urllib.request.urlopen(url, timeout=60).read())["result"]
        for g in need[i:i + 200]:
            r = res.get(g, {})
            cached[g] = [str((r.get("organism") or {}).get("taxid", "")), r.get("name", "")]
    cache.write_text(json.dumps(cached))
    for n in nodes.values():
        if n["category"] == "biolink:Gene" and not n.get("taxon"):
            tax, sym = cached.get(n["id"].split(":")[1], ["", ""])
            n["taxon"] = f"NCBITaxon:{tax}" if tax else ""


def build_nodes():
    nodes = {}
    for g in read_tsv(INTERIM / "genes_human.tsv"):
        nodes[g["ncbigene"]] = {
            "id": g["ncbigene"], "category": "biolink:Gene", "name": g["symbol"],
            "taxon": "NCBITaxon:9606", "provided_by": "infores:hgnc",
            "xrefs": "|".join(filter(None, [g["hgnc"]] + ["UniProtKB:" + u for u in g["uniprot"].split("|") if u]
                                         + (["ENSEMBL:" + g["ensembl"]] if g["ensembl"] else [])))}
    for m in read_tsv(INTERIM / "genes_mouse.tsv"):
        nodes.setdefault(m["ncbigene"], {"id": m["ncbigene"], "category": "biolink:Gene",
                                         "name": m["symbol"], "taxon": "NCBITaxon:10090",
                                         "provided_by": "infores:mgi", "xrefs": m["mgi"]})
    for f in ("l1_nodes.tsv", "l2_nodes.tsv", "l3_nodes.tsv"):
        for n in read_tsv(INTERIM / f):
            nodes.setdefault(n["id"], n)
    fill_gene_taxa(nodes)
    for k, (c, name) in FIXED_NAMES.items():
        nodes.setdefault(k, {"id": k, "category": c, "name": name, "provided_by": "infores:mesh"})
    return nodes


def main():
    if REL.exists():
        shutil.rmtree(REL)
    (REL / "features").mkdir(parents=True)
    (REL / "private").mkdir()
    nodes = build_nodes()

    edges, evidence, private_e, private_ev = [], [], [], []
    l1 = read_tsv(INTERIM / "l1_edges.tsv")
    for e in l1:
        pubs = [p for p in e["publications"].split(";") if p]
        edges.append({**e, "n_evidence": max(len(pubs), 1)})

    # 1:1 mouse->human orthologs, only for mouse genes that carry an edge
    l2 = read_tsv(INTERIM / "l2_edges.tsv")
    l3 = read_tsv(INTERIM / "l3_edges.tsv")
    ev2 = defaultdict(list)
    for r in read_tsv(INTERIM / "l2_evidence.tsv"):
        ev2[r["key"]].append(r)
    ev3 = defaultdict(list)
    for r in read_tsv(INTERIM / "l3_evidence.tsv"):
        ev3[r["key"]].append(r)
    years = pub_years(sorted({r["pmid"] for rs in list(ev2.values()) + list(ev3.values())
                              for r in rs if r.get("pmid")}))

    index = {(e["subject"], e["predicate"], e["object"], e.get("direction", "")): e for e in edges}
    merged = 0
    layer_of = lambda r, e: e["layer"]
    for layer_edges, ev_map in ((l2, ev2), (l3, ev3)):
        for e in layer_edges:
            evs = ev_map[e["key"]]
            pm = sorted({r["pmid"] for r in evs if r.get("pmid")}, key=int)
            ys = [int(years[p]) for p in pm if years.get(p, "").isdigit()]
            row = {**e, "n_evidence": len(evs), "publications": ";".join(pm),
                   "first_year": min(ys) if ys else "",
                   "score": max((float(r["extractor_score"]) for r in evs if r.get("extractor_score")),
                                default="")}
            k4 = (e["subject"], e["predicate"], e["object"], e.get("direction", ""))
            if e.get("public", "1") != "0" and k4 in index:  # same assertion from another layer
                base = index[k4]
                q = json.loads(base.get("qualifiers") or "{}")
                q.setdefault("also_supported_by", []).append(e["primary_knowledge_source"])
                base["qualifiers"] = dumps(q)
                base["n_evidence"] = int(base["n_evidence"]) + len(evs)
                base["publications"] = ";".join(sorted(set(filter(None, (base.get("publications") or "").split(";"))) | set(pm), key=int))
                e["key"] = base.setdefault("key", "|".join(k4))
                evidence += [{**r, "edge_id": e["key"], "layer": e_layer, "year": r.get("year") or years.get(r.get("pmid", ""), "")}
                             for r in evs for e_layer in [layer_of(r, e)]]
                merged += 1
                continue
            if e.get("public", "1") == "0":
                private_e.append(row)
                private_ev += [{**r, "edge_id": e["key"], "layer": "L2",
                                "year": years.get(r.get("pmid", ""), "")} for r in evs]
            else:
                edges.append(row)
                index[k4] = row
                evidence += [{**r, "edge_id": e["key"], "layer": e["layer"],
                              "year": r.get("year") or years.get(r.get("pmid", ""), "")} for r in evs]

    used = {x for e in edges for x in (e["subject"], e["object"])}
    orth = 0
    for m in read_tsv(INTERIM / "genes_mouse.tsv"):
        if m["ncbigene"] in used and m["human_ncbigene"]:
            edges.append({"subject": m["ncbigene"], "predicate": "biolink:orthologous_to",
                          "object": m["human_ncbigene"], "layer": "L1",
                          "knowledge_level": "knowledge_assertion", "agent_type": "manual_agent",
                          "primary_knowledge_source": "infores:mgi", "n_evidence": 1})
            orth += 1

    # ---- QC -----------------------------------------------------------------------------
    qc = []
    used = {x for e in edges for x in (e["subject"], e["object"])}
    missing = sorted(used - set(nodes))
    qc.append(("every edge endpoint is a node", not missing, f"{len(missing)} missing"))
    for mid in missing:  # species other than human/mouse (e.g. rat genes from PubTator3)
        cat = "biolink:Gene" if mid.startswith("NCBIGene:") else "biolink:NamedThing"
        nodes[mid] = {"id": mid, "category": cat, "name": mid, "provided_by": "infores:pubtator3"}
    keys = Counter((e["subject"], e["predicate"], e["object"], e.get("direction", "")) for e in edges)
    dup = sum(v - 1 for v in keys.values() if v > 1)
    qc.append(("no duplicate (s,p,o,direction)", dup == 0, f"{dup} duplicates"))
    selfl = sum(e["subject"] == e["object"] for e in edges)
    qc.append(("no self-loops", selfl == 0, f"{selfl}"))
    undirected = {"biolink:physically_interacts_with", "biolink:interacts_with"}
    rev = sum(1 for e in edges if e["predicate"] in undirected and e["layer"] == "L1"
              and e["subject"] > e["object"])
    qc.append(("undirected L1 edges stored as sorted pair", rev == 0, f"{rev} unsorted"))
    bad = [n for n in used if n.split(":")[0] not in PREFIX_IRI]
    qc.append(("all CURIE prefixes registered", not bad, f"{len(bad)} bad: {bad[:5]}"))
    semi = [n for n in used if ";" in n or "|" in n]
    qc.append(("no merged (;/|) node IDs", not semi, f"{len(semi)}"))
    noid = [e for e in edges if not e.get("primary_knowledge_source")]
    qc.append(("every edge has a primary knowledge source", not noid, f"{len(noid)}"))
    l3_nosent = sum(1 for r in evidence if r["layer"] == "L3" and not r.get("sentence"))
    n_l3 = sum(1 for r in evidence if r["layer"] == "L3")
    qc.append(("L3 evidence with a co-mention sentence (reported, not gated)", True,
               f"{n_l3 - l3_nosent}/{n_l3}"))

    # ---- write --------------------------------------------------------------------------
    used = {x for e in edges for x in (e["subject"], e["object"])}
    for i, e in enumerate(edges):
        e["id"] = f"TBIKG:e{i:07d}"
    kid = {e.get("key"): e["id"] for e in edges if e.get("key")}
    for r in evidence:
        r["edge_id"] = kid[r["edge_id"]]
    out_nodes = [dict(n, in_public_release=1) for k, n in nodes.items() if k in used]
    write_tsv(REL / "nodes.tsv", NODE_COLS, sorted(out_nodes, key=lambda n: n["id"]))
    write_tsv(REL / "edges.tsv", EDGE_COLS, edges)
    write_tsv(REL / "edge_evidence.tsv", EVID_COLS, evidence)
    write_tsv(REL / "private" / "edges.tsv", EDGE_COLS + ["key"], private_e)
    write_tsv(REL / "private" / "edge_evidence.tsv", EVID_COLS, private_ev)

    def iri(c):
        p, l = c.split(":", 1)
        return f"<{PREFIX_IRI[p]}{l}>"
    with open(REL / "graph.nt", "w") as f:
        for e in edges:
            f.write(f"{iri(e['subject'])} {iri(e['predicate'])} {iri(e['object'])} .\n")

    shutil.copy(INTERIM / "features_go.tsv", REL / "features" / "go.tsv")
    sym2id = {r["gene"]: r["human_ncbigene"] for r in read_tsv(INTERIM / "symbol_map.tsv")
              if r["human_ncbigene"]}
    ann = []
    for r in db(PANEL_DB).execute("SELECT gene, category, metric_key, value_num, value_text, "
                                  "source_id FROM annotations"):
        if r["gene"] in sym2id:
            ann.append({"ncbigene": sym2id[r["gene"]], **{k: r[k] for k in r.keys() if k != "gene"}})
    write_tsv(REL / "features" / "protein_annotations.tsv",
              ["ncbigene", "category", "metric_key", "value_num", "value_text", "source_id"], ann)

    # ---- stats --------------------------------------------------------------------------
    G = nx.Graph()
    G.add_edges_from((e["subject"], e["object"]) for e in edges)
    comps = sorted((len(c) for c in nx.connected_components(G)), reverse=True)
    stats = {
        "version": VERSION,
        "nodes": len(out_nodes), "edges": len(edges), "evidence_rows": len(evidence),
        "private_edges": len(private_e), "ortholog_edges": orth,
        "cross_layer_merges": merged,
        "nodes_by_category": Counter(n["category"] for n in out_nodes),
        "gene_nodes_by_taxon": Counter(n.get("taxon") or "unknown" for n in out_nodes
                                       if n["category"] == "biolink:Gene"),
        "edges_by_layer": Counter(e["layer"] for e in edges),
        "edges_by_source": Counter(e["primary_knowledge_source"] for e in edges),
        "edges_by_predicate": Counter(e["predicate"] for e in edges),
        "largest_component": comps[0], "n_components": len(comps),
        "features": {"go_pairs": sum(1 for _ in open(REL / "features" / "go.tsv")) - 1,
                     "protein_annotations": len(ann)},
    }
    (REL / "stats.json").write_text(json.dumps(stats, indent=1, default=dict))
    lines = [f"# QC — TBI-BiomarkerKG {VERSION}\n", "| Check | Pass | Detail |", "| --- | --- | --- |"]
    lines += [f"| {c} | {'PASS' if ok else 'FAIL'} | {d} |" for c, ok, d in qc]
    (REL / "QC.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({k: v for k, v in stats.items() if k != "edges_by_predicate"}, indent=1, default=dict))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
