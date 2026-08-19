# Quick Start

This page is a compact map. Follow the numbered manual pages for explanations and validation.

## 1. Synchronize the repository

On a normal NERSC shell:

```bash
cd "$SCRATCH/2x2_mcp"

git status -sb
git fetch origin
git pull --ff-only origin feature/pythia-spectrum-input

git submodule sync --recursive
git submodule update --init --recursive
```

If `software/flow/ndlar_flow` is dirty because runtime overlays were copied during a previous Flow run, read [Git and Repository Workflow](git-workflow.md) before cleaning it.

## 2. Establish paths

```bash
export MCP2X2_ROOT="$SCRATCH/2x2_mcp"
export TWOBYTWO_SIM="$SCRATCH/2x2_sim"
```

## 3. Build and sample the Pythia flux

The first reference model and sample commands are documented in [Build and Sample the Flux](run-generator.md).

Expected sample prefix:

```text
out/generator/mcp_020458GeV_100evt_seed12345
```

## 4. Run EDepSim in Shifter

```bash
shifter --image=mjkramer/sim2x2:ndlar011 --module=cvmfs /bin/bash
```

Inside Shifter:

```bash
source /opt/environment
export MCP2X2_ROOT="$SCRATCH/2x2_mcp"
export PATH="$MCP2X2_ROOT/software/edep-sim_install/bin:$PATH"
export LD_LIBRARY_PATH="$MCP2X2_ROOT/software/edep-sim_install/lib:${LD_LIBRARY_PATH:-}"
```

Then follow [Run and Validate EDepSim](run-edepsim.md).

## 5. Convert ROOT to HDF5

Still in the CPU simulation environment:

```bash
export ARCUBE_ACTIVE_VOLUME=volTPCActive
```

Follow [Convert ROOT to HDF5](run-convert2h5.md), preserve the raw converted file, and create a clean larnd input copy.

## 6. Run larnd-sim on a GPU node

Exit Shifter, obtain a GPU allocation, and launch the validated container:

```bash
salloc -A dune -q interactive -C gpu -t 00:30:00

cd "$SCRATCH/2x2_mcp"
./scripts/launch_larnd_container.sh
```

A healthy current launcher must end with:

```text
CONTAINER VALIDATION: PASS
larnd-sim environment ready
```

Then follow [Run larnd-sim](run-larnd-sim.md).

## 7. Run charge-only Flow

Back on the host:

```bash
module unload python 2>/dev/null || true
module load python/3.11
source "$SCRATCH/2x2_mcp/software/flow/flow.venv/bin/activate"
```

Follow [Run charge-only Flow](run-flow.md).

## 8. Compare against the worked reference

Use [Worked 100-event Reference](reference-sample.md). The most important closure points are:

```text
100 manifest events
100 EDepSim events
97 converted vertices
1331 converted segments
2142 larnd packets
941 data packets
5/5 charge Flow workflows
```
