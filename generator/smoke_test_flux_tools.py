#!/usr/bin/env python3
"""Small local smoke test for the realistic MCP flux tools.

This does not require PyROOT. It:
  1. byte-compiles the shared modules/entry points;
  2. constructs a tiny synthetic empirical-v3 accepted-stage flux model;
  3. samples 25 events through the real sampler;
  4. verifies the original two-module conditioning gap stays empty;
  5. checks the expected HEPEVT/manifest/summary/macro products.

Run from the repository root with:

    python generator/smoke_test_flux_tools.py
"""

from __future__ import annotations

import csv
import json
import py_compile
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def midpoint_bounds(values, groups, hard):
    values = np.asarray(values, float)
    lo = values.copy(); hi = values.copy()
    for g in np.unique(groups):
        idx = np.flatnonzero(groups == g)
        order = idx[np.argsort(values[idx])]
        v = values[order]
        if len(v) > 1:
            mids = 0.5 * (v[:-1] + v[1:])
            lo[order[1:]] = mids
            hi[order[:-1]] = mids
        hlo, hhi = hard[int(g)]
        lo[order] = np.maximum(lo[order], hlo)
        hi[order] = np.minimum(hi[order], hhi)
    return lo, hi


def main() -> int:
    for name in (
        "flux_model_core.py",
        "flux_model_empirical_v3.py",
        "flux_geometry.py",
        "build_pythia_flux_model.py",
        "sample_pythia_flux.py",
        "plot_flux_vs_mass.py",
        "prepare_pythia_flux.py",
    ):
        py_compile.compile(str(HERE / name), doraise=True)
    print("Python byte-compilation: OK")

    import flux_model_empirical_v3 as v3

    with tempfile.TemporaryDirectory(prefix="mcp_flux_smoke_") as td:
        root = Path(td)
        model = root / "synthetic_accepted_model.npz"
        out_prefix = root / "sample"

        E = np.array([0.10, 0.20, 0.50, 1.0, 2.0, 5.0])
        loge = np.log10(E)
        groups = np.array([-1, -1, -1, 1, 1, 1], dtype=np.int8)
        x = np.array([-0.64, -0.40, -0.051, 0.051, 0.30, 0.64])
        y = np.array([-0.4, 0.0, 0.4, -0.4, 0.0, 0.4])
        log_lo, log_hi = midpoint_bounds(loge, groups, {-1: (loge.min(), loge.max()), 1: (loge.min(), loge.max())})
        x_lo, x_hi = midpoint_bounds(x, groups, {-1: (-0.65, -0.05), 1: (0.05, 0.65)})
        y_lo, y_hi = midpoint_bounds(y, groups, {-1: (-0.70, 0.70), 1: (-0.70, 0.70)})
        metadata = {
            "schema_version": 3,
            "model_type": "weighted_empirical_donor_local_jitter_v3",
            "flux_stage": "accepted",
            "selected_mass_GeV": 0.020458,
            "total_stage_flux_per_pot_epsilon2": 1.0e-5,
            "components": [
                {
                    "component_index": 0,
                    "emitter_pdg": 111,
                    "emitter_name": "pi0",
                    "production_mode": 0,
                    "production_mode_name": "light_mesons",
                    "mixture_fraction": 1.0,
                    "stage_flux_per_pot_epsilon2": 1.0e-5,
                }
            ],
        }
        np.savez_compressed(
            model,
            metadata_json=np.array(json.dumps(metadata, sort_keys=True)),
            mcp_mass_GeV=np.array(0.020458),
            component_pdg=np.array([111], dtype=np.int32),
            component_flux=np.array([1.0e-5]),
            component_fraction=np.array([1.0]),
            c000_donor_logE=loge,
            c000_donor_theta_x=np.arctan2(x, 1040.0),
            c000_donor_theta_y=np.arctan2(y, 1040.0),
            c000_donor_xdet=x,
            c000_donor_ydet=y,
            c000_donor_prob=np.ones(len(E)) / len(E),
            c000_donor_side=groups,
            c000_logE_lo=log_lo,
            c000_logE_hi=log_hi,
            c000_xdet_lo=x_lo,
            c000_xdet_hi=x_hi,
            c000_ydet_lo=y_lo,
            c000_ydet_hi=y_hi,
        )

        rc = v3.sampler_main([
            str(model), str(out_prefix), "--n-events", "25", "--seed", "17", "--jitter-scale", "1.0"
        ])
        if rc != 0:
            raise RuntimeError(f"sampler_main returned {rc}")

        expected = [
            out_prefix.with_suffix(".hepevt"),
            out_prefix.with_suffix(".manifest.csv"),
            out_prefix.with_suffix(".summary.json"),
            out_prefix.with_suffix(".mac"),
            out_prefix.with_suffix(".sampled_flux.png"),
        ]
        missing = [str(p) for p in expected if not p.exists()]
        if missing:
            raise RuntimeError("Missing smoke-test outputs: " + ", ".join(missing))

        with out_prefix.with_suffix(".manifest.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        xs = np.array([float(r["x_pythia_detector_m"]) for r in rows])
        if np.any(np.abs(xs) < 0.05):
            raise RuntimeError("Empirical accepted sampler filled the central module gap")

        summary = json.loads(out_prefix.with_suffix(".summary.json").read_text())
        if summary["events_written"] != 25:
            raise RuntimeError("Expected 25 written events")
        if summary["model_flux_stage"] != "accepted":
            raise RuntimeError("Synthetic model stage was not preserved")
        if summary["schema_version"] != 3:
            raise RuntimeError("Expected sampler schema v3")

    print("Synthetic empirical-v3 accepted-stage sampler: OK")
    print("Central module gap preservation: OK")
    print("Flux-tool smoke test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
