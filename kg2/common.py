"""Shared paths, source registry, ID helpers and TSV writers for TBI-BiomarkerKG v2.

Design rules (see kg2/README.md):
  * every node has a CURIE from a public namespace (NCBIGene, MESH, CHEMBL, REACT, UBERON)
    or, only when none exists, the project namespace TBIKG;
  * every edge carries primary_knowledge_source, knowledge_level, agent_type and a layer
    (L1 curated reference, L2 omics measurement, L3 literature-extracted, L4 lab-curated);
  * one edge per (subject, predicate, object[, direction]); evidence rows live in
    edge_evidence.tsv and are aggregated, never duplicated;
  * scripts are idempotent: every output file is rewritten whole.
"""
from __future__ import annotations

import csv
import gzip
import json
import sqlite3
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KG2 = ROOT / "kg2"
RAW = KG2 / "raw"
INTERIM = KG2 / "interim"
OUT = KG2 / "out"
CURATION = KG2 / "curation"
for d in (RAW, INTERIM, OUT, CURATION):
    d.mkdir(parents=True, exist_ok=True)

KB_DB = ROOT / "data" / "tbi_papers.db"
PANEL_DB = ROOT / "05_analysis" / "panel.db"

VERSION = "2.0.0-dev"

# Upstream sources: (key, url, licence). Download date is recorded in SOURCES.tsv at fetch.
SOURCES = {
    "hgnc": ("https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt",
             "CC0"),
    "mgi_hom": ("https://www.informatics.jax.org/downloads/reports/HOM_MouseHumanSequence.rpt",
                "MGI terms of use (CC BY 4.0)"),
    "string_links": ("https://stringdb-downloads.org/download/protein.physical.links.v12.0/"
                     "9606.protein.physical.links.v12.0.txt.gz", "CC BY 4.0"),
    "string_info": ("https://stringdb-downloads.org/download/protein.info.v12.0/"
                    "9606.protein.info.v12.0.txt.gz", "CC BY 4.0"),
    "reactome_ncbi": ("https://reactome.org/download/current/NCBI2Reactome.txt", "CC BY 4.0"),
    "reactome_pathways": ("https://reactome.org/download/current/ReactomePathways.txt", "CC BY 4.0"),
    "goa_human": ("http://current.geneontology.org/annotations/goa_human.gaf.gz", "CC BY 4.0"),
    "omnipath": ("https://omnipathdb.org/interactions?datasets=omnipath&genesymbols=yes"
                 "&fields=curation_effort,references,sources&license=academic&format=tsv",
                 "Academic subset; per-resource licences (see OmniPath)"),
    "pubtator3": ("https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson",
                  "Public domain (NCBI); abstract text is publisher copyright"),
}

# Biofluid / tissue -> UBERON (used as edge qualifiers)
UBERON = {
    "plasma": "UBERON:0001969",
    "serum": "UBERON:0001977",
    "csf": "UBERON:0001359",
    "hippocampus": "UBERON:0002421",
    "cortex": "UBERON:0000956",
    "brain": "UBERON:0000955",
}

# Disease nodes used as objects of omics edges (MeSH descriptors).
MESH_TBI = "MESH:D000070642"          # Brain Injuries, Traumatic
MESH_CONCUSSION = "MESH:D001924"      # Brain Concussion
MESH_PCS = "MESH:D038223"             # Post-Concussion Syndrome

NODE_COLS = ["id", "category", "name", "taxon", "xrefs", "provided_by", "in_public_release"]
EDGE_COLS = ["id", "subject", "predicate", "object", "direction", "layer",
             "knowledge_level", "agent_type", "primary_knowledge_source", "n_evidence",
             "publications", "first_year", "score", "qualifiers"]
EVID_COLS = ["edge_id", "layer", "source", "pmid", "year", "dataset_id", "contrast",
             "species", "matrix", "log2fc", "effect", "pvalue", "padj", "n",
             "sentence", "extractor_score", "note"]


def fetch(key: str, fname: str | None = None, force: bool = False) -> Path:
    """Download a registered source once into kg2/raw and log it in SOURCES.tsv."""
    url, licence = SOURCES[key]
    path = RAW / (fname or url.rsplit("/", 1)[-1])
    if path.exists() and path.stat().st_size > 0 and not force:
        return path
    print(f"  downloading {key}: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "tbi-kg2/2.0 (academic)"})
    with urllib.request.urlopen(req, timeout=600) as r, open(path, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    log_source(key, url, licence, path)
    return path


def log_source(key, url, licence, path):
    reg = KG2 / "SOURCES.tsv"
    rows = {}
    if reg.exists():
        with open(reg) as f:
            for r in csv.DictReader(f, delimiter="\t"):
                rows[r["key"]] = r
    rows[key] = {"key": key, "url": url, "licence": licence, "file": path.name,
                 "bytes": str(path.stat().st_size),
                 "downloaded": time.strftime("%Y-%m-%d")}
    with open(reg, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[key]), delimiter="\t")
        w.writeheader()
        for k in sorted(rows):
            w.writerow(rows[k])


def open_text(path: Path):
    return gzip.open(path, "rt") if path.suffix == ".gz" else open(path, encoding="utf-8")


def write_tsv(path: Path, cols: list[str], rows) -> int:
    """Clear-then-write. Returns row count."""
    n = 0
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", extrasaction="ignore",
                           lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in cols})
            n += 1
    return n


def read_tsv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True) if obj else ""
