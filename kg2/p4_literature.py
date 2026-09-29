"""P4 — literature layer (L3) from PubTator3 (Wei et al., NAR 2024).

Replaces v1's 138-term regex dictionary. PubTator3 gives species-specific NCBIGene, MeSH
disease and MeSH chemical IDs plus scored document-level relations. We keep title + abstract
passages only, and attach to every relation the sentence(s) where both entities are mentioned.
A relation with no co-mention sentence is kept but flagged `document_level`.

Outputs
  raw/pubtator/batch_XXXX.json   cached API responses (100 PMIDs each)
  interim/l3_edges.tsv, interim/l3_evidence.tsv, interim/l3_nodes.tsv, interim/l3_mentions.tsv
"""
import json
import re
import time
import urllib.request
from collections import Counter, defaultdict

from common import INTERIM, RAW, SOURCES, dumps, log_source, read_tsv, write_tsv

API = SOURCES["pubtator3"][0]
BATCH = 100
KEEP_TYPES = {"Gene", "Disease", "Chemical"}
PRED = {
    "Positive_Correlation": "biolink:positively_correlated_with",
    "Negative_Correlation": "biolink:negatively_correlated_with",
    "Association": "biolink:associated_with",
    "Bind": "biolink:physically_interacts_with",
    "Drug_Interaction": "biolink:interacts_with",
    "Cotreatment": "biolink:related_to",
    "Comparison": "biolink:related_to",
    "Conversion": "biolink:related_to",
    "Treatment": "biolink:treats_or_applied_or_studied_to_treat",
    "Cause": "biolink:causes",
    "Inhibit": "biolink:affects",
    "Stimulate": "biolink:affects",
    "Prevent": "biolink:affects",
}
DIRECTION = {"Inhibit": "decreased", "Stimulate": "increased", "Prevent": "decreased"}
CATEGORY = {"Gene": "biolink:Gene", "Disease": "biolink:Disease", "Chemical": "biolink:ChemicalEntity"}
ORDER = {"Gene": 0, "Chemical": 1, "Disease": 2}  # subject precedence for undirected pairs
SENT = re.compile(r"[^.!?]+(?:[.!?]+(?=\s+[A-Z(\[]|\s*$)|$)", re.S)


def curie(inf):
    t, ident = inf.get("type"), str(inf.get("identifier") or "")
    if t not in KEEP_TYPES or not ident or ident in ("-", "None"):
        return None
    if ";" in ident or "|" in ident:  # multi-ID mention: ambiguous, dropped (as VitaGraph)
        return None
    if t == "Gene":
        return "NCBIGene:" + ident if ident.isdigit() else None
    return ident if ident.startswith("MESH:") else None


def fetch_all(pmids):
    cache = RAW / "pubtator"
    cache.mkdir(exist_ok=True)
    for i in range(0, len(pmids), BATCH):
        path = cache / f"batch_{i // BATCH:04d}.json"
        chunk = pmids[i:i + BATCH]
        if path.exists() and path.stat().st_size > 0:
            yield path
            continue
        url = f"{API}?pmids={','.join(chunk)}"
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "tbi-kg2/2.0 (academic)"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
                json.loads(data)
                path.write_bytes(data)
                break
            except Exception as e:  # noqa: BLE001 — retry transient API errors, then fail loud
                if attempt == 3:
                    raise RuntimeError(f"PubTator3 batch {i // BATCH} failed: {e}") from e
                time.sleep(3 * (attempt + 1))
        time.sleep(0.4)  # NCBI guidance: <= 3 requests / second
        yield path
    log_source("pubtator3", *SOURCES["pubtator3"], cache / "batch_0000.json")


def sentences(text, base):
    for m in SENT.finditer(text):
        s = m.group(0)
        if s.strip():
            yield base + m.start(), base + m.end(), s.strip()


def main():
    scope = [r for r in read_tsv(INTERIM / "scope_pmids.tsv") if r["in_scope"] == "1"]
    year = {r["pmid"]: r["year"] for r in scope}
    pmids = sorted(year, key=int)
    human = {r["ncbigene"] for r in read_tsv(INTERIM / "genes_human.tsv")}
    mouse = {r["ncbigene"] for r in read_tsv(INTERIM / "genes_mouse.tsv")}

    names = defaultdict(Counter)
    cat = {}
    mentions = Counter()
    edges, evid = {}, []
    n_docs = n_rel = n_rel_sent = 0
    got = set()
    for path in fetch_all(pmids):
        for doc in json.loads(path.read_text()).get("PubTator3", []):
            pmid = str(doc.get("pmid") or doc.get("id"))
            got.add(pmid)
            n_docs += 1
            spans = defaultdict(list)  # curie -> [offset]
            sents = []
            for p in doc["passages"]:
                if p["infons"].get("type") not in ("front", "title", "abstract"):
                    continue
                sents += list(sentences(p["text"], p["offset"]))
                for a in p["annotations"]:
                    c = curie(a["infons"])
                    if not c:
                        continue
                    spans[c] += [loc["offset"] for loc in a["locations"]]
                    names[c][a["infons"].get("name") or a["text"]] += 1
                    cat[c] = a["infons"]["type"]
            for c in spans:
                mentions[(pmid, c)] += len(spans[c])
            for rel in doc.get("relations", []):
                inf = rel["infons"]
                a, b = curie(inf.get("role1", {})), curie(inf.get("role2", {}))
                rtype = inf.get("type")
                if not a or not b or a == b or rtype not in PRED:
                    continue
                n_rel += 1
                for c, role in ((a, inf["role1"]), (b, inf["role2"])):
                    if c not in cat:  # role entity annotated only outside title/abstract
                        names[c][role.get("name") or c] += 1
                        cat[c] = role["type"]
                ta, tb = inf["role1"]["type"], inf["role2"]["type"]
                if ORDER[tb] < ORDER[ta] or (ta == tb and b < a):
                    a, b = b, a
                pred = PRED[rtype]
                direction = DIRECTION.get(rtype, "")
                key = f"{a}|{pred}|{b}|{direction}"
                e = edges.setdefault(key, {"key": key, "subject": a, "predicate": pred, "object": b,
                                           "direction": direction, "layer": "L3",
                                           "knowledge_level": "knowledge_assertion",
                                           "agent_type": "text_mining_agent",
                                           "primary_knowledge_source": "infores:pubtator3"})
                co = [s for (s0, s1, s) in sents
                      if any(s0 <= o < s1 for o in spans.get(a, []))
                      and any(s0 <= o < s1 for o in spans.get(b, []))]
                n_rel_sent += bool(co)
                evid.append({"key": key, "source": "infores:pubtator3", "pmid": pmid,
                             "year": year.get(pmid, ""), "sentence": co[0] if co else "",
                             "extractor_score": inf.get("score", ""),
                             "note": (f"pubtator_type={rtype}; co-mention sentences={len(co)}"
                                      + ("" if co else "; document_level"))})

    nodes = []
    for c, cnt in names.items():
        taxon = ("NCBITaxon:9606" if c in human else "NCBITaxon:10090" if c in mouse else "")
        nodes.append({"id": c, "category": CATEGORY[cat[c]], "name": cnt.most_common(1)[0][0],
                      "taxon": taxon, "provided_by": "infores:pubtator3"})
    write_tsv(INTERIM / "l3_edges.tsv", list(next(iter(edges.values())).keys()), edges.values())
    write_tsv(INTERIM / "l3_evidence.tsv",
              ["key", "source", "pmid", "year", "sentence", "extractor_score", "note"], evid)
    write_tsv(INTERIM / "l3_nodes.tsv", ["id", "category", "name", "taxon", "provided_by"], nodes)
    write_tsv(INTERIM / "l3_mentions.tsv", ["pmid", "id", "n"],
              ({"pmid": p, "id": c, "n": n} for (p, c), n in mentions.items()))
    missing = set(pmids) - got
    print(f"P4: PMIDs requested {len(pmids)}, returned {len(got)}, missing {len(missing)}")
    print(f"P4: entities {len(nodes)} ({dict(Counter(n['category'] for n in nodes))})")
    print(f"P4: relations kept {n_rel}; with a co-mention sentence {n_rel_sent} "
          f"({n_rel_sent / max(n_rel, 1):.1%}); unique L3 edges {len(edges)}")
    print(f"P4: predicates {dict(Counter(e['predicate'] for e in edges.values()))}")
    (INTERIM / "l3_missing_pmids.txt").write_text("\n".join(sorted(missing, key=int)))


if __name__ == "__main__":
    main()
