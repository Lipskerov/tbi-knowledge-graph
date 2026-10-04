"""P7 — publishable release, split by licence (see LICENCES.md). Reads the working graph in
out/<v>/ and writes out/<v>/release/; the working graph, benchmark and validation sheets are untouched.

release/
  edges.tsv, edge_evidence.tsv, nodes.tsv, graph.nt   CC BY 4.0 (main dataset)
  noncommercial/                                       third-party, NON-COMMERCIAL use only
      OmniPath edges resting only on non-commercial resources + BIO-AX-TBI (paper CC BY-NC)
  chembl_cc-by-sa-3.0/                                 ChEMBL edges, CC BY-SA 3.0 (share alike)
  LICENSE.txt                                          licence and attribution notices

Also, in every file:
  * no abstract text: the evidence `sentence` column is dropped; the PMID stays
  * main-file OmniPath edges keep only PMIDs and resource names from commercially reusable
    resources (OmniPath's own per-resource licence flag), re-derived from the raw OmniPath rows
"""
import json
import shutil
from collections import defaultdict

from common import INTERIM, NODE_COLS, OUT, RAW, VERSION, dumps, fetch, read_tsv, write_tsv
from p5_integrate import PREFIX_IRI

REL = OUT / VERSION
DST = REL / "release"
NC_SOURCES = {"infores:extc_bioaxtbi": "CC BY-NC 4.0 (source article, PMID 39323289)"}
SA_SOURCES = {"infores:chembl": "CC BY-SA 3.0 (ChEMBL)"}

LICENSE_TXT = """TBI-BiomarkerKG {v} — licence

Main dataset (edges.tsv, edge_evidence.tsv, nodes.tsv, graph.nt): Creative Commons Attribution 4.0
International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/

Third-party data kept under its original licence:
  noncommercial/        NON-COMMERCIAL USE ONLY. Edges from resources licensed for non-commercial
                        use (per-edge licence in the `licence` column). Not covered by CC BY 4.0.
  chembl_cc-by-sa-3.0/  ChEMBL data, CC BY-SA 3.0, https://creativecommons.org/licenses/by-sa/3.0/
                        Derivatives of these files must be shared under the same licence.

Attribution (required by the sources):
  STRING (CC BY 4.0), MGI (CC BY 4.0), RGD rat orthologs (CC BY 4.0), MONDO disease xrefs
  (CC BY 4.0), Gene Ontology (CC BY 4.0), OmniPath and the resources it aggregates, Reactome (CC0),
  HGNC (CC0), PubTator3 / NCBI. The omics edges cite their source articles (PMIDs in the files). MeSH: courtesy of the U.S. National
  Library of Medicine; this release uses the MeSH version current at build time, does not reflect
  later updates, and is not endorsed by NLM. Abstract text is not redistributed; each literature
  edge cites its PMID.
"""


def omnipath_licences():
    res = json.loads(fetch("omnipath_resources", "omnipath_resources.json").read_text())
    lic = {k: v.get("license", {}) for k, v in res.items()}

    def get(name):
        return lic.get(name) or lic.get(name.split("_")[0]) or {}
    return get


def omnipath_open_refs(open_res):
    """(subject, object, direction, predicate) -> (open PMIDs, open resource names), from raw rows,
    keyed exactly as p2_reference.omnipath_edges builds the edge."""
    by_uniprot = {}
    for g in read_tsv(INTERIM / "genes_human.tsv"):
        for u in filter(None, g["uniprot"].split("|")):
            by_uniprot.setdefault(u, g["ncbigene"])
    out = defaultdict(lambda: (set(), set()))
    for r in read_tsv(RAW / "omnipath_interactions.tsv"):
        s, o = by_uniprot.get(r["source"]), by_uniprot.get(r["target"])
        if not s or not o or s == o:
            continue
        directed = r["consensus_direction"] == "True"
        stim, inh = r["consensus_stimulation"] == "True", r["consensus_inhibition"] == "True"
        direction = "positive" if stim and not inh else "negative" if inh and not stim else ""
        if not directed:
            s, o = sorted((s, o))
        pred = "biolink:regulates" if directed else "biolink:interacts_with"
        pm, srcs = out[(s, o, direction, pred)]
        srcs.update(x for x in r["sources"].split(";") if open_res(x))
        pm.update(x.split(":", 1)[1] for x in r["references"].split(";")
                  if ":" in x and open_res(x.split(":", 1)[0]))
    return out


def rat_orthologs(nodes, used):
    """RGD rat -> human 1:1 orthologs for the rat genes the release carries. Release-only: the
    benchmarked working graph is left unchanged. Kept only where the human NCBI gene is an HGNC
    gene whose own rgd_id record names the same rat gene (independent confirmation)."""
    hgnc = {h["entrez_id"]: h for h in read_tsv(RAW / "hgnc_complete_set.txt") if h["entrez_id"]}
    rat = {i.split(":")[1] for i in used if nodes.get(i, {}).get("taxon") == "NCBITaxon:10116"}
    human_rows = {g["ncbigene"]: g for g in read_tsv(INTERIM / "genes_human.tsv")}
    edges, new_nodes, added = [], [], set()
    with open(fetch("rgd_orthologs")) as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if line.startswith(("#", "RAT_GENE_SYMBOL")) or len(p) < 8 or p[2] not in rat or not p[7]:
                continue
            h = hgnc.get(p[7])
            if not h or p[1] not in {x.replace("RGD:", "") for x in h.get("rgd_id", "").split("|")}:
                continue
            human = "NCBIGene:" + p[7]
            if human not in nodes and human not in added:
                g = human_rows.get(human)
                if not g:
                    continue
                added.add(human)
                new_nodes.append({"id": human, "category": "biolink:Gene", "name": g["symbol"],
                                  "taxon": "NCBITaxon:9606", "provided_by": "infores:hgnc",
                                  "xrefs": g["hgnc"], "in_public_release": 1})
            edges.append({"subject": "NCBIGene:" + p[2], "predicate": "biolink:orthologous_to",
                          "object": human, "layer": "L1", "knowledge_level": "knowledge_assertion",
                          "agent_type": "not_provided", "primary_knowledge_source": "infores:rgd",
                          "n_evidence": 1})
    for i, e in enumerate(sorted(edges, key=lambda e: e["subject"])):
        e["id"] = f"TBIKG:r{i:06d}"
    return sorted(edges, key=lambda e: e["id"]), new_nodes


def main():
    if DST.exists():
        shutil.rmtree(DST)
    (DST / "noncommercial").mkdir(parents=True)
    (DST / "chembl_cc-by-sa-3.0").mkdir()
    lic = omnipath_licences()
    is_open = lambda name: lic(name).get("purpose") == "commercial"
    open_refs = omnipath_open_refs(is_open)

    edges = read_tsv(REL / "edges.tsv")
    cols = list(edges[0].keys())
    ev = read_tsv(REL / "edge_evidence.tsv")
    ev_by_edge = defaultdict(list)
    for r in ev:
        ev_by_edge[r["edge_id"]].append(r)
    main_e, nc_e, sa_e = [], [], []
    for e in edges:
        src = e["primary_knowledge_source"]
        if src in SA_SOURCES:
            sa_e.append(dict(e, licence=SA_SOURCES[src]))
        elif src in NC_SOURCES:
            # L2 merges identical findings into one edge; if an openly licensed study also
            # reports it, the edge is released under that study and only the NC rows stay NC
            open_ev = [r for r in ev_by_edge[e["id"]] if r["source"] not in NC_SOURCES]
            if open_ev:
                pm = sorted({r["pmid"] for r in open_ev if r["pmid"]}, key=int)
                main_e.append(dict(e, primary_knowledge_source=open_ev[0]["source"],
                                   publications=";".join(pm), n_evidence=len(open_ev)))
            else:
                nc_e.append(dict(e, licence=NC_SOURCES[src]))
        elif src == "infores:omnipath":
            q = json.loads(e["qualifiers"] or "{}")
            agg = q.get("aggregated_sources", [])
            if not any(is_open(s) for s in agg):
                names = sorted({f"{lic(s).get('name', '?')} ({s.split('_')[0]})" for s in agg})
                nc_e.append(dict(e, licence="; ".join(names)))
                continue
            pm, srcs = open_refs[(e["subject"], e["object"], e["direction"], e["predicate"])]
            q["aggregated_sources"] = sorted(srcs)
            main_e.append(dict(e, qualifiers=dumps(q),
                               publications=";".join(sorted(pm, key=int))))
        else:
            main_e.append(e)

    where = {e["id"]: "main" for e in main_e} | {e["id"]: "nc" for e in nc_e} | {e["id"]: "sa" for e in sa_e}
    ev_cols = [c for c in ev[0].keys() if c != "sentence"]
    ev_split = defaultdict(list)
    for r in ev:  # an NC study's rows always go to the NC file, whichever file holds the edge
        dest = "nc" if r["source"] in NC_SOURCES else where[r["edge_id"]]
        ev_split[dest].append({k: r[k] for k in ev_cols})

    # KGX TSV convention: multivalued fields are '|'-separated CURIEs
    for e in main_e + nc_e + sa_e:
        e["publications"] = "|".join(f"PMID:{p}" for p in (e.get("publications") or "").split(";") if p)
    write_tsv(DST / "edge_evidence.tsv", ev_cols, ev_split["main"])
    write_tsv(DST / "noncommercial" / "edges.tsv", cols + ["licence"], nc_e)
    write_tsv(DST / "noncommercial" / "edge_evidence.tsv", ev_cols, ev_split["nc"])
    write_tsv(DST / "chembl_cc-by-sa-3.0" / "edges.tsv", cols + ["licence"], sa_e)
    nodes = {n["id"]: n for n in read_tsv(REL / "nodes.tsv")}
    used = {x for e in main_e + nc_e + sa_e for x in (e["subject"], e["object"])}
    rat_e, rat_n = rat_orthologs(nodes, used)
    main_e += rat_e
    write_tsv(DST / "edges.tsv", cols, main_e)
    write_tsv(DST / "nodes.tsv", NODE_COLS, list(nodes.values()) + rat_n)
    main_ids = {e["id"] for e in main_e}
    iri = lambda c: f"<{PREFIX_IRI[c.split(':', 1)[0]]}{c.split(':', 1)[1]}>"
    with open(REL / "graph.nt") as fin, open(DST / "graph.nt", "w") as fout:
        for e, line in zip(edges, fin):  # graph.nt is written in edges.tsv order
            if e["id"] in main_ids:
                fout.write(line)
        for e in rat_e:
            fout.write(f"{iri(e['subject'])} {iri(e['predicate'])} {iri(e['object'])} .\n")
    (DST / "LICENSE.txt").write_text(LICENSE_TXT.format(v=VERSION))
    (DST / "noncommercial" / "LICENSE.txt").write_text(
        "NON-COMMERCIAL USE ONLY. Third-party data under its original licences, listed per edge in the "
        "`licence` column. Not covered by the CC BY 4.0 licence of the main dataset.\n")
    (DST / "chembl_cc-by-sa-3.0" / "LICENSE.txt").write_text(
        "ChEMBL data, CC BY-SA 3.0 Unported (https://creativecommons.org/licenses/by-sa/3.0/). "
        "Share alike: derivatives must carry the same licence.\n")

    # checks: nothing lost, nothing duplicated, no abstract text anywhere in the release
    assert len(main_e) - len(rat_e) + len(nc_e) + len(sa_e) == len(edges), "edge count does not add up"
    assert len(where) == len(edges), "an edge landed in two files"
    assert sum(len(v) for v in ev_split.values()) == len(ev), "evidence rows lost"
    for path in DST.rglob("*.tsv"):
        with open(path) as f:
            assert "sentence" not in f.readline().split("\t"), f"sentence column in {path}"
    print(f"P7: release {VERSION}: main {len(main_e)} edges (CC BY 4.0, incl. {len(rat_e)} RGD rat orthologs, "
          f"{len(rat_n)} human nodes added), non-commercial {len(nc_e)}, "
          f"ChEMBL CC BY-SA {len(sa_e)}; evidence main {len(ev_split['main'])}, "
          f"non-commercial {len(ev_split['nc'])}; sentence text removed from {sum(1 for r in ev if r['sentence'])} rows")


if __name__ == "__main__":
    main()
