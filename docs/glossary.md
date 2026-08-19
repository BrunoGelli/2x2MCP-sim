# Glossary

**Accepted stage**  
Flux model conditioned on the existing Pythia detector-acceptance window. Normalized with `n_mcp_accepted`.

**Active LAr**  
The selected liquid-argon sensitive volume, named `volTPCActive` in the current EDepSim geometry/converter workflow.

**Aggregate summary**  
CSV produced by the Pythia-generation campaign containing production counters and normalization information across shards.

**Beam-axis reference**  
The global point where the nominal beam axis crosses the detector plane. The first realistic sample deliberately uses `(0,0,0)m`; a MiniRun5-inspired default elsewhere is `y=-0.42m`.

**Conditional dE/dx**  
Energy loss evaluated only for events/segments with accepted primary activity. It must not replace unconditional efficiency accounting.

**EDepSim**  
Geant4-based detector transport that produces ROOT truth, trajectories, and detector segments.

**Emitter**  
Parent particle that produces the MCP pair, such as `π0`, `η`, or `J/ψ`.

**Event weight**  
Physical flux represented by one sampled detector-MC primary, in `MCP/POT/epsilon²` for the accepted model.

**Flow**  
The `h5flow`/`ndlar_flow` reconstruction chain that builds events, hits, timing, calibration, and truth-linked reconstructed datasets.

**Geometry consistency diagnostic**  
Post-rotation detector-global face check applied to accepted-stage throws. It is not a second physical acceptance cut.

**HEPEVT `pbomb`**  
EDepSim's existing external event-record reader used to inject one MCP with event-specific position and momentum.

**Jitter scale**  
Fraction of an adaptive nearest-neighbor midpoint cell used around an empirical Pythia donor. `0` is bootstrap; `0.5` is current default; `1` is the full local cell.

**LARNDINPUT**  
Copy of the converted EDepSim HDF5 prepared for larnd-sim, with only zero-length incompatible truth datasets removed.

**larnd-sim**  
GPU detector-response simulation that models quenching, drift, pixels, thresholds, LArPix packets, truth associations, and optionally optical response.

**MCP**  
Millicharged particle. Current EDepSim truth code is PDG `9000001`.

**POT**  
Protons on target, used to normalize expected source yield.

**Runtime overlay**  
Project-specific Flow configuration copied from top-level `configs/` into a clean pinned upstream submodule for one run.

**Source stage**  
Pre-acceptance flux model normalized with `n_mcp_total`; intended for future beamline transport followed by detector acceptance.

**Spectra prescale**  
Weight associated with stored Pythia spectrum rows when only a subset of generated MCPs is written. It controls donor-shape weighting, not absolute emitter normalization.

**`straight_line_v0`**  
Named Level-0 beamline model with no energy loss, scattering, magnetic deflection, attenuation, or material interaction before local injection.

**Submodule pointer**  
Exact commit recorded by the parent repository for an external source tree. Parent Git does not preserve uncommitted submodule edits.

**Unconditional efficiency**  
Efficiency computed relative to the correct generated/source denominator, including events with zero active-LAr deposit or zero packets.

**Vertex ID**  
Event/interaction identifier propagated through HDF5. Local IDs can collide across shards; future production needs a global identity rule.
