# Provenance and Freezing

## Why provenance is part of the physics result

The expected MCP yield combines source normalization and several detector efficiencies. A result cannot be reproduced from a final HDF5 file alone.

Every important sample should identify:

- the production model and normalization source;
- the exact kinematic model;
- geometry and coordinate conventions;
- all software commits;
- random seeds;
- external configuration files;
- stage counts and warnings;
- checksums of preserved artifacts.

## Minimum production manifest

A future top-level production tool should write at least:

```yaml
production_id: mcp_020458GeV_q03_seed12345
created_utc: 2026-08-19T00:00:00Z

physics:
  mass_mev: 20.458
  charge_e: 0.3
  pdg: 9000001

generator:
  flux_stage: accepted
  model_type: weighted_empirical_donor_local_jitter_v3
  model_sha256: e2fe01ded73ded3e99ea713bedad1cf2bbaad4f656ff6cf6b810d15bfaf32bda
  seed: 12345
  jitter_scale: 0.5
  accepted_flux_per_pot_epsilon2: 7.495143384150902e-06
  event_weight_per_pot_epsilon2: 7.495143384150901e-08

coordinates:
  baseline_m: 1040
  beam_slope_y: -0.05836
  beam_axis_at_detector_m: [0, 0, 0]
  injection_z_m: -1.5
  transport_model: straight_line_v0

software:
  parent_commit: null
  edep_sim_commit: e489bba20fd83f820d6e446c26af05c0d372d077
  two_by_two_sim_commit: 7c621864155483fa30d741a69481fafd8fbcb5a8
  larnd_sim_commit: 3b6449466e1e8036413ad9c6750b04a68515aea3
  h5flow_commit: 1aaa36a0668f2a64f15703778c5c65168a24294f
  ndlar_flow_commit: 4705e95d20c3582e6421feb55a17a21c3bb1c24e
  larpix_control_commit: 5a69050422e82356c8faf9ad0ea3168c322d63e8

seeds:
  generator: 12345
  larnd: 67890

counts:
  generated: 100
  edep_events: 100
  active_lar_any: 97
  active_lar_primary: 96
  converted_vertices: 97
  converted_segments: 1331
  larnd_data_packets: 941

stages:
  generator: {status: pass, file: null, sha256: null}
  edep:      {status: pass, file: null, sha256: null}
  convert:   {status: pass, file: null, sha256: null}
  larnd:     {status: pass, file: null, sha256: null}
  flow:      {status: pass, file: null, sha256: null}
```

Do not copy this example without filling the null fields from the actual run.

## What to checksum

For a frozen sample:

```text
flux_model.npz
HEPEVT
manifest CSV
sample summary JSON
EDepSim macro
EDepSim ROOT
raw converted HDF5
clean larnd input HDF5
larnd output HDF5
Flow output HDF5
geometry GDML
converter script
runtime configuration overlays
```

Generate:

```bash
sha256sum FILES... > SHA256SUMS
sha256sum -c SHA256SUMS
```

## Environment capture

### Host and repository

```bash
date -u
hostname
uname -a

git rev-parse HEAD
git status --short
git submodule status

git -C "$SCRATCH/2x2_sim" rev-parse HEAD
```

### Geometry and converter

```bash
sha256sum "$GEOM"
sha256sum "$CONVERTER"
```

### larnd container

The setup script records a timestamped `pip freeze` after GPU validation. Also record:

```bash
nvidia-smi
python --version
python -m pip --version
python - <<'PY'
import numpy, cupy, numba, llvmlite
print(numpy.__version__)
print(cupy.__version__)
print(numba.__version__)
print(llvmlite.__version__)
PY
```

Capture the container image digest when tooling permits. A mutable tag alone is not a complete freeze.

### Flow environment

```bash
source "$MCP2X2_ROOT/software/flow/flow.venv/bin/activate"
python --version
python -m pip freeze > flow_pip_freeze.txt
```

The scikit-learn version is especially important because the reference emitted a serialized-model compatibility warning.

## Creating a new baseline

1. Start from clean parent and submodule states.
2. Record exact commits and external checksums.
3. Run a controlled reference with explicit seeds.
4. Validate every stage structurally and physically.
5. Preserve all stage outputs outside Git.
6. Generate checksums and verify them.
7. Store small manifests, summaries, logs, and notes in Git.
8. Add a descriptive parent commit and annotated tag.
9. Test checkout of the tag from a clean directory.
10. Copy large reference artifacts from scratch to durable storage.

## What belongs in Git

Track:

- scripts and small configurations;
- Markdown documentation;
- machine-readable manifests;
- summary tables;
- checksums;
- patches explaining local deviations;
- exact submodule pointers.

Do not track:

- ROOT files;
- large HDF5 files;
- virtual environments;
- build/install trees;
- logs or plots unless deliberately selected as small reference evidence.

## Documentation versioning

The handbook is stored in the parent repository. When freezing a baseline, tag the documentation with the code. Avoid an external GitHub Wiki as the canonical source because its history is a separate repository and can drift from the tagged simulation state.
