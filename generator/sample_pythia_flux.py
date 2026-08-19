#!/usr/bin/env python3
"""CLI entry point for realistic MCP flux sampling and EDepSim preparation.

The current implementation is the empirical donor + adaptive local-jitter v3
sampler.  Accepted-stage models are generated directly inside the original
Pythia conditioning domain, so no histogram-cell gap filling is possible.
"""

from flux_model_empirical_v3 import sampler_main


if __name__ == "__main__":
    raise SystemExit(sampler_main())
