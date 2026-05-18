"""
TBI Knowledge Graph — Interactive PyVis Visualization
======================================================
Generates data/tbi_graph.html — open in any browser.
Includes a live filter panel: node types, NQO2-only, cluster, min-papers, search.

Usage:
    python visualize_graph.py                  # full graph
    python visualize_graph.py --min-papers 5   # only entities with 5+ papers
    python visualize_graph.py --min-edge 3     # only edges with 3+ shared papers
"""

import argparse
import json
import sqlite3
from pathlib import Path

from pyvis.network import Network

ROOT = Path(__file__).parent
DB   = ROOT / "data" / "tbi_papers.db"
OUT  = ROOT / "data" / "tbi_graph.html"

TYPE_STYLE = {
    "protein":    {"color": "#4C9BE8", "shape": "dot"},
    "rna":        {"color": "#F4A261", "shape": "diamond"},
    "metabolite": {"color": "#2A9D8F", "shape": "dot"},
    "pathway":    {"color": "#E76F51", "shape": "hexagon"},
    "process":    {"color": "#E76F51", "shape": "hexagon"},
    "disease":    {"color": "#E63946", "shape": "star"},
    "drug":       {"color": "#8338EC", "shape": "triangle"},
}
DEFAULT_STYLE = {"color": "#aaaaaa", "shape": "dot"}

NQO2_PATHWAY = {
    "NQO2", "NQO1", "NRH", "miR-182", "ROS", "Kv2.1",
    "dopamine", "DRD1", "cAMP", "Nrf2", "HO-1", "SOD",
    "glutathione", "eIF2α", "PKR", "PERK", "eEF2",
    "ATF4", "CHOP", "S29434", "quercetin", "resveratrol",
    "QR2 inhibitor", "4-HNE", "catalase",
}

CLUSTER_LABELS = {
    "nqo2":           "NQO2 / QR2 pathway",
    "gfap_uchl1":     "GFAP + UCH-L1 diagnostics",
    "ppcs_prognosis": "PPCS prognosis",
    "exosomal_rna":   "Exosomal RNA",
    "tbi_mild_blood": "mTBI blood (2018–2026)",
    "tbi_proteomics": "TBI proteomics",
    "tbi_panel_poc":  "Multi-marker panels + POC",
    "nfl_tau":        "NfL + tau",
    "proteostasis":   "Proteostasis (p62/UPS)",
}


def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def build(min_papers: int, min_edge: int):
    conn = get_db()

    entity_rows = conn.execute("SELECT id, name, type FROM entities").fetchall()
    paper_counts = {
        r[0]: r[1] for r in conn.execute(
            "SELECT entity_id, COUNT(*) FROM paper_entity GROUP BY entity_id"
        )
    }
    edge_rows = conn.execute("""
        SELECT er.source_id, er.target_id, er.weight,
               e1.name as src_name, e2.name as tgt_name
        FROM entity_relations er
        JOIN entities e1 ON e1.id = er.source_id
        JOIN entities e2 ON e2.id = er.target_id
        WHERE er.weight >= ?
    """, (min_edge,)).fetchall()

    # Cluster memberships per entity
    cluster_rows = conn.execute("""
        SELECT pe.entity_id, p.topic_cluster
        FROM paper_entity pe
        JOIN papers p ON p.pmid = pe.pmid
        WHERE p.topic_cluster IS NOT NULL
        GROUP BY pe.entity_id, p.topic_cluster
    """).fetchall()
    entity_clusters: dict[int, list[str]] = {}
    for r in cluster_rows:
        entity_clusters.setdefault(r["entity_id"], []).append(r["topic_cluster"])

    conn.close()

    active_nodes = {e["source_id"] for e in edge_rows} | {e["target_id"] for e in edge_rows}

    # ── Build node metadata dict for JS injection ─────────────────────────────
    node_meta = {}
    for ent in entity_rows:
        eid   = ent["id"]
        name  = ent["name"]
        etype = ent["type"] or "protein"
        count = paper_counts.get(eid, 0)
        if eid not in active_nodes or count < min_papers:
            continue
        node_meta[eid] = {
            "name":        name,
            "type":        etype,
            "is_nqo2":     name in NQO2_PATHWAY,
            "paper_count": count,
            "clusters":    entity_clusters.get(eid, []),
        }

    # ── Build PyVis network ───────────────────────────────────────────────────
    net = Network(
        height="100vh",
        width="100%",
        bgcolor="#0f1117",
        font_color="#e0e0e0",
        notebook=False,
        directed=False,
    )
    net.barnes_hut(gravity=-8000, central_gravity=0.3,
                   spring_length=180, spring_strength=0.04, damping=0.09)

    for eid, meta in node_meta.items():
        etype = meta["type"]
        name  = meta["name"]
        count = meta["paper_count"]
        style = TYPE_STYLE.get(etype, DEFAULT_STYLE)
        size  = max(12, min(55, 12 + count ** 0.55))

        is_nqo2 = meta["is_nqo2"]
        bg_color     = "#FFB703" if is_nqo2 else style["color"]
        border_color = "#FF8C00" if is_nqo2 else style["color"]
        font_color   = "#1a1a1a" if is_nqo2 else "#ffffff"
        border_width = 3 if is_nqo2 else 1

        clusters_str = ", ".join(meta["clusters"]) if meta["clusters"] else "—"
        title = (
            f"<b>{name}</b><br>"
            f"Type: {etype}<br>"
            f"Papers: {count}<br>"
            f"Clusters: {clusters_str}"
            + ("<br><i>★ NQO2 pathway</i>" if is_nqo2 else "")
        )

        net.add_node(
            eid, label=name, title=title,
            color={"background": bg_color, "border": border_color,
                   "highlight": {"background": "#FFE566", "border": "#FF8C00"}},
            size=size, shape=style["shape"], borderWidth=border_width,
            font={"size": max(10, min(18, 9 + count ** 0.4)), "color": font_color},
        )

    edge_id = 0
    for edge in edge_rows:
        src, tgt = edge["source_id"], edge["target_id"]
        if src not in node_meta or tgt not in node_meta:
            continue
        w = edge["weight"]
        net.add_edge(
            src, tgt,
            title=f"{edge['src_name']} ↔ {edge['tgt_name']}<br>{int(w)} shared papers",
            width=max(1, min(10, w ** 0.6)),
            color=f"#8888ff{format(min(255, 60 + int(w * 8)), '02x')}",
        )
        edge_id += 1

    net.save_graph(str(OUT))

    # ── Inject filter panel + JS ──────────────────────────────────────────────
    html = OUT.read_text()
    html = html.replace("</body>", _controls_html(node_meta, min_papers, min_edge) + "\n</body>")

    # Push graph canvas right to make room for panel
    html = html.replace(
        "#mynetwork {",
        "#mynetwork { margin-left: 270px !important; width: calc(100% - 270px) !important;"
    )

    OUT.write_text(html)
    print(f"\n✓  Graph written to: {OUT}")
    print(f"   Nodes: {len(node_meta)}  |  Edges: {edge_id}")
    print(f"   Open in browser:  open {OUT}")


def _controls_html(node_meta: dict, min_papers_default: int, min_edge_default: int) -> str:
    node_meta_js  = json.dumps(node_meta)
    cluster_opts  = "".join(
        f'<option value="{k}">{v}</option>'
        for k, v in CLUSTER_LABELS.items()
    )
    type_colors = {
        "protein":    "#4C9BE8",
        "rna":        "#F4A261",
        "metabolite": "#2A9D8F",
        "pathway":    "#E76F51",
        "disease":    "#E63946",
        "drug":       "#8338EC",
    }
    type_checkboxes = "".join(
        f"""<label class="type-check">
              <input type="checkbox" class="type-cb" value="{t}" checked>
              <span class="dot" style="background:{c}"></span>{t.capitalize()}
            </label>"""
        for t, c in type_colors.items()
    )

    return f"""
<style>
  #ctrl {{
    position: fixed; top: 0; left: 0; height: 100vh; width: 255px;
    background: #14161f; border-right: 1px solid #2a2d3a;
    overflow-y: auto; z-index: 1000; padding: 14px 14px 20px;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 13px; color: #ccc; box-sizing: border-box;
  }}
  #ctrl h2 {{ margin: 0 0 4px; font-size: 15px; color: #fff; }}
  #ctrl .sub {{ font-size: 11px; color: #666; margin-bottom: 14px; }}
  #ctrl .section {{ margin-top: 14px; }}
  #ctrl .section-title {{
    font-size: 10px; text-transform: uppercase; letter-spacing: .08em;
    color: #555; margin-bottom: 7px;
  }}
  #ctrl input[type=text] {{
    width: 100%; padding: 6px 8px; background: #1e2130; border: 1px solid #333;
    border-radius: 5px; color: #ddd; font-size: 13px; box-sizing: border-box;
  }}
  #ctrl input[type=text]:focus {{ outline: none; border-color: #4C9BE8; }}
  .type-check {{
    display: flex; align-items: center; gap: 6px;
    cursor: pointer; padding: 3px 0;
  }}
  .type-check input {{ margin: 0; accent-color: #4C9BE8; cursor: pointer; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  #ctrl select {{
    width: 100%; padding: 5px 6px; background: #1e2130; border: 1px solid #333;
    border-radius: 5px; color: #ddd; font-size: 12px;
  }}
  #ctrl input[type=range] {{ width: 100%; accent-color: #4C9BE8; margin-top: 4px; }}
  .slider-row {{ display: flex; justify-content: space-between;
                 font-size: 11px; color: #888; margin-top: 2px; }}
  .toggle-btn {{
    width: 100%; padding: 6px; border-radius: 5px; cursor: pointer;
    border: 1px solid #333; font-size: 12px; text-align: left;
    background: #1e2130; color: #ccc; margin-bottom: 4px;
  }}
  .toggle-btn.active {{ background: #FFB703; color: #1a1a1a;
                         border-color: #FF8C00; font-weight: 600; }}
  #reset-btn {{
    width: 100%; padding: 7px; margin-top: 16px; border-radius: 5px;
    border: 1px solid #444; background: #1e2130; color: #aaa;
    font-size: 12px; cursor: pointer;
  }}
  #reset-btn:hover {{ background: #2a2d3a; color: #fff; }}
  #fit-btn {{
    width: 100%; padding: 7px; margin-top: 6px; border-radius: 5px;
    border: 1px solid #444; background: #1e2130; color: #aaa;
    font-size: 12px; cursor: pointer;
  }}
  #fit-btn:hover {{ background: #2a2d3a; color: #fff; }}
  #stats-bar {{
    margin-top: 14px; padding: 8px; background: #1a1d27;
    border-radius: 5px; font-size: 11px; color: #777; line-height: 1.7;
  }}
  #stats-bar b {{ color: #aaa; }}
  .amber-dot {{ display:inline-block; width:8px; height:8px;
                background:#FFB703; border-radius:50%; margin-right:4px; }}
</style>

<div id="ctrl">
  <h2>TBI Knowledge Graph</h2>
  <div class="sub">2,679 papers · 74 entities · 767 edges</div>

  <!-- Search -->
  <div class="section">
    <div class="section-title">Search node</div>
    <input type="text" id="search-input" placeholder="e.g. NQO2, GFAP, tau…">
  </div>

  <!-- Node types -->
  <div class="section">
    <div class="section-title">Node type</div>
    {type_checkboxes}
  </div>

  <!-- NQO2 pathway -->
  <div class="section">
    <div class="section-title">NQO2 / QR2 pathway</div>
    <button class="toggle-btn" id="nqo2-btn" onclick="toggleNQO2()">
      <span class="amber-dot"></span>Show NQO2 pathway only
    </button>
  </div>

  <!-- Cluster -->
  <div class="section">
    <div class="section-title">Paper cluster</div>
    <select id="cluster-sel" onchange="applyFilters()">
      <option value="all">All clusters</option>
      {cluster_opts}
    </select>
  </div>

  <!-- Min papers slider -->
  <div class="section">
    <div class="section-title">Min papers per node</div>
    <input type="range" id="min-papers" min="1" max="50"
           value="{min_papers_default}" oninput="updateSlider('min-papers','min-papers-val'); applyFilters()">
    <div class="slider-row"><span>1</span><span id="min-papers-val">{min_papers_default}</span><span>50</span></div>
  </div>

  <!-- Min edge slider -->
  <div class="section">
    <div class="section-title">Min shared papers per edge</div>
    <input type="range" id="min-edge" min="1" max="30"
           value="{min_edge_default}" oninput="updateSlider('min-edge','min-edge-val'); applyFilters()">
    <div class="slider-row"><span>1</span><span id="min-edge-val">{min_edge_default}</span><span>30</span></div>
  </div>

  <button id="reset-btn" onclick="resetFilters()">↺  Reset all filters</button>
  <button id="fit-btn"   onclick="network.fit()">⤢  Fit to screen</button>

  <div id="stats-bar">
    <b id="stat-nodes">—</b> nodes visible<br>
    <b id="stat-edges">—</b> edges visible
  </div>

  <!-- Rotation -->
  <div class="section" style="border-top:1px solid #2a2d3a;padding-top:12px;margin-top:12px">
    <div class="section-title">⟳ Rotation</div>
    <button class="toggle-btn" id="rotate-btn" onclick="toggleAutoRotate()">
      ↻  Auto-rotate
    </button>
    <div style="margin-top:9px">
      <div class="section-title" style="margin-bottom:3px">Speed</div>
      <input type="range" id="rot-speed" min="1" max="10" value="3"
             oninput="rotSpeed=parseInt(this.value);document.getElementById('rot-speed-val').textContent=this.value">
      <div class="slider-row"><span>slow</span><span id="rot-speed-val">3</span><span>fast</span></div>
    </div>
    <div style="margin-top:9px">
      <div class="section-title" style="margin-bottom:3px">Manual angle</div>
      <input type="range" id="rot-angle" min="0" max="360" value="0"
             oninput="setManualRotation(parseFloat(this.value))">
      <div class="slider-row"><span>0°</span><span id="rot-angle-val">0°</span><span>360°</span></div>
    </div>
    <button onclick="captureBasePositions()" style="width:100%;padding:5px;margin-top:8px;
            border-radius:5px;border:1px solid #333;background:#1e2130;color:#777;
            font-size:11px;cursor:pointer;text-align:left;">
      📍 Refreeze layout
    </button>
  </div>

  <!-- Legend -->
  <div class="section" style="margin-top:16px;border-top:1px solid #2a2d3a;padding-top:12px">
    <div class="section-title">Legend</div>
    <div style="line-height:2">
      <span class="amber-dot"></span>NQO2 pathway<br>
      <span class="dot" style="background:#4C9BE8;display:inline-block;margin-right:4px"></span>Protein<br>
      <span class="dot" style="background:#2A9D8F;display:inline-block;margin-right:4px"></span>Metabolite<br>
      <span class="dot" style="background:#F4A261;display:inline-block;border-radius:0;transform:rotate(45deg);margin-right:4px"></span>RNA<br>
      <span class="dot" style="background:#E76F51;display:inline-block;margin-right:4px"></span>Pathway<br>
      <span class="dot" style="background:#E63946;display:inline-block;margin-right:4px"></span>Disease<br>
      <span class="dot" style="background:#8338EC;display:inline-block;margin-right:4px"></span>Drug / Platform
    </div>
    <div style="margin-top:8px;font-size:11px;color:#555">
      Node size ∝ paper count<br>
      Edge width ∝ shared papers
    </div>
  </div>
</div>

<script>
const NODE_META = {node_meta_js};

// ── State ──────────────────────────────────────────────────────────────────
let nqo2Active  = false;
let activeTypes = new Set(['protein','rna','metabolite','pathway','process','disease','drug']);

// ── Helpers ────────────────────────────────────────────────────────────────
function updateSlider(sliderId, valId) {{
  document.getElementById(valId).textContent = document.getElementById(sliderId).value;
}}

function toggleNQO2() {{
  nqo2Active = !nqo2Active;
  document.getElementById('nqo2-btn').classList.toggle('active', nqo2Active);
  applyFilters();
}}

// ── Core filter function ───────────────────────────────────────────────────
function applyFilters() {{
  // Read controls
  const searchText  = document.getElementById('search-input').value.trim().toLowerCase();
  const clusterSel  = document.getElementById('cluster-sel').value;
  const minPapers   = parseInt(document.getElementById('min-papers').value);
  const minEdgeW    = parseInt(document.getElementById('min-edge').value);

  activeTypes = new Set(
    [...document.querySelectorAll('.type-cb:checked')].map(cb => cb.value)
  );

  // Decide visibility for each node
  const visibleIds = new Set();
  const nodeUpdates = [];

  Object.entries(NODE_META).forEach(([idStr, meta]) => {{
    const id = parseInt(idStr);
    let visible = true;

    if (!activeTypes.has(meta.type) && meta.type !== 'process') visible = false;
    if (meta.type === 'process' && !activeTypes.has('pathway'))  visible = false;
    if (nqo2Active && !meta.is_nqo2)                             visible = false;
    if (meta.paper_count < minPapers)                            visible = false;
    if (clusterSel !== 'all' && !meta.clusters.includes(clusterSel)) visible = false;
    if (searchText && !meta.name.toLowerCase().includes(searchText)) visible = false;

    if (visible) visibleIds.add(id);
    nodeUpdates.push({{ id, hidden: !visible }});
  }});

  nodes.update(nodeUpdates);

  // Hide edges where either endpoint is invisible or weight below threshold
  const edgeUpdates = [];
  edges.get().forEach(edge => {{
    edgeUpdates.push({{
      id: edge.id,
      hidden: !visibleIds.has(edge.from) || !visibleIds.has(edge.to) || edge.width < (minEdgeW ** 0.6)
    }});
  }});
  edges.update(edgeUpdates);

  // Update stats
  const visibleEdges = edgeUpdates.filter(e => !e.hidden).length;
  document.getElementById('stat-nodes').textContent = visibleIds.size;
  document.getElementById('stat-edges').textContent = visibleEdges;
}}

// ── Reset ──────────────────────────────────────────────────────────────────
function resetFilters() {{
  document.querySelectorAll('.type-cb').forEach(cb => cb.checked = true);
  document.getElementById('search-input').value  = '';
  document.getElementById('cluster-sel').value   = 'all';
  document.getElementById('min-papers').value    = '{min_papers_default}';
  document.getElementById('min-edge').value      = '{min_edge_default}';
  document.getElementById('min-papers-val').textContent = '{min_papers_default}';
  document.getElementById('min-edge-val').textContent   = '{min_edge_default}';
  nqo2Active = false;
  document.getElementById('nqo2-btn').classList.remove('active');
  applyFilters();
}}

// ── Wire up live events ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {{
  document.getElementById('search-input').addEventListener('input', applyFilters);
  document.querySelectorAll('.type-cb').forEach(cb =>
    cb.addEventListener('change', applyFilters)
  );
  setTimeout(applyFilters, 800);
}});

// ── Rotation ───────────────────────────────────────────────────────────────
let rotAngle      = 0;
let rotSpeed      = 3;
let autoRotating  = false;
let rafId         = null;
let basePositions = null;
let rotCenter     = {{x: 0, y: 0}};

function captureBasePositions() {{
  network.setOptions({{physics: {{enabled: false}}}});
  const pos = network.getPositions();
  const ids  = Object.keys(pos);
  if (!ids.length) return;
  basePositions = pos;
  rotCenter.x   = ids.reduce((s, id) => s + pos[id].x, 0) / ids.length;
  rotCenter.y   = ids.reduce((s, id) => s + pos[id].y, 0) / ids.length;
  rotAngle = 0;
  document.getElementById('rot-angle').value           = 0;
  document.getElementById('rot-angle-val').textContent = '0°';
}}

function applyRotation(angle) {{
  if (!basePositions) return;
  const cos = Math.cos(angle), sin = Math.sin(angle);
  const cx  = rotCenter.x,    cy  = rotCenter.y;
  const updates = Object.entries(basePositions).map(([id, p]) => {{
    const dx = p.x - cx, dy = p.y - cy;
    return {{ id: parseInt(id), x: cx + dx*cos - dy*sin, y: cy + dx*sin + dy*cos }};
  }});
  nodes.update(updates);
}}

function toggleAutoRotate() {{
  autoRotating = !autoRotating;
  document.getElementById('rotate-btn').classList.toggle('active', autoRotating);
  if (autoRotating) {{
    if (!basePositions) captureBasePositions();
    let last = null;
    function frame(ts) {{
      if (last !== null) {{
        rotAngle += rotSpeed * 0.0007 * (ts - last);
        applyRotation(rotAngle);
        const deg = ((rotAngle * 180 / Math.PI) % 360 + 360) % 360;
        document.getElementById('rot-angle').value           = deg;
        document.getElementById('rot-angle-val').textContent = Math.round(deg) + '°';
      }}
      last = ts;
      if (autoRotating) rafId = requestAnimationFrame(frame);
    }}
    rafId = requestAnimationFrame(frame);
  }} else {{
    if (rafId) {{ cancelAnimationFrame(rafId); rafId = null; }}
  }}
}}

function setManualRotation(deg) {{
  document.getElementById('rot-angle-val').textContent = Math.round(deg) + '°';
  if (!basePositions) captureBasePositions();
  // stop auto-rotate if running
  if (autoRotating) {{
    autoRotating = false;
    document.getElementById('rotate-btn').classList.remove('active');
    if (rafId) {{ cancelAnimationFrame(rafId); rafId = null; }}
  }}
  rotAngle = deg * Math.PI / 180;
  applyRotation(rotAngle);
}}

// Freeze layout once physics stabilises so rotation has clean base positions
network.once('stabilized', captureBasePositions);
setTimeout(function() {{ if (!basePositions) captureBasePositions(); }}, 4000);
</script>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-papers", type=int, default=2)
    parser.add_argument("--min-edge",   type=int, default=2)
    args = parser.parse_args()

    print(f"Building graph  min-papers={args.min_papers}  min-edge={args.min_edge}")
    build(args.min_papers, args.min_edge)


if __name__ == "__main__":
    main()
