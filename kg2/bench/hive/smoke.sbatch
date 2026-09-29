#!/bin/bash
# Smoke: every model x the feature arm, 2 epochs. Catches import/API/shape errors in minutes.
#SBATCH --job-name=tbikg_smoke
#SBATCH --account=krosenblum
#SBATCH --partition=OldBees
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=48G
#SBATCH --time=01:00:00
#SBATCH --output=/lustre1/home/krosenblum/flipskerov/tbikg2/logs/smoke_%j.out
#SBATCH --error=/lustre1/home/krosenblum/flipskerov/tbikg2/logs/smoke_%j.err
set -eo pipefail
source /lustre1/home/krosenblum/flipskerov/tbikg2/bench/hive/common.sh
for m in rgcn rgat transe rotate; do
  "$PY" train.py --arm ref_lit_feat --model $m --seed 0 --epochs 2 --out results_smoke
done
echo SMOKE_DONE
