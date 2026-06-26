"""
PubMed Paper Fetcher for TBI Knowledge Base
============================================
Searches PubMed across 6 topic clusters and stores results in SQLite.
Adapted from TrialSense/scripts/fetch_pubmed_abstracts.py (requests + E-utilities).

Usage:
    python kb/fetch_papers.py [--api-key KEY] [--cluster NAME] [--limit N] [--dry-run]
"""

import argparse
import json
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
import requests

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
HEADERS  = {"User-Agent": "TBI-KnowledgeBase/1.0 (research; fedorlipskerov@gmail.com)"}
BATCH    = 200

CLUSTERS = {
    # ── NQO2 / QR2 — all papers, no tissue/disease filter ───────────────────
    "nqo2": (
        '(NQO2 OR "quinone reductase 2" OR QR2 OR "NQO2 protein" OR "NRH:quinone oxidoreductase")'
    ),
    # ── Established TBI blood biomarkers ────────────────────────────────────
    "gfap_uchl1": (
        '(GFAP OR UCH-L1 OR "glial fibrillary acidic protein" OR "ubiquitin C-terminal hydrolase") '
        'AND "traumatic brain injury" AND (diagnostic OR biomarker OR detection)'
    ),
    "exosomal_rna": (
        '("traumatic brain injury" OR TBI) '
        'AND (exosome OR "extracellular vesicle" OR miRNA OR lncRNA OR "non-coding RNA") '
        'AND (biomarker OR diagnostic OR detection)'
    ),
    "ppcs_prognosis": (
        '"post-concussion syndrome" '
        'AND (biomarker OR prognosis OR prediction OR outcome OR diagnosis)'
    ),
    "nfl_tau": (
        '("traumatic brain injury" OR TBI OR concussion) '
        'AND (NfL OR "neurofilament light" OR tau OR "phospho-tau" OR "p-tau" OR "neurofilament") '
        'AND (blood OR plasma OR serum OR diagnosis OR prognosis)'
    ),
    # ── TBI blood diagnostics expansion ─────────────────────────────────────
    "tbi_proteomics": (
        '"traumatic brain injury" '
        'AND (proteomics OR metabolomics OR "mass spectrometry" OR multi-omics OR "protein profiling")'
    ),
    "tbi_mild_blood": (
        '(mTBI OR "mild TBI" OR concussion OR "mild traumatic brain injury") '
        'AND (blood OR plasma OR serum) '
        'AND (biomarker OR diagnostic OR triage OR "rule out" OR "CT-negative") '
        'AND ("2018"[pdat]:"2026"[pdat])'
    ),
    "tbi_panel_poc": (
        '"traumatic brain injury" AND ('
        '"biomarker panel" OR "multi-marker" OR "multiple biomarkers" OR "panel of biomarkers" OR '
        '"point of care" OR POC OR "rapid test" OR "lateral flow" OR "whole blood test"'
        ')'
    ),
    "aging_neuro": (
        '("brain aging" OR "aging brain" OR "cognitive aging" OR "age-related cognitive decline" '
        'OR "neurobiological aging" OR "brain senescence" OR "aging brain biomarker") '
        'AND (biomarker OR "oxidative stress" OR neurodegeneration OR "synaptic plasticity" '
        'OR neuroinflammation OR mitochondria OR senescence)'
    ),
    # ── QR2 / NQO2 inhibitor space (v2.0) ───────────────────────────────────
    "qr2_inhibitors": (
        '(NQO2 OR "quinone reductase 2" OR QR2 OR "NRH:quinone oxidoreductase 2") '
        'AND (inhibitor OR inhibition OR antagonist OR "small molecule" OR pharmacolog* '
        'OR IC50 OR Ki OR potency OR "drug discovery")'
    ),
    "qr2_melatonin_mt3": (
        '("quinone reductase 2" OR NQO2 OR QR2) '
        'AND (melatonin OR "MT3 binding" OR "melatonin binding site" OR "2-iodomelatonin" '
        'OR prazosin OR "N-acetylserotonin")'
    ),
    "qr2_antimalarials": (
        '(NQO2 OR QR2 OR "quinone reductase 2") '
        'AND (chloroquine OR primaquine OR quinacrine OR antimalarial OR imatinib OR mefloquine)'
    ),
    "qr2_flavonoids": (
        '(NQO2 OR QR2 OR "quinone reductase 2") '
        'AND (quercetin OR resveratrol OR flavonoid OR casimiroin OR polyphenol '
        'OR genistein OR curcumin OR apigenin OR kaempferol)'
    ),
    "qr2_structure_kinetics": (
        '(NQO2 OR QR2 OR "quinone reductase 2") '
        'AND (crystal OR structure OR "X-ray" OR kinetics OR "active site" '
        'OR "structure-activity" OR cofactor OR FAD OR NRH OR mechanism OR substrate)'
    ),
}

# Per-cluster fetch caps (None = fetch all available)
CLUSTER_CAPS = {
    "nqo2":          None,    # 367 total — fetch all
    "tbi_proteomics": 500,
    "tbi_mild_blood": 500,
    "tbi_panel_poc":  None,   # ~300 total — fetch all
    "aging_neuro":    500,
    # QR2/NQO2 inhibitor space — small corpora, fetch all (v2.0)
    "qr2_inhibitors":        None,
    "qr2_melatonin_mt3":     None,
    "qr2_antimalarials":     None,
    "qr2_flavonoids":        None,
    "qr2_structure_kinetics": None,
}
MAX_PER_CLUSTER = 300


# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS papers (
            pmid         TEXT PRIMARY KEY,
            title        TEXT,
            abstract     TEXT,
            authors      TEXT,
            journal      TEXT,
            year         INTEGER,
            pub_date     TEXT,
            doi          TEXT,
            pmc_id       TEXT,
            article_types TEXT,
            source       TEXT DEFAULT 'pubmed',
            topic_cluster TEXT,
            fetched_at   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_papers_cluster ON papers(topic_cluster);
        CREATE INDEX IF NOT EXISTS idx_papers_year    ON papers(year);

        CREATE TABLE IF NOT EXISTS entities (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT UNIQUE NOT NULL,
            type    TEXT,
            aliases TEXT
        );

        CREATE TABLE IF NOT EXISTS paper_entity (
            pmid      TEXT,
            entity_id INTEGER,
            relation  TEXT,
            context   TEXT,
            PRIMARY KEY (pmid, entity_id),
            FOREIGN KEY (pmid)      REFERENCES papers(pmid),
            FOREIGN KEY (entity_id) REFERENCES entities(id)
        );

        CREATE TABLE IF NOT EXISTS entity_relations (
            source_id      INTEGER,
            target_id      INTEGER,
            relation       TEXT,
            evidence_pmids TEXT,
            weight         REAL DEFAULT 1.0,
            edge_kind      TEXT DEFAULT 'cooccur',
            directed       INTEGER DEFAULT 0,
            PRIMARY KEY (source_id, target_id, relation),
            FOREIGN KEY (source_id) REFERENCES entities(id),
            FOREIGN KEY (target_id) REFERENCES entities(id)
        );

        -- v2.0: many-to-many cluster tagging (replaces single-value topic_cluster
        -- for faceting; papers.topic_cluster kept for v1.0 back-compat)
        CREATE TABLE IF NOT EXISTS paper_clusters (
            pmid    TEXT,
            cluster TEXT,
            PRIMARY KEY (pmid, cluster),
            FOREIGN KEY (pmid) REFERENCES papers(pmid)
        );
        CREATE INDEX IF NOT EXISTS idx_pc_cluster ON paper_clusters(cluster);

        -- v2.0: SQLite FTS5 full-text index over abstracts (stdlib sqlite3)
        CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
            pmid UNINDEXED, title, abstract, authors,
            content='papers', content_rowid='rowid'
        );

        CREATE TABLE IF NOT EXISTS clinical_context (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            pmid            TEXT,
            sample_type     TEXT,
            n_patients      INTEGER,
            tbi_severity    TEXT,
            time_from_injury TEXT,
            clinical_goal   TEXT,
            performance_json TEXT,
            FOREIGN KEY (pmid) REFERENCES papers(pmid)
        );
    """)
    _migrate_schema(conn)
    conn.commit()


def _migrate_schema(conn: sqlite3.Connection):
    """Additive migrations for DBs created by v1.0 (no-op on fresh DBs)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(entity_relations)")}
    if "edge_kind" not in cols:
        conn.execute("ALTER TABLE entity_relations ADD COLUMN edge_kind TEXT DEFAULT 'cooccur'")
    if "directed" not in cols:
        conn.execute("ALTER TABLE entity_relations ADD COLUMN directed INTEGER DEFAULT 0")


# ── PubMed E-utilities ─────────────────────────────────────────────────────────

def esearch(query: str, retmax: int = MAX_PER_CLUSTER, api_key: str = None) -> list[str]:
    """Search PubMed and return list of PMIDs."""
    params = {
        "db":      "pubmed",
        "term":    query,
        "retmax":  retmax,
        "retmode": "json",
        "sort":    "relevance",
    }
    if api_key:
        params["api_key"] = api_key

    for attempt in range(3):
        try:
            resp = requests.get(BASE_URL + "esearch.fcgi", params=params,
                                headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            pmids = data.get("esearchresult", {}).get("idlist", [])
            total = data.get("esearchresult", {}).get("count", "?")
            return pmids, int(total) if str(total).isdigit() else 0
        except Exception as e:
            if attempt == 2:
                print(f"  esearch failed: {e}")
                return [], 0
            time.sleep(2 ** attempt)
    return [], 0


def parse_abstract_xml(article_elem):
    """Parse structured or plain abstract from PubMed XML."""
    abstract_elem = article_elem.find(".//Abstract")
    if abstract_elem is None:
        return None

    parts = abstract_elem.findall("AbstractText")
    if not parts:
        return None

    if len(parts) == 1 and not parts[0].get("Label"):
        return (parts[0].text or "").strip()

    # Structured abstract — join sections
    sections = []
    for part in parts:
        label = (part.get("Label") or "").strip()
        text  = "".join(part.itertext()).strip()
        if label:
            sections.append(f"{label}: {text}")
        elif text:
            sections.append(text)
    return " ".join(sections)


def efetch_batch(pmids: list, api_key: str = None) -> list[dict]:
    """Fetch paper metadata for a batch of PMIDs."""
    params = {
        "db":      "pubmed",
        "id":      ",".join(pmids),
        "rettype": "xml",
        "retmode": "xml",
    }
    if api_key:
        params["api_key"] = api_key

    for attempt in range(3):
        try:
            resp = requests.get(BASE_URL + "efetch.fcgi", params=params,
                                headers=HEADERS, timeout=30)
            resp.raise_for_status()
            break
        except Exception as e:
            if attempt == 2:
                print(f"  efetch batch failed: {e}")
                return []
            time.sleep(2 ** attempt)

    records = []
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return []

    for article in root.findall(".//PubmedArticle"):
        try:
            medline = article.find("MedlineCitation")
            if medline is None:
                continue
            pmid = medline.findtext("PMID")
            art  = medline.find("Article")
            if art is None:
                continue

            title = "".join(art.find("ArticleTitle").itertext()) if art.find("ArticleTitle") is not None else None
            abstract = parse_abstract_xml(art)

            journal_elem = art.find("Journal")
            journal  = journal_elem.findtext("Title") if journal_elem else None
            pub_date_elem = journal_elem.find(".//PubDate") if journal_elem else None
            pub_year = None
            pub_date = None
            if pub_date_elem is not None:
                yr = pub_date_elem.findtext("Year")
                pub_year = int(yr) if yr and yr.isdigit() else None
                pub_date = f"{yr or ''} {pub_date_elem.findtext('Month') or ''} {pub_date_elem.findtext('Day') or ''}".strip()

            doi = None
            for loc_id in art.findall(".//ELocationID"):
                if loc_id.get("EIdType") == "doi":
                    doi = loc_id.text

            pmc_id = None
            for art_id in article.findall(".//ArticleId"):
                if art_id.get("IdType") == "pmc":
                    pmc_id = art_id.text

            article_types = [
                pt.text for pt in art.findall(".//PublicationTypeList/PublicationType")
                if pt.text
            ]

            authors_list = []
            for auth in medline.findall(".//AuthorList/Author")[:5]:
                ln  = auth.findtext("LastName") or ""
                ini = auth.findtext("Initials") or ""
                if ln:
                    authors_list.append(f"{ln} {ini}".strip())
            authors = ", ".join(authors_list)
            if len(medline.findall(".//AuthorList/Author")) > 5:
                authors += " et al."

            records.append({
                "pmid":          pmid,
                "title":         title,
                "abstract":      abstract,
                "authors":       authors,
                "journal":       journal,
                "year":          pub_year,
                "pub_date":      pub_date,
                "doi":           doi,
                "pmc_id":        pmc_id,
                "article_types": json.dumps(article_types),
            })
        except Exception:
            continue

    return records


def upsert_papers(conn: sqlite3.Connection, records: list, cluster: str):
    now = datetime.utcnow().isoformat()
    conn.executemany("""
        INSERT INTO papers (pmid, title, abstract, authors, journal, year, pub_date,
                            doi, pmc_id, article_types, source, topic_cluster, fetched_at)
        VALUES (:pmid, :title, :abstract, :authors, :journal, :year, :pub_date,
                :doi, :pmc_id, :article_types, 'pubmed', :cluster, :now)
        ON CONFLICT(pmid) DO UPDATE SET
            title         = excluded.title,
            abstract      = excluded.abstract,
            topic_cluster = CASE WHEN papers.topic_cluster IS NULL
                                 THEN excluded.topic_cluster
                                 ELSE papers.topic_cluster END,
            fetched_at    = excluded.fetched_at
    """, [{**r, "cluster": cluster, "now": now} for r in records])
    # v2.0: many-to-many cluster tag — a PMID may belong to several clusters
    conn.executemany(
        "INSERT OR IGNORE INTO paper_clusters (pmid, cluster) VALUES (?, ?)",
        [(r["pmid"], cluster) for r in records],
    )
    conn.commit()


def fetch_cluster(cluster: str, query: str, db_path: str, api_key: str = None,
                  limit: int = None, dry_run: bool = False):
    cap = CLUSTER_CAPS.get(cluster, MAX_PER_CLUSTER)
    max_pmids = limit if limit is not None else (cap if cap is not None else 9999)
    print(f"\n[{cluster}] Searching PubMed...")
    print(f"  Query: {query[:80]}...")

    pmids, total = esearch(query, retmax=max_pmids, api_key=api_key)
    print(f"  Found {total:,} papers on PubMed, fetching {len(pmids)} most relevant")

    if dry_run or not pmids:
        return 0

    conn = get_db(db_path)
    existing = {row["pmid"] for row in conn.execute("SELECT pmid FROM papers")}
    new_pmids = [p for p in pmids if p not in existing]
    print(f"  New PMIDs to fetch: {len(new_pmids)} ({len(pmids) - len(new_pmids)} already in DB)")

    # v2.0: tag already-present papers under this cluster too, so a PMID retrieved
    # by several cluster queries becomes multi-cluster (enables faceting). New PMIDs
    # are tagged by upsert_papers below.
    already = [p for p in pmids if p in existing]
    if already:
        conn.executemany(
            "INSERT OR IGNORE INTO paper_clusters (pmid, cluster) VALUES (?, ?)",
            [(p, cluster) for p in already],
        )
        conn.commit()

    rate = 10 if api_key else 3
    delay = 1.0 / rate
    inserted = 0

    batches = [new_pmids[i:i+BATCH] for i in range(0, len(new_pmids), BATCH)]
    for i, batch in enumerate(batches):
        records = efetch_batch(batch, api_key)
        upsert_papers(conn, records, cluster)
        inserted += len(records)
        print(f"  Batch {i+1}/{len(batches)}: +{len(records)} papers (total inserted: {inserted})")
        time.sleep(delay)

    conn.close()
    return inserted


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fetch TBI papers from PubMed into SQLite")
    parser.add_argument("--api-key",  default=None, help="NCBI API key (10 req/s vs 3 req/s)")
    parser.add_argument("--cluster",  default=None, help="Fetch only this cluster")
    parser.add_argument("--limit",    type=int, default=None, help="Max PMIDs per cluster")
    parser.add_argument("--dry-run",  action="store_true", help="Show query plan only")
    parser.add_argument("--db",       default="data/tbi_papers.db", help="SQLite DB path")
    args = parser.parse_args()

    db_path = Path(__file__).parent.parent / args.db
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = get_db(str(db_path))
    init_schema(conn)
    conn.close()

    clusters = {args.cluster: CLUSTERS[args.cluster]} if args.cluster else CLUSTERS

    print(f"\n{'='*60}")
    print(f"TBI Knowledge Base — PubMed Fetcher")
    print(f"  DB: {db_path}")
    print(f"  Clusters: {list(clusters.keys())}")
    if args.dry_run:
        print("  MODE: DRY RUN")
    print(f"{'='*60}")

    total_inserted = 0
    for cluster, query in clusters.items():
        n = fetch_cluster(cluster, query, str(db_path),
                          api_key=args.api_key,
                          limit=args.limit,
                          dry_run=args.dry_run)
        total_inserted += n

    if not args.dry_run:
        conn = get_db(str(db_path))
        counts = {row[0]: row[1] for row in conn.execute(
            "SELECT topic_cluster, COUNT(*) FROM papers GROUP BY topic_cluster")}
        total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        conn.close()
        print(f"\n{'='*60}")
        print(f"Done. Total papers in DB: {total}")
        for c, n in counts.items():
            print(f"  {c:<20}: {n:>4} papers")
        print(f"{'='*60}")
        print(f"\nNext: python build_kb.py (or python kb/build_graph.py)")


if __name__ == "__main__":
    main()
