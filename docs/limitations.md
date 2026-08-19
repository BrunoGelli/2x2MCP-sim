# Limitations and Roadmap

This page separates demonstrated capability from planned realism. Do not interpret the current successful pipeline as a complete physical model of MCP propagation from the NuMI target.

## Physics-model limitations

### Mass floor

The custom MCP implementation currently requires:

```text
m_chi > 10 MeV
```

A dedicated lower-mass ionization treatment is needed before simulating lighter points.

### Electromagnetic processes

The current particle has ionization and multiple scattering but no dedicated MCP implementation of bremsstrahlung, pair production, or single-Coulomb scattering.

### Antiparticle identity

There is one fixed PDG species. A negative runtime charge is not a complete MCP/anti-MCP truth model.

### Step-limiter boundary

The EDepSim step limiter changes at `|q|>0.1e`. Controlled scans found no obvious discontinuity, but precision low-charge work should continue to monitor it.

## Beamline limitations

The current named transport model is:

```text
straight_line_v0
```

Not modeled:

- energy loss in beamline material;
- multiple scattering before local injection;
- horn or other magnetic deflection;
- attenuation;
- hard interactions;
- a full engineering beamline geometry.

A future model should preserve the current flux-model interface and replace only the transport layer.

## Accepted-stage limitations

The present high-statistics model is conditioned on the old Pythia `geometry_id=1` accepted window.

Consequences:

- it cannot recover trajectories rejected by that window;
- the real MiniRun5 beam-axis offset cannot be applied fully self-consistently;
- scattering-induced migration across acceptance cannot be modeled;
- the post-rotation detector-face check is only a diagnostic.

The correct long-term solution is a high-statistics pre-acceptance/source production.

## Finite-donor limitations

Rare emitters can have few accepted donors. Generating many detector throws does not remove this source-model uncertainty. The v3 sampler avoids extrapolation but cannot invent unobserved phase space.

Monitor:

- donor count by emitter;
- local-cell widths;
- emitter-specific energy/angle distributions;
- bootstrap versus jitter comparisons.

## Geometry and external dependency gaps

The realistic run used an external `2x2_sim` checkout. Remaining freeze work:

- record the GDML SHA-256;
- record the converter SHA-256;
- decide whether to pin `2x2_sim` as a submodule or formal external dependency;
- pin/reproduce the yaml-cpp dependency used to build custom EDepSim;
- capture the Podman image digest.

## larnd-sim environment limitations

The startup validator proves the runtime works, but:

- `numba-cuda[cu12]` is still resolved dynamically;
- the base image is pinned by tag, not digest;
- transitive packages are not installed from a complete lockfile;
- the overlay is rebuilt each container launch;
- optical simulation is currently performed even for charge-only Flow.

A derived immutable container or locked requirements set is preferable before very large production.

## Flow limitations

### Runtime overlays

Project configuration must currently be copied into the clean upstream submodule. A future wrapper should install and remove overlays safely and record their hashes.

### Runlist fallback

The realistic filename does not have an explicit runlist row, so defaults were used. Production needs a dedicated MCP run-data definition.

### Event identity

`vertex_id` fallback is acceptable for a single file but is not collision-safe across independently numbered shards.

### Serialized sklearn model

The reference loaded a `KernelDensity` estimator created under scikit-learn 1.3.2 using version 1.9.0. Pin or regenerate before production.

### Threshold coverage

Some used channels were absent from the threshold file and used a default. Quantify the effect on MCP efficiency.

### Light

The realistic sample has not run light reconstruction or charge-light association. Charge-only Flow is the current validated scope.

## Analysis and production limitations

Not yet demonstrated:

- realistic event-display inspection;
- reconstruction-efficiency extraction by generator event ID;
- low-charge packet/hit efficiency at useful statistics;
- large-shard merging with globally unique event identity;
- automated retries and stage status tracking;
- neutrino/rock overlays;
- final MCP selection and sensitivity calculation from this pipeline.

## Recommended roadmap

### Near term

1. Inspect the realistic Flow file in the event display.
2. Freeze the 100-event realistic reference with checksums.
3. Add a top-level Flow wrapper and output validator.
4. Add explicit MCP run-data/runlist metadata.
5. Pin or regenerate the sklearn object.
6. Extract per-event packet and Flow efficiencies.

### Pilot production

1. Benchmark `10^3`, `10^4`, and `10^5` events.
2. Benchmark EDepSim shard sizes such as 1k, 5k, and 10k.
3. Benchmark larnd batches and peak GPU memory.
4. Compare charge-only larnd with and without optical simulation.
5. Reuse identical kinematics for `q=0.3e` and a low-charge point.
6. Define structural and physics regression tolerances.

### Physics expansion

1. Produce a high-statistics source-stage model.
2. Apply the real beam-axis convention self-consistently.
3. Add named beamline material/field transport versions.
4. Validate acceptance migration.
5. Introduce overlays only after MCP-only bookkeeping is stable.
