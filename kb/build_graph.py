"""
TBI Knowledge Graph Builder
============================
Reads papers from SQLite, extracts entity mentions via keyword matching,
builds a co-occurrence graph with NetworkX, and exports:
  - data/knowledge_graph.json   (machine-readable, for Claude context)
  - data/paper_summaries.md     (human-readable index)

Usage:
    python kb/build_graph.py [--db data/tbi_papers.db]
"""

import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

try:
    import networkx as nx
except ImportError:
    print("Install networkx: pip install networkx --break-system-packages")
    raise

# ── Entity seed catalog ────────────────────────────────────────────────────────
# Format: (canonical_name, type, [aliases...])
ENTITY_SEEDS = [
    # ── NQO2/QR2 enzyme ──────────────────────────────────────────────────────
    ("NQO2",         "protein",  ["NQO2", "QR2", "quinone reductase 2", "quinone reductase-2",
                                   "NAD(P)H quinone oxidoreductase 2", "NRH quinone oxidoreductase",
                                   "NRH:quinone oxidoreductase", "NRH:quinone reductase"]),
    ("NQO1",         "protein",  ["NQO1", "QR1", "quinone reductase 1", "DT-diaphorase",
                                   "NAD(P)H quinone oxidoreductase 1"]),
    ("NRH",          "metabolite", ["NRH", "dihydronicotinamide riboside",
                                    "N-ribosyldihydronicotinamide", "NRH substrate"]),

    # ── NQO2 upstream signaling: dopamine → DRD1 → miR-182 → NQO2 ───────────
    ("dopamine",     "metabolite", ["dopamine", "DA", "catecholamine", "dopaminergic"]),
    ("DRD1",         "protein",  ["DRD1", "dopamine D1 receptor", "D1R", "D1 receptor",
                                   "dopamine receptor D1"]),
    ("cAMP",         "metabolite", ["cAMP", "cyclic AMP", "adenylyl cyclase", "PKA",
                                    "protein kinase A", "cAMP-PKA"]),
    ("miR-182",      "rna",      ["miR-182", "miRNA-182", "hsa-mir-182", "microRNA-182"]),

    # ── NQO2 downstream: ROS → Kv2.1 oxidation → interneuron excitability ────
    ("ROS",          "metabolite", ["ROS", "reactive oxygen species", "superoxide",
                                    "hydrogen peroxide", "free radicals"]),
    ("Kv2.1",        "protein",  ["Kv2.1", "KCNB1", "potassium channel Kv2.1",
                                   "Kv2.1 channel", "delayed rectifier potassium"]),

    # ── NQO2 inhibitors (pharmacology arm) ───────────────────────────────────
    ("S29434",       "drug",     ["S29434", "S-29434"]),
    ("quercetin",    "drug",     ["quercetin", "quercetin inhibitor"]),
    ("resveratrol",  "drug",     ["resveratrol", "trans-resveratrol"]),

    # ── Antioxidant response arm: NQO2 modulates Nrf2 ────────────────────────
    ("Nrf2",         "protein",  ["Nrf2", "NFE2L2", "NF-E2-related factor 2",
                                   "nuclear factor erythroid 2"]),
    ("HO-1",         "protein",  ["HO-1", "HMOX1", "heme oxygenase 1", "heme oxygenase-1"]),
    ("SOD",          "protein",  ["SOD", "SOD1", "SOD2", "superoxide dismutase",
                                   "Cu/Zn-SOD", "Mn-SOD"]),
    ("glutathione",  "metabolite", ["glutathione", "GSH", "GSSG", "glutathione peroxidase",
                                    "GPx", "oxidized glutathione"]),
    ("catalase",     "protein",  ["catalase", "CAT", "H2O2 degradation"]),
    ("4-HNE",        "metabolite", ["4-HNE", "4-hydroxynonenal", "HNE", "lipid peroxidation product",
                                    "aldehyde adduct"]),

    # ── ISR / translation regulation arm ─────────────────────────────────────
    ("eIF2α",        "protein",  ["eIF2α", "eIF2alpha", "EIF2S1", "EIF2A",
                                   "eIF2 alpha subunit"]),
    ("PKR",          "protein",  ["PKR", "EIF2AK2", "protein kinase R",
                                   "dsRNA-activated kinase", "dsRNA-dependent kinase"]),
    ("PERK",         "protein",  ["PERK", "EIF2AK3", "protein kinase R-like ER kinase",
                                   "ER stress kinase"]),
    ("GCN2",         "protein",  ["GCN2", "EIF2AK4", "general control non-derepressible 2"]),
    ("eEF2",         "protein",  ["eEF2", "EEF2", "eukaryotic elongation factor 2"]),
    ("ATF4",         "protein",  ["ATF4", "activating transcription factor 4",
                                   "CREB2", "ATF-4"]),
    ("CHOP",         "protein",  ["CHOP", "DDIT3", "GADD153", "C/EBP homologous protein",
                                   "DNA damage-inducible transcript 3"]),
    ("eIF2B",        "protein",  ["eIF2B", "eIF2B epsilon", "guanine nucleotide exchange factor eIF2B"]),

    # ── Synaptic plasticity / memory effectors (Rosenblum lab context) ───────
    ("CaMKII",       "protein",  ["CaMKII", "CaMKIIα", "CAMK2A", "calcium calmodulin kinase II",
                                   "calcium/calmodulin-dependent protein kinase II"]),
    ("Arc",          "protein",  ["Arc", "Arg3.1", "activity-regulated cytoskeleton",
                                   "activity-regulated cytoskeleton-associated protein"]),
    ("AMPA receptor","protein",  ["AMPA receptor", "AMPAR", "GluA1", "GluA2", "GRIA",
                                   "alpha-amino-3-hydroxy-5-methyl-4-isoxazolepropionic acid receptor"]),
    ("NMDA receptor","protein",  ["NMDA receptor", "NMDAR", "GluN1", "GluN2",
                                   "N-methyl-D-aspartate receptor"]),

    # ── Additional TBI blood biomarkers ──────────────────────────────────────
    ("NSE",          "protein",  ["NSE", "neuron-specific enolase", "ENO2",
                                   "gamma-enolase"]),
    ("MBP",          "protein",  ["MBP", "myelin basic protein", "myelin"]),
    ("VILIP-1",      "protein",  ["VILIP-1", "visinin-like protein 1", "VSNL1"]),

    # Established TBI blood biomarkers
    ("GFAP",         "protein",  ["GFAP", "glial fibrillary acidic protein", "glial fibillary"]),
    ("UCH-L1",       "protein",  ["UCH-L1", "UCHL1", "ubiquitin C-terminal hydrolase L1",
                                   "ubiquitin carboxyl-terminal hydrolase isozyme L1", "PGP9.5"]),
    ("S100B",        "protein",  ["S100B", "S100 beta", "S100-beta", "S100β"]),
    ("NfL",          "protein",  ["NfL", "NFL", "neurofilament light", "neurofilament light chain",
                                   "NEFL", "NF-L"]),
    ("NfH",          "protein",  ["NfH", "neurofilament heavy", "NF-H", "NEFH"]),
    ("tau",          "protein",  ["tau", "MAPT", "microtubule-associated protein tau"]),
    ("p-tau",        "protein",  ["p-tau", "phospho-tau", "phosphorylated tau", "tau-181",
                                   "ptau181", "tau phosphorylation"]),
    ("BDNF",         "protein",  ["BDNF", "brain-derived neurotrophic factor"]),

    # Neuroinflammation markers
    ("Iba1",         "protein",  ["Iba1", "IBA-1", "AIF-1", "ionized calcium binding adaptor molecule 1"]),
    ("IL-6",         "protein",  ["IL-6", "interleukin-6", "interleukin 6"]),
    ("TNF-α",        "protein",  ["TNF-α", "TNF-alpha", "tumor necrosis factor", "TNF"]),
    ("IL-1β",        "protein",  ["IL-1β", "IL-1beta", "interleukin-1 beta"]),
    ("Aβ42",         "protein",  ["Aβ42", "amyloid beta 42", "amyloid-β42", "Abeta42", "amyloid β"]),

    # RNA biomarkers in TBI
    ("VLDLR-AS1",    "rna",      ["VLDLR-AS1", "VLDLR antisense", "VLDR-AS1"]),
    ("MALAT1",       "rna",      ["MALAT1", "NEAT2", "nuclear-enriched abundant transcript 2"]),
    ("GAS5",         "rna",      ["GAS5", "growth arrest-specific 5"]),
    ("NEAT1",        "rna",      ["NEAT1", "nuclear-enriched abundant transcript 1"]),
    ("miR-21",       "rna",      ["miR-21", "miRNA-21", "hsa-mir-21"]),
    ("miR-let-7",    "rna",      ["let-7", "miR-let-7", "let7"]),

    # Pathways / processes
    ("neuroinflammation", "pathway", ["neuroinflammation", "neuroinflammatory", "microglial activation",
                                       "astrocyte activation", "glial activation"]),
    ("oxidative stress", "pathway", ["oxidative stress", "ROS production", "oxidative damage",
                                      "redox stress", "redox imbalance", "oxidative burden"]),
    ("ISR",          "pathway",  ["integrated stress response", "ISR", "stress response pathway"]),
    ("BBB",          "process",  ["blood-brain barrier", "BBB", "BBB disruption",
                                   "blood brain barrier permeability"]),

    # Clinical entities
    ("mTBI",         "disease",  ["mTBI", "mild TBI", "mild traumatic brain injury", "concussion",
                                   "sports concussion"]),
    ("TBI",          "disease",  ["traumatic brain injury", "TBI", "brain injury"]),
    ("PPCS",         "disease",  ["post-concussion syndrome", "PPCS", "post-concussion symptoms",
                                   "persistent post-concussion", "PCS"]),
    ("CTE",          "disease",  ["CTE", "chronic traumatic encephalopathy",
                                   "chronic traumatic encephalopath"]),
    ("Alzheimer",    "disease",  ["Alzheimer", "Alzheimer's disease", "AD", "dementia",
                                   "neurodegeneration"]),

    # Diagnostic platforms
    ("i-STAT TBI",   "drug",     ["i-STAT TBI", "Abbott TBI", "Abbott i-STAT", "Banyan Brain Trauma"]),
    ("Simoa",        "drug",     ["Simoa", "single molecule array", "digital ELISA"]),
    ("Olink",        "drug",     ["Olink", "proximity extension assay", "Olink proteomics"]),
    ("Quanterix",    "drug",     ["Quanterix", "HD-X"]),

    # Therapeutic compounds
    ("QR2 inhibitor","drug",     ["QR2 inhibitor", "QR2i", "quinone reductase inhibitor"]),
    ("lecanemab",    "drug",     ["lecanemab", "Leqembi", "BAN2401"]),
    ("donanemab",    "drug",     ["donanemab", "Kisunla"]),
]


# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def seed_entities(conn: sqlite3.Connection):
    for name, etype, aliases in ENTITY_SEEDS:
        conn.execute("""
            INSERT OR IGNORE INTO entities (name, type, aliases)
            VALUES (?, ?, ?)
        """, (name, etype, json.dumps(aliases)))
    conn.commit()


def load_entities(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, name, type, aliases FROM entities").fetchall()
    entities = []
    for row in rows:
        aliases = json.loads(row["aliases"] or "[]")
        patterns = [re.compile(r'\b' + re.escape(a) + r'\b', re.IGNORECASE) for a in aliases]
        entities.append({
            "id":       row["id"],
            "name":     row["name"],
            "type":     row["type"],
            "aliases":  aliases,
            "patterns": patterns,
        })
    return entities


# ── Entity extraction ──────────────────────────────────────────────────────────

def extract_entities_from_text(text: str, entities: list[dict]) -> list[tuple]:
    """Return list of (entity_id, relation, context_snippet) for entities found in text."""
    if not text:
        return []
    found = []
    for ent in entities:
        for pat in ent["patterns"]:
            m = pat.search(text)
            if m:
                start = max(0, m.start() - 80)
                end   = min(len(text), m.end() + 80)
                context = "..." + text[start:end].strip() + "..."
                # Infer relation from surrounding text
                relation = infer_relation(text, m)
                found.append((ent["id"], relation, context))
                break  # one match per entity per text
    return found


ELEVATED_WORDS = re.compile(r'\b(elevated|increased|higher|upregulated|raised)\b', re.IGNORECASE)
REDUCED_WORDS  = re.compile(r'\b(reduced|decreased|lower|downregulated|diminished)\b', re.IGNORECASE)
MEASURES_WORDS = re.compile(r'\b(measured|detected|quantified|assessed|determined|plasma|serum|blood)\b', re.IGNORECASE)
TARGETS_WORDS  = re.compile(r'\b(inhibit|target|block|suppress|antagonize|treat)\b', re.IGNORECASE)


def infer_relation(text: str, match) -> str:
    window = text[max(0, match.start()-120):match.end()+120]
    if ELEVATED_WORDS.search(window):
        return "finds_elevated"
    if REDUCED_WORDS.search(window):
        return "finds_reduced"
    if TARGETS_WORDS.search(window):
        return "targets"
    if MEASURES_WORDS.search(window):
        return "measures"
    return "studies"


def populate_paper_entity(conn: sqlite3.Connection, entities: list[dict]):
    papers = conn.execute(
        "SELECT pmid, title, abstract FROM papers WHERE abstract IS NOT NULL"
    ).fetchall()

    print(f"  Scanning {len(papers)} paper abstracts for entity mentions...")
    total_links = 0

    for paper in papers:
        text = f"{paper['title'] or ''} {paper['abstract'] or ''}"
        mentions = extract_entities_from_text(text, entities)
        for entity_id, relation, context in mentions:
            conn.execute("""
                INSERT OR REPLACE INTO paper_entity (pmid, entity_id, relation, context)
                VALUES (?, ?, ?, ?)
            """, (paper["pmid"], entity_id, relation, context))
        total_links += len(mentions)

    conn.commit()
    print(f"  Created {total_links} paper-entity links")


# ── Knowledge graph ────────────────────────────────────────────────────────────

def build_entity_relations(conn: sqlite3.Connection):
    """Build entity co-occurrence edges from paper_entity links."""
    # Group entity_ids by paper
    paper_entities: dict[str, list[int]] = defaultdict(list)
    for row in conn.execute("SELECT pmid, entity_id FROM paper_entity"):
        paper_entities[row["pmid"]].append(row["entity_id"])

    # Count co-occurrences
    cooccur: dict[tuple, list] = defaultdict(list)
    for pmid, eids in paper_entities.items():
        eids = sorted(set(eids))
        for i in range(len(eids)):
            for j in range(i+1, len(eids)):
                key = (eids[i], eids[j])
                cooccur[key].append(pmid)

    print(f"  Building {len(cooccur)} entity co-occurrence edges...")

    conn.execute("DELETE FROM entity_relations")
    for (src, tgt), pmids in cooccur.items():
        conn.execute("""
            INSERT OR REPLACE INTO entity_relations
                (source_id, target_id, relation, evidence_pmids, weight)
            VALUES (?, ?, 'co-occurs', ?, ?)
        """, (src, tgt, json.dumps(pmids[:20]), len(pmids)))
    conn.commit()


def export_graph_json(conn: sqlite3.Connection, out_path: str):
    """Export the full knowledge graph as JSON for Claude context loading."""
    G = nx.Graph()

    # Add entity nodes
    for row in conn.execute("SELECT id, name, type FROM entities"):
        G.add_node(row["id"], name=row["name"], type=row["type"])

    # Add edges
    for row in conn.execute(
        "SELECT source_id, target_id, weight, evidence_pmids FROM entity_relations WHERE weight >= 2"
    ):
        G.add_edge(row["source_id"], row["target_id"],
                   weight=row["weight"],
                   pmids=json.loads(row["evidence_pmids"] or "[]"))

    # Compute centrality
    centrality = nx.degree_centrality(G) if G.number_of_nodes() > 0 else {}

    # Build output
    entity_map = {
        row["id"]: {"name": row["name"], "type": row["type"]}
        for row in conn.execute("SELECT id, name, type FROM entities")
    }

    nodes = []
    for node_id, data in G.nodes(data=True):
        paper_count = conn.execute(
            "SELECT COUNT(*) FROM paper_entity WHERE entity_id = ?", (node_id,)
        ).fetchone()[0]
        nodes.append({
            "id":           node_id,
            "name":         data.get("name"),
            "type":         data.get("type"),
            "paper_count":  paper_count,
            "centrality":   round(centrality.get(node_id, 0), 4),
        })

    edges = []
    for u, v, data in G.edges(data=True):
        edges.append({
            "source":   entity_map.get(u, {}).get("name"),
            "target":   entity_map.get(v, {}).get("name"),
            "weight":   data.get("weight", 1),
            "n_papers": data.get("weight", 1),
        })

    # Per-cluster stats
    cluster_stats = {
        row[0]: row[1]
        for row in conn.execute("SELECT topic_cluster, COUNT(*) FROM papers GROUP BY topic_cluster")
    }

    out = {
        "generated_at":  __import__("datetime").datetime.utcnow().isoformat(),
        "n_papers":      conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
        "n_entities":    len(nodes),
        "n_edges":       len(edges),
        "cluster_stats": cluster_stats,
        "nodes":         sorted(nodes, key=lambda x: -x["paper_count"]),
        "edges":         sorted(edges, key=lambda x: -x["weight"])[:500],
    }

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)

    print(f"  Exported graph: {len(nodes)} nodes, {len(edges)} edges → {out_path}")
    return G


def export_paper_summaries(conn: sqlite3.Connection, out_path: str):
    """Export human-readable markdown index of all papers."""
    papers = conn.execute("""
        SELECT p.pmid, p.title, p.authors, p.journal, p.year,
               p.topic_cluster, p.doi, p.abstract
        FROM papers p
        WHERE p.title IS NOT NULL
        ORDER BY p.topic_cluster, p.year DESC
    """).fetchall()

    # Get entity mentions per paper (top 5)
    def get_entities(pmid):
        rows = conn.execute("""
            SELECT e.name FROM paper_entity pe
            JOIN entities e ON e.id = pe.entity_id
            WHERE pe.pmid = ?
            LIMIT 5
        """, (pmid,)).fetchall()
        return [r[0] for r in rows]

    lines = [
        "# TBI Knowledge Base — Paper Index",
        f"*Generated: {__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d')}*",
        f"*Total papers: {len(papers)}*\n",
    ]

    current_cluster = None
    for p in papers:
        if p["topic_cluster"] != current_cluster:
            current_cluster = p["topic_cluster"]
            lines.append(f"\n## Cluster: {current_cluster}")
            lines.append("")

        entities = get_entities(p["pmid"])
        entity_str = ", ".join(entities) if entities else "—"
        abstract_preview = (p["abstract"] or "")[:200].replace("\n", " ")
        if len(p["abstract"] or "") > 200:
            abstract_preview += "..."

        lines += [
            f"### {p['title'] or 'Untitled'}",
            f"**Authors:** {p['authors'] or '—'}  ",
            f"**Journal:** {p['journal'] or '—'} ({p['year'] or '—'})  ",
            f"**PMID:** {p['pmid']}  " + (f"**DOI:** {p['doi']}" if p['doi'] else ""),
            f"**Entities:** {entity_str}  ",
            f"**Abstract:** {abstract_preview}",
            "",
        ]

    with open(out_path, "w") as f:
        f.write("\n".join(lines))

    print(f"  Exported summaries: {len(papers)} papers → {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build TBI knowledge graph from SQLite")
    parser.add_argument("--db",   default="data/tbi_papers.db")
    parser.add_argument("--out",  default="data/knowledge_graph.json")
    parser.add_argument("--md",   default="data/paper_summaries.md")
    args = parser.parse_args()

    base = Path(__file__).parent.parent
    db_path  = base / args.db
    out_path = base / args.out
    md_path  = base / args.md

    if not db_path.exists():
        print(f"DB not found: {db_path}. Run fetch_papers.py first.")
        return

    conn = get_db(str(db_path))

    print("\n[1/4] Seeding entity catalog...")
    seed_entities(conn)
    n_entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    print(f"  {n_entities} entities seeded")

    print("\n[2/4] Extracting entity mentions from abstracts...")
    entities = load_entities(conn)
    populate_paper_entity(conn, entities)

    print("\n[3/4] Building co-occurrence graph...")
    build_entity_relations(conn)

    print("\n[4/4] Exporting...")
    export_graph_json(conn, str(out_path))
    export_paper_summaries(conn, str(md_path))

    conn.close()
    print("\nDone. Files written:")
    print(f"  {out_path}")
    print(f"  {md_path}")


if __name__ == "__main__":
    main()
