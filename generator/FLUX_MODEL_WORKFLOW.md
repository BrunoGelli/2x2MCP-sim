# MCP flux-model workflow

This document is the current, authoritative guide to the realistic MCP flux
interface in `2x2MCP-sim`.

It supplements `generator/README.md`.  Where an older generator note conflicts
with this document, **this document wins**.  In particular, the obsolete
Pythia `+z -> EDepSim -x` mapping and direct replay of individual Pythia rows
must not be used.

The frozen monoenergetic GPS tests under `gun_tests/` remain unchanged and are
still the regression baseline for MCP transport, charge scaling, conversion,
larnd-sim, Flow, and event display.

---

## 1. Current architecture

The realistic workflow has two separate programs:

```text
2x2MCP-PythiaGen ROOT production
        │
        ▼
generator/build_pythia_flux_model.py
        │
        ├── flux_model.npz
        ├── provenance.json
        ├── component_normalization.csv
        └── plots/
                │
                ▼
generator/sample_pythia_flux.py
        │
        ├── *.hepevt
        ├── *.manifest.csv
        ├── *.summary.json
        ├── *.mac
        └── *.sampled_flux.png
                │
                ▼
custom EDepSim
        │
        ▼
convert2h5 -> larnd-sim -> ndlar_flow
```

Pythia supplies a finite production sample.  The builder turns that sample into
a reusable, non-parametric flux model.  The sampler can then draw as many MCP
kinematics as are useful for detector MC.

Generating more throws from the model reduces detector-MC statistical
uncertainty; it does **not** create additional independent knowledge of the
underlying Pythia production spectrum.

---

## 2. Two flux stages

The builder supports two physically different stages.

### 2.1 `accepted` -- current recommended mode

```bash
--flux-stage accepted
```

This is the default and is the recommended mode for the present detector study.

It models the MCP spectrum **after the existing `2x2MCP-PythiaGen`
`geometry_id=1` acceptance**.  This lets us use the high-statistics production
that stored accepted MCP spectra instead of forcing a low-statistics
pre-acceptance spectrum run.

Normalization is based on:

```text
n_mcp_accepted
```

for every emitter.

The sampler does **not** apply a second acceptance rejection.  It computes the
transformed detector intersection and records whether it is still consistent
with the current approximate detector face, but this is a diagnostic only.

This avoids conditioning the flux twice.

Use this mode for the first realistic EDepSim production.

### 2.2 `source` -- future beamline-transport mode

```bash
--flux-stage source
```

This models the spectrum before detector acceptance and normalizes with:

```text
n_mcp_total
```

It requires an all-MCP / pre-acceptance `mcp_spectra` production.  An
accepted-only spectrum is rejected unless the user explicitly overrides the
safety check.

The sampler ordering is:

```text
sample source flux
    -> rotate into 2x2 coordinates
    -> beamline transport
    -> detector acceptance
    -> local EDepSim injection
```

This mode is the correct starting point once beamline material effects are
introduced, because scattering can move trajectories into or out of the
detector acceptance.

---

## 3. Beamline transport in this version

Both model provenance and sampled-run provenance explicitly record:

```text
straight_line_v0
```

This is **Level 0** beamline transport.

It means:

```text
energy loss             false
multiple scattering     false
magnetic deflection     false
attenuation              false
material interactions   false
```

The source-to-detector path is therefore treated as straight free propagation.

This is an intentional first approximation, not a claim that the real NuMI
beamline is vacuum.  A future transport implementation can replace this layer
without changing the Pythia flux-model or EDepSim interfaces.

For an `accepted` model, `straight_line_v0` is also the assumption under which
we reuse Pythia's precomputed geometric acceptance.

---

## 4. All emitters are included with physical relative normalization

The flux model is **not** formed by concatenating raw Pythia rows and treating
them equally across emitters.

The supported components are:

```text
pi0
eta
eta'
rho0
omega
phi
J/psi
```

when kinematically open for the chosen MCP mass.

Each emitter keeps its own empirical energy/angular distribution.  The final
model is a weighted mixture of those emitter-specific distributions.

The relative normalization follows the same convention as
`2x2MCP-PythiaGen/scripts/export_toymc_spectra.py`.

For an emitter `P`, mass `m_chi`, and one unit of POT with the common
`epsilon^2` factor divided out,

```text
flux_P(stage) = process_scale_P
                * Br_exotic(P,m_chi)/epsilon^2
                * N_MCP(stage) / N_events
```

where:

```text
N_MCP(source)   = n_mcp_total
N_MCP(accepted) = n_mcp_accepted
```

For light mesons:

```text
process_scale = 1
```

For the charmonium importance-sampled production:

```text
process_scale_Jpsi = <sigma_charmonium> / <sigma_SoftQCD>
```

using the **mean** generated cross section per input shard, consistent with the
existing Pythia normalization code.

The common `epsilon^2` cancels from emitter mixture fractions at fixed mass.
The saved model is therefore normalized in:

```text
MCP / POT / epsilon^2
```

and can be reused across detector charge points.

---

## 5. Kinematic model

The previous prototype modeled:

```text
t_x = px/pz
t_y = py/pz
```

Those variables diverge for small positive `pz` and caused very large,
unphysical interpolation cells in the unrestricted smoke test.

Version 2 instead models:

```text
log10(E / GeV)
theta_x = atan2(px, pz)
theta_y = atan2(py, pz)
```

separately for every emitter.

The model is a weighted 3-D histogram with weighted-quantile bin edges.  It is
non-parametric: no Gaussian beam, polynomial spectrum, or analytic angular fit
is imposed.

When sampling a histogram cell, the sampler draws uniformly inside that
occupied cell.  Validation plots compare the original physically weighted
Pythia sample with a large independently resampled model sample.

The accepted model should be much better behaved than the first unrestricted
smoke test because it only describes the narrow forward phase space that
actually points at the 2x2.

---

## 6. Coordinates

The Pythia production convention is beam-aligned:

```text
nominal Pythia beam = (0, 0, +1)
```

The standard 2x2 simulation convention uses approximately:

```text
beam_dir = (0, -0.05836, +1)
```

which is about 3.34 degrees downward in `y`.

The `x` and `y` signs in Pythia are the same as the 2x2 simulation signs.
There is **no x/z permutation**.

The sampler therefore applies only an `x`-axis rotation.  Its mandatory console
cross-check is approximately:

```text
Pythia (0,0,+1) -> 2x2 (0, -0.058..., +0.998...)
```

The current defaults use:

```text
baseline                       1040 m
beam axis at detector          (0, -0.42, 0) m
beam slope in y/z              -0.05836
```

All are recorded in sampled-run provenance and can be overridden from the CLI.

The old frozen gun direction `(-1,0,0)` was simply a convenient transverse
validation trajectory.  It never defined the NuMI beam direction.

---

## 7. Acceptance

The current approximate Pythia `geometry_id=1` detector face is represented as
beam-axis-relative offsets:

```text
x in [-0.65,-0.05] m  OR  [0.05,+0.65] m
y in [-0.70,+0.70] m
```

For an **accepted-stage model**, this cut was already used to condition the
Pythia training sample.  The sampler evaluates it only as a geometry diagnostic
and reports:

```text
geometry_consistency_fraction
```

A value close to 1 is expected.  A significant discrepancy means the
interpolation, coordinate conversion, or assumed beam-axis reference needs to
be investigated before EDepSim production.

For a **source-stage model**, the cut is applied after `straight_line_v0`
transport and controls whether the source throw is written to EDepSim.

---

## 8. Flux-versus-mass cross-check

Every build now derives normalization-only mass scans directly from the
aggregate summary CSV.  These plots do not depend on the histogram model.

The builder writes under `plots/`:

```text
flux_vs_mass.csv
flux_vs_mass.png
```

The figure contains:

1. source flux / POT / epsilon^2 versus MCP mass;
2. accepted flux / POT / epsilon^2 versus MCP mass;
3. physically weighted geometric acceptance versus MCP mass.

Source and accepted fluxes are decomposed by emitter and include a total curve.

This is deliberately close to the existing Pythia normalized-yield plot.  The
new accepted-flux curve should have the same physics shape after stripping the
chosen `N_POT * epsilon^2` factor.

This is one of the strongest normalization cross-checks for the new workflow.

---

## 9. Model-building plots

A successful build writes:

```text
plots/flux_model_overview.png
plots/flux_model_resampling_validation.png
plots/pythia_detector_projection.png
plots/flux_vs_mass.png
plots/flux_vs_mass.csv
```

### `flux_model_overview.png`

Shows physically normalized distributions for:

```text
E
theta_x
theta_y
theta_x vs theta_y
E vs theta_x
E vs theta_y
```

Energy uses logarithmic x and y where appropriate.  Angular axes are shown in
mrad and 1-D flux uses logarithmic y.

### `flux_model_resampling_validation.png`

Compares:

```text
physically weighted original Pythia
vs
independent throws from flux_model.npz
```

in both 1-D and 2-D projections.

Do not approve a flux model based only on 1-D agreement.  The first unrestricted
smoke test taught us that 2-D angular plots can reveal interpolation artifacts
hidden by excellent-looking marginal distributions.

### `pythia_detector_projection.png`

Shows the detector-plane `x_at_detector_m,y_at_detector_m` values stored in the
training Pythia sample with the approximate geometry boxes overlaid.

---

## 10. Provenance

Every source ROOT file used to construct a model is recorded with:

```text
absolute path
file name
file size
modification timestamp in UTC
SHA-256
```

The aggregate summary CSV gets the same treatment.

`provenance.json` also stores:

```text
flux stage
selected MCP mass
geometry ID
production tag
optional PythiaGen git SHA
2x2MCP-sim git SHA
normalization convention
SoftQCD/charmonium cross-section normalization
emitter fluxes and mixture fractions
kinematic coordinates
histogram definition
straight_line_v0 transport assumptions
```

The NPZ contains a copy of the same metadata so the model remains self
describing if moved away from its original directory.

---

## 11. Recommended first build

Use a mass **strictly greater than 10 MeV** for the first EDepSim sample.  The
current custom EDepSim MCP uses `G4hIonisation` and deliberately rejects masses
at or below 10 MeV.

The earlier smoke command selected exactly `0.010 GeV`, despite writing into a
directory named `mcp_020MeV`; do not reuse that directory name for a 10 MeV
sample.

If the normal high-statistics accepted production contains the nearby
`0.020458 GeV` point, a recommended command is:

```bash
cd /pscratch/sd/b/bgelli/2x2_mcp

git switch feature/pythia-spectrum-input
git pull

python generator/build_pythia_flux_model.py \
    /path/to/high_statistics_accepted_spectra/ \
    --summary /path/to/matching_aggregate_summary.csv \
    --mass-gev 0.020458 \
    --geometry-id 1 \
    --flux-stage accepted \
    --output-dir out/flux_models/mcp_020458GeV_accepted \
    --production-tag accepted_flux_smoke_test
```

`--flux-stage accepted` is currently the default, so it may be omitted, but it
is useful to keep it explicit in production commands.

Before sampling, inspect:

```text
component_normalization.csv
provenance.json
plots/flux_model_overview.png
plots/flux_model_resampling_validation.png
plots/pythia_detector_projection.png
plots/flux_vs_mass.png
```

---

## 12. Sampling an accepted-stage model

After approving the model:

```bash
python generator/sample_pythia_flux.py \
    out/flux_models/mcp_020458GeV_accepted/flux_model.npz \
    out/generator/mcp_020458GeV_seed12345 \
    --n-events 100 \
    --seed 12345
```

For accepted-stage models, `--n-accepted 100` is retained as a convenient alias,
but `--n-events` better describes what is happening: all model draws are already
conditioned on Pythia acceptance.

The sampler writes:

```text
*.hepevt
*.manifest.csv
*.summary.json
*.mac
*.sampled_flux.png
```

The console prints the coordinate cross-check and the geometry-consistency
fraction.

A low geometry-consistency fraction is a stop condition for the first test.

---

## 13. Sampling a source-stage model

Future pre-acceptance operation can use either:

```bash
--n-source N
```

for a fixed number of source throws, or:

```bash
--n-accepted N
```

to continue throwing the source model until `N` trajectories pass the Level-0
acceptance.

This mode is not needed for the immediate accepted-flux detector study.

---

## 14. Event weights

For an accepted-stage model with total physical accepted flux

```text
Phi_acc [MCP / POT / epsilon^2]
```

and `N` generated EDepSim primaries, each event receives:

```text
w_event = Phi_acc / N
```

in the manifest.

For a source-stage rejection run, each source trial represents:

```text
w_source = Phi_source / N_source_trials
```

and accepted events carry that same weight.

A later detector/reconstruction selection can therefore be normalized as:

```text
N_expected = N_POT * epsilon^2 * sum(selected event weights)
```

The phase-space sample itself is independent of the chosen detector charge.
The same HEPEVT sample should be reused for multiple `EDEPSIM_MCP_CHARGE`
values whenever possible so charge comparisons share identical kinematics.

---

## 15. EDepSim interface

The sampler uses EDepSim's existing HEPEVT `pbomb` reader rather than adding
another custom generator implementation.

The generated macro configures:

```text
/generator/kinematics/hepevt/input ...
/generator/kinematics/hepevt/flavor pbomb
/generator/kinematics/set hepevt
/generator/position/set free
/generator/time/set free
/generator/count/fixed/number 1
/generator/count/set fixed
/generator/add
```

and keeps zero-hit events:

```text
/edep/db/set/requireEventsWithHits false
```

For a 20.458 MeV model, for example:

```bash
export EDEPSIM_MCP_MASS_MEV=20.458
export EDEPSIM_MCP_CHARGE=0.3
```

before launching EDepSim with the generated macro and the same 2x2 GDML used by
the frozen pipeline.

Stop at EDepSim ROOT for the first realistic sample and validate primary
position/momentum before running `convert2h5`.

---

## 16. Current limitations

The present workflow intentionally does **not** yet include:

- MCP energy loss through the NuMI beamline;
- multiple scattering through absorber/rock;
- magnetic deflection between target and detector;
- attenuation or hard beamline scattering;
- a full engineering beamline geometry;
- separate EDepSim MCP/anti-MCP particle definitions;
- physical pair grouping into one EDepSim event.

The first five are collectively the future replacement for
`straight_line_v0`.

The Pythia source contains chi and chibar, but current EDepSim defines one custom
PDG `9000001` with a run-wide charge.  The sampler randomly preserves a source
chi/chibar sign in its manifest while transporting both with EDepSim PDG
`9000001`.  This is sufficient for the current ionization-focused,
no-magnetic-field detector response.

---

## 17. Why both stages are being kept

Using accepted spectra now is a practical choice, not abandonment of the source
model.

```text
accepted stage
    high-statistics detector work now
    Pythia acceptance already applied
    straight_line_v0 assumption

source stage
    future beamline physics
    acceptance after transport
    required when scattering/energy loss can change trajectories
```

Keeping both stages in the same normalization and provenance framework lets the
project move forward immediately without blocking on a new large Pythia
pre-acceptance production, while preserving the architecture needed for a more
complete beamline treatment later.
