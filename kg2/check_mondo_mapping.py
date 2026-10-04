"""Verify the MeSH -> MONDO disease xrefs three independent ways; writes mondo_mesh_check.tsv.

    python3 check_mondo_mapping.py        # after p5_integrate.py; network only to fill caches

For every MeSH disease node with a MONDO exact match in MONDO's SSSOM file:
  1. name     current MeSH label (NLM lookup API) against the MONDO label + synonyms (OLS),
              token Jaccard after plural folding; 1.0 = same name or a listed synonym
  2. DOID     does a Disease Ontology term that MONDO maps to carry this MeSH id as an xref?
  3. status   is the MONDO term obsolete (OLS)?
Weak and partial name matches were then reviewed by hand; the rejects live in
mondo_mesh_rejects.tsv with a reason each. Negative control: the same name score on shuffled
MeSH -> MONDO pairs, which must collapse.
"""
import json
import random
import re
import time
import urllib.request
from collections import defaultdict

from common import KG2, OUT, RAW, VERSION, read_tsv, write_tsv


def cached(path, keys, fetch_one):
    data = json.loads(path.read_text()) if path.exists() else {}
    for k in keys:
        if k not in data:
            try:
                data[k] = fetch_one(k)
            except Exception as e:  # noqa: BLE001 — recorded, never silently dropped
                data[k] = ["ERR " + str(e)[:60]]
            time.sleep(0.05)
    path.write_text(json.dumps(data))
    return data


def ols(mondo):
    url = f"https://www.ebi.ac.uk/ols4/api/ontologies/mondo/terms?obo_id={mondo}"
    t = json.load(urllib.request.urlopen(url, timeout=60))["_embedded"]["terms"][0]
    return [t.get("is_obsolete"), t.get("label") or "", t.get("synonyms") or []]


def mesh_label(uid):
    r = json.load(urllib.request.urlopen(f"https://id.nlm.nih.gov/mesh/lookup/label?resource={uid}", timeout=30))
    return r[0] if r else ""


def toks(s):
    w = re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split()
    def singular(x):  # injuries -> injury, diseases -> disease, glass stays
        if len(x) > 4 and x.endswith("ies"):
            return x[:-3] + "y"
        return x[:-1] if len(x) > 3 and x.endswith("s") and not x.endswith("ss") else x
    return frozenset(x for x in map(singular, w)
                     if x not in {"of", "the", "and", "disease", "disorder", "syndrome"})


def name_score(mesh, names):
    a = toks(mesh)
    return max((len(a & toks(n)) / len(a | toks(n)) for n in names if a | toks(n)), default=0.0)


def main():
    nodes = {n["id"]: n for n in read_tsv(OUT / VERSION / "nodes.tsv")
             if n["id"].startswith("MESH:") and n["category"] == "biolink:Disease"}
    m, mondo2doid = {}, defaultdict(set)
    for line in open(RAW / "mondo.sssom.tsv"):
        p = line.rstrip("\n").split("\t")
        if len(p) < 4 or p[2] != "skos:exactMatch":
            continue
        if p[3].startswith("mesh:") and "MESH:" + p[3][5:] in nodes:
            m["MESH:" + p[3][5:]] = p[0]
        elif p[3].startswith("DOID:"):
            mondo2doid[p[0]].add(p[3])
    curated = {r["mesh_id"]: r["mondo_id"] for r in read_tsv(KG2 / "mondo_mesh_additions.tsv")}
    m.update({k: v for k, v in curated.items() if k in nodes})
    doid_mesh, cur = defaultdict(set), None
    for line in open(RAW / "doid.obo"):
        line = line.strip()
        if line.startswith("id: DOID:"):
            cur = line[4:]
        elif line.startswith("xref: MESH:") and cur:
            doid_mesh[cur].add("MESH:" + line.split("MESH:")[1].split()[0])
    st = cached(RAW / "mondo_ols_full.json", sorted(set(m.values())), ols)
    labels = cached(RAW / "mesh_labels.json", [i.split(":")[1] for i in m], mesh_label)
    rejects = {r["mesh_id"]: r["reason"] for r in read_tsv(KG2 / "mondo_mesh_rejects.tsv")}

    rows = []
    for mesh, mondo in sorted(m.items()):
        obs, lab, syn = (st[mondo] + [None, "", []])[:3]
        failed = isinstance(obs, str) and obs.startswith("ERR")  # network error, not "obsolete"
        mlab = labels.get(mesh.split(":")[1], "")
        mlab = "" if isinstance(mlab, list) else mlab
        doids = mondo2doid.get(mondo, set())
        rows.append({
            "mesh_id": mesh, "mesh_label": mlab, "mondo_id": mondo, "mondo_label": lab,
            "name_match": round(name_score(mlab, [lab] + syn), 2),
            "doid_confirms": ("yes" if any(mesh in doid_mesh[d] for d in doids)
                              else "no" if any(doid_mesh[d] for d in doids) else "n/a"),
            "mondo_obsolete": obs,
            "decision": ("unverified: OLS lookup failed" if failed else
                         "reject: obsolete MONDO term" if obs else
                         "reject: " + rejects[mesh] if mesh in rejects else
                         "accept: curated (MONDO lacks the MeSH xref)" if mesh in curated else "accept")})
    write_tsv(KG2 / "mondo_mesh_check.tsv", list(rows[0].keys()), rows)

    acc = [r for r in rows if r["decision"].startswith("accept")]
    full = lambda rs: sum(r["name_match"] == 1.0 for r in rs)
    rng = random.Random(20260929)
    shuffled = [r["mondo_id"] for r in rows]
    rng.shuffle(shuffled)
    names = lambda mo: [(st[mo] + [None, "", []])[1]] + ((st[mo] + [None, "", []])[2] or [])
    shuf_full = sum(name_score(r["mesh_label"], names(s)) == 1.0 for r, s in zip(rows, shuffled))
    print(f"MeSH disease nodes {len(nodes)}; MONDO exact match {len(rows)}; accepted {len(acc)}; "
          f"rejected {len(rows) - len(acc)}")
    print(f"accepted: full name/synonym match {full(acc)}, DOID confirms "
          f"{sum(r['doid_confirms'] == 'yes' for r in acc)}, DOID disagrees "
          f"{sum(r['doid_confirms'] == 'no' for r in acc)}")
    print(f"negative control, shuffled pairs: full name match {shuf_full}/{len(rows)} "
          f"(real pairs {full(rows)}/{len(rows)})")


if __name__ == "__main__":
    main()
