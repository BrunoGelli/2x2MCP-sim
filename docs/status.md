# Current Status

## Executive summary

The simulation is no longer in basic custom-particle bring-up. The project has demonstrated both:

1. a frozen, controlled MCP detector-simulation baseline through the event display; and
2. a realistic Pythia-derived 100-event sample through charge-only `ndlar_flow`.

## Capability matrix

| Component | Status | Notes |
|---|---:|---|
| Custom MCP particle in Geant4 | ✅ | Runtime mass and charge; PDG `9000001` |
| Controlled unit-charge MCP vs muon | ✅ | Agreement in the expected limit |
| Approximate `q²` energy-loss scaling | ✅ | Scanned down to about `q=0.01e` |
| Pythia multi-emitter normalization | ✅ | Physical mixture, not raw row abundance |
| Empirical donor+jitter v3 model | ✅ | No extrapolation; protects module gap |
| Pythia→2×2 coordinate rotation | ✅ | Mostly `+z`, small `-y` NuMI slope |
| Pythia manifest→EDepSim closure | ✅ | 100/100 identities and floating-point residuals |
| ROOT→HDF5 closure | ✅ | 1331 segments and total energy agree |
| Non-GENIE truth workaround | ✅ | Remove only zero-length truth datasets in a copy |
| Modern larnd-sim on A100 | ✅ | Four modules complete; validator added |
| Charge-only Flow | ✅ | Five MC charge workflows complete |
| Realistic-sample event display | ⏳ | Not yet checked |
| Realistic light Flow | ⏳ | Intentionally skipped for now |
| Fully physical beamline | ❌ | Current model is `straight_line_v0` |
| Large low-charge production | ⏳ | Requires pilot benchmarks and bookkeeping |
| Neutrino/rock overlay | ⏳ | Deliberately deferred |

## Current development branch

```text
feature/pythia-spectrum-input
```

Normal synchronization:

```bash
cd "$SCRATCH/2x2_mcp"
git fetch origin
git pull --ff-only origin feature/pythia-spectrum-input
git submodule sync --recursive
git submodule update --init --recursive
```

See [Git and Repository Workflow](git-workflow.md) before pulling when the Flow submodule contains runtime overlays.

## Current realistic reference point

| Parameter | Value |
|---|---:|
| Mass | `20.458 MeV` |
| Detector charge | `q=0.3e` |
| Generator seed | `12345` |
| larnd-sim seed | `67890` |
| Event count | `100` |
| Flux stage | `accepted` |
| Geometry ID | `1` |
| Resampler | empirical donor + adaptive local jitter v3 |
| Jitter scale | `0.5` |
| Beamline | `straight_line_v0` |
| Beam-axis reference for this sample | detector center `(0,0,0)m` |
| Baseline | `1040m` |
| Injection plane | global `z=-1.5m` |
| Flow scope | charge only |

## Immediate priorities

1. Preserve the documentation and worked reference.
2. Inspect the realistic Flow file in the event display.
3. Add a production-grade Flow wrapper in a later code task.
4. Freeze checksums and complete external geometry provenance.
5. Resolve the Flow scikit-learn version mismatch and runlist fallback.
6. Run moderate-statistics pilots before a realistic `q≈0.01e` production.
