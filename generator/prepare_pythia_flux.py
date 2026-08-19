#!/usr/bin/env python3
"""Deprecated compatibility entry point.

The first prototype replayed individual Pythia rows directly into EDepSim and
used an incorrect x/z coordinate mapping inferred from the arbitrary frozen
validation gun.

The supported workflow now has two explicit programs:

  1. ``build_pythia_flux_model.py`` builds a physically normalized,
     multi-emitter, non-parametric flux model.  It supports both the current
     high-statistics ``accepted`` stage and the future pre-acceptance ``source``
     stage.
  2. ``sample_pythia_flux.py`` samples as many MCPs as needed, applies the
     Pythia-beam -> 2x2 coordinate rotation, records explicit
     ``straight_line_v0`` beamline assumptions, and writes EDepSim HEPEVT input.

This file is intentionally retained so old commands fail loudly instead of
silently using the obsolete coordinate convention.
"""

import sys

MESSAGE = """
DEPRECATED: generator/prepare_pythia_flux.py is no longer the supported MCP
flux interface.

Use:
  generator/build_pythia_flux_model.py
  generator/sample_pythia_flux.py

Current detector studies should normally build with:
  --flux-stage accepted

Future beamline-transport studies can use:
  --flux-stage source

See:
  generator/FLUX_MODEL_WORKFLOW.md
for the current normalization, coordinate, plotting, provenance, acceptance,
and straight_line_v0 transport conventions.
""".strip()

print(MESSAGE, file=sys.stderr)
sys.exit(2)
