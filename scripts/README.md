# Runtime helper scripts

This directory contains the small, reproducible entry points used to recover and validate the known-good MCP detector-simulation environment on NERSC Perlmutter.

## larnd-sim GPU container

From a Perlmutter GPU node:

```bash
cd "$SCRATCH/2x2_mcp"
./scripts/launch_larnd_container.sh
```

The launcher starts the disposable `docker.io/mjkramer/sim2x2:ndlar011` Podman-HPC container, mounts `$SCRATCH`, CVMFS, and the NERSC CUDA tree, then sources:

```text
scripts/setup_larnd_container.sh
```

The setup script:

1. loads the base container environment;
2. configures the mounted CUDA 12.2 paths;
3. installs/updates the `numba-cuda[cu12]` overlay;
4. prepends pip's `libnvJitLink.so.12` directory;
5. reinstalls the pinned `larpix-control` code with **`--no-deps`**;
6. verifies the pinned larnd-sim checkout;
7. installs larnd-sim from the persistent submodule;
8. runs the GPU validation script;
9. records a runtime `pip freeze` only after validation passes.

The `--no-deps` flag on the LArPix reinstall is mandatory. Without it, pip can replace NumPy/Numba/llvmlite and break the already-working CuPy/Numba CUDA environment.

## Validate a live container

The validation can be rerun at any time inside the GPU container:

```bash
bash "$MCP2X2_ROOT/scripts/validate_larnd_container.sh"
```

A healthy environment ends with:

```text
CONTAINER VALIDATION: PASS
```

The validator checks the pinned larnd-sim commit, NumPy/CuPy compatibility, CuPy GPU execution, Numba CUDA availability and JIT execution, LArPix packet classes, `pip check`, and the `simulate_pixels.py` CLI.

## Recovery rule

If setup unexpectedly starts reinstalling NumPy, Numba, llvmlite, CuPy, SciPy, matplotlib, or a large unrelated dependency set while installing `larpix-control`, stop. The container is launched with `--rm`, so `/opt/venv` is intentionally disposable.

Prefer:

```text
fix persistent setup script
-> exit contaminated container
-> relaunch clean container
```

over repeated in-place package surgery.

Full incident documentation:

```text
freeze/2026-08-17_working_baseline/notes/larnd_container_dependency_recovery.md
```

## Realistic generator validation

The event-by-event Pythia/HEPEVT -> EDepSim regression check lives at:

```text
generator/validate_pythia_edep.py
```

Example:

```bash
python generator/validate_pythia_edep.py \
    out/generator/mcp_020458GeV_100evt_seed12345.manifest.csv \
    out/edep/mcp_020458GeV_q03_100evt_seed12345.root
```

It verifies event identity, PDG, mass, injection vertex, momentum, energy, beam direction, and active-LAr bookkeeping before ROOT -> HDF5 conversion.
