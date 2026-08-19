#!/usr/bin/env bash

# Fast validation of the larnd-sim Podman environment.
#
# Run inside the GPU container after scripts/setup_larnd_container.sh, or call
# it manually with:
#
#   bash "$MCP2X2_ROOT/scripts/validate_larnd_container.sh"
#
# The test deliberately exercises imports, CuPy, Numba CUDA JIT, LArPix packet
# classes, the pinned larnd-sim checkout, and the simulate_pixels.py CLI.

set -euo pipefail

PROJECT_DIR="${MCP2X2_ROOT:-${SCRATCH:-}/2x2_mcp}"
LARND_DIR="${PROJECT_DIR}/software/larnd-sim-current"
EXPECTED_LARND_COMMIT="3b6449466e1e8036413ad9c6750b04a68515aea3"

fail() {
    echo "CONTAINER VALIDATION: FAIL"
    echo "ERROR: $*"
    exit 1
}

echo "------------------------------------------------------------"
echo " larnd-sim container validation"
echo "------------------------------------------------------------"

echo
echo "[1/5] Executables and checkout"
command -v python >/dev/null || fail "python not found"
command -v simulate_pixels.py >/dev/null || fail "simulate_pixels.py not found"
command -v nvidia-smi >/dev/null || fail "nvidia-smi not found"

if ! git -C "${LARND_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    fail "invalid larnd-sim checkout: ${LARND_DIR}"
fi

ACTUAL_LARND_COMMIT="$(git -C "${LARND_DIR}" rev-parse HEAD)"
echo "larnd-sim expected: ${EXPECTED_LARND_COMMIT}"
echo "larnd-sim actual:   ${ACTUAL_LARND_COMMIT}"
[[ "${ACTUAL_LARND_COMMIT}" == "${EXPECTED_LARND_COMMIT}" ]] \
    || fail "larnd-sim commit mismatch"

echo
echo "[2/5] Python/CUDA imports and versions"
python - <<'PY'
import os
import sys

import numpy as np
import cupy as cp
import numba
import llvmlite
import h5py
import larndsim
import numba.cuda
from numba import cuda
from larpix.packet import Packet_v2, Packet_v3

print("Python       :", sys.version.split()[0])
print("NumPy        :", np.__version__)
print("CuPy         :", cp.__version__)
print("Numba        :", numba.__version__)
print("llvmlite     :", llvmlite.__version__)
print("h5py         :", h5py.__version__)
print("larnd-sim    :", larndsim.__file__)
print("numba.cuda   :", numba.cuda.__file__)
print("Packet_v2    :", Packet_v2)
print("Packet_v3    :", Packet_v3)

major, minor = (int(x) for x in np.__version__.split(".")[:2])
if (major, minor) >= (1, 27):
    raise RuntimeError(
        "NumPy is too new for the pinned CuPy 12.2 environment; "
        f"found {np.__version__}, require <1.27"
    )

n_gpu = cp.cuda.runtime.getDeviceCount()
print("CuPy GPUs    :", n_gpu)
if n_gpu < 1:
    raise RuntimeError("CuPy sees no CUDA devices")

if not cuda.is_available():
    raise RuntimeError("Numba CUDA reports unavailable")

print("Numba GPUs   :", len(cuda.gpus))

ld = os.environ.get("LD_LIBRARY_PATH", "")
print("LD_LIBRARY_PATH first entries:")
for p in ld.split(":")[:8]:
    if p:
        print("  ", p)
PY

echo
echo "[3/5] CuPy device execution"
python - <<'PY'
import numpy as np
import cupy as cp

x = cp.arange(8, dtype=cp.float32)
out = cp.asnumpy(x * x)
expected = np.arange(8, dtype=np.float32) ** 2
print("CuPy result:", out)
if not np.array_equal(out, expected):
    raise RuntimeError("CuPy GPU result mismatch")
print("CuPy GPU TEST: PASS")
PY

echo
echo "[4/5] Numba CUDA JIT execution"
python - <<'PY'
import numpy as np
from numba import cuda

@cuda.jit
def add_one(x):
    i = cuda.grid(1)
    if i < x.size:
        x[i] += 1

host = np.arange(10, dtype=np.float32)
dev = cuda.to_device(host)
add_one[1, 32](dev)
cuda.synchronize()
out = dev.copy_to_host()
expected = host + 1
print("Numba result:", out)
if not np.array_equal(out, expected):
    raise RuntimeError("Numba CUDA JIT result mismatch")
print("NUMBA CUDA JIT TEST: PASS")
PY

echo
echo "[5/5] Package and CLI checks"
python -m pip check
simulate_pixels.py --help >/dev/null

echo
echo "CONTAINER VALIDATION: PASS"
