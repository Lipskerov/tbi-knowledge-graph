#!/bin/bash
# Full ablation: L1-as-of-2020 arm: 4 models x 10 seeds = 40 tasks, max 12 concurrent (288 CPUs of the
# 512 cap, leaving room for the LLM work on hive1d). Task -> (arm, model, seed) is fixed below.
# Idempotent: a task whose result JSON exists is skipped.
#SBATCH --job-name=tbikg_2020
#SBATCH --account=krosenblum
#SBATCH --partition=OldBees
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=64G
#SBATCH --time=03:00:00
#SBATCH --array=0-39%12
#SBATCH --output=/lustre1/home/krosenblum/flipskerov/tbikg2/logs/y2020_%A_%a.out
#SBATCH --error=/lustre1/home/krosenblum/flipskerov/tbikg2/logs/y2020_%A_%a.err
set -eo pipefail
source /lustre1/home/krosenblum/flipskerov/tbikg2/bench/hive/common.sh
ARMS=(ref_lit_2020)
MODELS=(rgcn rgat transe rotate)
i=$SLURM_ARRAY_TASK_ID
SEED=$(( i % 10 )); MODEL=${MODELS[$(( (i / 10) % 4 ))]}; ARM=${ARMS[$(( i / 40 ))]}
TAG="${ARM}__${MODEL}__s${SEED}"
if [ -s "results/${TAG}.json" ]; then echo "skip ${TAG} (done)"; exit 0; fi
"$PY" train.py --arm "$ARM" --model "$MODEL" --seed "$SEED" --out results
