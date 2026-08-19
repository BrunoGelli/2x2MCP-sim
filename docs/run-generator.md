# 1. Build and Sample the Flux

This page reproduces the first realistic `mχ=20.458 MeV` accepted-stage sample.

## Environment

Run from a normal NERSC shell with a Python environment that provides PyROOT, NumPy, pandas, and matplotlib. The model builder reads Pythia ROOT files directly.

```bash
cd "$SCRATCH/2x2_mcp"
export MCP2X2_ROOT="$SCRATCH/2x2_mcp"

python - <<'PY'
import ROOT
import numpy
import pandas
import matplotlib
print("PyROOT:", ROOT.gROOT.GetVersion())
print("generator Python environment: OK")
PY
```

If PyROOT is unavailable, enter the same ROOT-enabled environment used for the existing generator work before continuing. The exact activation command is site/user-specific and is not yet wrapped by this repository.

## Confirm repository state

```bash
git branch --show-current
git status -sb
git log -1 --oneline
```

Expected branch:

```text
feature/pythia-spectrum-input
```

## Input production

The worked model used:

```bash
export PYTHIA_ROOT_DIR="/global/homes/b/bgelli/2x2MCP-PythiaGen/outputs/raw_combined_v2"
export PYTHIA_SUMMARY="/global/homes/b/bgelli/2x2MCP-PythiaGen/outputs/aggregate_summary_combined_v2.csv"
```

Confirm both:

```bash
test -d "$PYTHIA_ROOT_DIR" || { echo "Missing ROOT directory"; exit 1; }
test -s "$PYTHIA_SUMMARY" || { echo "Missing aggregate summary"; exit 1; }
```

## Build the accepted-stage model

```bash
cd "$MCP2X2_ROOT"

python generator/build_pythia_flux_model.py \
  "$PYTHIA_ROOT_DIR" \
  --summary "$PYTHIA_SUMMARY" \
  --mass-gev 0.020458 \
  --geometry-id 1 \
  --flux-stage accepted \
  --output-dir out/flux_models/mcp_020458GeV_accepted_v3 \
  --production-tag accepted_flux_empirical_v3
```

Add the Pythia generator commit when known:

```text
--pythia-gen-git-sha <commit>
```

## Required build checks

The command must produce:

```text
out/flux_models/mcp_020458GeV_accepted_v3/
├── flux_model.npz
├── provenance.json
├── component_normalization.csv
├── input_summary_audit.csv
└── plots/
    ├── flux_model_overview.png
    ├── flux_model_resampling_validation.png
    ├── flux_model_projection_validation.png
    ├── pythia_detector_projection.png
    ├── flux_vs_mass.png
    └── flux_vs_mass.csv
```

Inspect the counter audit:

```bash
python - <<'PY'
import pandas as pd
fn = "out/flux_models/mcp_020458GeV_accepted_v3/input_summary_audit.csv"
df = pd.read_csv(fn)
print(df.to_string(index=False))
assert df["all_counts_match"].all()
print("INPUT SUMMARY AUDIT: PASS")
PY
```

Inspect normalization:

```bash
column -s, -t \
  < out/flux_models/mcp_020458GeV_accepted_v3/component_normalization.csv \
  | less -S
```

Review every plot before sampling. In particular:

- the central module gap must remain empty;
- resampled energy tails must remain inside donor support;
- emitter fractions must be physically normalized;
- original and resampled detector-plane projections must agree within the finite donor statistics.

## Record the model checksum

```bash
sha256sum out/flux_models/mcp_020458GeV_accepted_v3/flux_model.npz
```

Worked-reference checksum:

```text
e2fe01ded73ded3e99ea713bedad1cf2bbaad4f656ff6cf6b810d15bfaf32bda
```

A mismatch can be legitimate after a deliberate model/code change, but it must trigger a new validation and provenance record.

## Sample the deterministic 100-event reference

The first sample intentionally maps the accepted-window center to the detector center. Pass the coordinates explicitly rather than depending on defaults:

```bash
cd "$MCP2X2_ROOT"

python generator/sample_pythia_flux.py \
  out/flux_models/mcp_020458GeV_accepted_v3/flux_model.npz \
  out/generator/mcp_020458GeV_100evt_seed12345 \
  --n-events 100 \
  --seed 12345 \
  --jitter-scale 0.5 \
  --baseline-m 1040 \
  --beam-slope-y -0.05836 \
  --beam-axis-x-m 0.0 \
  --beam-axis-y-m 0.0 \
  --detector-z-m 0.0 \
  --injection-distance-m 1.5
```

!!! warning "Why beam-axis y is zero here"
    The first accepted-stage sample deliberately does **not** use the MiniRun5 `-0.42m` vertical offset. Applying that offset self-consistently requires a sufficiently populated pre-acceptance/source model.

## Expected sampler output

The console coordinate check should be approximately:

```text
Pythia (0,0,+1) -> 2x2 (+0.00000000, -0.05826087, +0.99830139)
```

The worked sample reports:

```text
Events written: 100
Geometry consistency diagnostic: 99.000%
Accepted flux / POT / epsilon^2: 7.49514338415e-06
Per-event weight / POT / epsilon^2: 7.49514338415e-08
```

Products:

```text
out/generator/mcp_020458GeV_100evt_seed12345.hepevt
out/generator/mcp_020458GeV_100evt_seed12345.manifest.csv
out/generator/mcp_020458GeV_100evt_seed12345.summary.json
out/generator/mcp_020458GeV_100evt_seed12345.mac
out/generator/mcp_020458GeV_100evt_seed12345.sampled_flux.png
```

## Validate the sample products

```bash
python - <<'PY'
import csv
import json
from pathlib import Path

prefix = Path("out/generator/mcp_020458GeV_100evt_seed12345")
required = [
    prefix.with_suffix(".hepevt"),
    prefix.with_suffix(".manifest.csv"),
    prefix.with_suffix(".summary.json"),
    prefix.with_suffix(".mac"),
    prefix.with_suffix(".sampled_flux.png"),
]
for p in required:
    assert p.is_file() and p.stat().st_size > 0, p
    print("OK", p)

with prefix.with_suffix(".manifest.csv").open(newline="") as f:
    rows = list(csv.DictReader(f))
assert len(rows) == 100
assert [int(r["edepsim_event_id"]) for r in rows] == list(range(100))

summary = json.loads(prefix.with_suffix(".summary.json").read_text())
assert summary["events_written"] == 100
assert abs(summary["mcp_mass_GeV"] - 0.020458) < 1e-12
assert summary["seed"] == 12345
assert abs(summary["jitter_scale"] - 0.5) < 1e-12

print("GENERATOR SAMPLE: PASS")
PY
```

Also inspect:

```bash
cat out/generator/mcp_020458GeV_100evt_seed12345.mac
python -m json.tool \
  out/generator/mcp_020458GeV_100evt_seed12345.summary.json \
  | less
```

The macro must retain:

```text
/edep/phys/ionizationModel 0
/edep/hitSeparation volTPCActive -1 mm
/generator/kinematics/hepevt/flavor pbomb
/edep/db/set/requireEventsWithHits false
```

## Charge-scan rule

Reuse this same HEPEVT sample for other charges at fixed mass. Do not resample kinematics for each detector charge unless there is a documented reason.
