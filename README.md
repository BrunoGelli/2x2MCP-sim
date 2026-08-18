# MCP 2x2 Simulation

Simulation and analysis workspace for millicharged particle studies in the
DUNE ND-LAr 2x2 demonstrator.

Pipeline:

EDepSim
→ convert2h5
→ larnd-sim
→ ndlar_flow
→ analysis / event display

The `software/` directory contains pinned upstream software repositories
as Git submodules.

The `gun_tests/` directory contains MCP/muon generator configurations and
validation tools.

Known-good pipeline states are recorded under `freeze/`.
