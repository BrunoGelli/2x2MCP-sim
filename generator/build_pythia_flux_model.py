#!/usr/bin/env python3
"""CLI entry point for the realistic MCP flux-model builder.

The current implementation is the empirical donor + adaptive local-jitter v3
model in ``flux_model_empirical_v3.py``.  The older histogram implementation is
kept in ``flux_model_core.py`` only for history/utility helpers.
"""

from flux_model_empirical_v3 import build_main


if __name__ == "__main__":
    raise SystemExit(build_main())
