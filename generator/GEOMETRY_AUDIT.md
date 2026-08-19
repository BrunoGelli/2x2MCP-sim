# Geometry audit note

This note clarifies one subtle point in `FLUX_MODEL_WORKFLOW.md`.

There are **two different rectangles/coordinate uses** in the current accepted-flux workflow:

1. **Pythia training acceptance (`geometry_id=1`)**
   - defined in the Pythia beam frame;
   - uses the stored projection `x_at_detector_m`, `y_at_detector_m`;
   - applies the familiar boxes
     `x in [-0.65,-0.05] or [0.05,0.65]`, `y in [-0.70,0.70]`;
   - this is the conditioning that defines an `accepted` training sample and
     the `n_mcp_accepted` normalization.

2. **Independent post-rotation 2x2 consistency audit**
   - performed after rotating Pythia kinematics into the 2x2 global frame;
   - uses the same approximate box dimensions, but they are interpreted in
     **detector/global coordinates**, centered on the detector coordinate
     origin;
   - the beam axis is allowed to cross the detector off-center (default
     MiniRun5 value `y = -0.42 m`);
   - the beam-axis offset is therefore **not subtracted** before this check.

The second check intentionally does not reproduce the Pythia conditioning.  It
asks whether an event sampled from the Pythia-accepted model also points through
the corresponding approximate face after applying the current 2x2 coordinate
convention.

For an `accepted` model this is a **diagnostic only**.  Events are not rejected a
second time.  The sampler reports `geometry_consistency_fraction` and stores a
per-event `geometry_consistent_with_current_face` flag.

A significantly sub-unity consistency fraction is important information.  It
can indicate one or more of:

- the vertical beam-axis offset matters for the acceptance;
- the Pythia acceptance approximation is not identical to the detector-global
  approximation;
- histogram interpolation has moved events across an acceptance edge;
- one of the coordinate/position assumptions needs refinement.

Because an accepted-only training sample contains no information about MCPs
that Pythia rejected, it cannot recover trajectories that were outside the old
Pythia window but would enter the corrected detector-global window.  A fully
self-consistent acceptance recalculation therefore ultimately requires the
high-statistics pre-acceptance `source` model.  This is one reason the `source`
stage is retained for future production even though the high-statistics
`accepted` stage is the practical choice for the present Level-0 detector study.
