"""P2b — L1 curated reference layer AS OF 2020, for a leakage-free time-split benchmark.

  STRING v11.0 (Jan 2019)  the physical subnetwork only exists from v11.5 (2021). We keep the
                           `experimental` channel >= 700 (44,107 edges; 63% of them are also in
                           v12 physical >= 700). Rejected, measured 29.09 BEFORE any model run:
                           experimental+database combined >= 700 (337,477 edges) or >= 900 (305,773;
                           15% in v12 physical) — the database channel adds functional
                           co-membership, a different network type. No text mining in L1.
  Reactome                 archived releases are not downloadable (S3 AccessDenied, 2026-09-29);
                           keep gene->pathway edges only for pathways whose first `releaseDate`
                           (Reactome ContentService) is <= 2020-12-31. Caveat: genes added to an
                           old pathway after 2020 are still included.
  OmniPath                 no dated snapshot; keep an interaction only if >= 1 supporting PMID is
                           published <= 2020 (years from NCBI esummary, cached).
  ChEMBL                   same PMID-year rule.
  Orthologs (MGI)          added in P5 as before (orthology is not TBI knowledge).

Output: interim/l1_edges_2020.tsv (same columns as l1_edges.tsv)
"""
import json
import time
import urllib.request
from collections import defaultdict

from common import INTERIM, RAW, dumps, log_source, open_text, read_tsv, write_tsv
from p1_ids import load_hgnc, resolve
from p2_reference import EDGE_COLS

CUTOFF = 2020
PRIOR = 0.041
S11 = "https://stringdb-downloads.org/download/stream/"
URLS = {
    "string11_links": S11 + "protein.links.detailed.v11.0/9606.protein.links.detailed.v11.0.txt.gz",
    "string11_info": S11 + "protein.info.v11.0/9606.protein.info.v11.0.txt.gz",
}


def get(key):
    url = URLS[key]
    path = RAW / url.rsplit("/", 1)[-1]
    if not path.exists() or path.stat().st_size == 0:
        print(f"  downloading {key}")
        req = urllib.request.Request(url, headers={"User-Agent": "tbi-kg2/2.0 (academic)"})
        with urllib.request.urlopen(req, timeout=900) as r, open(path, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        log_source(key, url, "CC BY 4.0", path)
    return path


def combine(*scores):
    """STRING channel combination: remove prior, combine as independent, add prior back."""
    p = 1.0
    for s in scores:
        s = s / 1000
        s = max(0.0, (s - PRIOR) / (1 - PRIOR))
        p *= 1 - s
    c = 1 - p
    return c + PRIOR * (1 - c)


def pmid_years(pmids):
    cache = RAW / "esummary_years.json"
    years = json.loads(cache.read_text()) if cache.exists() else {}
    need = sorted(p for p in pmids if p.isdigit() and p not in years)
    print(f"  esummary: {len(need)} PMIDs to fetch ({len(years)} cached)")
    for i in range(0, len(need), 200):
        chunk = need[i:i + 200]
        data = ("db=pubmed&retmode=json&id=" + ",".join(chunk)).encode()
        for attempt in range(4):
            try:
                req = urllib.request.Request("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                                             data=data)
                res = json.loads(urllib.request.urlopen(req, timeout=120).read())["result"]
                break
            except Exception as e:  # noqa: BLE001 — retry transient errors, fail loud at the end
                if attempt == 3:
                    raise RuntimeError(f"esummary chunk {i} failed: {e}") from e
                time.sleep(3 * (attempt + 1))
        for p in chunk:
            years[p] = (res.get(p, {}).get("pubdate") or "")[:4]
        if i % 10000 == 0:
            cache.write_text(json.dumps(years))
        time.sleep(0.35)
    cache.write_text(json.dumps(years))
    return years


def string_2020(cur, prev, alias):
    ensp2sym = {}
    with open_text(get("string11_info")) as f:
        next(f)
        for line in f:
            p = line.split("\t")
            ensp2sym[p[0]] = p[1]
    seen, n_unmapped = {}, 0
    with open_text(get("string11_links")) as f:
        head = f.readline().split()
        ix = {c: i for i, c in enumerate(head)}
        for line in f:
            p = line.split()
            s = int(p[ix["experimental"]]) / 1000
            if s < 0.7:
                continue
            ga, _ = resolve(ensp2sym.get(p[0], ""), cur, prev, alias)
            gb, _ = resolve(ensp2sym.get(p[1], ""), cur, prev, alias)
            if not ga or not gb:
                n_unmapped += 1
                continue
            if ga != gb:
                k = tuple(sorted((ga, gb)))
                seen[k] = max(seen.get(k, 0), s)
    print(f"  STRING v11.0 experimental >= 0.700: {len(seen)} edges; {n_unmapped} rows with unmapped ENSP")
    for (a, b), s in seen.items():
        yield {"subject": a, "predicate": "biolink:physically_interacts_with", "object": b,
               "layer": "L1", "knowledge_level": "knowledge_assertion", "agent_type": "automated_agent",
               "primary_knowledge_source": "infores:string", "score": round(s, 3),
               "qualifiers": dumps({"release": "v11.0", "channel": "experimental"})}


def reactome_2020(l1_now):
    rows = [e for e in l1_now if e["primary_knowledge_source"] == "infores:reactome"]
    pw = sorted({e["object"][6:] for e in rows})
    cache = RAW / "reactome_release_dates.json"
    dates = json.loads(cache.read_text()) if cache.exists() else {}
    need = [p for p in pw if p not in dates]
    for i in range(0, len(need), 20):
        chunk = need[i:i + 20]
        req = urllib.request.Request("https://reactome.org/ContentService/data/query/ids",
                                     data=",".join(chunk).encode(),
                                     headers={"Content-Type": "text/plain",
                                              "User-Agent": "Mozilla/5.0 (tbi-kg2 academic)"})
        for x in json.loads(urllib.request.urlopen(req, timeout=120).read()):
            dates[x["stId"]] = x.get("releaseDate") or ""
        time.sleep(0.2)
    cache.write_text(json.dumps(dates))
    ok = {p for p in pw if dates.get(p, "9999")[:4].isdigit() and int(dates[p][:4]) <= CUTOFF}
    kept = [e for e in rows if e["object"][6:] in ok]
    print(f"  Reactome: pathways {len(pw)} -> {len(ok)} released <= {CUTOFF} "
          f"({sum(1 for p in pw if not dates.get(p))} without a date, dropped); edges {len(rows)} -> {len(kept)}")
    return kept


def pmid_filtered(l1_now, source, years):
    rows = [e for e in l1_now if e["primary_knowledge_source"] == source]
    kept = []
    for e in rows:
        pm = [p for p in e["publications"].split(";") if p]
        early = sorted(p for p in pm if years.get(p, "").isdigit() and int(years[p]) <= CUTOFF)
        if early:
            kept.append({**e, "publications": ";".join(early)})
    print(f"  {source}: {len(rows)} -> {len(kept)} with a PMID <= {CUTOFF}")
    return kept


def main():
    _, cur, prev, alias = load_hgnc()
    l1_now = read_tsv(INTERIM / "l1_edges.tsv")
    pm = {p for e in l1_now if e["primary_knowledge_source"] in ("infores:omnipath", "infores:chembl")
          for p in e["publications"].split(";") if p}
    years = pmid_years(pm)
    edges = list(string_2020(cur, prev, alias))
    edges += reactome_2020(l1_now)
    edges += pmid_filtered(l1_now, "infores:omnipath", years)
    edges += pmid_filtered(l1_now, "infores:chembl", years)
    n = write_tsv(INTERIM / "l1_edges_2020.tsv", EDGE_COLS, edges)
    by = defaultdict(int)
    for e in edges:
        by[e["primary_knowledge_source"]] += 1
    print(f"P2b: L1-2020 edges {n} ({dict(by)}); current L1 had {len(l1_now)}")


if __name__ == "__main__":
    main()
