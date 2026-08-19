#!/usr/bin/env python3
"""CLI entry point for the realistic MCP flux-model builder.

Implementation lives in ``flux_model_core.py`` so the builder and sampler share
one normalization/coordinate contract.
"""

from flux_model_core import build_main


if __name__ == "__main__":
    raise SystemExit(build_main())
