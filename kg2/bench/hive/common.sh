source /etc/profile.d/modules.sh
module load miniconda3/24.1.2
ROOT=/lustre1/home/krosenblum/flipskerov/tbikg2
PY=$ROOT/venv/bin/python
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export OPENBLAS_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export PYSTOW_HOME=$ROOT/.pystow
cd "$ROOT/bench"
echo "node $(hostname), cpus ${SLURM_CPUS_PER_TASK}, job ${SLURM_JOB_ID}"
echo "train.py sha1 $(sha1sum train.py | cut -c1-12)"
