"""
bioRxiv Preprint Fetcher for TBI Knowledge Base (v2.0)
======================================================
Adds bioRxiv preprints to the same `papers` table used by the PubMed pipeline,
tagged `source='biorxiv'`, so they flow into the graph, FTS index and facets.

Why two steps? `api.biorxiv.org` has **no keyword/topic search** — its endpoints
are date-range / DOI based. So we:
  1. Keyword-search bioRxiv preprints per cluster via the Europe PMC REST API
     (`SRC:PPR`, which indexes bioRxiv) to collect DOIs + metadata.
  2. Enrich each hit via `api.biorxiv.org/details/biorxiv/{DOI}` for canonical
     preprint metadata (version, date, abstract).
Published versions (a DOI already present from PubMed) are skipped.

Usage:
    python kb/fetch_preprints.py [--cluster NAME] [--limit N] [--dry-run]
"""

import argparse
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests

# Allow running directly (`python kb/fetch_preprints.py`) as well as importing
# from the repo root: ensure the repo root is on sys.path before the kb import.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kb.fetch_papers import CLUSTERS, get_db, init_schema

EPMC_URL    = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
BIORXIV_URL = "https://api.biorxiv.org/details/biorxiv/"
HEADERS     = {"User-Agent": "TBI-KnowledgeBase/2.0 (research; fedorlipskerov@gmail.com)"}
PAGE_SIZE   = 100
MAX_PER_CLUSTER = 200   # preprint corpora are small; keep network modest


def europepmc_query(pubmed_query: str) -> str:
    """Adapt a PubMed cluster query for Europe PMC and restrict to preprints.

    PubMed-only field tags (e.g. `"2018"[pdat]`) are stripped — Europe PMC uses a
    different date syntax — while boolean/quote/wildcard structure is preserved.
    """
    q = pubmed_query
    # Drop any parenthetical group that carries a [pdat] date filter
    q = re.sub(r'\(\s*"[^"]*"\[pdat\][^)]*\)', "", q, flags=re.IGNORECASE)
    # Drop any stray field tags like [pdat], [tiab], [mesh]
    q = re.sub(r'\[[a-z]+\]', "", q, flags=re.IGNORECASE)
    # Drop a trailing dangling AND/OR left by the removals
    q = re.sub(r'\b(AND|OR)\s*$', "", q.strip(), flags=re.IGNORECASE).strip()
    return f"({q}) AND SRC:PPR"


def epmc_search(query: str, limit: int = MAX_PER_CLUSTER) -> list[dict]:
    """Keyword-search Europe PMC preprints; return bioRxiv hits with core metadata."""
    results, cursor = [], "*"
    while len(results) < limit:
        params = {
            "query":      query,
            "resultType": "core",
            "format":     "json",
            "pageSize":   PAGE_SIZE,
            "cursorMark": cursor,
        }
        for attempt in range(3):
            try:
                resp = requests.get(EPMC_URL, params=params, headers=HEADERS, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  Europe PMC search failed: {e}")
                    return results
                time.sleep(2 ** attempt)

        hits = data.get("resultList", {}).get("result", [])
        if not hits:
            break
        for h in hits:
            doi = (h.get("doi") or "").strip()
            # bioRxiv (and medRxiv) DOIs are under the 10.1101 prefix; keep bioRxiv
            publisher = (h.get("publisher") or h.get("bookOrReportDetails", {}).get("publisher") or "")
            is_biorxiv = doi.startswith("10.1101") and "medrxiv" not in doi.lower()
            if not doi or not is_biorxiv:
                continue
            results.append({
                "doi":      doi,
                "title":    h.get("title"),
                "abstract": h.get("abstractText"),
                "authors":  h.get("authorString"),
                "year":     int(h["pubYear"]) if str(h.get("pubYear", "")).isdigit() else None,
                "pub_date": h.get("firstPublicationDate"),
            })
            if len(results) >= limit:
                break

        next_cursor = data.get("nextCursorMark")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
        time.sleep(0.2)
    return results


def biorxiv_enrich(doi: str) -> dict | None:
    """Fetch canonical bioRxiv metadata for a DOI (best-effort)."""
    try:
        resp = requests.get(BIORXIV_URL + doi, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        coll = resp.json().get("collection", [])
        if not coll:
            return None
        latest = coll[-1]  # newest version
        return {
            "title":    latest.get("title"),
            "authors":  latest.get("authors"),
            "abstract": latest.get("abstract"),
            "pub_date": latest.get("date"),
            "year":     int(latest["date"][:4]) if latest.get("date", "")[:4].isdigit() else None,
            "version":  latest.get("version"),
            "category": latest.get("category"),
        }
    except Exception:
        return None


def upsert_preprints(conn: sqlite3.Connection, records: list[dict], cluster: str) -> int:
    """Insert bioRxiv preprints into `papers` (source='biorxiv'); skip published DOIs."""
    now = datetime.utcnow().isoformat()
    inserted = 0
    for r in records:
        doi = r["doi"]
        # Skip if this DOI is already in the DB as a (published) PubMed paper
        dup = conn.execute(
            "SELECT 1 FROM papers WHERE doi = ? AND source != 'biorxiv' LIMIT 1", (doi,)
        ).fetchone()
        if dup:
            continue
        pmid = f"biorxiv:{doi}"  # synthetic key — papers.pmid is the PK
        conn.execute("""
            INSERT INTO papers (pmid, title, abstract, authors, journal, year, pub_date,
                                doi, pmc_id, article_types, source, topic_cluster, fetched_at)
            VALUES (:pmid, :title, :abstract, :authors, 'bioRxiv', :year, :pub_date,
                    :doi, NULL, :atypes, 'biorxiv', :cluster, :now)
            ON CONFLICT(pmid) DO UPDATE SET
                title      = excluded.title,
                abstract   = excluded.abstract,
                fetched_at = excluded.fetched_at
        """, {
            "pmid": pmid, "title": r.get("title"), "abstract": r.get("abstract"),
            "authors": r.get("authors"), "year": r.get("year"), "pub_date": r.get("pub_date"),
            "doi": doi, "atypes": json.dumps(["Preprint"]), "cluster": cluster, "now": now,
        })
        conn.execute(
            "INSERT OR IGNORE INTO paper_clusters (pmid, cluster) VALUES (?, ?)", (pmid, cluster)
        )
        inserted += 1
    conn.commit()
    return inserted


def fetch_cluster_preprints(cluster: str, query: str, db_path: str,
                            limit: int = None, dry_run: bool = False) -> int:
    epmc_q = europepmc_query(query)
    cap = limit if limit is not None else MAX_PER_CLUSTER
    print(f"\n[{cluster}] Searching bioRxiv via Europe PMC...")
    print(f"  Query: {epmc_q[:90]}...")

    hits = epmc_search(epmc_q, limit=cap)
    print(f"  Europe PMC returned {len(hits)} bioRxiv preprint(s)")
    if dry_run or not hits:
        return 0

    conn = get_db(db_path)
    # Enrich each hit with canonical bioRxiv metadata (best-effort)
    for h in hits:
        enriched = biorxiv_enrich(h["doi"])
        if enriched:
            for k, v in enriched.items():
                if v:
                    h[k] = v
        time.sleep(0.2)

    inserted = upsert_preprints(conn, hits, cluster)
    conn.close()
    print(f"  Inserted {inserted} new bioRxiv preprint(s) "
          f"({len(hits) - inserted} duplicate/published, skipped)")
    return inserted


def main():
    parser = argparse.ArgumentParser(description="Fetch bioRxiv preprints into the TBI DB")
    parser.add_argument("--cluster", default=None, help="Fetch only this cluster")
    parser.add_argument("--limit",   type=int, default=None, help="Max preprints per cluster")
    parser.add_argument("--dry-run", action="store_true", help="Show query plan only")
    parser.add_argument("--db",      default="data/tbi_papers.db", help="SQLite DB path")
    args = parser.parse_args()

    db_path = Path(__file__).parent.parent / args.db
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db(str(db_path))
    init_schema(conn)
    conn.close()

    clusters = {args.cluster: CLUSTERS[args.cluster]} if args.cluster else CLUSTERS
    total = 0
    for cluster, query in clusters.items():
        total += fetch_cluster_preprints(cluster, query, str(db_path),
                                         limit=args.limit, dry_run=args.dry_run)
    print(f"\nDone. Inserted {total} bioRxiv preprints total.")


if __name__ == "__main__":
    main()
