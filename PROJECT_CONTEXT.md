# MCP 2×2 Simulation — Canonical Project Context

> **Purpose:** canonical AI/code-agent handoff for the `2x2MCP-sim` project. Read this file before proposing, reviewing, or implementing changes to the simulation chain.
>
> **Documented state:** 2026-08-19, after the first realistic Pythia-derived 100-event sample successfully reached charge-only `ndlar_flow` reconstruction.
>
> **Scope:** this file describes the current technical state, decisions, validated configurations, known limitations, and operator preferences. The human operational manual lives in the MkDocs handbook under `docs/`.

---

## 1. Project identity

- **Repository:** `BrunoGelli/2x2MCP-sim`
- **Development branch for the realistic generator:** `feature/pythia-spectrum-input`
- **NERSC checkout:** `/pscratch/sd/b/bgelli/2x2_mcp`
- **Convenience variable:** `MCP2X2_ROOT=$SCRATCH/2x2_mcp`
- **Primary platform:** NERSC Perlmutter
- **Scientific target:** simulate millicharged particles (MCPs) in the DUNE ND-LAr 2×2 demonstrator, preserving generator normalization, detector response, truth associations, and reconstruction efficiency.

The current full chain is:

```text
2x2MCP-PythiaGen production
        ↓
empirical Pythia flux model
        ↓
HEPEVT + manifest + summary + EDepSim macro
        ↓
custom EDepSim / Geant4 MCP transport
        ↓
EDepSim ROOT
        ↓
ROOT → HDF5 conversion
        ↓
larnd-sim charge + optical detector response
        ↓
LArPix packets + truth associations
        ↓
ndlar_flow reconstruction
        ↓
Flow HDF5
        ↓
event display and MCP analysis
```

The pipeline is intentionally divided into independent, restartable stages. A late-stage failure must not require rerunning Pythia or EDepSim.

---

## 2. Authority order when documents disagree

Some older notes describe earlier prototypes. Use this priority order:

1. **Machine-readable provenance generated with the sample** (`*.summary.json`, `*.manifest.csv`, model `provenance.json`, checksums).
2. **This file**, `PROJECT_CONTEXT.md`, for current cross-stage project state.
3. `generator/FLUX_MODEL_WORKFLOW.md` for the realistic flux architecture.
4. `generator/EMPIRICAL_RESAMPLING_V3.md` for the current donor+jitter algorithm.
5. `generator/GEOMETRY_AUDIT.md` for the accepted-window versus detector-global geometry distinction.
6. The MkDocs handbook under `docs/` for operator instructions.
7. The root `README.md` for the frozen historical baseline and broad repository background.
8. Older chat logs or deprecated generator notes only as historical context.

Important examples of superseded material:

- The physical Pythia beam is **not** mapped to EDepSim `-x`.
- The current flux sampler is **not** uniform sampling inside 3D histogram cells.
- The first realistic sample does **not** use the MiniRun5 `y=-0.42 m` beam-axis offset.
- The current larnd-sim CLI uses the named configuration as a positional argument: `simulate_pixels.py 2x2_mpvmpr ...`.

---

## 3. Current milestone

Two distinct milestones must remain separate.

### 3.1 Frozen controlled GPS baseline (2026-08-17)

A monoenergetic MCP gun was validated end to end:

```text
GPS MCP → EDepSim → convert2h5 → larnd-sim → ndlar_flow → event display
```

This baseline uses a simple transverse trajectory and remains the regression instrument for:

- custom-particle behavior;
- unit-charge MCP versus muon agreement;
- approximate `q²` energy-loss scaling;
- charge scans down to about `q=0.01e`;
- geometry and coordinate plumbing;
- conversion, larnd-sim, Flow, and display compatibility.

Do not remove or repurpose the controlled gun to serve as the realistic generator.

### 3.2 First realistic Pythia-derived sample (2026-08-19)

A deterministic 100-event sample using Pythia-derived kinematics was validated through:

```text
empirical accepted-flux model
→ HEPEVT
→ custom EDepSim
→ ROOT→HDF5
→ larnd-sim
→ charge-only ndlar_flow
```

The realistic sample has **not yet been promoted to a frozen tagged baseline**, and its Flow output has not yet been checked in the event display. It is nevertheless the first demonstrated realistic generator-to-reconstruction path.

---

## 4. Pinned and external software state

### 4.1 Parent-managed submodules

| Component | Path | Validated commit |
|---|---|---|
| Custom EDepSim | `software/edep-sim` | `e489bba20fd83f820d6e446c26af05c0d372d077` |
| larnd-sim | `software/larnd-sim-current` | `3b6449466e1e8036413ad9c6750b04a68515aea3` |
| h5flow | `software/flow/h5flow` | `1aaa36a0668f2a64f15703778c5c65168a24294f` |
| ndlar_flow | `software/flow/ndlar_flow` | `4705e95d20c3582e6421feb55a17a21c3bb1c24e` |

### 4.2 Runtime-pinned dependency

| Component | Commit |
|---|---|
| larpix-control | `5a69050422e82356c8faf9ad0ea3168c322d63e8` |

### 4.3 External `2x2_sim` checkout used by the realistic sample

- Commit: `7c621864155483fa30d741a69481fafd8fbcb5a8`
- Geometry:
  `geometry/Merged2x2MINERvA_v4/Merged2x2MINERvA_v4_withRock.gdml`
- Converter:
  `run-convert2h5/convert_edepsim_roottoh5.py`
- Runtime path: `$SCRATCH/2x2_sim`

This external checkout is not yet a submodule of `2x2MCP-sim`. Record its commit and the geometry checksum in every future frozen production.

### 4.4 Container

- Base tag: `docker.io/mjkramer/sim2x2:ndlar011`
- Launch: `scripts/launch_larnd_container.sh`
- The image tag is documented, but the image digest has not yet been frozen.

---

## 5. Custom MCP physics in EDepSim

### 5.1 Particle definition

| Property | Value |
|---|---|
| Geant4 name | `mcp` |
| PDG | `9000001` |
| Stable | yes |
| Spin | 1/2 |
| Type/subtype | lepton / mcp |
| Runtime mass | `EDEPSIM_MCP_MASS_MEV` |
| Runtime charge | `EDEPSIM_MCP_CHARGE` |

The validated implementation rejects:

- mass `<=10 MeV`;
- zero charge;
- malformed or non-finite environment-variable values.

### 5.2 Attached processes

```text
G4hMultipleScattering
G4hIonisation
```

Not implemented as dedicated MCP processes:

- bremsstrahlung;
- pair production;
- a separate single-Coulomb-scattering model;
- a dedicated low-mass ionization model;
- separate MCP and anti-MCP truth species.

Changing the sign of `EDEPSIM_MCP_CHARGE` does not create a separate antiparticle PDG definition.

### 5.3 Validation facts

- A unit-charge MCP with muon mass agreed with a standard muon under the controlled gun.
- The charge scan followed approximately `q²` energy-loss behavior down to about `q=0.01e`.
- An EDepSim step-limiter condition changes at `|q|>0.1e`; the scan did not reveal a physical discontinuity, but this implementation detail must remain documented.
- The controlled and realistic macros use `/edep/phys/ionizationModel 0` to avoid a charge-based particle-category branch that is conceptually unsafe for MCPs.

### 5.4 Interpretation at low charge

Never report only conditional `dE/dx` among events with hits. Preserve separately:

```text
all generated events
geometrically relevant events
events with active-LAr deposition
events with direct primary MCP deposition
events surviving conversion
events producing packets
events reconstructed
```

Low-charge efficiency can fall even when the conditional energy-loss distribution still follows `q²`.

---

## 6. Realistic Pythia flux model

### 6.1 Source repository

Production inputs come from `BrunoGelli/2x2MCP-PythiaGen`.

### 6.2 Current model stage

The first detector study uses:

```text
flux_stage = accepted
geometry_id = 1
```

This means the model is conditioned on the existing Pythia 2×2 acceptance. It uses `n_mcp_accepted` for physical normalization. The sampler does **not** apply a second physical acceptance rejection; the post-rotation face check is diagnostic only.

The `source` stage remains in the architecture for future pre-acceptance sampling and beamline transport. It is required once scattering, energy loss, or magnetic effects can move trajectories into or out of acceptance.

### 6.3 Current kinematic model

```text
schema: 3
model type: weighted_empirical_donor_local_jitter_v3
```

For each emitter, accepted Pythia rows are stored as donors in:

```text
log10(E)
x_at_detector_m
y_at_detector_m
```

A throw:

1. chooses an emitter with its physically normalized flux fraction;
2. chooses a real donor using the spectrum-prescale weight;
3. jitters locally inside nearest-neighbor midpoint cells;
4. preserves the observed energy domain without extrapolation;
5. treats left and right detector modules independently, preventing interpolation across the central gap.

Default jitter scale:

```text
0.5
```

Interpretation:

```text
0.0 = exact weighted bootstrap
0.5 = half adaptive local cell (current default)
1.0 = full local midpoint cell
```

### 6.4 Physical component normalization

Supported parent components, when kinematically open:

```text
pi0, eta, eta', rho0, omega, phi, J/psi
```

The raw number of stored Pythia rows does not determine the physical mixture. Shapes come from `mcp_spectra`; normalization comes from the aggregate summary and the same branching/process convention used in the Pythia export tools.

Model units:

```text
MCP / POT / epsilon^2
```

The common `epsilon²` factor is restored later for the requested physical charge. Detector charge scans should reuse the same HEPEVT trajectories whenever possible.

### 6.5 Build and audit state for 20.458 MeV

The current model was built from the combined production at:

```text
/global/homes/b/bgelli/2x2MCP-PythiaGen/outputs/raw_combined_v2/
```

with aggregate summary:

```text
/global/homes/b/bgelli/2x2MCP-PythiaGen/outputs/aggregate_summary_combined_v2.csv
```

The model's ROOT-counter audit passed for every selected emitter. Matching donor files at this mass came from `base_4h` and `global_v2`; `endpoint_v1` did not contribute matching donor files at this mass.

Total accepted flux:

```text
7.495143384150902e-06 MCP / POT / epsilon^2
```

Model file SHA-256:

```text
e2fe01ded73ded3e99ea713bedad1cf2bbaad4f656ff6cf6b810d15bfaf32bda
```

---

## 7. Coordinate and beamline conventions

### 7.1 Directions

Pythia nominal beam:

```text
(0, 0, +1)
```

Current 2×2 on-axis direction:

```text
(0.0, -0.05826086929091219, 0.9983013929217305)
```

The transform is a rotation about global `+x`. There is no x/z permutation. The negative y component represents the approximately 3.34-degree downward NuMI direction.

### 7.2 First-sample geometry choice

For the first accepted-stage pipeline test:

```text
beam axis at detector = (0, 0, 0) m
baseline              = 1040 m
injection plane z     = -1.5 m
beam slope y/z        = -0.05836
```

The Level-0 target position recorded in the sample is:

```text
(0.0, 60.59130406254868, -1038.2334486385996) m
```

The MiniRun5 convention `beam-axis y=-0.42 m` is deliberately deferred. An accepted-only training model cannot recover particles that the old Pythia window rejected but a shifted detector-global window would accept. Apply the real offset only with a sufficiently populated pre-acceptance/source model or a carefully redefined acceptance treatment.

### 7.3 Beamline model

```text
straight_line_v0
```

Explicitly disabled between target and local injection:

```text
beamline energy loss
multiple scattering
magnetic deflection
attenuation
hard material interactions
```

This is a named Level-0 approximation, not a statement that real NuMI material effects are negligible for all masses and charges.

---

## 8. First realistic 100-event sample

### 8.1 Generator provenance

| Quantity | Value |
|---|---:|
| MCP mass | `20.458 MeV` |
| Events | `100` |
| Seed | `12345` |
| Jitter scale | `0.5` |
| Flux stage | `accepted` |
| Model type | `weighted_empirical_donor_local_jitter_v3` |
| Emitter count in this throw | `pi0: 98`, `eta: 2` |
| Energy range | `0.7653915–70.7053422 GeV` |
| Median energy | `7.3976680 GeV` |
| Geometry-consistency diagnostic | `99/100` |
| Accepted flux | `7.495143384150902e-06 / POT / epsilon²` |
| Event weight | `7.495143384150901e-08 / POT / epsilon²` |

Products:

```text
out/generator/mcp_020458GeV_100evt_seed12345.hepevt
out/generator/mcp_020458GeV_100evt_seed12345.manifest.csv
out/generator/mcp_020458GeV_100evt_seed12345.summary.json
out/generator/mcp_020458GeV_100evt_seed12345.mac
out/generator/mcp_020458GeV_100evt_seed12345.sampled_flux.png
```

The macro selects EDepSim's HEPEVT `pbomb` reader, free vertex/time, one particle per event, `ionizationModel 0`, and `requireEventsWithHits false`.

### 8.2 EDepSim point

```text
EDEPSIM_MCP_MASS_MEV = 20.458
EDEPSIM_MCP_CHARGE    = 0.3
```

`q=0.3e` was chosen as a high-signal integration test. A later realistic production should include lower charges such as `q=0.01e`; those points require substantially more statistics and careful threshold-efficiency bookkeeping.

---

## 9. Validated stage closure for the realistic sample

### 9.1 Pythia manifest → EDepSim ROOT

| Check | Result |
|---|---:|
| Manifest events | 100 |
| ROOT events | 100 |
| Missing IDs | none |
| Bad primary counts | none |
| Bad PDGs | none |
| Max position-component difference | `4.97494e-10 mm` |
| Max momentum-component difference | `4.82632e-08 MeV/c` |
| Max total-energy difference | `4.81887e-08 MeV` |
| Max mass difference | `2.75953e-08 MeV` |
| Mean direction | `(-6.8e-7, -0.05826939, +0.99830075)` |
| Events with any TPC segment | `97/100` |
| Events with primary MCP TPC segment | `96/100` |
| TPC segments | `1331` |
| Total TPC Edep | `2323.42025 MeV` |
| Mean primary dE/dx | `0.0175774809 MeV/mm` |
| Validator | PASS |

Representative analyzer summary:

```text
primary Edep/event       19.0813 MeV
primary path/event       1085.93 mm
primary dE/dx            0.0175775 MeV/mm
secondary trajectories   e- 2947, gamma 738, e+ 44
```

### 9.2 ROOT → converted HDF5

Raw converted file:

```text
vertices      97
trajectories  622
segments      1331
mc_hdr        0
mc_stack      0
total dE      2323.42041 MeV
```

The ROOT and HDF5 active-LAr totals agree to conversion precision.

The three absent converted event IDs are:

```text
31, 80, 90
```

They had no selected active-volume segment. Event 20 had active-LAr deposition only through secondaries, explaining `97` events with any activity versus `96` with direct primary activity.

### 9.3 Clean larnd-sim input

The raw `.EDEPSIM.hdf5` is preserved. A copy named `.LARNDINPUT.hdf5` removes only zero-length `mc_hdr` and `mc_stack`.

Never delete non-empty generator-truth datasets.

### 9.4 larnd-sim

Configuration and seed:

```text
2x2_mpvmpr
rand_seed = 67890
```

Results:

```text
vertices             97
input segments       1331
neutral segments rejected 60
output segments      1271
packets               2142
mc_packets_assn       2142
packet type 0          941
packet type 4         1024
packet type 6           80
packet type 7           97
elapsed time        325.62 s
output size          ~382 MB
```

All four detector modules completed. Optical response was simulated and produced `light_wvfm`, although the next stage intentionally ran charge-only Flow.

### 9.5 charge-only ndlar_flow

Five workflows completed with exit status 0:

```text
charge_event_building_mc
charge_event_reconstruction_mc
combined_reconstruction_mc
prompt_calibration_mc
final_calibration_mc
```

Output:

```text
size ~3.2 MB
top-level groups:
  charge
  combined
  geometry_info
  lar_info
  mc_truth
  run_info
```

This realistic sample has not yet run the light workflows, charge-light association, or event display.

---

## 10. Runtime environment decisions

### 10.1 EDepSim and conversion

The successful path used the standard `mjkramer/sim2x2:ndlar011` Shifter environment for CPU-side EDepSim/conversion, then explicitly selected the locally built custom EDepSim executable and library.

### 10.2 larnd-sim

Use Podman-HPC through:

```bash
./scripts/launch_larnd_container.sh
```

The base image supplies the broad 2×2 environment; the script overlays the pinned modern larnd-sim and CUDA-Python support.

Observed known-good Python/CUDA stack:

```text
NumPy       1.26.2
CuPy        12.2.0
Numba       0.67.0
llvmlite    0.49.0
numba-cuda  0.30.4
nvJitLink   12.9
```

The setup validator must execute both a CuPy GPU operation and a real Numba CUDA JIT kernel before declaring the environment ready.

### 10.3 Critical dependency rule

Pinned `larpix-control` must be installed with:

```text
--no-deps
```

Without it, pip previously upgraded NumPy to 2.x and reinstalled Numba/llvmlite, breaking CuPy and then exposing a binary ABI mismatch.

Recovery policy:

```text
fix the persistent setup script
→ exit the disposable --rm container
→ relaunch a clean container
```

Do not compile CUDA or Numba and do not keep performing package surgery inside a contaminated disposable container.

### 10.4 Flow

Flow runs on the host using:

```text
software/flow/flow.venv
```

with Python 3.11 and the pinned h5flow/ndlar_flow submodules. Project-specific 2×2 configuration overlays live under top-level `configs/ndlar_flow/` and are copied into the clean upstream submodule at runtime.

The submodule becoming dirty after overlay installation is expected. Do not commit those copied runtime files inside the upstream submodule.

---

## 11. Known warnings and their current interpretation

### 11.1 ROOT→HDF5 NumPy deprecation warning

The converter assigns a one-element array to scalar `pdg_id`. NumPy 1.25+ warns that this will become an error in the future. It did not alter this sample's numerical closure. Modernize the converter before a future NumPy upgrade.

### 11.2 No `mpi4py` in Flow

Flow warns and runs serially. This is acceptable for the small validation sample. Production should decide deliberately between serial jobs and an MPI-enabled environment.

### 11.3 Flow input not found in runlist

The sample filename did not match a runlist row, so MC defaults were used. Current defaults include:

```text
e_field             0.05 kV/mm
charge_thresholds   medm
is_mc               true
crs_ticks           0.1 us
lrs_ticks           0.016 us
```

For production, generate an explicit runlist row or a dedicated MCP run-data configuration rather than relying silently on fallback defaults.

### 11.4 `vertex_id` instead of `file_vertex_id`

Expected for this independent-particle single-file sample. It becomes dangerous if multiple shards with repeated vertex IDs are merged without namespacing. Define global event identity before large production.

### 11.5 No neutrino interaction information

The message is expected for MCP-only simulation. Do not suppress it by fabricating neutrino truth.

### 11.6 scikit-learn pickle version mismatch

A `KernelDensity` object created under scikit-learn 1.3.2 was loaded under 1.9.0. The run completed, but this is a real reproducibility concern. Pin or regenerate the model before production.

### 11.7 Default threshold fallback

During final calibration, some used channels were absent from the threshold file and used the default threshold:

```text
10/170, 11/198, 11/252, 8/69
```

Record and quantify this behavior; do not treat it as a fatal error or silently ignore it in detector-efficiency studies.

### 11.8 Charge-only Flow still loads light geometry metadata

The geometry resource may load a light-module description during initialization. This does not mean light workflows ran. Only the five charge-side workflows were executed.

---

## 12. Project invariants and operator preferences

These are intentional design choices and should not be changed casually.

1. **Preserve the controlled GPS baseline.** It is a regression instrument, not obsolete clutter.
2. **Keep Pythia normalization separate from detector efficiency.** Do not infer physical yield from the number of final reconstructed events.
3. **Reuse the same kinematic throws across charge points.** Change only `EDEPSIM_MCP_CHARGE` when comparing detector response at fixed mass.
4. **Keep zero-hit EDepSim events.** `requireEventsWithHits false` is essential to the efficiency denominator.
5. **Preserve raw stage outputs.** Modify copies for compatibility workarounds.
6. **Delete `mc_hdr`/`mc_stack` only when they exist and have zero rows.**
7. **Use exact parent-pinned submodule commits.** Do not run `git submodule update --remote` on a frozen state.
8. **Keep upstream submodules clean.** MCP-specific configs belong in the parent repository.
9. **Fail early on provenance mismatches.** The Pythia ROOT-summary audit is mandatory unless a mismatch is explicitly understood.
10. **Name approximation layers.** Use labels such as `accepted`, `source`, `straight_line_v0`, and `point_target_v0` in provenance.
11. **Prefer simple, explicit commands over clever hidden automation.** Every production stage should echo inputs, outputs, seeds, commits, and configuration.
12. **Treat low-charge efficiency as an unconditional problem.** Conditional hit distributions alone are insufficient.
13. **Do not overlay neutrino/rock events yet.** First stabilize MCP-only production and reconstruction bookkeeping.
14. **Do not introduce code changes while freezing/documenting a successful milestone.** Documentation and provenance should be completed before the next physics modification.

---

## 13. What currently works

- Custom runtime-configurable MCP in EDepSim.
- Controlled unit-charge and charge-scaling validation.
- Pythia aggregate-summary normalization and strict ROOT-counter audit.
- Empirical v3 donor+jitter accepted-flux model.
- Correct NuMI beam rotation into the 2×2 frame.
- HEPEVT `pbomb` interface with event-by-event manifest closure.
- Custom EDepSim transport at `m=20.458 MeV`, `q=0.3e`.
- ROOT→HDF5 closure for active-LAr segments and energy.
- Non-GENIE empty-truth compatibility workaround.
- Module-dependent `2x2_mpvmpr` larnd-sim on A100 GPUs.
- Automated larnd container validation and dependency recovery.
- Charge-only Flow reconstruction with pinned software and runtime overlays.
- Historical event-display compatibility for the controlled GPS baseline.

---

## 14. What does not yet work or is not yet demonstrated

- Fully physical beamline transport through target/horns/absorber/rock.
- A high-statistics pre-acceptance/source model at the chosen mass.
- Self-consistent use of the real MiniRun5 `y=-0.42 m` beam offset for accepted flux.
- Separate MCP and anti-MCP species in EDepSim.
- A dedicated low-mass MCP ionization implementation at or below 10 MeV.
- A fully immutable larnd container pinned by digest and lockfile.
- A clean-account recreation of the custom EDepSim build including pinned yaml-cpp.
- A fully frozen geometry checksum for the realistic sample.
- A top-level production-grade wrapper for conversion and Flow.
- Light reconstruction or charge-light association for the realistic sample.
- Event-display inspection for the realistic sample.
- Large-statistics low-charge performance and reconstruction efficiency.
- Collision-safe event identity across merged production shards.
- Neutrino/rock overlay.

---

## 15. Immediate next milestones

Recommended order:

1. Finish documentation and create a documentation commit.
2. Inspect the realistic charge-only Flow file in the event display.
3. Add a top-level Flow wrapper that installs overlays safely, records revisions, and validates output.
4. Freeze the 100-event realistic sample with checksums and a machine-readable stage manifest.
5. Record the geometry checksum and exact external `2x2_sim` provenance.
6. Resolve or pin the scikit-learn model-version mismatch.
7. Add a deliberate MCP runlist/run-data entry rather than using fallback defaults.
8. Benchmark a moderate pilot sample at `q=0.3e` and then at a realistic low charge such as `q=0.01e` using identical kinematics.
9. Quantify packet, hit, event, and reconstruction efficiency by input event ID.
10. Benchmark disabling optical simulation when light is intentionally excluded.
11. Only then design larger sharded production and future source-stage beamline physics.

---

## 16. File-role map

```text
PROJECT_CONTEXT.md
    canonical AI/code-agent handoff

docs/
    human operational handbook (MkDocs source)

generator/FLUX_MODEL_WORKFLOW.md
    authoritative realistic flux architecture

generator/EMPIRICAL_RESAMPLING_V3.md
    current empirical sampler algorithm

generator/GEOMETRY_AUDIT.md
    acceptance-coordinate distinction

generator/validate_pythia_edep.py
    event-by-event manifest→EDepSim validator

scripts/launch_larnd_container.sh
scripts/setup_larnd_container.sh
scripts/validate_larnd_container.sh
    known-good GPU environment entry points

configs/ndlar_flow/
    project-owned runtime overlays

freeze/2026-08-17_working_baseline/
    historical controlled GPS baseline and incident notes
```

---

## 17. Minimal state check for a new AI session

Before suggesting work, inspect:

```bash
cd "$SCRATCH/2x2_mcp"
git status -sb
git log -1 --oneline
git submodule status
```

Then establish which artifact is being discussed:

```text
controlled GPS baseline
or
realistic Pythia sample
```

Never combine their numerical expectations. Use the worked-reference tables in the handbook and the sample's own machine-readable provenance.
