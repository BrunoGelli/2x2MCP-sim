#!/usr/bin/env python3
"""CLI entry point for realistic MCP flux sampling and EDepSim preparation."""

import flux_model_core as core
from flux_geometry import acceptance_mask_global
from flux_sampling_constraints import make_conditioned_draw

# Accepted-stage sampling is constrained to remain inside the original Pythia
# conditioning window, preventing histogram interpolation from inventing
# out-of-domain accepted points.  The independent post-rotation detector/global
# face remains a diagnostic only.
core.draw_model = make_conditioned_draw(core.draw_model)
core.acceptance_mask = acceptance_mask_global


if __name__ == "__main__":
    raise SystemExit(core.sampler_main())
