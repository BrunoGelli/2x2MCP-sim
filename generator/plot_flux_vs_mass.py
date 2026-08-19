#!/usr/bin/env python3
"""Plot source/accepted MCP flux and effective acceptance versus mass.

This uses only the 2x2MCP-PythiaGen aggregate summary CSV; it does not depend on
a built phase-space model or PyROOT.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from flux_model_core import read_aggregate_summary, write_mass_scan


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("summary", type=Path, help="aggregate_summary.csv")
    p.add_argument("--geometry-id", type=int, default=1)
    p.add_argument("--output-dir", type=Path, default=Path("out/flux_mass_scan"))
    args = p.parse_args()
    if not args.summary.is_file():
        raise SystemExit(f"Summary CSV not found: {args.summary}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows, sigma_soft, sigma_charm, charm_scale = read_aggregate_summary(args.summary)
    write_mass_scan(rows, charm_scale, args.geometry_id, args.output_dir)
    print(f"sigma_softqcd_mb_mean={sigma_soft:.12g}")
    print(f"sigma_charmonium_mb_mean={sigma_charm:.12g}")
    print(f"charmonium_process_scale={charm_scale:.12g}")
    print(f"CSV:  {args.output_dir/'flux_vs_mass.csv'}")
    print(f"Plot: {args.output_dir/'flux_vs_mass.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
