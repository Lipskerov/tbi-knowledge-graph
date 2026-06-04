/* TBI Knowledge Graph v2.0 — frontend logic.
   Talks to the FastAPI /api/* endpoints; renders the vis.js graph + detail panel. */

"use strict";

const API = "";  // same origin
const TYPE_COLORS = {
  protein:    "#4ea1ff",
  drug:       "#ff7043",
  metabolite: "#ffca40",
  rna:        "#b388ff",
  pathway:    "#4dd0a0",
  process:    "#9ccc65",
  disease:    "#ef5d8f",
  other:      "#90a4ae",
};

let network = null;
let nodesDS = null;
let edgesDS = null;
let allNodeIds = [];
let tomTypes = null, tomClusters = null;

// ── boot ─────────────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", async () => {
  ensureLibs();
  wireControls();
  await loadStats();
  await loadGraph();
});

/* If the vendored /lib assets didn't load, fall back to CDN once. */
function ensureLibs() {
  if (typeof vis === "undefined") {
    const s = document.createElement("script");
    s.src = "https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/dist/vis-network.min.js";
    s.async = false;
    document.head.appendChild(s);
    console.warn("Local vis-network missing; loading from CDN.");
  }
}

function wireControls() {
  document.getElementById("search-btn").addEventListener("click", runSearch);
  document.getElementById("search-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runSearch();
  });
  document.getElementById("reset-btn").addEventListener("click", resetAll);
  document.getElementById("apply-btn").addEventListener("click", loadGraph);

  const mp = document.getElementById("f-minpapers");
  const me = document.getElementById("f-minedge");
  mp.addEventListener("input", () => (document.getElementById("mp-val").textContent = mp.value));
  me.addEventListener("input", () => (document.getElementById("me-val").textContent = me.value));
}

// ── data loads ───────────────────────────────────────────────────────────────
async function getJSON(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

async function loadStats() {
  const s = await getJSON("/api/stats");
  document.getElementById("stats").innerHTML =
    `<b>${s.papers.toLocaleString()}</b> papers · <b>${s.entities}</b> entities<br>` +
    `<b>${s.edges}</b> edges (<b>${s.curated_edges}</b> curated` +
    (s.chembl_edges ? ` · <b>${s.chembl_edges}</b> ChEMBL` : ``) +
    `) · <b>${s.clusters}</b> clusters<br>` +
    `sources: ` + Object.entries(s.by_source).map(([k, v]) => `${k} ${v}`).join(" · ");

  // cluster facet from real paper_clusters counts
  const clusterEl = document.getElementById("f-clusters");
  clusterEl.innerHTML = "";
  Object.entries(s.by_cluster).forEach(([c, n]) => {
    clusterEl.appendChild(new Option(`${c} (${n})`, c));
  });

  // year defaults
  if (s.year_range && s.year_range[0]) {
    document.getElementById("year-min").placeholder = s.year_range[0];
    document.getElementById("year-max").placeholder = s.year_range[1];
  }
  if (window.TomSelect) {
    tomClusters = new TomSelect("#f-clusters", { plugins: ["remove_button"], maxItems: null });
  }
}

function currentFilters() {
  const val = (id) => document.getElementById(id).value;
  const multi = (tom, id) =>
    tom ? tom.getValue() : Array.from(document.getElementById(id).selectedOptions).map((o) => o.value);
  const p = new URLSearchParams();
  const types = multi(tomTypes, "f-types");
  const clusters = multi(tomClusters, "f-clusters");
  if (types.length) p.set("types", types.join(","));
  if (clusters.length) p.set("clusters", clusters.join(","));
  const disease = val("f-disease");
  if (disease) p.set("disease", disease);
  p.set("min_papers", val("f-minpapers"));
  p.set("min_edge", val("f-minedge"));
  return p;
}

async function loadGraph() {
  const p = currentFilters();
  const g = await getJSON("/api/graph?" + p.toString());
  renderGraph(g);
  populateTypeAndDiseaseFacets(g.nodes);
}

// Derive node-type and disease facet options from the loaded graph (first run).
function populateTypeAndDiseaseFacets(nodes) {
  const typeEl = document.getElementById("f-types");
  if (typeEl.options.length === 0) {
    [...new Set(nodes.map((n) => n.type))].sort().forEach((t) => typeEl.appendChild(new Option(t, t)));
    if (window.TomSelect) tomTypes = new TomSelect("#f-types", { plugins: ["remove_button"], maxItems: null });
  }
  const dEl = document.getElementById("f-disease");
  if (dEl.options.length <= 1) {
    nodes.filter((n) => n.type === "disease").sort((a, b) => a.name.localeCompare(b.name))
      .forEach((n) => dEl.appendChild(new Option(n.name, n.name)));
  }
}

// ── graph rendering ──────────────────────────────────────────────────────────
function renderGraph(g) {
  const nodes = g.nodes.map((n) => ({
    id: n.id,
    label: n.name,
    title: `${n.name} · ${n.type} · ${n.paper_count} papers`,
    value: Math.max(n.paper_count, 1),
    group: n.type,
    color: { background: TYPE_COLORS[n.type] || TYPE_COLORS.other, border: "#0c1117" },
    font: { color: "#e6edf3" },
  }));

  const edges = g.edges.map((e) => {
    const chembl = e.edge_kind === "chembl";
    const mech = e.edge_kind === "curated" || chembl;   // typed/directed mechanism
    const color = chembl ? "#4dd0a0" : (e.edge_kind === "curated" ? "#ff7043" : "rgba(120,140,160,0.35)");
    const hi    = chembl ? "#8ee7c4" : (e.edge_kind === "curated" ? "#ffab91" : "#8aa");
    return {
      from: e.source,
      to: e.target,
      label: mech ? e.relation : undefined,
      title: chembl && e.annotation ? e.annotation : undefined,   // hover → potency
      arrows: e.directed ? "to" : undefined,
      width: mech ? 2.5 : Math.min(0.5 + Math.log2((e.weight || 1) + 1), 5),
      color: { color, highlight: hi },
      dashes: chembl ? [5, 3] : false,
      font: mech ? { color: hi, size: 11, strokeWidth: 0, align: "middle" } : undefined,
      smooth: { type: "continuous" },
    };
  });

  allNodeIds = nodes.map((n) => n.id);
  nodesDS = new vis.DataSet(nodes);
  edgesDS = new vis.DataSet(edges);

  const container = document.getElementById("graph");
  const options = {
    nodes: { shape: "dot", scaling: { min: 6, max: 42 }, borderWidth: 1.5 },
    edges: { selectionWidth: 2 },
    physics: {
      barnesHut: { gravitationalConstant: -9000, springLength: 130, springConstant: 0.03 },
      stabilization: { iterations: 180 },
    },
    interaction: { hover: true, tooltipDelay: 120, multiselect: false },
  };
  network = new vis.Network(container, { nodes: nodesDS, edges: edgesDS }, options);
  network.on("click", (params) => {
    if (params.nodes.length) openNode(params.nodes[0]);
  });
}

function highlightNodes(ids) {
  if (!nodesDS) return;
  const set = new Set(ids);
  nodesDS.update(allNodeIds.map((id) => ({
    id,
    opacity: set.size === 0 || set.has(id) ? 1 : 0.15,
    borderWidth: set.has(id) ? 3 : 1.5,
  })));
}

// ── detail panel ─────────────────────────────────────────────────────────────
async function openNode(entityId) {
  const panel = document.getElementById("detail");
  panel.innerHTML = `<div class="placeholder">Loading…</div>`;
  try {
    const [ent, pap] = await Promise.all([
      getJSON(`/api/entity/${entityId}`),
      getJSON(`/api/node/${entityId}/papers?limit=50`),
    ]);
    panel.innerHTML = renderEntity(ent) + renderPapers(pap.papers, `Papers (${pap.n_papers})`);
  } catch (e) {
    panel.innerHTML = `<div class="placeholder">Error: ${e.message}</div>`;
  }
}

function renderEntity(ent) {
  const potency = (m) =>
    m.annotation ? ` <span class="potency">${esc(m.annotation)}</span>` : "";
  const mech = (arr, dir) =>
    arr.map((m) =>
      dir === "out"
        ? `<div class="edge">${esc(ent.name)} <span class="rel">${esc(m.relation)}</span> → ${esc(m.target)}${potency(m)}</div>`
        : `<div class="edge">${esc(m.source)} <span class="rel">${esc(m.relation)}</span> → ${esc(ent.name)}${potency(m)}</div>`
    ).join("");

  let html = `<div class="detail-head">
      <div class="type">${esc(ent.type)}</div>
      <h2>${esc(ent.name)}</h2>
      <div class="aliases">${(ent.aliases || []).map(esc).join(", ")}</div>
      <div class="aliases">${ent.paper_count} papers</div>
    </div>`;

  if ((ent.mechanism_out || []).length || (ent.mechanism_in || []).length) {
    html += `<div class="mech"><h4>Mechanism links (curated + ChEMBL)</h4>
      ${mech(ent.mechanism_out || [], "out")}${mech(ent.mechanism_in || [], "in")}</div>`;
  }
  if ((ent.top_related || []).length) {
    html += `<div class="mech"><h4>Top co-occurring</h4>` +
      ent.top_related.slice(0, 8).map((r) =>
        `<div class="edge">${esc(r.name)} <span class="meta">(${r.shared_papers})</span></div>`).join("") +
      `</div>`;
  }
  return html;
}

function renderPapers(papers, title) {
  if (!papers || !papers.length) return `<div class="papers"><h4>${title}</h4><div class="placeholder">No papers.</div></div>`;
  const items = papers.map((p) => {
    const links = Object.entries(p.links || {})
      .map(([k, url]) => `<a href="${url}" target="_blank" rel="noopener">${k.toUpperCase()}</a>`).join("");
    const tag = p.source === "biorxiv"
      ? `<span class="tag preprint">bioRxiv preprint</span>`
      : `<span class="tag">${esc(p.source || "pubmed")}</span>`;
    const chips = (p.clusters || []).map((c) => `<span class="cluster-chip">${esc(c)}</span>`).join("");
    return `<div class="paper">
        <div class="title">${esc(p.title || "Untitled")} ${tag}</div>
        <div class="meta">${esc(p.authors || "—")} · ${esc(p.journal || "—")} ${p.year ? "(" + p.year + ")" : ""}</div>
        <div>${chips}</div>
        <div class="links">${links || '<span class="meta">no links</span>'}</div>
      </div>`;
  }).join("");
  return `<div class="papers"><h4>${title}</h4>${items}</div>`;
}

// ── search ───────────────────────────────────────────────────────────────────
async function runSearch() {
  const q = document.getElementById("search-input").value.trim();
  if (!q) { highlightNodes([]); return; }
  const p = new URLSearchParams({ q });
  const ymin = document.getElementById("year-min").value;
  const ymax = document.getElementById("year-max").value;
  const clusters = tomClusters ? tomClusters.getValue() : [];
  if (ymin) p.set("year_min", ymin);
  if (ymax) p.set("year_max", ymax);
  if (clusters.length) p.set("clusters", clusters.join(","));

  const res = await getJSON("/api/search?" + p.toString());
  highlightNodes(res.node_ids || []);
  document.getElementById("detail").innerHTML =
    `<div class="detail-head"><h2>Search</h2><div class="aliases">“${esc(q)}” — ${res.n_results} hits, ` +
    `${(res.node_ids || []).length} nodes highlighted</div></div>` +
    renderPapers(res.papers, "Matching papers");
}

function resetAll() {
  document.getElementById("search-input").value = "";
  document.getElementById("year-min").value = "";
  document.getElementById("year-max").value = "";
  document.getElementById("f-disease").value = "";
  document.getElementById("f-minpapers").value = 0;
  document.getElementById("f-minedge").value = 1;
  document.getElementById("mp-val").textContent = "0";
  document.getElementById("me-val").textContent = "1";
  if (tomTypes) tomTypes.clear();
  if (tomClusters) tomClusters.clear();
  document.getElementById("detail").innerHTML =
    `<div class="placeholder">Click a node to see its papers and mechanism links.</div>`;
  loadGraph();
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
