"""
TBI Knowledge Base — Main Build Pipeline
==========================================
One-command build:
    python build_kb.py               # full build
    python build_kb.py --dry-run     # show plan only
    python build_kb.py --skip-fetch  # rebuild graph only (papers already fetched)
    python build_kb.py --api-key KEY # NCBI API key for 10 req/s (vs 3 req/s)

Get a free NCBI API key at: https://www.ncbi.nlm.nih.gov/account/
"""

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent


def add_local_papers(db_path: str):
    """
    Insert the 3 Rosenblum lab PDFs that are already on disk.
    PMIDs are looked up from known DOIs/titles. Update when confirmed.
    """
    LOCAL_PAPERS = [
        {
            "pmid":          "34493578",
            "title":         "Somatostatin Interneurons of the Insula Mediate QR2-Dependent Novel Taste Memory Enhancement",
            "authors":       "Gould NL, Kolatt Chandran S, Kayyal H, Edry E, Rosenblum K",
            "journal":       "eNeuro",
            "year":          2021,
            "doi":           "10.1523/ENEURO.0152-21.2021",
            "pmc_id":        "PMC8477156",
            "source":        "local",
            "topic_cluster": "nqo2",
            "abstract": (
                "Quinone reductase 2 (QR2) is removed from anterior insular cortex (aIC) "
                "excitatory and SST-expressing neurons 3 hours following novel taste learning. "
                "QR2 removal in somatostatin (SST) interneurons reduces their excitability via "
                "ROS-dependent oxidation of Kv2.1 channels. Both novel taste and QR2 inhibition "
                "reduce SST neuron excitability. QR2-mediated redox modulation in SST interneurons "
                "is sufficient to enhance novel taste memory. Opens avenue for age-related cognitive "
                "deficit treatment via QR2 pathway."
            ),
            "article_types": json.dumps(["Journal Article", "Research Support, Non-U.S. Gov't"]),
        },
        {
            "pmid":          "35617003",
            "title":         "Specific quinone reductase 2 inhibitors reduce metabolic burden and reverse Alzheimer's disease phenotype in mice",
            "authors":       "Gould NL, Scherer GR, Carvalho S, Shurrush K, Kayyal H, Edry E et al.",
            "journal":       "Journal of Clinical Investigation",
            "year":          2022,
            "doi":           "10.1172/JCI162120",
            "pmc_id":        None,
            "source":        "local",
            "topic_cluster": "nqo2",
            "abstract": (
                "QR2 KO in HCT116 cells produces proteome shift antagonistic to Alzheimer's disease "
                "(AD), with increased mitochondrial function and reduced cell-junction proteins. "
                "Continuous oral QR2 inhibitor (QR2i) consumption improved cognition and reduced "
                "amyloid-β42, GFAP, and Iba1 pathology in 5xFAD AD-model mice. QR2i microinjection "
                "improved hippocampal and cortical-dependent learning in rats and mice. "
                "Metabolic stress reduction via QR2 inhibition may be more important than single-target "
                "tau/amyloid approaches. Between-sex effect: females showed more pronounced benefits "
                "for some markers. Novel highly selective QR2 inhibitors developed with >100-fold "
                "selectivity over NQO1."
            ),
            "article_types": json.dumps(["Journal Article", "Research Support, Non-U.S. Gov't"]),
        },
        {
            "pmid":          "32948681",
            "title":         "Dopamine-Dependent QR2 Pathway Activation in CA1 Interneurons Enhances Novel Memory Formation",
            "authors":       "Gould NL, Sharma V, Hleihil M, Kolatt Chandran S, David O, Edry E, Rosenblum K",
            "journal":       "Journal of Neuroscience",
            "year":          2020,
            "doi":           "10.1523/JNEUROSCI.0243-20.2020",
            "pmc_id":        "PMC7574660",
            "source":        "local",
            "topic_cluster": "nqo2",
            "abstract": (
                "Novel information acquisition triggers dopamine release in CA1 via locus coeruleus, "
                "activating D1 receptors, upregulating miR-182, and suppressing QR2 expression. "
                "QR2 is primarily expressed in inhibitory interneurons; its suppression reduces "
                "their excitability via ROS and Kv2.1 channel oxidation. In aged animals, "
                "miR-182 underexpression and QR2 overexpression leads to accumulated oxidative "
                "stress and impaired memory. This represents the first description of a "
                "dopamine-dependent QR2 pathway in hippocampal CA1 interneurons as a mechanism "
                "for novelty-induced memory enhancement. Chronic QR2 overactivation in aging "
                "represents a novel therapeutic target for age-dependent memory deficits."
            ),
            "article_types": json.dumps(["Journal Article"]),
        },
    ]

    conn = sqlite3.connect(db_path)
    now = datetime.utcnow().isoformat()
    for p in LOCAL_PAPERS:
        conn.execute("""
            INSERT OR IGNORE INTO papers
                (pmid, title, abstract, authors, journal, year, doi, pmc_id,
                 article_types, source, topic_cluster, fetched_at)
            VALUES
                (:pmid, :title, :abstract, :authors, :journal, :year, :doi, :pmc_id,
                 :article_types, :source, :topic_cluster, :now)
        """, {**p, "now": now})
    conn.commit()
    conn.close()
    print(f"  Added {len(LOCAL_PAPERS)} local Rosenblum lab papers (PMIDs pre-filled, verify if needed)")


def main():
    parser = argparse.ArgumentParser(description="Build TBI knowledge base end-to-end")
    parser.add_argument("--api-key",    default=None, help="NCBI API key (10 req/s vs 3 req/s)")
    parser.add_argument("--dry-run",    action="store_true", help="Show plan only, no fetching")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip PubMed fetch, rebuild graph only")
    parser.add_argument("--cluster",    default=None, help="Fetch only this cluster")
    parser.add_argument("--limit",      type=int, default=None, help="Max PMIDs per cluster (for testing)")
    args = parser.parse_args()

    db_path   = ROOT / "data" / "tbi_papers.db"
    graph_out = ROOT / "data" / "knowledge_graph.json"
    md_out    = ROOT / "data" / "paper_summaries.md"
    ctx_out   = ROOT / "data" / "claude_context.json"

    print(f"\n{'='*60}")
    print(f"TBI Knowledge Base Builder")
    print(f"  DB:    {db_path}")
    print(f"  Graph: {graph_out}")
    if args.dry_run:
        print("  MODE: DRY RUN — no changes")
    print(f"{'='*60}\n")

    # ── Step 1: Init schema ───────────────────────────────────────────────────
    from kb.fetch_papers import get_db, init_schema
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db(str(db_path))
    init_schema(conn)
    conn.close()
    print("[1/5] Schema initialized")

    # ── Step 2: Add local PDFs ────────────────────────────────────────────────
    print("\n[2/5] Adding local Rosenblum lab papers...")
    if not args.dry_run:
        add_local_papers(str(db_path))
    else:
        print("  (skipped — dry run)")

    # ── Step 3: Fetch from PubMed ─────────────────────────────────────────────
    if not args.skip_fetch:
        print("\n[3/5] Fetching papers from PubMed...")
        if args.dry_run:
            print("  (dry run — showing queries only)")

        from kb.fetch_papers import CLUSTERS, fetch_cluster
        clusters = {args.cluster: CLUSTERS[args.cluster]} if args.cluster else CLUSTERS
        for cluster, query in clusters.items():
            fetch_cluster(cluster, query, str(db_path),
                          api_key=args.api_key,
                          limit=args.limit,
                          dry_run=args.dry_run)
    else:
        print("\n[3/5] Skipping PubMed fetch (--skip-fetch)")

    if args.dry_run:
        print("\nDry run complete. Re-run without --dry-run to fetch.")
        return

    # ── Step 4: Build graph ───────────────────────────────────────────────────
    print("\n[4/5] Building knowledge graph...")
    from kb.build_graph import (
        get_db as bg_get_db, seed_entities, load_entities,
        populate_paper_entity, build_entity_relations,
        export_graph_json, export_paper_summaries
    )
    conn = bg_get_db(str(db_path))
    seed_entities(conn)
    entities = load_entities(conn)
    populate_paper_entity(conn, entities)
    build_entity_relations(conn)
    export_graph_json(conn, str(graph_out))
    export_paper_summaries(conn, str(md_out))
    conn.close()

    # ── Step 5: Export Claude context ─────────────────────────────────────────
    print("\n[5/5] Exporting Claude context...")
    conn = bg_get_db(str(db_path))
    from kb.query_kb import cmd_export_context
    cmd_export_context(conn, out_path=str(ctx_out))
    conn.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    conn = sqlite3.connect(str(db_path))
    total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    cluster_counts = conn.execute(
        "SELECT topic_cluster, COUNT(*) FROM papers GROUP BY topic_cluster"
    ).fetchall()
    conn.close()

    print(f"\n{'='*60}")
    print(f"Build complete!")
    print(f"  Total papers: {total}")
    for cluster, count in cluster_counts:
        print(f"    {cluster:<25}: {count:>4}")
    print(f"\n  Files written:")
    print(f"    {db_path}")
    print(f"    {graph_out}")
    print(f"    {md_out}")
    print(f"    {ctx_out}")
    print(f"\n  Query examples:")
    print(f"    python kb/query_kb.py --stats")
    print(f"    python kb/query_kb.py --q 'NQO2 blood biomarker'")
    print(f"    python kb/query_kb.py --entity NQO2 --show-papers")
    print(f"    python kb/query_kb.py --cluster nqo2")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
