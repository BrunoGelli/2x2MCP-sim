#!/usr/bin/env python3
"""Deprecated compatibility entry point.

The first prototype of this file replayed individual Pythia ``mcp_spectra``
rows directly into EDepSim and used an incorrect x/z coordinate mapping inferred
from the arbitrary frozen validation gun.

The production design now uses two explicit stages instead:

  1. ``build_pythia_flux_model.py`` builds a physically normalized,
     multi-emitter, non-parametric source-flux model from Pythia output.
  2. ``sample_pythia_flux.py`` samples as many MCPs as needed, rotates the
     Pythia beam frame into the 2x2 global frame, applies explicit
     ``straight_line_v0`` beamline transport and detector acceptance, then
     writes EDepSim HEPEVT input.

This file is intentionally kept so old notes/commands fail loudly instead of
silently using the obsolete coordinate convention.
"""

import sys

MESSAGE = """
DEPRECATED: generator/prepare_pythia_flux.py is no longer the supported MCP
flux interface.

Use:
  generator/build_pythia_flux_model.py
  generator/sample_pythia_flux.py

See generator/README.md for the current workflow, normalization convention,
coordinate transform, Level-0 beamline transport assumptions, and provenance.
""".strip()

print(MESSAGE, file=sys.stderr)
sys.exit(2)
