"""Train one (arm, model, seed) and score the time-split test candidates. CPU only.

    python train.py --arm ref_lit --model rgcn --seed 0 --out results/
Models
  rgcn    2-layer R-GCN encoder (basis decomposition) + DistMult decoder   (PyTorch Geometric)
  rgat    2-layer R-GAT encoder + DistMult decoder                        (PyTorch Geometric)
  transe  TransE, sLCWA                                                   (PyKEEN)
  rotate  RotatE, sLCWA                                                   (PyKEEN)
Hyperparameters are fixed a priori (no validation set; see prepare.py) and written to the
result JSON. Test = score(g, tbi_link, TBI*) for every candidate gene; AUROC, AUPRC, P@k.
"""
import argparse
import csv
import json
import os
import random
import time
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import average_precision_score, roc_auc_score

HP = {  # fixed a priori, standard values from the R-GCN / PyKEEN literature
    "rgcn": {"dim": 64, "layers": 2, "bases": 8, "lr": 0.01, "epochs": 300, "batch": 8192, "neg": 4},
    "rgat": {"dim": 64, "layers": 2, "heads": 2, "lr": 0.005, "epochs": 200, "batch": 8192, "neg": 4},
    "transe": {"dim": 128, "lr": 0.001, "epochs": 150, "batch": 4096, "neg": 16},
    "rotate": {"dim": 128, "lr": 0.001, "epochs": 150, "batch": 4096, "neg": 16},
}


def read(path):
    with open(path) as f:
        return list(csv.DictReader(f, delimiter="\t"))


def load(arm_dir):
    ents = read(arm_dir / "entities.tsv")
    rels = read(arm_dir / "relations.tsv")
    tr = np.array([[int(r["h"]), int(r["r"]), int(r["t"])] for r in read(arm_dir / "train.tsv")])
    cand = read(arm_dir / "test_candidates.tsv")
    meta = {r["key"]: r["value"] for r in read(arm_dir / "meta.tsv")}
    feats = None
    if (arm_dir / "features.tsv").exists():
        fr = read(arm_dir / "features.tsv")
        idx = torch.tensor([[int(r["node"]) for r in fr], [int(r["feat"]) for r in fr]])
        feats = torch.sparse_coo_tensor(idx, torch.tensor([float(r["value"]) for r in fr]),
                                        (len(ents), int(meta["n_features"]))).coalesce()
    return ents, rels, tr, cand, meta, feats


def metrics(scores, labels):
    order = np.argsort(-scores)
    out = {"AUROC": float(roc_auc_score(labels, scores)),
           "AUPRC": float(average_precision_score(labels, scores)),
           "prevalence": float(np.mean(labels))}
    for k in (50, 100, 500):
        out[f"P@{k}"] = float(np.mean(labels[order[:k]]))
    return out


# ---------------------------------------------------------------- GNN (PyG) -------------------
def run_gnn(model_name, tr, n_ent, n_rel, feats, hp, log):
    from torch_geometric.nn import RGATConv, RGCNConv

    class Enc(torch.nn.Module):
        def __init__(self):
            super().__init__()
            d = hp["dim"]
            self.emb = torch.nn.Embedding(n_ent, d)
            self.proj = torch.nn.Linear(feats.shape[1], d, bias=False) if feats is not None else None
            R = 2 * n_rel  # + inverse relations
            if model_name == "rgcn":
                self.convs = torch.nn.ModuleList(RGCNConv(d, d, R, num_bases=hp["bases"])
                                                 for _ in range(hp["layers"]))
            else:
                self.convs = torch.nn.ModuleList(RGATConv(d, d // hp["heads"], R, heads=hp["heads"])
                                                 for _ in range(hp["layers"]))
            self.rel = torch.nn.Parameter(torch.randn(n_rel, d) * 0.1)  # DistMult

        def forward(self, ei, et):
            x = self.emb.weight
            if self.proj is not None:
                x = x + torch.sparse.mm(feats, self.proj.weight.T)
            for i, c in enumerate(self.convs):
                x = c(x, ei, et)
                if i < len(self.convs) - 1:
                    x = torch.relu(x)
            return x

        def score(self, x, h, r, t):
            return (x[h] * self.rel[r] * x[t]).sum(-1)

    h, r, t = (torch.tensor(tr[:, i]) for i in range(3))
    ei = torch.cat([torch.stack([h, t]), torch.stack([t, h])], 1)
    et = torch.cat([r, r + n_rel])
    m = Enc()
    opt = torch.optim.Adam(m.parameters(), lr=hp["lr"])
    bce = torch.nn.BCEWithLogitsLoss()
    n = len(tr)
    for ep in range(hp["epochs"]):
        m.train()
        idx = torch.randint(0, n, (hp["batch"],))
        bh, br, bt = h[idx], r[idx], t[idx]
        k = hp["neg"]
        nh, nr, nt = bh.repeat(k), br.repeat(k), bt.repeat(k)
        flip = torch.rand(len(nh)) < 0.5
        rnd = torch.randint(0, n_ent, (len(nh),))
        nh = torch.where(flip, rnd, nh)
        nt = torch.where(flip, nt, rnd)
        x = m(ei, et)
        s = torch.cat([m.score(x, bh, br, bt), m.score(x, nh, nr, nt)])
        y = torch.cat([torch.ones(len(bh)), torch.zeros(len(nh))])
        loss = bce(s, y)
        opt.zero_grad()
        loss.backward()
        opt.step()
        if ep % 25 == 0 or ep == hp["epochs"] - 1:
            log(f"epoch {ep} loss {loss.item():.4f}")
    m.eval()
    with torch.no_grad():
        x = m(ei, et)
    def score(hh, rr, tt):
        with torch.no_grad():
            return m.score(x, hh, rr, tt).detach().numpy()
    return score


# ---------------------------------------------------------------- KGE (PyKEEN) ----------------
def run_kge(model_name, tr, ents, rels, hp, seed, log):
    from pykeen.models import RotatE, TransE
    from pykeen.training import SLCWATrainingLoop
    from pykeen.triples import TriplesFactory

    tf = TriplesFactory(mapped_triples=torch.tensor(tr, dtype=torch.long),
                        entity_to_id={e["id"]: i for i, e in enumerate(ents)},
                        relation_to_id={x["relation"]: i for i, x in enumerate(rels)})
    cls = {"transe": TransE, "rotate": RotatE}[model_name]
    model = cls(triples_factory=tf, embedding_dim=hp["dim"], random_seed=seed)
    loop = SLCWATrainingLoop(model=model, triples_factory=tf,
                             optimizer=torch.optim.Adam(model.get_grad_params(), lr=hp["lr"]),
                             negative_sampler_kwargs={"num_negs_per_pos": hp["neg"]})
    losses = loop.train(triples_factory=tf, num_epochs=hp["epochs"], batch_size=hp["batch"],
                        use_tqdm=False)
    log(f"epochs {len(losses)} first loss {losses[0]:.4f} last loss {losses[-1]:.4f}")
    model.eval()

    def score(hh, rr, tt):
        with torch.no_grad():
            return model.score_hrt(torch.stack([hh, rr, tt], 1)).squeeze(-1).numpy()
    return score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True)
    ap.add_argument("--model", required=True, choices=list(HP))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--data", default=str(Path(__file__).resolve().parent / "data"))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "results"))
    ap.add_argument("--epochs", type=int, default=None, help="override (smoke tests only)")
    a = ap.parse_args()
    threads = int(os.environ.get("SLURM_CPUS_PER_TASK", "4"))
    torch.set_num_threads(threads)
    random.seed(a.seed)
    np.random.seed(a.seed)
    torch.manual_seed(a.seed)
    hp = dict(HP[a.model])
    if a.epochs:
        hp["epochs"] = a.epochs
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tag = f"{a.arm}__{a.model}__s{a.seed}" + (f"__e{a.epochs}" if a.epochs else "")
    logf = open(out / f"{tag}.log", "w")

    def log(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    t0 = time.time()
    ents, rels, tr, cand, meta, feats = load(Path(a.data) / a.arm)
    if a.model in ("transe", "rotate"):
        feats = None  # KGE baselines have no node features
    log(f"{tag}: entities {len(ents)} relations {len(rels)} triples {len(tr)} threads {threads} "
        f"features {None if feats is None else tuple(feats.shape)}")
    if a.model in ("rgcn", "rgat"):
        score = run_gnn(a.model, tr, len(ents), len(rels), feats, hp, log)
    else:
        score = run_kge(a.model, tr, ents, rels, hp, a.seed, log)
    ci = torch.tensor([int(c["idx"]) for c in cand])
    labels = np.array([int(c["label"]) for c in cand])
    s = score(ci, torch.full_like(ci, int(meta["tbi_link_rel"])), torch.full_like(ci, int(meta["target_idx"])))
    res = {"arm": a.arm, "model": a.model, "seed": a.seed, "hp": hp, "threads": threads,
           "seconds": round(time.time() - t0, 1), "n_candidates": len(labels),
           "n_positives": int(labels.sum()), **metrics(s, labels)}
    try:
        import resource
        res["max_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except Exception:  # noqa: BLE001
        pass
    (out / f"{tag}.json").write_text(json.dumps(res, indent=1))
    log(json.dumps({k: res[k] for k in ("AUROC", "AUPRC", "P@50", "seconds", "max_rss_mb") if k in res}))


if __name__ == "__main__":
    main()
