#!/bin/bash
# 72B second extractor on the 400 V2 gold-set items. Queued with --dependency=afterany:<trialytic
# array> so it never competes with trialytic for the per-user CPU cap. Uses the trialytic Ollama
# binary + model store READ-ONLY (OLLAMA_NOPRUNE=1); own port range (45000-54999; trialytic uses
# 20000-39999), own logs and outputs under ~/tbikg2. 6 shards (round-robin, ~67 items each), one
# node + one Ollama per shard. Smoke 5 items -> validate -> rest of the shard (resumable).
#SBATCH --job-name=tbikg_llm72b
#SBATCH --array=0-5
#SBATCH --account=krosenblum
#SBATCH --partition=hive1d
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=80G
#SBATCH --time=23:00:00
#SBATCH --output=/lustre1/home/krosenblum/flipskerov/tbikg2/logs/llm72b_%A_%a.out
#SBATCH --error=/lustre1/home/krosenblum/flipskerov/tbikg2/logs/llm72b_%A_%a.err
set -eo pipefail
ROOT=/lustre1/home/krosenblum/flipskerov/tbikg2
TL=/lustre1/home/krosenblum/flipskerov/trialytic_llm
PY=$ROOT/venv/bin/python
MODEL=qwen2.5:72b-instruct-q4_K_M
export OLLAMA_MODELS=$TL/models OLLAMA_NOPRUNE=1
export OLLAMA_FLASH_ATTENTION=1 OLLAMA_CONTEXT_LENGTH=2048 OLLAMA_KEEP_ALIVE=24h OLLAMA_NUM_PARALLEL=1
PORT=$(( 45000 + (SLURM_ARRAY_JOB_ID + SLURM_ARRAY_TASK_ID) % 10000 ))
SH=$SLURM_ARRAY_TASK_ID; NSH=6
export OLLAMA_HOST="http://127.0.0.1:${PORT}"
cd "$ROOT/bench"
echo "node $(hostname) cpus $SLURM_CPUS_PER_TASK port $PORT job $SLURM_JOB_ID shard $SH/$NSH"
echo "llm_extract.py sha1 $(sha1sum llm_extract.py | cut -c1-12) items sha1 $(sha1sum llm_items.tsv | cut -c1-12)"
"$TL/bin/bin/ollama" serve > "$ROOT/logs/ollama_llm72b_${SLURM_ARRAY_JOB_ID}_${SH}.log" 2>&1 &
OPID=$!
trap 'kill $OPID 2>/dev/null || true' EXIT
for i in $(seq 1 120); do curl -sf "$OLLAMA_HOST/api/tags" >/dev/null && break; sleep 2; done
curl -sf "$OLLAMA_HOST/api/tags" | grep -q "72b-instruct" || { echo "72B model not visible to Ollama"; exit 1; }
OUT=$ROOT/bench/llm_preds_qwen72b_shard${SH}.jsonl
"$PY" llm_extract.py --items llm_items.tsv --out "$OUT" --model "$MODEL" --shard $SH --nshards $NSH --limit 5
"$PY" - "$OUT" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()][:5]
bad = [r for r in rows if r["error"] or not r["relation"]]
print("smoke:", [(r["item"], r["relation"], r["seconds"]) for r in rows])
sys.exit(1 if bad or len(rows) < 5 else 0)
PY
"$PY" llm_extract.py --items llm_items.tsv --out "$OUT" --model "$MODEL" --shard $SH --nshards $NSH
echo LLM72B_DONE
