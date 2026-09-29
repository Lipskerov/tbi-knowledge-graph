"""P0 — freeze the v1 baseline and fix the literature scope.

Outputs
  interim/baseline_v1/{tbi_papers.db,panel.db}   byte copies (ablation arm 1)
  interim/baseline_v1/v1_edges.tsv                v1 entity_relations as a flat edge list
  interim/scope_pmids.tsv                         pmid, year, clusters, in_scope, reason

Scope rule: TBI + neurodegeneration bridge + NQO2 biology. A paper is OUT only when every
cluster it belongs to is in EXCLUDED_CLUSTERS.
"""
import shutil

from common import INTERIM, KB_DB, PANEL_DB, db, write_tsv

EXCLUDED_CLUSTERS = {"lupus_biomarkers"}


def main():
    base = INTERIM / "baseline_v1"
    base.mkdir(exist_ok=True)
    for src in (KB_DB, PANEL_DB):
        shutil.copy2(src, base / src.name)

    con = db(KB_DB)
    edges = con.execute("""
        SELECT a.name AS subject, r.relation AS predicate, b.name AS object,
               r.edge_kind, r.weight, r.directed, r.evidence_pmids
        FROM entity_relations r JOIN entities a ON a.id = r.source_id
                                JOIN entities b ON b.id = r.target_id""").fetchall()
    n_v1 = write_tsv(base / "v1_edges.tsv",
                     ["subject", "predicate", "object", "edge_kind", "weight", "directed",
                      "evidence_pmids"], (dict(e) for e in edges))

    clusters = {}
    for pmid, cl in con.execute("SELECT pmid, cluster FROM paper_clusters"):
        clusters.setdefault(pmid, set()).add(cl)
    rows = []
    for pmid, year, tc, abstract in con.execute(
            "SELECT pmid, year, topic_cluster, abstract FROM papers"):
        cl = clusters.get(pmid) or ({tc} if tc else set())
        if not cl:
            ok, why = False, "no cluster"
        elif cl <= EXCLUDED_CLUSTERS:
            ok, why = False, "excluded cluster only"
        elif not pmid.isdigit():
            ok, why = False, "not a PMID (preprint id)"
        else:
            ok, why = True, ""
        rows.append({"pmid": pmid, "year": year, "clusters": ";".join(sorted(cl)),
                     "has_abstract": int(bool(abstract)), "in_scope": int(ok), "reason": why})
    write_tsv(INTERIM / "scope_pmids.tsv",
              ["pmid", "year", "clusters", "has_abstract", "in_scope", "reason"], rows)
    n_in = sum(r["in_scope"] for r in rows)
    print(f"P0: v1 edges {n_v1}; papers {len(rows)}; in scope {n_in}; "
          f"out {len(rows) - n_in} "
          f"({sum(r['reason'] == 'excluded cluster only' for r in rows)} lupus-only, "
          f"{sum(r['reason'].startswith('not a PMID') for r in rows)} non-PMID)")


if __name__ == "__main__":
    main()
