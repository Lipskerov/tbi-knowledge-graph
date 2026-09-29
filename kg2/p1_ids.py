"""P1 — identifier backbone.

Primary gene ID = NCBIGene (what PubTator3, Reactome and MGI use); HGNC, UniProt, Ensembl, MGI
kept as xrefs. Human symbols resolve through HGNC current -> previous -> alias symbols, in that
order; an alias shared by >1 gene is ambiguous and left unmapped (never guessed).

Outputs
  interim/genes_human.tsv      ncbigene, hgnc, symbol, name, uniprot, ensembl
  interim/genes_mouse.tsv      ncbigene, mgi, symbol, human_ncbigene (ortholog)
  interim/symbol_map.tsv       every panel.db gene -> NCBIGene (or unmapped + reason)
"""
from collections import defaultdict

from common import INTERIM, PANEL_DB, db, fetch, open_text, write_tsv


def load_hgnc():
    path = fetch("hgnc")
    genes, cur, prev, alias = [], {}, defaultdict(set), defaultdict(set)
    with open_text(path) as f:
        head = f.readline().rstrip("\n").split("\t")
        ix = {c: i for i, c in enumerate(head)}
        for line in f:
            r = line.rstrip("\n").split("\t")
            g = lambda c: r[ix[c]].strip('"') if ix.get(c) is not None and ix[c] < len(r) else ""
            if g("status") != "Approved" or not g("entrez_id"):
                continue
            nid = "NCBIGene:" + g("entrez_id")
            genes.append({"ncbigene": nid, "hgnc": g("hgnc_id"), "symbol": g("symbol"),
                          "name": g("name"), "uniprot": g("uniprot_ids"),
                          "ensembl": g("ensembl_gene_id"), "locus_group": g("locus_group")})
            cur[g("symbol").upper()] = nid
            for s in filter(None, g("prev_symbol").split("|")):
                prev[s.upper()].add(nid)
            for s in filter(None, g("alias_symbol").split("|")):
                alias[s.upper()].add(nid)
    return genes, cur, prev, alias


def load_mgi():
    """HOM_MouseHumanSequence.rpt: rows grouped by 'DB Class Key' (homology class)."""
    path = fetch("mgi_hom")
    classes = defaultdict(lambda: {"human": [], "mouse": []})
    with open_text(path) as f:
        head = f.readline().rstrip("\n").split("\t")
        ix = {c: i for i, c in enumerate(head)}
        for line in f:
            r = line.rstrip("\n").split("\t")
            org = r[ix["Common Organism Name"]]
            key = r[ix["DB Class Key"]]
            rec = {"symbol": r[ix["Symbol"]], "ncbigene": "NCBIGene:" + r[ix["EntrezGene ID"]],
                   "mgi": r[ix["Mouse MGI ID"]] if "Mouse MGI ID" in ix else ""}
            if org.startswith("human"):
                classes[key]["human"].append(rec)
            elif org.startswith("mouse"):
                classes[key]["mouse"].append(rec)
    mouse = []
    for c in classes.values():
        # 1:1 orthologs only carry an ortholog link; 1:n / n:m kept as nodes without it
        hum = c["human"][0]["ncbigene"] if len(c["human"]) == 1 and len(c["mouse"]) == 1 else ""
        for m in c["mouse"]:
            mouse.append({**m, "human_ncbigene": hum,
                          "n_human": len(c["human"]), "n_mouse": len(c["mouse"])})
    return mouse


def resolve(sym, cur, prev, alias):
    s = sym.upper().strip()
    if s in cur:
        return cur[s], "symbol"
    if len(prev.get(s, ())) == 1:
        return next(iter(prev[s])), "previous_symbol"
    if len(alias.get(s, ())) == 1:
        return next(iter(alias[s])), "alias"
    if prev.get(s) or alias.get(s):
        return "", "ambiguous"
    return "", "not_found"


def main():
    genes, cur, prev, alias = load_hgnc()
    mouse = load_mgi()
    write_tsv(INTERIM / "genes_human.tsv",
              ["ncbigene", "hgnc", "symbol", "name", "uniprot", "ensembl", "locus_group"], genes)
    write_tsv(INTERIM / "genes_mouse.tsv",
              ["ncbigene", "mgi", "symbol", "human_ncbigene", "n_human", "n_mouse"], mouse)
    mouse_sym = {m["symbol"].upper(): m["ncbigene"] for m in mouse}

    con = db(PANEL_DB)
    rows, how_n = [], defaultdict(int)
    for gene, raw, species in con.execute("SELECT gene, raw_symbol, species_seen FROM proteins"):
        nid, how = resolve(gene, cur, prev, alias)
        mid = mouse_sym.get((raw or gene).upper(), "")
        how_n[how] += 1
        rows.append({"gene": gene, "species_seen": species, "human_ncbigene": nid,
                     "human_how": how, "mouse_ncbigene": mid})
    write_tsv(INTERIM / "symbol_map.tsv",
              ["gene", "species_seen", "human_ncbigene", "human_how", "mouse_ncbigene"], rows)
    n_1to1 = sum(1 for m in mouse if m["human_ncbigene"])
    print(f"P1: HGNC genes with NCBIGene {len(genes)}; mouse genes {len(mouse)} "
          f"({n_1to1} with 1:1 human ortholog)")
    print(f"P1: panel.db proteins {len(rows)} -> " + ", ".join(f"{k} {v}" for k, v in sorted(how_n.items())))
    print(f"P1: panel.db proteins with a mouse NCBIGene {sum(1 for r in rows if r['mouse_ncbigene'])}")


if __name__ == "__main__":
    main()
