# Worked 100-event Reference

This page records the numerical expectations for the first realistic Pythia-derived sample. Use it as a structural and physics sanity check, not as a promise of byte-identical output on every future software stack.

## Identity

```text
sample prefix: mcp_020458GeV_100evt_seed12345
generator seed: 12345
larnd seed: 67890
m_chi: 20.458 MeV
EDepSim charge: 0.3e
flux stage: accepted
model: weighted_empirical_donor_local_jitter_v3
jitter scale: 0.5
Flow: charge only
```

## Generator

| Quantity | Value |
|---|---:|
| Events | 100 |
| π0-derived events | 98 |
| η-derived events | 2 |
| Minimum energy | `0.765391525 GeV` |
| Median energy | `7.397668041 GeV` |
| Maximum energy | `70.705342194 GeV` |
| Geometry consistency | 99/100 |
| Accepted flux | `7.495143384150902e-06 MCP/POT/ε²` |
| Event weight | `7.495143384150901e-08 MCP/POT/ε²` |

Coordinate state:

```text
Pythia beam              (0,0,+1)
2x2 on-axis unit         (0,-0.0582608693,+0.9983013929)
beam axis at detector    (0,0,0)m
baseline                 1040m
injection z              -1.5m
beamline                 straight_line_v0
```

## EDepSim

### Interface closure

| Check | Result |
|---|---:|
| Manifest events | 100 |
| ROOT events | 100 |
| Missing event IDs | 0 |
| Bad primary count | 0 |
| Bad PDG | 0 |
| Max position difference | `4.97494e-10 mm` |
| Max momentum difference | `4.82632e-08 MeV/c` |
| Max energy difference | `4.81887e-08 MeV` |
| Max mass difference | `2.75953e-08 MeV` |
| Validator | PASS |

### Active-LAr response

| Quantity | Value |
|---|---:|
| Events with any active-LAr segment | 97 |
| Events with direct primary segment | 96 |
| Total active-LAr segments | 1331 |
| Total active-LAr Edep | `2323.42025 MeV` |
| Mean primary Edep/event | `19.0813 MeV` |
| Mean primary path/event | `1085.93 mm` |
| Mean primary dE/dx | `0.0175774809 MeV/mm` |

The three no-segment event IDs are `31`, `80`, and `90`. Event `20` has secondary-only active-LAr deposition.

### Secondary trajectories

```text
e-       2947
gamma     738
e+         44
```

## Converted HDF5

```text
vertices          97
trajectories      622
segments          1331
total dE          2323.42041 MeV
mc_hdr               0
mc_stack             0
```

Segment PDG population:

```text
e-        820
gamma      60
MCP       451
```

Trajectory PDG population:

```text
e-        463
gamma      62
MCP        97
```

The `.LARNDINPUT.hdf5` copy has the two zero-length truth datasets removed and otherwise preserves these counts.

## larnd-sim

| Quantity | Value |
|---|---:|
| Configuration | `2x2_mpvmpr` |
| Input vertices | 97 |
| Input segments | 1331 |
| Neutral segments rejected | 60 |
| Output segments | 1271 |
| Packets | 2142 |
| Truth associations | 2142 |
| Data packets, type 0 | 941 |
| Packet type 4 | 1024 |
| Packet type 6 | 80 |
| Packet type 7 | 97 |
| Light triggers | 97 |
| Light waveform shape | `(97,384,1000)` |
| Runtime | `325.62s` |
| File size | about `382MB` |

## charge-only Flow

Five workflows completed:

```text
charge_event_building_mc
charge_event_reconstruction_mc
combined_reconstruction_mc
prompt_calibration_mc
final_calibration_mc
```

Result:

```text
exit status: 0
output size: ~3.2MB
```

Top-level groups:

```text
charge
combined
geometry_info
lar_info
mc_truth
run_info
```

## Files

```text
out/generator/mcp_020458GeV_100evt_seed12345.hepevt
out/generator/mcp_020458GeV_100evt_seed12345.manifest.csv
out/generator/mcp_020458GeV_100evt_seed12345.summary.json
out/generator/mcp_020458GeV_100evt_seed12345.mac

out/edep/mcp_020458GeV_q03_100evt_seed12345.root
out/edep/mcp_020458GeV_q03_100evt_seed12345.EDEPSIM.hdf5
out/edep/mcp_020458GeV_q03_100evt_seed12345.LARNDINPUT.hdf5

out/larnd/mcp_020458GeV_q03_100evt_seed12345.LARNDSIM.hdf5
out/flow/mcp_020458GeV_q03_100evt_seed12345.FLOW.hdf5
```

## Interpreting differences in future reruns

Exact equality is expected for identity and schema invariants, such as:

- event count before conversion;
- PDG and mass;
- manifest→ROOT ordering;
- required datasets;
- use of the selected active volume;
- configured seeds and commits.

Small numerical or count changes can be legitimate after a deliberate update to:

- Geant4;
- detector geometry;
- response maps;
- thresholds/pedestals;
- CUDA kernels;
- dependency versions;
- HDF5 compression.

Any change must be explained by provenance and evaluated with the [Validation Strategy](validation.md).
