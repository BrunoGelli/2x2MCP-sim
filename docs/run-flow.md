# 5. Run charge-only Flow

This page reproduces the successful five-stage charge-only `ndlar_flow` reconstruction. It intentionally skips light reconstruction and charge-light association.

## Environment

Run on the host after leaving the larnd Podman container:

```bash
cd "$SCRATCH/2x2_mcp"

export MCP2X2_ROOT="$SCRATCH/2x2_mcp"
export NDLAR_DIR="$MCP2X2_ROOT/software/flow/ndlar_flow"

module unload python 2>/dev/null || true
module load python/3.11

source "$MCP2X2_ROOT/software/flow/flow.venv/bin/activate"
```

Verify:

```bash
which python
which h5flow

git -C "$MCP2X2_ROOT/software/flow/h5flow" rev-parse HEAD
git -C "$NDLAR_DIR" rev-parse HEAD
```

Expected commits:

```text
h5flow     1aaa36a0668f2a64f15703778c5c65168a24294f
ndlar_flow 4705e95d20c3582e6421feb55a17a21c3bb1c24e
```

!!! note "Flow virtual environment"
    The existing `software/flow/flow.venv` is the known-good runtime. A fully clean-account recreation of this environment has not yet been promoted to a regression-tested script. Preserve it and record its package state for a future baseline.

## Install project-owned runtime overlays

The upstream `ndlar_flow` submodule is kept clean. Copy the MCP project's known-good 2×2 files into the paths expected by Flow:

```bash
mkdir -p "$NDLAR_DIR/data/ndlar_flow"
mkdir -p "$NDLAR_DIR/data/proto_nd_flow"

command cp -f \
  "$MCP2X2_ROOT/configs/ndlar_flow/data/ndlar_flow/ndlar-module.yaml" \
  "$NDLAR_DIR/data/ndlar_flow/ndlar-module.yaml"

command cp -f \
  "$MCP2X2_ROOT/configs/ndlar_flow/data/proto_nd_flow/2x2.yaml" \
  "$NDLAR_DIR/data/proto_nd_flow/2x2.yaml"

command cp -f \
  "$MCP2X2_ROOT/configs/ndlar_flow/data/proto_nd_flow/multi_tile_layout-2.4.16_v4.yaml" \
  "$NDLAR_DIR/data/proto_nd_flow/multi_tile_layout-2.4.16_v4.yaml"

command cp -f \
  "$MCP2X2_ROOT/configs/ndlar_flow/data/proto_nd_flow/multi_tile_layout-2.5.16_v4.yaml" \
  "$NDLAR_DIR/data/proto_nd_flow/multi_tile_layout-2.5.16_v4.yaml"

command cp -f \
  "$MCP2X2_ROOT/configs/ndlar_flow/data/ndlar_flow/runlist-2x2-mcexample.txt" \
  "$NDLAR_DIR/data/proto_nd_flow/runlist-2x2-mcexample.txt"
```

`command cp -f` bypasses an interactive `cp -i` alias encountered on NERSC.

Expected temporary dirty state:

```bash
git -C "$NDLAR_DIR" status --short
```

The copied overlays are runtime state. Do not commit them inside the upstream submodule.

## Define input, output, and log

```bash
export FLOW_IN="$MCP2X2_ROOT/out/larnd/mcp_020458GeV_q03_100evt_seed12345.LARNDSIM.hdf5"

mkdir -p "$MCP2X2_ROOT/out/flow"
mkdir -p "$MCP2X2_ROOT/log/flow"

export FLOW_OUT="$MCP2X2_ROOT/out/flow/mcp_020458GeV_q03_100evt_seed12345.FLOW.hdf5"
export FLOW_LOG="$MCP2X2_ROOT/log/flow/mcp_020458GeV_q03_100evt_seed12345.log"

test -s "$FLOW_IN" || { echo "Missing larnd input"; exit 1; }
```

## Run the five charge workflows

Run from the `ndlar_flow` root because YAML and data paths are repository-relative:

```bash
cd "$NDLAR_DIR"
rm -f "$FLOW_OUT"

h5flow -z lzf \
  -c \
  yamls/proto_nd_flow/workflows/charge/charge_event_building_mc.yaml \
  yamls/proto_nd_flow/workflows/charge/charge_event_reconstruction_mc.yaml \
  yamls/proto_nd_flow/workflows/combined/combined_reconstruction_mc.yaml \
  yamls/proto_nd_flow/workflows/charge/prompt_calibration_mc.yaml \
  yamls/proto_nd_flow/workflows/charge/final_calibration_mc.yaml \
  -i "$FLOW_IN" \
  -o "$FLOW_OUT" \
  2>&1 | tee "$FLOW_LOG"

status=${PIPESTATUS[0]}
echo "Flow exit status: $status"
test "$status" -eq 0
```

This is the charge portion of the standard external 2×2 Flow wrapper. It intentionally omits:

```text
light_event_building_mc
light_event_reconstruction_mc
charge_light_assoc_mc
```

## Expected workflow progression

```text
WORKFLOW 1/5  charge event building
WORKFLOW 2/5  raw charge reconstruction
WORKFLOW 3/5  combined t0 reconstruction
WORKFLOW 4/5  prompt calibration
WORKFLOW 5/5  final calibration/noise filtering
```

Each workflow must reach its `FINISH` block and the final shell status must be zero.

## Inspect the output

```bash
ls -lh "$FLOW_OUT" "$FLOW_LOG"

python - "$FLOW_OUT" <<'PY'
import sys
import h5py

with h5py.File(sys.argv[1], "r") as f:
    print("Top-level Flow content:")
    for name in f:
        obj = f[name]
        print(f"  {name:32s}", getattr(obj, "shape", "<group>"))
print("FLOW FILE OPEN/CLOSE: PASS")
PY
```

Worked-reference output:

```text
size: ~3.2 MB
charge          group
combined        group
geometry_info   group
lar_info        group
mc_truth        group
run_info        group
```

For a detailed inventory:

```bash
python - "$FLOW_OUT" <<'PY'
import sys
import h5py

with h5py.File(sys.argv[1], "r") as f:
    def visit(name, obj):
        if isinstance(obj, h5py.Dataset):
            print(f"{name:70s} {obj.shape}")
    f.visititems(visit)
PY
```

## Warnings observed in the successful run

### No mpi4py

```text
Running without mpi4py
```

The small reference ran serially and completed. Decide deliberately whether production jobs should be serial or MPI-enabled.

### Input path absent from runlist

Flow did not find the realistic filename in the example runlist and used MC defaults. This worked, but production should use an explicit MCP runlist/run-data entry rather than relying silently on fallback values.

### `vertex_id` fallback

The raw event generator used `vertex_id` because `file_vertex_id` was unavailable. This is safe for this single-file reference but can collide across merged shards.

### No neutrino interactions

Expected for MCP-only simulation. Do not fabricate neutrino truth to silence it.

### scikit-learn version mismatch

A `KernelDensity` pickle created under scikit-learn 1.3.2 was loaded under 1.9.0. The job completed, but the environment/model should be pinned or regenerated before large production.

### Default threshold fallback

The four processed event groups reported:

```text
10 of 170 channels
11 of 198 channels
11 of 252 channels
8 of 69 channels
```

using the default threshold. Preserve this in detector-response systematics.

## Clean the runtime overlays after use

See [Git and Repository Workflow](git-workflow.md). A selective cleanup is preferred when only the documented overlays were copied.
