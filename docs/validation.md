# Validation Strategy

Validation is layered. A successful process exit is necessary but not sufficient.

## Level 0 — provenance preflight

Before a run, record:

```text
parent repository commit
submodule commits
external 2x2_sim commit
geometry path and checksum
converter path and checksum
mass and charge
generator and detector seeds
flux model checksum
larnd configuration
Flow workflow list
```

A run with unknown inputs is not a reference sample even if the output looks plausible.

## Level 1 — file integrity

Use SHA-256 to protect archived artifacts:

```bash
sha256sum FILE
sha256sum -c SHA256SUMS
```

This answers whether a stored file changed. It does not prove a regenerated file is scientifically correct.

## Level 2 — structural validation

Check schemas and populations at every boundary.

### Generator

- all required products exist;
- manifest rows match requested event count;
- event IDs are contiguous and unique;
- mass, seed, model type, and event weights are present;
- HEPEVT records contain one MCP per event.

### EDepSim ROOT

- `EDepSimEvents` exists;
- event count equals the manifest count;
- exactly one primary per event;
- PDG and mass are correct;
- zero-hit events are retained.

### Converted HDF5

- `vertices`, `trajectories`, and `segments` exist;
- active-volume segment count and energy match ROOT;
- converted vertex IDs are a subset of generated IDs;
- empty non-GENIE truth datasets are understood.

### larnd-sim

- `packets` and `mc_packets_assn` exist and have compatible lengths;
- module processing completed;
- packet types are sensible;
- `segments`, `trajectories`, and `vertices` are preserved as expected.

### Flow

- every requested workflow reaches `FINISH`;
- output opens with h5py;
- `charge`, `combined`, `mc_truth`, and metadata groups exist;
- reconstructed event/hit datasets are non-empty for the high-charge reference.

## Level 3 — interface closure

The most important realistic-generator regression is:

```text
manifest event i
    == HEPEVT event i
    == EDepSim event i
```

Use:

```bash
python generator/validate_pythia_edep.py MANIFEST.csv EDEPSIM.root
```

It checks event identity, primary count, PDG, mass, injection position, momentum, energy, beam direction, and active-LAr bookkeeping.

The first reference closes at floating-point serialization precision.

## Level 4 — physics validation

Monitor distributions, not only totals:

- energy and angle by emitter;
- detector-plane x/y and central gap;
- path length;
- primary and total active-LAr deposition;
- conditional and unconditional `dE/dx`;
- fraction with no active-LAr activity;
- primary versus secondary-only activity;
- packets/event and charge/event;
- reconstructed hits/events;
- module dependence;
- angular residuals after reconstruction.

For charge scans, reuse identical kinematics and compare:

```text
q² scaling
zero-hit fraction
packet efficiency
Flow efficiency
selection efficiency
```

## Level 5 — operational regression

A complete operational test includes:

1. fresh parent checkout or clean working tree;
2. exact submodule restoration;
3. container validator pass;
4. small EDepSim sample;
5. conversion and compatibility cleanup;
6. larnd-sim completion;
7. Flow completion;
8. event-display opening;
9. clear log and provenance artifacts.

## Tolerance policy

### Require exact equality for

- requested and stored event IDs before conversion;
- PDG and configured mass;
- model/seed/configuration identifiers;
- required dataset presence;
- zero-length-dataset safety checks;
- source-summary audit pass.

### Use numerical tolerances for

- serialized floating-point coordinates and momenta;
- deposited energy after format conversion;
- physics distributions after software changes;
- GPU-generated response values.

### Do not require regenerated SHA equality by default

GPU reduction order, HDF5 metadata, compression, and dependency versions can change bytes without changing scientific content. Use checksums for archived-file integrity and physics/structural tolerances for reruns.

## Recommended stage summary

Every production shard should eventually write a compact record such as:

```yaml
counts:
  generated: 100
  edep_events: 100
  active_lar_any: 97
  active_lar_primary: 96
  converted_vertices: 97
  larnd_data_packets: 941
  flow_events: null
status:
  generator: pass
  edep: pass
  conversion: pass
  larnd: pass
  flow: pass
```

The `flow_events` field should be populated from a dedicated output validator rather than inferred from file size.
