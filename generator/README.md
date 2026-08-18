# Realistic MCP generator integration

This directory connects the validated detector simulation in `2x2MCP-sim` to MCP flux files produced by [`BrunoGelli/2x2MCP-PythiaGen`](https://github.com/BrunoGelli/2x2MCP-PythiaGen).

The frozen monoenergetic GPS gun under `gun_tests/` is deliberately left unchanged. It remains the regression source for custom-particle physics, charge scaling, geometry debugging, and end-to-end software checks.

## Architecture

```text
2x2MCP-PythiaGen ROOT
  ├── mcp_summary        normalization / provenance
  └── mcp_spectra        one row per retained MCP
             │
             ▼
generator/prepare_pythia_flux.py
  ├── *.hepevt           EDepSim kinematics input
  ├── *.manifest.csv     source ↔ EDepSim event map
  ├── *.summary.json     selection / geometry / provenance
  └── *.mac              generated EDepSim macro
             │
             ▼
custom EDepSim
             │
             ▼
existing ROOT → HDF5 → larnd-sim → ndlar_flow pipeline
```

EDepSim already contains a native HEPEVT kinematics reader. The adapter therefore does **not** add another custom C++ generator to EDepSim. It translates the Pythia ROOT product into EDepSim's existing `hepevt` / `pbomb` interface.

## Source ROOT contract

`2x2MCP-PythiaGen` writes two TTrees per job.

`mcp_summary` contains generator and normalization bookkeeping such as:

- MCP mass and emitter identity;
- production mode and geometry ID;
- generated-event count;
- total and geometrically accepted MCP counts;
- acceptance fraction;
- generated cross-section metadata;
- spectra prescale.

`mcp_spectra` contains one row per retained MCP according to the generator's `--write-spectra` and `--spectra-prescale` settings. The adapter uses, among other fields:

```text
mcp_mass_GeV
mcp_pdg
px_GeV py_GeV pz_GeV E_GeV
x_at_detector_m y_at_detector_m
event_index seed
emitter_pdg
mother_pdg mother_index
passed_geometry / accepted
```

The sidecar CSV preserves source identifiers so an EDepSim event can always be traced back to the generator row.

## Charge and normalization

The current Pythia generator forces the exotic decay for statistics. Physical rare-decay branching ratios and epsilon scaling are applied later in post-processing.

Consequently, for a fixed MCP mass and production model, the **kinematic flux shape is reusable across charge points**. The detector transport is not: EDepSim must still be rerun for each charge because MCP ionization changes with charge (approximately as `q^2` in the validated regime).

A useful production pattern is therefore:

```text
one phase-space sample at m_chi
        │
        ├── EDepSim q = 0.1 e
        ├── EDepSim q = 0.2 e
        └── EDepSim q = 0.3 e
```

Do not multiply the generated kinematic distribution itself by epsilon before EDepSim. Keep normalization weights separate from detector response.

## Acceptance strategy

For detector simulation, there is no benefit in transporting MCPs that analytically miss the detector. The recommended default is therefore:

```text
--selection recompute
```

which reproduces the present `2x2MCP-PythiaGen` geometry-1 projection:

```text
z_detector = 1040 m
x_detector = (px/pz) * 1040 m
y_detector = (py/pz) * 1040 m

accepted if
  x in [-0.65, -0.05] m OR [0.05, 0.65] m
  y in [-0.70, +0.70] m
```

The original source flag is kept in parallel, making `source_accepted` versus `recomputed_accepted` a useful geometry regression.

**Normalization must still come from `mcp_summary`, not from the number of EDepSim events.** Preserve at least:

```text
n_events_generated
n_mcp_total
n_mcp_accepted
acceptance_fraction
```

If an accepted-only spectra run is used for transport, that is fine as long as its matching summary tree is retained. An all-MCP spectrum with `spectra_prescale=1` is more useful for auditing the acceptance calculation, but is not necessary to waste EDepSim CPU on rejected particles.

## Beamline and coordinate conventions

The physical NuMI target is approximately **1.04 km upstream** of the 2x2 and the beam points downward by approximately **3 degrees** in elevation.

The Pythia generator uses a convenient beam frame in which the target-to-detector direction is `+z` and the detector projection is evaluated at `z = 1040 m`.

The validated 2x2 EDepSim gun uses a different global frame:

```text
position  = (1.5, -0.2, 0.3) m
direction = (-1, 0, 0)
```

The adapter therefore defines the right-handed mapping:

```text
Pythia +z_beam  -> EDepSim -x_global
Pythia +y_beam  -> EDepSim +y_global
Pythia +x_beam  -> EDepSim +z_global
```

and uses this detector beam-plane reference point by default:

```text
(0.0, -0.2, 0.3) m
```

With the default 1.5 m upstream injection distance, an exactly on-axis Pythia MCP becomes:

```text
position  = (1.5, -0.2, 0.3) m
direction = (-1, 0, 0)
```

which exactly reproduces the frozen gun geometry.

The physical 3-degree beamline elevation is recorded in the JSON/macro provenance but is **not applied as an additional rotation** inside EDepSim. The GDML already has its own detector/global coordinate convention. Applying another 3-degree rotation without an explicit survey-derived GDML transform would guess or double-count the relation between civil coordinates and detector coordinates.

## Injection plane

The adapter does not start Geant4 particles 1040 m away.

For a retained MCP, the Pythia momentum is first projected to the detector plane. The same ray is then propagated backward by a small configurable distance, 1.5 m by default:

```text
x_inj = x_detector - (px/pz) * d
y_inj = y_detector - (py/pz) * d
z_inj = -d
```

The resulting position and momentum are transformed into EDepSim global coordinates. Momentum magnitude is unchanged.

This cleanly separates:

```text
1040 m source-to-detector free flight   analytical
local detector/material transport        Geant4 / EDepSim
```

## First test

Choose **one mass greater than 10 MeV** for the first realistic integration. The current custom EDepSim MCP uses `G4hIonisation` and deliberately rejects `m_chi <= 10 MeV`.

For a multi-mass ROOT file:

```bash
cd "$SCRATCH/2x2_mcp"

python generator/prepare_pythia_flux.py \
    /path/to/pythia_output.root \
    out/generator/mcp_020gev_test \
    --mass-gev 0.020 \
    --selection recompute \
    --max-events 100
```

The command prints a nominal-axis cross-check. With default geometry it must report:

```text
injection position = (1.5, -0.2, 0.3) m
direction          = (-1.0, 0.0, 0.0)
```

It writes:

```text
out/generator/mcp_020gev_test.hepevt
out/generator/mcp_020gev_test.manifest.csv
out/generator/mcp_020gev_test.summary.json
out/generator/mcp_020gev_test.mac
```

`out/` is already the natural location for generated products and remains outside the source/freeze material.

## Run EDepSim

Set the detector charge point separately from the phase-space file:

```bash
export EDEPSIM_MCP_MASS_MEV=20
export EDEPSIM_MCP_CHARGE=0.3
```

Then run the generated macro with the same 2x2 GDML used by the frozen baseline:

```bash
edep-sim \
    -g /path/to/2x2.gdml \
    -o out/generator/mcp_020gev_03e_100evt.root \
    -e 100 \
    out/generator/mcp_020gev_test.mac
```

The generated macro keeps zero-hit events:

```text
/edep/db/set/requireEventsWithHits false
```

so detector inefficiency is not silently converted into event loss.

## What to validate before downstream simulation

Before `convert2h5` or larnd-sim, compare the generated manifest against the EDepSim ROOT event-by-event. The first 100-event test should establish:

- EDepSim primary PDG is `9000001`;
- initial momentum is the transformed Pythia momentum;
- momentum magnitude and total energy agree with the source row;
- the primary vertex agrees with the computed injection point;
- nominal/on-axis direction is `-x_global`;
- accepted MCPs intersect the expected detector region;
- `source_accepted` and `recomputed_accepted` agree for the current geometry definition;
- source event identity remains recoverable through the manifest.

Only after this ROOT-level validation should the sample enter the existing conversion → larnd-sim → Flow chain.

## Current limitations

### One EDepSim MCP species

Pythia distinguishes `chi` and `chibar` with opposite signs of its MCP PDG. The current EDepSim fork defines one custom particle, PDG `9000001`, with one run-wide charge configured through `EDEPSIM_MCP_CHARGE`.

For this first integration the adapter therefore transports both source signs as `9000001` and preserves the original sign in `manifest.csv`. This is appropriate for the current ionization-focused detector model, where the response depends on `|q|` and no magnetic bending is modeled. If charge-sign-dependent transport is later required, EDepSim should gain separate MCP/anti-MCP definitions.

### One retained MCP per EDepSim event

A physical exotic meson decay produces an MCP pair. The first integration intentionally makes each retained MCP an independent EDepSim event, matching the existing detector-efficiency workflow. `event_index`, `mother_index`, and the source PDG sign are preserved so pair grouping can be implemented later without changing the source format.

### Low masses

The generator can produce MCP masses below 10 MeV, but the current `G4hIonisation`-based EDepSim particle cannot transport them. The adapter fails early for such a selected mass instead of producing misleading input.

## Production principle

Keep the three efficiencies conceptually separate:

```text
production / normalization
    mcp_summary + post-processing weights

geometric acceptance
    Pythia projection / adapter

detector efficiency
    EDepSim → larnd-sim → Flow
```

This separation is intentional. It makes every loss measurable and prevents the number of reconstructed events from being mistaken for the original MCP flux.
