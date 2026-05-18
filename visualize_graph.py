"""
TBI Knowledge Graph — Interactive PyVis Visualization
======================================================
Generates data/tbi_graph.html — open in any browser.

Usage:
    python visualize_graph.py                  # full graph
    python visualize_graph.py --min-papers 5   # only entities with 5+ papers
    python visualize_graph.py --min-edge 3     # only edges with 3+ shared papers
    python visualize_graph.py --cluster nqo2   # highlight one cluster's papers
"""

import argparse
import json
import sqlite3
from pathlib import Path

from pyvis.network import Network

ROOT = Path(__file__).parent
DB   = ROOT / "data" / "tbi_papers.db"
OUT  = ROOT / "data" / "tbi_graph.html"

# ── Colour palette by entity type ────────────────────────────────────────────
TYPE_STYLE = {
    "protein":    {"color": "#4C9BE8", "shape": "dot"},        # blue
    "rna":        {"color": "#F4A261", "shape": "diamond"},    # orange
    "metabolite": {"color": "#2A9D8F", "shape": "dot"},        # teal
    "pathway":    {"color": "#E76F51", "shape": "hexagon"},    # red-orange
    "process":    {"color": "#E76F51", "shape": "hexagon"},    # same as pathway
    "disease":    {"color": "#E63946", "shape": "star"},       # red
    "drug":       {"color": "#8338EC", "shape": "triangle"},   # purple
}
DEFAULT_STYLE = {"color": "#aaaaaa", "shape": "dot"}

# Special highlight for the core NQO2 pathway nodes
NQO2_PATHWAY = {
    "NQO2", "NQO1", "NRH", "miR-182", "ROS", "Kv2.1",
    "dopamine", "DRD1", "cAMP", "Nrf2", "HO-1", "SOD",
    "glutathione", "eIF2α", "PKR", "PERK", "eEF2",
    "ATF4", "CHOP", "S29434", "quercetin", "resveratrol",
    "QR2 inhibitor", "4-HNE", "catalase",
}


def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def build(min_papers: int, min_edge: int, highlight_cluster: str):
    conn = get_db()

    # ── Load entities ─────────────────────────────────────────────────────────
    entity_rows = conn.execute(
        "SELECT id, name, type FROM entities"
    ).fetchall()

    paper_counts = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT entity_id, COUNT(*) FROM paper_entity GROUP BY entity_id"
        )
    }

    # ── Load edges ────────────────────────────────────────────────────────────
    edge_rows = conn.execute("""
        SELECT er.source_id, er.target_id, er.weight,
               e1.name as src_name, e2.name as tgt_name
        FROM entity_relations er
        JOIN entities e1 ON e1.id = er.source_id
        JOIN entities e2 ON e2.id = er.target_id
        WHERE er.weight >= ?
    """, (min_edge,)).fetchall()

    # ── Cluster highlight: which entities appear in cluster papers? ───────────
    cluster_entities = set()
    if highlight_cluster:
        rows = conn.execute("""
            SELECT DISTINCT pe.entity_id
            FROM paper_entity pe
            JOIN papers p ON p.pmid = pe.pmid
            WHERE p.topic_cluster = ?
        """, (highlight_cluster,)).fetchall()
        cluster_entities = {r[0] for r in rows}

    conn.close()

    # ── Filter to nodes that appear in at least one qualifying edge ───────────
    active_nodes = set()
    for e in edge_rows:
        active_nodes.add(e["source_id"])
        active_nodes.add(e["target_id"])

    # ── Build PyVis network ───────────────────────────────────────────────────
    net = Network(
        height="920px",
        width="100%",
        bgcolor="#0f1117",
        font_color="#e0e0e0",
        notebook=False,
        directed=False,
    )

    net.barnes_hut(
        gravity=-8000,
        central_gravity=0.3,
        spring_length=180,
        spring_strength=0.04,
        damping=0.09,
    )

    added_nodes = set()
    for ent in entity_rows:
        eid   = ent["id"]
        name  = ent["name"]
        etype = ent["type"] or "protein"
        count = paper_counts.get(eid, 0)

        if eid not in active_nodes:
            continue
        if count < min_papers:
            continue

        style = TYPE_STYLE.get(etype, DEFAULT_STYLE)

        # Size: log-scaled on paper count, clamped 12–55
        size = max(12, min(55, 12 + count ** 0.55))

        # NQO2 pathway nodes get a distinct amber fill overriding the type colour
        is_nqo2 = name in NQO2_PATHWAY
        if is_nqo2:
            bg_color     = "#FFB703"   # amber — stands out on dark background
            border_color = "#FF8C00"   # darker orange border
            border_width = 3
            font_color   = "#1a1a1a"   # dark text on light node
        else:
            bg_color     = style["color"]
            border_color = style["color"]
            border_width = 1
            font_color   = "#ffffff"

        if highlight_cluster and eid in cluster_entities and not is_nqo2:
            border_color = "#FFFFFF"
            border_width = 2

        title = (
            f"<b>{name}</b><br>"
            f"Type: {etype}<br>"
            f"Papers: {count}"
            + ("<br><i>★ NQO2 pathway</i>" if is_nqo2 else "")
            + (f"<br><i>In cluster: {highlight_cluster}</i>"
               if highlight_cluster and eid in cluster_entities else "")
        )

        net.add_node(
            eid,
            label=name,
            title=title,
            color={"background": bg_color,
                   "border":     border_color,
                   "highlight":  {"background": "#FFE566", "border": "#FF8C00"}},
            size=size,
            shape=style["shape"],
            borderWidth=border_width,
            font={"size": max(10, min(18, 9 + count ** 0.4)),
                  "color": font_color},
        )
        added_nodes.add(eid)

    for edge in edge_rows:
        src, tgt = edge["source_id"], edge["target_id"]
        if src not in added_nodes or tgt not in added_nodes:
            continue
        weight = edge["weight"]
        width  = max(1, min(10, weight ** 0.6))
        opacity_hex = format(min(255, 60 + int(weight * 8)), "02x")
        color = f"#8888ff{opacity_hex}"
        net.add_edge(
            src, tgt,
            title=f"{edge['src_name']} ↔ {edge['tgt_name']}<br>{int(weight)} shared papers",
            width=width,
            color=color,
        )

    # ── Inject legend + controls HTML ─────────────────────────────────────────
    legend_html = """
<div style="position:fixed;top:16px;left:16px;z-index:999;
            background:#1a1d27;border:1px solid #333;border-radius:8px;
            padding:14px 18px;font-family:sans-serif;font-size:13px;color:#ddd;
            min-width:200px;box-shadow:0 4px 20px rgba(0,0,0,0.5)">
  <div style="font-weight:bold;font-size:15px;margin-bottom:10px;color:#fff">
    TBI Knowledge Graph
  </div>
  <div style="margin-bottom:8px;font-size:11px;color:#aaa">
    2,679 papers &nbsp;·&nbsp; 74 entities &nbsp;·&nbsp; 767 edges
  </div>

  <div style="margin-bottom:6px;font-weight:bold;color:#ccc">Node type</div>
  <div style="display:flex;flex-direction:column;gap:4px;margin-bottom:12px">
    <span><span style="color:#4C9BE8">●</span> Protein</span>
    <span><span style="color:#F4A261">◆</span> RNA</span>
    <span><span style="color:#2A9D8F">●</span> Metabolite</span>
    <span><span style="color:#E76F51">⬡</span> Pathway / Process</span>
    <span><span style="color:#E63946">★</span> Disease</span>
    <span><span style="color:#8338EC">▲</span> Drug / Platform</span>
  </div>

  <div style="margin-bottom:6px;font-weight:bold;color:#ccc">Node size</div>
  <div style="font-size:12px;color:#aaa;margin-bottom:12px">
    ∝ number of papers mentioning entity
  </div>

  <div style="margin-bottom:6px;font-weight:bold;color:#ccc">Highlight</div>
  <div style="font-size:12px;color:#aaa;margin-bottom:4px">
    <span style="background:#FFB703;color:#1a1a1a;padding:1px 5px;border-radius:3px">amber</span>
    = NQO2 pathway node
  </div>

  <hr style="border-color:#333;margin:10px 0">
  <div style="font-size:11px;color:#888">
    Drag to pan &nbsp;·&nbsp; Scroll to zoom<br>
    Hover for details &nbsp;·&nbsp; Click to select
  </div>
</div>
"""

    # Write HTML and inject legend
    net.save_graph(str(OUT))
    html = OUT.read_text()
    html = html.replace("</body>", legend_html + "\n</body>")
    OUT.write_text(html)

    print(f"\n✓  Graph written to: {OUT}")
    print(f"   Nodes: {len(added_nodes)}  |  Edges: {len(edge_rows)}")
    print(f"   Open in browser:  open {OUT}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-papers", type=int, default=2,
                        help="Min papers for a node to appear (default 2)")
    parser.add_argument("--min-edge",   type=int, default=2,
                        help="Min shared papers for an edge to appear (default 2)")
    parser.add_argument("--cluster",    default=None,
                        help="Highlight entities from this cluster (e.g. nqo2)")
    args = parser.parse_args()

    print(f"Building graph  min-papers={args.min_papers}  min-edge={args.min_edge}"
          + (f"  highlight={args.cluster}" if args.cluster else ""))
    build(args.min_papers, args.min_edge, args.cluster)


if __name__ == "__main__":
    main()
