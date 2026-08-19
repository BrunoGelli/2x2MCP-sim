# 2. Run and Validate EDepSim

The first realistic sample should enter the same custom EDepSim and GDML used by the controlled baseline.

## Enter the CPU simulation environment

From a normal Perlmutter shell:

```bash
shifter \
  --image=mjkramer/sim2x2:ndlar011 \
  --module=cvmfs \
  /bin/bash
```

Inside Shifter:

```bash
source /opt/environment

export MCP2X2_ROOT="$SCRATCH/2x2_mcp"
export TWOBYTWO_SIM="$SCRATCH/2x2_sim"

export PATH="$MCP2X2_ROOT/software/edep-sim_install/bin:$PATH"
export LD_LIBRARY_PATH="$MCP2X2_ROOT/software/edep-sim_install/lib:${LD_LIBRARY_PATH:-}"
```

## Verify the custom executable

```bash
which edep-sim
git -C "$MCP2X2_ROOT/software/edep-sim" rev-parse HEAD
```

Expected executable path:

```text
$SCRATCH/2x2_mcp/software/edep-sim_install/bin/edep-sim
```

Expected source commit:

```text
e489bba20fd83f820d6e446c26af05c0d372d077
```

Do not allow a stock `/opt/generators/...` EDepSim to take precedence.

## Define inputs and physics point

```bash
cd "$MCP2X2_ROOT"

export SAMPLE_PREFIX="$MCP2X2_ROOT/out/generator/mcp_020458GeV_100evt_seed12345"
export GEOM="$TWOBYTWO_SIM/geometry/Merged2x2MINERvA_v4/Merged2x2MINERvA_v4_withRock.gdml"

export EDEPSIM_MCP_MASS_MEV=20.458
export EDEPSIM_MCP_CHARGE=0.3

mkdir -p "$MCP2X2_ROOT/out/edep"
mkdir -p "$MCP2X2_ROOT/log/edep"

export OUTROOT="$MCP2X2_ROOT/out/edep/mcp_020458GeV_q03_100evt_seed12345.root"
export OUTLOG="$MCP2X2_ROOT/log/edep/mcp_020458GeV_q03_100evt_seed12345.log"
```

Preflight:

```bash
for f in \
  "$SAMPLE_PREFIX.hepevt" \
  "$SAMPLE_PREFIX.manifest.csv" \
  "$SAMPLE_PREFIX.summary.json" \
  "$SAMPLE_PREFIX.mac" \
  "$GEOM"; do
    test -s "$f" || { echo "Missing input: $f"; exit 1; }
done
```

## Run EDepSim

Run from the project root so a relative HEPEVT path inside the generated macro resolves correctly:

```bash
cd "$MCP2X2_ROOT"
rm -f "$OUTROOT"

"$MCP2X2_ROOT/software/edep-sim_install/bin/edep-sim" \
  -C \
  -g "$GEOM" \
  -o "$OUTROOT" \
  -e 100 \
  "$SAMPLE_PREFIX.mac" \
  2>&1 | tee "$OUTLOG"

status=${PIPESTATUS[0]}
echo "EDepSim exit status: $status"
test "$status" -eq 0
```

## Basic ROOT analysis

```bash
python "$MCP2X2_ROOT/gun_tests/analyze_gun.py" "$OUTROOT"
```

The worked reference reports:

```text
Events stored             100
PDG                       9000001
mass                      20.458000 MeV
TPC segments/event        13.31
primary TPC Edep/event    19.0813 MeV
primary path/event        1085.93 mm
primary dE/dx             0.0175775 MeV/mm
```

The analyzer's displayed initial momentum/energy are representative of the first primary; the realistic sample has a broad energy distribution. Use the event-by-event validator for the actual interface test.

## Event-by-event Pythia→EDepSim validation

```bash
cd "$MCP2X2_ROOT"

python generator/validate_pythia_edep.py \
  "$SAMPLE_PREFIX.manifest.csv" \
  "$OUTROOT"
```

Required result:

```text
VALIDATION: PASS
```

Worked-reference residuals:

| Quantity | Maximum component difference |
|---|---:|
| Position | `4.97494e-10 mm` |
| Momentum | `4.82632e-08 MeV/c` |
| Total energy | `4.81887e-08 MeV` |
| Mass | `2.75953e-08 MeV` |

Expected mean direction:

```text
(-0.00000068, -0.05826939, +0.99830075)
```

Expected event bookkeeping:

```text
100 ROOT events
97 with any volTPCActive segment
96 with direct primary MCP activity
1331 active-LAr segments
2323.42025 MeV total active-LAr deposition
```

## Interpreting the 97/96 difference

- Events `31`, `80`, and `90` have no selected active-volume segment.
- Event `20` has active-LAr deposition from secondaries but no segment directly attributed to the MCP primary.

This is valid detector/transport behavior, not an interface failure.

## Do not proceed when

Stop before conversion if any of these occur:

- ROOT event count differs from the manifest;
- primary PDG or mass is wrong;
- event IDs are missing or reordered;
- coordinate/momentum residuals are larger than plausible file precision;
- mean direction is not dominantly `+z` with the expected small `-y` slope;
- EDepSim used a different executable or geometry.
