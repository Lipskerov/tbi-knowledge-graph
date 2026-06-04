"""
Read-only SQLite data access for the TBI Knowledge Graph web app (v2.0).

All query logic lives here; `app/main.py` is a thin FastAPI layer on top.
The DB is opened read-only (URI `mode=ro`) — the app never writes.
"""

import os
import re
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get(
    "TBI_DB",
    str(Path(__file__).resolve().parent.parent / "data" / "tbi_papers.db"),
)


def connect() -> sqlite3.Connection:
    """Open a fresh read-only connection (sqlite is cheap; one per request)."""
    uri = f"file:{Path(DB_PATH).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _split(csv: str | None) -> list[str]:
    """Parse a comma-separated multi-value query param into a clean list."""
    if not csv:
        return []
    return [v.strip() for v in csv.split(",") if v.strip()]


def _fts_match(q: str) -> str:
    """Turn free text into a safe FTS5 AND-of-tokens MATCH string."""
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", q or "")
    return " AND ".join(f'"{t}"' for t in tokens)


def _has_col(conn: sqlite3.Connection, table: str, col: str) -> bool:
    """Whether a column exists (tolerates DBs built before a migration)."""
    return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({table})"))


# Edge kinds rendered as directed mechanism links (always shown, ignore min_edge).
MECH_KINDS = ("curated", "chembl")


# ── /api/stats ──────────────────────────────────────────────────────────────────

def stats() -> dict:
    conn = connect()
    try:
        g = lambda sql: conn.execute(sql).fetchone()[0]
        by_cluster = {
            r["cluster"]: r["n"]
            for r in conn.execute(
                "SELECT cluster, COUNT(*) AS n FROM paper_clusters GROUP BY cluster ORDER BY n DESC"
            )
        }
        by_source = {
            r["source"]: r["n"]
            for r in conn.execute(
                "SELECT COALESCE(source,'pubmed') AS source, COUNT(*) AS n "
                "FROM papers GROUP BY source"
            )
        }
        yr = conn.execute("SELECT MIN(year), MAX(year) FROM papers WHERE year IS NOT NULL").fetchone()
        return {
            "papers":        g("SELECT COUNT(*) FROM papers"),
            "entities":      g("SELECT COUNT(*) FROM entities"),
            "edges":         g("SELECT COUNT(*) FROM entity_relations"),
            "curated_edges": g("SELECT COUNT(*) FROM entity_relations WHERE edge_kind='curated'"),
            "chembl_edges":  g("SELECT COUNT(*) FROM entity_relations WHERE edge_kind='chembl'"),
            "clusters":      g("SELECT COUNT(DISTINCT cluster) FROM paper_clusters"),
            "year_range":    [yr[0], yr[1]],
            "by_cluster":    by_cluster,
            "by_source":     by_source,
        }
    finally:
        conn.close()


# ── /api/graph ──────────────────────────────────────────────────────────────────

def graph(min_papers: int = 0, min_edge: int = 1, types: str | None = None,
          clusters: str | None = None, disease: str | None = None,
          q: str | None = None) -> dict:
    conn = connect()
    try:
        type_list    = _split(types)
        cluster_list = _split(clusters)

        # paper_count per entity (distinct papers mentioning it)
        counts = {
            r["entity_id"]: r["n"]
            for r in conn.execute(
                "SELECT entity_id, COUNT(DISTINCT pmid) AS n FROM paper_entity GROUP BY entity_id"
            )
        }

        # entities in a given cluster set (OR within the facet)
        in_clusters = None
        if cluster_list:
            ph = ",".join("?" * len(cluster_list))
            in_clusters = {
                r[0] for r in conn.execute(
                    f"SELECT DISTINCT pe.entity_id "
                    f"FROM paper_entity pe JOIN paper_clusters pc ON pc.pmid = pe.pmid "
                    f"WHERE pc.cluster IN ({ph})", cluster_list
                )
            }

        # entities hit by a full-text query (for graph-side highlight/filter)
        q_hits = None
        match = _fts_match(q) if q else ""
        if match:
            q_hits = {
                r[0] for r in conn.execute(
                    "SELECT DISTINCT pe.entity_id "
                    "FROM papers_fts f JOIN papers p ON p.rowid = f.rowid "
                    "JOIN paper_entity pe ON pe.pmid = p.pmid "
                    "WHERE papers_fts MATCH ?", (match,)
                )
            }

        # neighbours of a chosen disease entity (focus subgraph)
        disease_set = None
        if disease:
            drow = conn.execute(
                "SELECT id FROM entities WHERE name = ? COLLATE NOCASE", (disease,)
            ).fetchone()
            if drow:
                did = drow["id"]
                disease_set = {did}
                for r in conn.execute(
                    "SELECT CASE WHEN source_id=? THEN target_id ELSE source_id END AS nb "
                    "FROM entity_relations WHERE source_id=? OR target_id=?",
                    (did, did, did),
                ):
                    disease_set.add(r["nb"])

        nodes, active = [], set()
        for row in conn.execute("SELECT id, name, type FROM entities"):
            eid, pc = row["id"], counts.get(row["id"], 0)
            if type_list and row["type"] not in type_list:
                continue
            if pc < min_papers:
                continue
            if in_clusters is not None and eid not in in_clusters:
                continue
            if q_hits is not None and eid not in q_hits:
                continue
            if disease_set is not None and eid not in disease_set:
                continue
            active.add(eid)
            nodes.append({"id": eid, "name": row["name"], "type": row["type"], "paper_count": pc})

        has_ann = _has_col(conn, "entity_relations", "annotation")
        ann_sel = ", annotation" if has_ann else ""
        edges = []
        for row in conn.execute(
            f"SELECT source_id, target_id, relation, weight, edge_kind, directed{ann_sel} "
            "FROM entity_relations"
        ):
            s, t = row["source_id"], row["target_id"]
            if s not in active or t not in active:
                continue
            if row["edge_kind"] not in MECH_KINDS and (row["weight"] or 0) < min_edge:
                continue
            edges.append({
                "source":     s,
                "target":     t,
                "relation":   row["relation"],
                "edge_kind":  row["edge_kind"],
                "directed":   bool(row["directed"]),
                "weight":     row["weight"],
                "annotation": row["annotation"] if has_ann else None,
            })
        return {"nodes": nodes, "edges": edges}
    finally:
        conn.close()


# ── /api/node/{id}/papers ───────────────────────────────────────────────────────

def node_papers(entity_id: int, year_min: int | None = None, year_max: int | None = None,
                cluster: str | None = None, limit: int = 50) -> dict:
    conn = connect()
    try:
        ent = conn.execute("SELECT id, name, type FROM entities WHERE id=?", (entity_id,)).fetchone()
        if not ent:
            return {"error": f"entity {entity_id} not found"}

        sql = [
            "SELECT p.pmid, p.title, p.authors, p.journal, p.year, p.doi, p.source, pe.relation,",
            " (SELECT GROUP_CONCAT(cluster) FROM paper_clusters WHERE pmid = p.pmid) AS clusters",
            "FROM paper_entity pe JOIN papers p ON p.pmid = pe.pmid",
            "WHERE pe.entity_id = ?",
        ]
        params: list = [entity_id]
        if year_min is not None:
            sql.append("AND p.year >= ?"); params.append(year_min)
        if year_max is not None:
            sql.append("AND p.year <= ?"); params.append(year_max)
        if cluster:
            sql.append("AND EXISTS (SELECT 1 FROM paper_clusters pc "
                       "WHERE pc.pmid = p.pmid AND pc.cluster = ?)")
            params.append(cluster)
        sql.append("ORDER BY p.year DESC LIMIT ?"); params.append(limit)

        papers = [_paper_row(r) for r in conn.execute(" ".join(sql), params)]
        return {"entity": ent["name"], "type": ent["type"], "n_papers": len(papers), "papers": papers}
    finally:
        conn.close()


def _paper_row(r: sqlite3.Row) -> dict:
    """Shape a paper row + build PubMed/DOI/bioRxiv links by source."""
    pmid, source, doi = r["pmid"], (r["source"] or "pubmed"), r["doi"]
    links = {}
    if doi:
        links["doi"] = f"https://doi.org/{doi}"
    if source == "biorxiv" and doi:
        links["biorxiv"] = f"https://www.biorxiv.org/content/{doi}"
    elif source != "biorxiv" and pmid and pmid.isdigit():
        links["pubmed"] = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}"
    return {
        "pmid":     pmid,
        "title":    r["title"],
        "authors":  r["authors"],
        "journal":  r["journal"],
        "year":     r["year"],
        "doi":      doi,
        "source":   source,
        "relation": r["relation"] if "relation" in r.keys() else None,
        "clusters": (r["clusters"].split(",") if ("clusters" in r.keys() and r["clusters"]) else []),
        "links":    links,
    }


# ── /api/entity/{id} ────────────────────────────────────────────────────────────

def entity(entity_id: int) -> dict:
    conn = connect()
    try:
        import json
        row = conn.execute(
            "SELECT id, name, type, aliases FROM entities WHERE id=?", (entity_id,)
        ).fetchone()
        if not row:
            return {"error": f"entity {entity_id} not found"}
        eid = row["id"]
        paper_count = conn.execute(
            "SELECT COUNT(DISTINCT pmid) FROM paper_entity WHERE entity_id=?", (eid,)
        ).fetchone()[0]

        # Typed mechanism links (curated + ChEMBL inhibitor) — directional, with potency
        has_ann = _has_col(conn, "entity_relations", "annotation")
        ann_sel = ", er.annotation" if has_ann else ""
        kinds_ph = ",".join("?" * len(MECH_KINDS))
        out_links = [
            {"target": r["name"], "relation": r["relation"], "directed": bool(r["directed"]),
             "edge_kind": r["edge_kind"], "annotation": (r["annotation"] if has_ann else None)}
            for r in conn.execute(
                f"SELECT e.name, er.relation, er.directed, er.edge_kind{ann_sel} "
                "FROM entity_relations er JOIN entities e ON e.id = er.target_id "
                f"WHERE er.source_id = ? AND er.edge_kind IN ({kinds_ph})", (eid, *MECH_KINDS))
        ]
        in_links = [
            {"source": r["name"], "relation": r["relation"], "directed": bool(r["directed"]),
             "edge_kind": r["edge_kind"], "annotation": (r["annotation"] if has_ann else None)}
            for r in conn.execute(
                f"SELECT e.name, er.relation, er.directed, er.edge_kind{ann_sel} "
                "FROM entity_relations er JOIN entities e ON e.id = er.source_id "
                f"WHERE er.target_id = ? AND er.edge_kind IN ({kinds_ph})", (eid, *MECH_KINDS))
        ]
        # Top co-occurring entities
        related = [
            {"name": r["name"], "type": r["type"], "shared_papers": r["weight"]}
            for r in conn.execute(
                "SELECT e.name, e.type, er.weight FROM entity_relations er "
                "JOIN entities e ON (CASE WHEN er.source_id=? THEN er.target_id ELSE er.source_id END = e.id) "
                "WHERE (er.source_id=? OR er.target_id=?) AND er.edge_kind='cooccur' "
                "ORDER BY er.weight DESC LIMIT 15", (eid, eid, eid))
        ]
        return {
            "id":            eid,
            "name":          row["name"],
            "type":          row["type"],
            "aliases":       json.loads(row["aliases"] or "[]"),
            "paper_count":   paper_count,
            "mechanism_out": out_links,
            "mechanism_in":  in_links,
            "top_related":   related,
        }
    finally:
        conn.close()


# ── /api/search ─────────────────────────────────────────────────────────────────

def search(q: str, clusters: str | None = None, types: str | None = None,
           year_min: int | None = None, year_max: int | None = None,
           limit: int = 50) -> dict:
    conn = connect()
    try:
        match = _fts_match(q)
        if not match:
            return {"query": q, "n_results": 0, "papers": [], "node_ids": []}

        cluster_list = _split(clusters)
        sql = [
            "SELECT p.pmid, p.title, p.authors, p.journal, p.year, p.doi, p.source,",
            " (SELECT GROUP_CONCAT(cluster) FROM paper_clusters WHERE pmid = p.pmid) AS clusters",
            "FROM papers_fts f JOIN papers p ON p.rowid = f.rowid",
            "WHERE papers_fts MATCH ?",
        ]
        params: list = [match]
        if year_min is not None:
            sql.append("AND p.year >= ?"); params.append(year_min)
        if year_max is not None:
            sql.append("AND p.year <= ?"); params.append(year_max)
        if cluster_list:
            ph = ",".join("?" * len(cluster_list))
            sql.append(f"AND EXISTS (SELECT 1 FROM paper_clusters pc "
                       f"WHERE pc.pmid = p.pmid AND pc.cluster IN ({ph}))")
            params.extend(cluster_list)
        sql.append("ORDER BY bm25(papers_fts) LIMIT ?"); params.append(limit)

        try:
            rows = conn.execute(" ".join(sql), params).fetchall()
        except sqlite3.OperationalError as e:
            return {"query": q, "error": f"search failed: {e}", "papers": [], "node_ids": []}

        papers = [_paper_row(r) for r in rows]

        # Entity node-ids hit by the matching papers (for graph highlight)
        type_list = _split(types)
        node_ids: set[int] = set()
        pmids = [p["pmid"] for p in papers]
        if pmids:
            ph = ",".join("?" * len(pmids))
            tfilter = ""
            tparams: list = list(pmids)
            if type_list:
                tph = ",".join("?" * len(type_list))
                tfilter = f"AND e.type IN ({tph})"
                tparams.extend(type_list)
            for r in conn.execute(
                f"SELECT DISTINCT pe.entity_id FROM paper_entity pe "
                f"JOIN entities e ON e.id = pe.entity_id "
                f"WHERE pe.pmid IN ({ph}) {tfilter}", tparams
            ):
                node_ids.add(r[0])

        return {"query": q, "n_results": len(papers), "papers": papers, "node_ids": sorted(node_ids)}
    finally:
        conn.close()
