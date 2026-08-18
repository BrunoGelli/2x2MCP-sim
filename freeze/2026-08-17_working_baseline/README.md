# MCP 2x2 working baseline — 2026-08-17

This directory freezes the first known-good end-to-end MCP simulation.

Baseline:

- MCP mass: 105.658374 MeV
- kinetic energy: 600 MeV
- charge: 0.3 e
- events: 100

Working chain:

MCP generator
    -> custom EDepSim / Geant4
    -> convert2h5
    -> empty mc_hdr/mc_stack cleanup
    -> larnd-sim
    -> ndlar_flow
    -> event display

The files in `reference/` are the known-good outputs and should not be
modified.

`manifests/SHA256SUMS` records their checksums.

Important implementation details are recorded in `notes/`.

This baseline is the checkpoint immediately before beginning further
physics studies / charge scans / model changes.
