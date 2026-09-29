#!/bin/bash
# Timing: ONE real run (R-GCN, ref_lit, seed 0, full epochs) to set walltime/memory for the array.
#SBATCH --job-name=tbikg_timing
#SBATCH --account=krosenblum
#SBATCH --partition=OldBees
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=24
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --output=/lustre1/home/krosenblum/flipskerov/tbikg2/logs/timing_%j.out
#SBATCH --error=/lustre1/home/krosenblum/flipskerov/tbikg2/logs/timing_%j.err
set -eo pipefail
source /lustre1/home/krosenblum/flipskerov/tbikg2/bench/hive/common.sh
"$PY" train.py --arm ref_lit --model rgcn --seed 0 --out results_timing
echo TIMING_DONE
