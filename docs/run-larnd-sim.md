# 4. Run larnd-sim

larnd-sim is the GPU stage. The repository launcher creates a disposable Podman-HPC container and validates the actual CUDA runtime before use.

## Leave the CPU simulation environment

Exit Shifter before launching Podman:

```bash
exit
```

You should be back at a normal NERSC host prompt.

## Obtain a GPU allocation

```bash
salloc -A dune -q interactive -C gpu -t 00:30:00
```

Account and QoS details can change; use the current DUNE allocation syntax when different.

## Launch the validated container

```bash
cd "$SCRATCH/2x2_mcp"
./scripts/launch_larnd_container.sh
```

The current setup performs:

1. base-container environment activation;
2. CUDA path configuration;
3. `numba-cuda[cu12]` overlay;
4. pip nvJitLink path selection;
5. pinned `larpix-control` installation with `--no-deps`;
6. larnd-sim commit verification;
7. editable larnd-sim installation;
8. CuPy and Numba CUDA execution tests;
9. package/CLI checks;
10. environment capture after validation.

A healthy launch ends with:

```text
CuPy GPU TEST: PASS
NUMBA CUDA JIT TEST: PASS
CONTAINER VALIDATION: PASS
larnd-sim environment ready
```

Do not start a production run if the validator fails.

## Expected source and runtime state

```bash
git -C "$MCP2X2_ROOT/software/larnd-sim-current" rev-parse HEAD
```

Expected:

```text
3b6449466e1e8036413ad9c6750b04a68515aea3
```

The worked container resolved:

```text
NumPy       1.26.2
CuPy        12.2.0
Numba       0.67.0
llvmlite    0.49.0
numba-cuda  0.30.4
nvJitLink   12.9
```

The setup is validated at runtime but is not yet an immutable digest+lockfile image. Preserve the timestamped pip freeze from every important run.

## Define files and seed

Inside Podman:

```bash
cd "$MCP2X2_ROOT"

export LARND_IN="$MCP2X2_ROOT/out/edep/mcp_020458GeV_q03_100evt_seed12345.LARNDINPUT.hdf5"

mkdir -p "$MCP2X2_ROOT/out/larnd"
mkdir -p "$MCP2X2_ROOT/log/larnd"

export LARND_OUT="$MCP2X2_ROOT/out/larnd/mcp_020458GeV_q03_100evt_seed12345.LARNDSIM.hdf5"
export LARND_LOG="$MCP2X2_ROOT/log/larnd/mcp_020458GeV_q03_100evt_seed12345.log"
export LARND_SEED=67890
```

Preflight:

```bash
python - "$LARND_IN" <<'PY'
import sys
import h5py
with h5py.File(sys.argv[1], "r") as f:
    print("vertices     :", len(f["vertices"]))
    print("trajectories :", len(f["trajectories"]))
    print("segments     :", len(f["segments"]))
    print("mc_hdr       :", "present" if "mc_hdr" in f else "absent")
    print("mc_stack     :", "present" if "mc_stack" in f else "absent")
PY
```

Expected:

```text
vertices      97
trajectories  622
segments      1331
mc_hdr        absent
mc_stack      absent
```

## Why `2x2_mpvmpr`

Use:

```text
2x2_mpvmpr
```

It retains the detailed module-dependent 2×2 response while using independent-event timing appropriate for MCP throws. The ordinary `2x2` configuration assumes beam-spill timing and is not the current baseline for these events.

## Run larnd-sim

```bash
rm -f "$LARND_OUT"

simulate_pixels.py 2x2_mpvmpr \
  --input_filename "$LARND_IN" \
  --output_filename "$LARND_OUT" \
  --rand_seed "$LARND_SEED" \
  2>&1 | tee "$LARND_LOG"

status=${PIPESTATUS[0]}
echo "larnd-sim exit status: $status"
test "$status" -eq 0
```

Do not add `--n_events` for this reference; process all 97 converted vertices.

## Worked-reference behavior

The successful run:

- used `singles_sim.yaml` and `2x2.yaml`;
- processed all four detector modules;
- used module-dependent pixel layouts, response files, threshold maps, and pedestal maps;
- rejected 60 neutral gamma segments;
- completed in `325.62s`;
- produced a file of about `382MB`.

## Inspect output

```bash
python - "$LARND_OUT" <<'PY'
import sys
import h5py
import numpy as np

with h5py.File(sys.argv[1], "r") as f:
    print("Top-level content:")
    for name in f:
        obj = f[name]
        print(f"  {name:24s}", getattr(obj, "shape", "<group>"))

    packets = f["packets"][:]
    print("packets:", len(packets))
    ptype, count = np.unique(packets["packet_type"], return_counts=True)
    print("packet types:")
    for p, n in zip(ptype, count):
        print(f"  {int(p):4d}: {int(n)}")

    print("mc_packets_assn:", len(f["mc_packets_assn"]))
    print("segments:", len(f["segments"]))
    print("trajectories:", len(f["trajectories"]))
    print("vertices:", len(f["vertices"]))
PY
```

Worked-reference result:

```text
packets          2142
packet type 0     941
packet type 4    1024
packet type 6      80
packet type 7      97
mc_packets_assn  2142
segments         1271
trajectories      622
vertices           97
```

`1271 = 1331 - 60` because neutral gamma segments are not charge-drift inputs.

## Light products in a charge-only campaign

The current `2x2_mpvmpr` run still calculates optical response and writes:

```text
light_trig  (97,)
light_wvfm  (97, 384, 1000)
```

The first realistic Flow pass intentionally ignores these datasets. Disabling light at larnd-sim may save significant time and storage in future charge-only production, but that optimization has not yet been validated and should be treated as a separate code/configuration task.

## Exit behavior

The container uses `--rm`; `/opt/venv` modifications vanish when you exit. Files under `$SCRATCH` persist.

```bash
exit
```

If the shell then remains inside a Slurm allocation, exit that allocation separately when finished.
