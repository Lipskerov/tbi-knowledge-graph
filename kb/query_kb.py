"""
TBI Knowledge Base Query CLI
==============================
Query the TBI SQLite database interactively or programmatically.
Returns structured JSON output suitable for use as Claude context.

Usage:
    python kb/query_kb.py --stats
    python kb/query_kb.py --q "NQO2 blood biomarker TBI"
    python kb/query_kb.py --entity NQO2
    python kb/query_kb.py --entity GFAP --show-papers
    python kb/query_kb.py --cluster nqo2 --year-min 2020
    python kb/query_kb.py --pmid 35534389
    python kb/query_kb.py --related NQO2          # entities that co-occur with NQO2
    python kb/query_kb.py --export-context        # dump compact JSON for Claude
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path


def get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def print_json(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ── Query functions ────────────────────────────────────────────────────────────

def cmd_stats(conn: sqlite3.Connection):
    total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    clusters = {
        r[0]: r[1]
        for r in conn.execute("SELECT topic_cluster, COUNT(*) FROM papers GROUP BY topic_cluster")
    }
    year_range = conn.execute(
        "SELECT MIN(year), MAX(year) FROM papers WHERE year IS NOT NULL"
    ).fetchone()
    n_entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    n_links = conn.execute("SELECT COUNT(*) FROM paper_entity").fetchone()[0]
    n_edges = conn.execute("SELECT COUNT(*) FROM entity_relations").fetchone()[0]

    print_json({
        "total_papers":    total,
        "year_range":      [year_range[0], year_range[1]],
        "n_entities":      n_entities,
        "n_paper_entity_links": n_links,
        "n_graph_edges":   n_edges,
        "by_cluster":      clusters,
    })


def cmd_search(conn: sqlite3.Connection, query: str, limit: int = 10):
    """Keyword search across title + abstract. Returns top N papers ranked by hit count."""
    keywords = [k.strip().lower() for k in re.split(r'\s+', query.strip()) if k.strip()]
    if not keywords:
        print("No keywords provided")
        return

    # Score: count keyword hits in title (×3) + abstract (×1)
    papers = conn.execute(
        "SELECT pmid, title, abstract, authors, journal, year, topic_cluster, doi "
        "FROM papers WHERE title IS NOT NULL"
    ).fetchall()

    scored = []
    for p in papers:
        title_text    = (p["title"]    or "").lower()
        abstract_text = (p["abstract"] or "").lower()
        score = sum(
            title_text.count(kw) * 3 + abstract_text.count(kw)
            for kw in keywords
        )
        if score > 0:
            scored.append((score, p))

    scored.sort(key=lambda x: -x[0])
    results = []
    for score, p in scored[:limit]:
        entities = [
            r[0] for r in conn.execute("""
                SELECT e.name FROM paper_entity pe
                JOIN entities e ON e.id = pe.entity_id
                WHERE pe.pmid = ?
            """, (p["pmid"],)).fetchall()
        ]
        results.append({
            "pmid":          p["pmid"],
            "score":         score,
            "title":         p["title"],
            "authors":       p["authors"],
            "journal":       p["journal"],
            "year":          p["year"],
            "cluster":       p["topic_cluster"],
            "doi":           p["doi"],
            "abstract":      (p["abstract"] or "")[:400] + ("..." if len(p["abstract"] or "") > 400 else ""),
            "entities":      entities,
        })

    print_json({"query": query, "n_results": len(results), "papers": results})


def cmd_entity(conn: sqlite3.Connection, name: str, show_papers: bool = False):
    """Look up an entity and its connections."""
    row = conn.execute(
        "SELECT id, name, type, aliases FROM entities WHERE name = ? COLLATE NOCASE",
        (name,)
    ).fetchone()

    if not row:
        # Fuzzy: search aliases
        all_ents = conn.execute("SELECT id, name, type, aliases FROM entities").fetchall()
        for e in all_ents:
            aliases = json.loads(e["aliases"] or "[]")
            if any(name.lower() in a.lower() for a in aliases):
                row = e
                break

    if not row:
        print(json.dumps({"error": f"Entity '{name}' not found"}))
        return

    eid = row["id"]

    # Co-occurring entities (top 15 by weight)
    related = conn.execute("""
        SELECT e.name, e.type, er.weight, er.evidence_pmids
        FROM entity_relations er
        JOIN entities e ON (
            CASE WHEN er.source_id = ? THEN er.target_id ELSE er.source_id END = e.id
        )
        WHERE er.source_id = ? OR er.target_id = ?
        ORDER BY er.weight DESC
        LIMIT 15
    """, (eid, eid, eid)).fetchall()

    paper_count = conn.execute(
        "SELECT COUNT(*) FROM paper_entity WHERE entity_id = ?", (eid,)
    ).fetchone()[0]

    out = {
        "entity":      row["name"],
        "type":        row["type"],
        "aliases":     json.loads(row["aliases"] or "[]"),
        "paper_count": paper_count,
        "top_related": [
            {"name": r["name"], "type": r["type"], "shared_papers": r["weight"]}
            for r in related
        ],
    }

    if show_papers:
        papers = conn.execute("""
            SELECT p.pmid, p.title, p.year, p.journal, p.topic_cluster, pe.relation
            FROM paper_entity pe
            JOIN papers p ON p.pmid = pe.pmid
            WHERE pe.entity_id = ?
            ORDER BY p.year DESC
            LIMIT 30
        """, (eid,)).fetchall()
        out["papers"] = [dict(p) for p in papers]

    print_json(out)


def cmd_cluster(conn: sqlite3.Connection, cluster: str, year_min: int = None, limit: int = 30):
    """List papers in a cluster, optionally filtered by year."""
    q = "SELECT pmid, title, authors, journal, year, doi FROM papers WHERE topic_cluster = ?"
    params = [cluster]
    if year_min:
        q += " AND year >= ?"
        params.append(year_min)
    q += " ORDER BY year DESC LIMIT ?"
    params.append(limit)

    papers = conn.execute(q, params).fetchall()
    print_json({
        "cluster":  cluster,
        "n_papers": len(papers),
        "papers": [dict(p) for p in papers],
    })


def cmd_pmid(conn: sqlite3.Connection, pmid: str):
    """Full record for a single paper."""
    p = conn.execute(
        "SELECT * FROM papers WHERE pmid = ?", (pmid,)
    ).fetchone()
    if not p:
        print(json.dumps({"error": f"PMID {pmid} not found"}))
        return

    entities = conn.execute("""
        SELECT e.name, e.type, pe.relation, pe.context
        FROM paper_entity pe JOIN entities e ON e.id = pe.entity_id
        WHERE pe.pmid = ?
    """, (pmid,)).fetchall()

    out = dict(p)
    out["entities"] = [dict(e) for e in entities]
    print_json(out)


def cmd_related(conn: sqlite3.Connection, name: str):
    """Show all entities that co-occur with the given entity, with shared paper counts."""
    row = conn.execute(
        "SELECT id, name FROM entities WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if not row:
        print(json.dumps({"error": f"Entity '{name}' not found"}))
        return

    eid = row["id"]
    related = conn.execute("""
        SELECT e.name, e.type, er.weight,
               (SELECT GROUP_CONCAT(p.title, ' || ')
                FROM papers p
                WHERE p.pmid IN (
                    SELECT value FROM json_each(er.evidence_pmids)
                )
                LIMIT 3) as sample_titles
        FROM entity_relations er
        JOIN entities e ON (
            CASE WHEN er.source_id = ? THEN er.target_id ELSE er.source_id END = e.id
        )
        WHERE (er.source_id = ? OR er.target_id = ?)
        ORDER BY er.weight DESC
    """, (eid, eid, eid)).fetchall()

    print_json({
        "entity":  row["name"],
        "related": [
            {"name": r["name"], "type": r["type"], "shared_papers": r["weight"]}
            for r in related
        ],
    })


def cmd_export_context(conn: sqlite3.Connection, out_path: str = None):
    """Export compact knowledge context JSON for Claude — includes top papers and graph summary."""
    n_papers = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]

    # Top papers per cluster (up to 10 each)
    cluster_papers = {}
    for row in conn.execute("SELECT DISTINCT topic_cluster FROM papers"):
        cluster = row[0]
        papers = conn.execute("""
            SELECT p.pmid, p.title, p.authors, p.year, p.journal,
                   GROUP_CONCAT(e.name, ', ') as entities
            FROM papers p
            LEFT JOIN paper_entity pe ON pe.pmid = p.pmid
            LEFT JOIN entities e ON e.id = pe.entity_id
            WHERE p.topic_cluster = ? AND p.title IS NOT NULL
            GROUP BY p.pmid
            ORDER BY p.year DESC
            LIMIT 10
        """, (cluster,)).fetchall()
        cluster_papers[cluster] = [dict(p) for p in papers]

    # Top entities by paper count
    top_entities = conn.execute("""
        SELECT e.name, e.type, COUNT(pe.pmid) as paper_count
        FROM entities e
        LEFT JOIN paper_entity pe ON pe.entity_id = e.id
        GROUP BY e.id
        ORDER BY paper_count DESC
        LIMIT 30
    """).fetchall()

    # Top co-occurrences
    top_edges = conn.execute("""
        SELECT e1.name as source, e2.name as target, er.weight
        FROM entity_relations er
        JOIN entities e1 ON e1.id = er.source_id
        JOIN entities e2 ON e2.id = er.target_id
        ORDER BY er.weight DESC
        LIMIT 50
    """).fetchall()

    out = {
        "description": "TBI Knowledge Base — compact context for Claude queries",
        "n_papers":    n_papers,
        "clusters": {
            "nqo2":           "NQO2/QR2 pathway in brain/TBI/neurodegeneration",
            "gfap_uchl1":     "GFAP and UCH-L1 as TBI diagnostic biomarkers",
            "exosomal_rna":   "Exosomal/extracellular vesicle RNA biomarkers in TBI",
            "proteostasis":   "p62/SQSTM1, autophagy, UPS in TBI",
            "ppcs_prognosis": "Post-concussion syndrome biomarkers and prognosis",
            "nfl_tau":        "NfL and tau in TBI blood diagnosis/prognosis",
        },
        "cluster_papers":  cluster_papers,
        "top_entities":    [dict(e) for e in top_entities],
        "top_cooccurrences": [dict(e) for e in top_edges],
    }

    if out_path:
        with open(out_path, "w") as f:
            json.dump(out, f, indent=2)
        print(f"Context exported to {out_path}")
    else:
        print_json(out)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Query TBI knowledge base")
    parser.add_argument("--db",           default="data/tbi_papers.db")
    parser.add_argument("--stats",        action="store_true", help="Show DB statistics")
    parser.add_argument("--q",            default=None, help="Keyword search query")
    parser.add_argument("--entity",       default=None, help="Look up a specific entity")
    parser.add_argument("--show-papers",  action="store_true", help="Include papers in entity lookup")
    parser.add_argument("--cluster",      default=None, help="List papers in cluster")
    parser.add_argument("--year-min",     type=int, default=None, help="Filter by min year")
    parser.add_argument("--pmid",         default=None, help="Show full record for PMID")
    parser.add_argument("--related",      default=None, help="Show entities co-occurring with NAME")
    parser.add_argument("--export-context", action="store_true", help="Export compact context JSON")
    parser.add_argument("--limit",        type=int, default=10, help="Max results")
    args = parser.parse_args()

    db_path = Path(__file__).parent.parent / args.db
    if not db_path.exists():
        print(f"DB not found: {db_path}. Run build_kb.py first.")
        return

    conn = get_db(str(db_path))

    if args.stats:
        cmd_stats(conn)
    elif args.q:
        cmd_search(conn, args.q, limit=args.limit)
    elif args.entity:
        cmd_entity(conn, args.entity, show_papers=args.show_papers)
    elif args.cluster:
        cmd_cluster(conn, args.cluster, year_min=args.year_min, limit=args.limit)
    elif args.pmid:
        cmd_pmid(conn, args.pmid)
    elif args.related:
        cmd_related(conn, args.related)
    elif args.export_context:
        out = str(Path(__file__).parent.parent / "data" / "claude_context.json")
        cmd_export_context(conn, out_path=out)
    else:
        parser.print_help()

    conn.close()


if __name__ == "__main__":
    main()
