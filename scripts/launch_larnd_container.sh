#!/usr/bin/env bash

set -euo pipefail

: "${SCRATCH:?SCRATCH is not defined}"

PROJECT_DIR="${SCRATCH}/2x2_mcp"
IMAGE="docker.io/mjkramer/sim2x2:ndlar011"

if [[ ! -d "${PROJECT_DIR}" ]]; then
    echo "ERROR: project directory not found:"
    echo "  ${PROJECT_DIR}"
    exit 1
fi

echo "Launching MCP 2x2 larnd-sim container"
echo
echo "Image:"
echo "  ${IMAGE}"
echo
echo "Project:"
echo "  ${PROJECT_DIR}"
echo

exec podman-hpc run \
    --rm \
    -it \
    --gpu \
    --cvmfs \
    --env SCRATCH="${SCRATCH}" \
    --env MCP2X2_ROOT="${PROJECT_DIR}" \
    -v "${SCRATCH}:${SCRATCH}" \
    -v /dvs_ro/cfs:/dvs_ro/cfs \
    -v /opt/nvidia/hpc_sdk/Linux_x86_64/23.9:/opt/cuda \
    "${IMAGE}" \
    /bin/bash -lc \
    "source '${PROJECT_DIR}/scripts/setup_larnd_container.sh'; exec /bin/bash -i"
