#!/usr/bin/env python3
"""CLI entry point for realistic MCP flux sampling and EDepSim preparation."""

import flux_model_core as core
from flux_geometry import acceptance_mask_global

# Keep Pythia acceptance as training-stage provenance, but make the independent
# post-rotation check use the detector/global face.  ``sampler_main`` resolves
# this helper dynamically from the shared core module.
core.acceptance_mask = acceptance_mask_global


if __name__ == "__main__":
    raise SystemExit(core.sampler_main())
