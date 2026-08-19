# Empirical flux resampling v3

This note documents the current kinematic resampler used by
`build_pythia_flux_model.py` and `sample_pythia_flux.py`.

It supersedes the v2 **uniform-inside-3D-histogram-cell** resampling method.
The overall normalization, all-emitter mixture, coordinate rotation,
`straight_line_v0` beamline model, and EDepSim interface are unchanged.

## Why v3 was needed

The v2 accepted-flux model used weighted-quantile bins in
`(log10(E), theta_x, theta_y)` and sampled uniformly inside an occupied 3-D
cell.  The validation plots showed two artifacts:

- the first/last energy cells were broad enough to distort the low- and
  high-energy tails;
- one `theta_x` cell straddled the physical gap between the two 2x2 modules,
  so the resampler populated directions that were absent from the accepted
  Pythia sample.

These were interpolation artifacts, not problems in the Pythia production or
normalization.

## Current accepted-stage representation

For every emitter, the model stores the actual accepted Pythia rows as
**donors**:

```text
log10(E)
x_at_detector_m
y_at_detector_m
Pythia theta_x, theta_y
spectra-prescale sampling weight
left/right module label
```

The physical emitter normalization still comes from the aggregate summary:

```text
Phi_P,accepted = process_scale_P
                 * Br_exotic(P,mchi)/epsilon^2
                 * n_mcp_accepted / n_events_generated
```

The donors define only the kinematic shape.

## Adaptive local jitter

A new throw is made by:

1. choosing an emitter with its physical flux fraction;
2. choosing one real Pythia donor using its spectra-prescale weight;
3. finding the midpoint cell around that donor along each empirical coordinate;
4. drawing a small random displacement inside that local cell.

The default sampling-time jitter scale is `0.5`:

```text
--jitter-scale 0.5
```

Interpretation:

```text
0.0  exact weighted bootstrap of Pythia donors
0.5  half of each adaptive local midpoint cell (default)
1.0  full local midpoint cell
```

The empirical model never extrapolates below the minimum or above the maximum
observed energy.

## Module-gap protection

Accepted-stage donors are separated into:

```text
left module:  x_at_detector < 0
right module: x_at_detector > 0
```

Adaptive cells are built independently for the two sides and clipped to the
original Pythia geometry-id-1 windows:

```text
left:  -0.65 <= x <= -0.05 m
right: +0.05 <= x <= +0.65 m
        -0.70 <= y <= +0.70 m
```

Therefore interpolation cannot cross the central module gap.

For an accepted model, the sampled detector-plane position is converted back
to the Pythia beam-frame direction using the same 1040 m projection convention:

```text
theta_x = atan2(x_at_detector, 1040 m)
theta_y = atan2(y_at_detector, 1040 m)
```

The subsequent Pythia-to-2x2 3.34-degree rotation is unchanged.

## Validation outputs

The builder writes:

```text
plots/flux_model_resampling_validation.png
plots/flux_model_projection_validation.png
```

The first compares weighted Pythia and empirical resampling in energy and
angles.  The second directly compares the original and resampled detector-plane
`x/y` distributions.  The central gap must remain empty.

## Combined productions and normalization

Input directories are searched recursively.  A hierarchy such as

```text
raw_combined_v2/
  base_4h/
  endpoint_v1/
  global_v2/
```

is therefore supported directly.

Folder names do **not** alter physics weights.  Each ROOT file contributes its
matching `mcp_spectra` rows and its file-local `spectra_prescale`; absolute
normalization comes from the supplied aggregate summary CSV.

To prevent accidental mismatches, v3 independently sums the matching
`mcp_summary` counters from all ROOT files and compares them to the aggregate
CSV for each `(mass, emitter, production_mode, geometry_id)` key:

```text
n_events_generated
n_mcp_total
n_mcp_accepted
```

The build fails on a mismatch by default.  The audit is written to:

```text
input_summary_audit.csv
```

and copied into `provenance.json`.

The provenance also reports a best-effort count of used spectrum files by run
group, e.g. `base_4h`, `endpoint_v1`, and `global_v2`.

This audit verifies that the ROOT directory and aggregate summary describe the
same combined production.  It does not decide whether differently named run
groups *should* be combined physically; that decision belongs to the Pythia
production definition and aggregate-summary construction.

## Recommended first rerun

Rebuild the 20.458 MeV accepted model with the same command as before:

```bash
python generator/build_pythia_flux_model.py \
  /global/homes/b/bgelli/2x2MCP-PythiaGen/outputs/raw_combined_v2/ \
  --summary /global/homes/b/bgelli/2x2MCP-PythiaGen/outputs/aggregate_summary_combined_v2.csv \
  --mass-gev 0.020458 \
  --geometry-id 1 \
  --flux-stage accepted \
  --output-dir out/flux_models/mcp_020458GeV_accepted_v3 \
  --production-tag accepted_flux_empirical_v3
```

Then inspect:

```text
input_summary_audit.csv
component_normalization.csv
plots/flux_model_resampling_validation.png
plots/flux_model_projection_validation.png
plots/flux_model_overview.png
```

Only after those agree should the model be sampled for EDepSim.
