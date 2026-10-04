"""P6d — automated V3 audit of the L1 and L2 rows: is each sampled edge in the source file it cites?

    python3 p6_v3_auto.py      # -> curation/V3_auto_L1L2.tsv (read by p6_score.py)

Independent of the build: IDs are mapped from the raw HGNC and MGI files, not from interim/, and
each source file is re-read here, so a mapping or parsing bug in P1-P3 shows up as "no".
  STRING     the gene pair at combined score >= 700 in the v12 physical file (either order)
  OmniPath   a row joining the two proteins; for 'regulates' the same direction and sign, and every
             PMID on the edge present in that row's references
  Reactome   the (NCBI gene, human pathway) row in NCBI2Reactome
  MGI        mouse and human gene in one homology class
  Mantash    a mantash_mouse_de row for the mouse gene, same direction, padj < 0.05
  cohorts    a dataset_evidence row for the gene in that dataset, same direction
L2 is checked against panel.db, the curated transcription of each paper; whether panel.db matches
the paper itself is not re-checked here.

Negative control: every edge is re-checked with its object swapped for another sampled edge's
object of the same source; the share of swapped edges that still pass is the false-pass rate.
"""
import gzip
import random
import sqlite3
from collections import defaultdict

from openpyxl import load_workbook

from common import CURATION, PANEL_DB, RAW, read_tsv, write_tsv

SEED = 20260929
STRING_MIN = 700


def hgnc():
    """entrez -> (all symbols upper, uniprot ids)."""
    out = {}
    for r in read_tsv(RAW / "hgnc_complete_set.txt"):
        if r["entrez_id"]:
            syms = {r["symbol"].upper()} | {s.upper() for f in ("prev_symbol", "alias_symbol")
                                            for s in r[f].split("|") if s}
            out[r["entrez_id"]] = (r["symbol"].upper(), syms, set(filter(None, r["uniprot_ids"].split("|"))))
    return out


def mgi():
    """entrez -> (class key, symbol) for mouse and human rows of the MGI homology report."""
    out = {}
    for r in read_tsv(RAW / "HOM_MouseHumanSequence.rpt"):
        out[r["EntrezGene ID"]] = (r["DB Class Key"], r["Symbol"].upper(), r["NCBI Taxon ID"])
    return out


def nid(curie):
    return curie.split(":", 1)[1]


class Checker:
    def __init__(self, rows):
        self.H, self.M = hgnc(), mgi()
        need = {nid(r[c]) for r in rows for c in ("subject_id", "object_id") if r[c].startswith("NCBIGene:")}
        self.string = self._string({self.H[g][0] for g in need if g in self.H})
        self.omni = [r for r in read_tsv(RAW / "omnipath_interactions.tsv")]
        self.reactome = set()
        with open(RAW / "NCBI2Reactome.txt") as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 6 and p[5] == "Homo sapiens":
                    self.reactome.add((p[0], p[1]))
        self.con = sqlite3.connect(f"file:{PANEL_DB}?mode=ro", uri=True)

    def _string(self, syms):
        ensp = {}
        with gzip.open(RAW / "9606.protein.info.v12.0.txt.gz", "rt") as f:
            next(f)
            for line in f:
                e, name = line.split("\t")[:2]
                if name.upper() in syms:
                    ensp[e] = name.upper()
        pairs = {}
        with gzip.open(RAW / "9606.protein.physical.links.v12.0.txt.gz", "rt") as f:
            next(f)
            for line in f:
                a, b, s = line.split()
                if a in ensp and b in ensp:
                    k = frozenset((ensp[a], ensp[b]))
                    pairs[k] = max(pairs.get(k, 0), int(s))
        return pairs

    def check(self, e):
        """-> (verdict, evidence). verdict: yes / no / cannot_check."""
        src, s, o = e["source"], nid(e["subject_id"]), nid(e["object_id"])
        if src == "infores:string":
            if s not in self.H or o not in self.H:
                return "cannot_check", "gene not in HGNC"
            score = self.string.get(frozenset((self.H[s][0], self.H[o][0])), 0)
            return ("yes" if score >= STRING_MIN else "no"), f"STRING v12 physical score {score}"
        if src == "infores:omnipath":
            if s not in self.H or o not in self.H:
                return "cannot_check", "gene not in HGNC"
            us, uo = self.H[s][2], self.H[o][2]
            pm = set(filter(None, (e["publications"] or "").split(";")))
            hits = [r for r in self.omni if (r["source"] in us and r["target"] in uo)
                    or (r["source"] in uo and r["target"] in us)]
            match = []
            for r in hits:
                if e["predicate"] == "biolink:regulates":
                    stim, inh = r["consensus_stimulation"] == "True", r["consensus_inhibition"] == "True"
                    sign = "positive" if stim and not inh else "negative" if inh and not stim else ""
                    if not (r["source"] in us and r["consensus_direction"] == "True" and sign == e["direction"]):
                        continue
                elif r["consensus_direction"] == "True":
                    continue  # interacts_with is built only from undirected rows
                match.append(r)
            refs = {x.split(":", 1)[1] for r in match for x in r["references"].split(";") if ":" in x}
            if match and pm <= refs:
                return "yes", f"OmniPath {len(match)} matching row(s), {len(pm)} PMIDs found"
            return "no", f"OmniPath: {len(hits)} rows for pair, {len(match)} matching, PMIDs missing {len(pm - refs)}"
        if src == "infores:reactome":
            return ("yes" if (s, nid(e["object_id"])) in self.reactome else "no"), "NCBI2Reactome"
        if src == "infores:mgi":
            a, b = self.M.get(s), self.M.get(o)
            if not a or not b:
                return "no", "gene missing from HOM report"
            return ("yes" if a[0] == b[0] and {a[2], b[2]} == {"10090", "9606"} else "no"), f"class {a[0]} vs {b[0]}"
        up = e["direction"] == "increased"
        if src == "infores:mantash2025":
            m = self.M.get(s)
            if not m or m[2] != "10090":
                return "cannot_check", "mouse gene not in HOM report"
            rows = self.con.execute("""SELECT direction, padj FROM measurements WHERE dataset_id='mantash_mouse_de'
                                       AND upper(coalesce(raw_symbol, gene))=?""", (m[1],)).fetchall()
            good = [r for r in rows if r[0] == ("up" if up else "down") and r[1] is not None and r[1] < 0.05]
            return ("yes" if good else "no"), f"{len(good)}/{len(rows)} rows same direction, padj<0.05"
        if src.startswith("infores:extc_"):
            if s not in self.H:
                return "cannot_check", "gene not in HGNC"
            ds = {d.lower(): d for (d,) in self.con.execute("SELECT DISTINCT dataset_id FROM dataset_evidence")}
            d = ds.get(src.split(":", 1)[1])
            if not d:
                return "cannot_check", "dataset not in panel.db"
            syms = self.H[s][1]
            rows = [r for r in self.con.execute("SELECT gene, direction FROM dataset_evidence WHERE dataset_id=?", (d,))
                    if (r[0] or "").upper() in syms]
            good = [r for r in rows if r[1] == ("up" if up else "down")]
            return ("yes" if good else "no"), f"{len(good)}/{len(rows)} rows in {d} same direction"
        return "cannot_check", f"no checker for {src}"


def main():
    ws = load_workbook(CURATION / "V3_edge_audit.xlsx", read_only=True)["edges"]
    rows = list(ws.values)
    head = rows[0]
    edges = [{k: ("" if v is None else str(v)) for k, v in zip(head, r)} for r in rows[1:]]
    edges = [e for e in edges if e["layer"] in ("L1", "L2")]
    C = Checker(edges)
    out = []
    for e in edges:
        v, ev = C.check(e)
        out.append({"edge_id": e["edge_id"], "layer": e["layer"], "source": e["source"],
                    "subject": e["subject"], "predicate": e["predicate"], "object": e["object"],
                    "auto_supported": v, "evidence": ev})
    write_tsv(CURATION / "V3_auto_L1L2.tsv",
              ["edge_id", "layer", "source", "subject", "predicate", "object", "auto_supported", "evidence"], out)

    # negative controls. L1: object swapped for another sampled edge's object of the same source
    # (MGI: a random human gene). L2 (object is always the condition node): subject swapped for a
    # random gene of the same species, and separately the direction flipped.
    rng = random.Random(SEED)
    human_genes = sorted(g for g in C.H)
    mouse_genes = sorted(g for g, v in C.M.items() if v[2] == "10090")
    by_src = defaultdict(list)
    for e in edges:
        by_src[e["source"]].append(e)
    neg, flip = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for src, es in by_src.items():
        objs = sorted({e["object_id"] for e in es})
        for e in es:
            if e["layer"] == "L1":
                pool = ["NCBIGene:" + g for g in human_genes] if src == "infores:mgi" else objs
                fake = dict(e, object_id=rng.choice([x for x in pool if x != e["object_id"]]))
            else:
                pool = mouse_genes if src == "infores:mantash2025" else human_genes
                fake = dict(e, subject_id="NCBIGene:" + rng.choice(pool))
                v, _ = C.check(dict(e, direction="decreased" if e["direction"] == "increased" else "increased"))
                if v != "cannot_check":
                    flip[src][0] += v == "yes"
                    flip[src][1] += 1
            v, _ = C.check(fake)
            if v != "cannot_check":
                neg[src][0] += v == "yes"
                neg[src][1] += 1

    tally = defaultdict(lambda: defaultdict(int))
    for r in out:
        tally[r["source"]][r["auto_supported"]] += 1
    print(f"{'source':<32}{'yes':>5}{'no':>5}{'n/a':>5}   swapped passing   flipped passing")
    for src in sorted(tally):
        t = tally[src]
        fp, n = neg[src]
        ff, nf = flip[src]
        print(f"{src:<32}{t['yes']:>5}{t['no']:>5}{t['cannot_check']:>5}   {fp:>5}/{n:<10} {ff:>3}/{nf}" if nf
              else f"{src:<32}{t['yes']:>5}{t['no']:>5}{t['cannot_check']:>5}   {fp:>5}/{n:<10}   -")
    print(f"P6d: {len(out)} L1/L2 edges -> {CURATION / 'V3_auto_L1L2.tsv'}")


if __name__ == "__main__":
    main()
