#!/usr/bin/env bash

# This script must be sourced so that CUDA/environment variables remain
# available in the interactive container shell.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "ERROR: source this script instead of executing it:"
    echo "  source scripts/setup_larnd_container.sh"
    exit 1
fi

set -e

PROJECT_DIR="${MCP2X2_ROOT:-${SCRATCH}/2x2_mcp}"
LARND_DIR="${PROJECT_DIR}/software/larnd-sim-current"
FREEZE_DIR="${PROJECT_DIR}/freeze/2026-08-17_working_baseline"
VALIDATOR="${PROJECT_DIR}/scripts/validate_larnd_container.sh"

EXPECTED_LARND_COMMIT="3b6449466e1e8036413ad9c6750b04a68515aea3"
LARPIX_CONTROL_COMMIT="5a69050422e82356c8faf9ad0ea3168c322d63e8"

echo "============================================================"
echo " MCP 2x2 larnd-sim container setup"
echo "============================================================"
echo "Project: ${PROJECT_DIR}"
echo

# ----------------------------------------------------------------------
# Base container environment
# ----------------------------------------------------------------------

source /opt/environment

export CUDA_HOME=/opt/cuda/cuda/12.2
export PATH="${CUDA_HOME}/bin:${PATH}"

export LD_LIBRARY_PATH="/opt/cuda/math_libs/12.2/targets/x86_64-linux/lib:${CUDA_HOME}/lib64:${LD_LIBRARY_PATH:-}"

# ----------------------------------------------------------------------
# Python / CUDA hotfixes
# ----------------------------------------------------------------------

echo
echo "[1/5] Installing/updating numba-cuda..."

# This is the same overlay used by the successful hand-tested recovery.
# Do not replace this with a CUDA/Numba source rebuild. The base image remains
# the environment anchor; numba-cuda supplies the modern Python CUDA layer.
python -m pip install --upgrade 'numba-cuda[cu12]'

# numba-cuda installs NVIDIA runtime libraries into the Python environment.
# The pip-provided nvJitLink must precede the mounted CUDA 12.2 copy because
# the modern Python CUDA stack can require symbols from the newer library.
NVJITLINK_DIR="$(
    find /opt/venv \
        -type f \
        -name 'libnvJitLink.so.12' \
        -printf '%h\n' \
        -quit 2>/dev/null || true
)"

if [[ -n "${NVJITLINK_DIR}" ]]; then
    export LD_LIBRARY_PATH="${NVJITLINK_DIR}:${LD_LIBRARY_PATH}"
    echo "Found nvJitLink library:"
    echo "  ${NVJITLINK_DIR}"
else
    echo "WARNING: libnvJitLink.so.12 was not found under /opt/venv."
fi

# ----------------------------------------------------------------------
# LArPix hotfix
# ----------------------------------------------------------------------

echo
echo "[2/5] Installing pinned larpix-control without touching dependencies..."

# CRITICAL: --no-deps is intentional.
#
# A force reinstall without --no-deps caused pip to upgrade the base image's
# NumPy 1.26.2 to NumPy 2.x and to reinstall Numba/llvmlite. That broke the
# already-repaired CuPy/Numba CUDA environment. We only need the pinned LArPix
# code here; its runtime dependencies are supplied by the container/steps above.
python -m pip install \
    --upgrade \
    --force-reinstall \
    --no-deps \
    "git+https://github.com/larpix/larpix-control.git@${LARPIX_CONTROL_COMMIT}"

# ----------------------------------------------------------------------
# larnd-sim
# ----------------------------------------------------------------------

echo
echo "[3/5] Checking larnd-sim checkout..."

# A submodule's .git entry may be a file rather than a directory, so ask Git
# whether this is a valid work tree instead of testing -d "$LARND_DIR/.git".
if ! git -C "${LARND_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "ERROR: larnd-sim checkout not found or invalid:"
    echo "  ${LARND_DIR}"
    return 1
fi

ACTUAL_LARND_COMMIT="$(git -C "${LARND_DIR}" rev-parse HEAD)"

echo "Expected: ${EXPECTED_LARND_COMMIT}"
echo "Actual:   ${ACTUAL_LARND_COMMIT}"

if [[ "${ACTUAL_LARND_COMMIT}" != "${EXPECTED_LARND_COMMIT}" ]]; then
    echo
    echo "ERROR: larnd-sim is not at the known-good baseline commit."
    echo "Run from the parent project:"
    echo "  git submodule update --init --recursive"
    return 1
fi

echo
echo "[4/5] Installing larnd-sim editable checkout..."

cd "${LARND_DIR}"

SKIP_CUPY_INSTALL=1 python -m pip install -e .

# ----------------------------------------------------------------------
# Validate the actual GPU runtime before declaring success
# ----------------------------------------------------------------------

echo
echo "[5/5] Validating larnd-sim GPU environment..."

if [[ ! -f "${VALIDATOR}" ]]; then
    echo "ERROR: container validator not found:"
    echo "  ${VALIDATOR}"
    return 1
fi

bash "${VALIDATOR}"

# ----------------------------------------------------------------------
# Record environment only after validation succeeds
# ----------------------------------------------------------------------

mkdir -p "${FREEZE_DIR}/manifests"
mkdir -p "${PROJECT_DIR}/log/container"

BASELINE_PIP_FREEZE="${FREEZE_DIR}/manifests/larnd_container_pip_freeze.txt"

if [[ ! -s "${BASELINE_PIP_FREEZE}" ]]; then
    echo
    echo "Capturing baseline pip environment:"
    echo "  ${BASELINE_PIP_FREEZE}"

    python -m pip freeze > "${BASELINE_PIP_FREEZE}"
else
    RUNTIME_FREEZE="${PROJECT_DIR}/log/container/pip_freeze_$(date +%Y%m%d_%H%M%S).txt"
    python -m pip freeze > "${RUNTIME_FREEZE}"

    echo
    echo "Baseline pip manifest already exists."
    echo "Current validated environment written to:"
    echo "  ${RUNTIME_FREEZE}"
fi

cd "${PROJECT_DIR}"

echo
echo "============================================================"
echo " larnd-sim environment ready"
echo "============================================================"
echo
echo "larnd-sim commit:"
echo "  ${ACTUAL_LARND_COMMIT}"
echo
echo "MCP larnd-sim configuration:"
echo "  --config 2x2_mpvmpr"
echo
