#!/bin/bash
# Offline env for the TBI-KG benchmark: a venv layered on edge_v2 (read-only), plus
# torch_geometric + pykeen from pre-downloaded wheels (HIVE has no internet).
set -eo pipefail
source /etc/profile.d/modules.sh
module load miniconda3/24.1.2
ROOT=/lustre1/home/krosenblum/flipskerov/tbikg2
BASE=/lustre1/home/krosenblum/flipskerov/.conda/envs/edge_v2/bin/python
V=$ROOT/venv
[ -d "$V" ] || "$BASE" -m venv --system-site-packages "$V"
"$V/bin/python" -m pip install --no-index --find-links "$ROOT/wheels" torch_geometric pykeen
"$V/bin/python" - <<'PY'
import sys, torch, torch_geometric, pykeen, sklearn, numpy
print("python", sys.version.split()[0], "| torch", torch.__version__, "| pyg", torch_geometric.__version__,
      "| pykeen", pykeen.get_version(), "| sklearn", sklearn.__version__, "| numpy", numpy.__version__)
from torch_geometric.nn import RGCNConv, RGATConv
from pykeen.models import TransE, RotatE
print("imports OK")
PY
