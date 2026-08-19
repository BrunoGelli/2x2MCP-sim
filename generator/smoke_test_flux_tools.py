#!/usr/bin/env python3
"""Small local smoke test for the realistic MCP flux tools.

This does not require PyROOT.  It:
  1. byte-compiles the shared modules/entry points;
  2. constructs a tiny synthetic accepted-stage flux model;
  3. samples 25 events through the real accepted-stage guards/sampler;
  4. checks the expected HEPEVT/manifest/summary/macro products.

Run from the repository root with:

    python generator/smoke_test_flux_tools.py
"""

from __future__ import annotations

import json
import py_compile
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def main() -> int:
    for name in (
        "flux_model_core.py",
        "flux_geometry.py",
        "flux_sampling_constraints.py",
        "build_pythia_flux_model.py",
        "sample_pythia_flux.py",
        "plot_flux_vs_mass.py",
        "prepare_pythia_flux.py",
    ):
        py_compile.compile(str(HERE / name), doraise=True)
    print("Python byte-compilation: OK")

    import flux_model_core as core
    from flux_geometry import acceptance_mask_global
    from flux_sampling_constraints import make_conditioned_draw

    core.draw_model = make_conditioned_draw(core.draw_model)
    core.acceptance_mask = acceptance_mask_global

    with tempfile.TemporaryDirectory(prefix="mcp_flux_smoke_") as td:
        root = Path(td)
        model = root / "synthetic_accepted_model.npz"
        out_prefix = root / "sample"

        # Compact forward component entirely around the two Pythia x windows.
        # theta_x avoids the central x gap at the 1040 m projection plane.
        hist = np.ones((3, 4, 3), dtype=float)
        hist /= hist.sum()
        metadata = {
            "schema_version": 2,
            "model_type": "weighted_histogram_logE_thetaX_thetaY_v2",
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
            c000_hist=hist,
            c000_logE_edges=np.array([-0.5, 0.0, 0.5, 1.0]),
            c000_theta_x_edges=np.array([-5e-4, -2e-4, -6e-5, 2e-4, 5e-4]),
            c000_theta_y_edges=np.array([-4e-4, -1e-4, 1e-4, 4e-4]),
        )

        rc = core.sampler_main([
            str(model), str(out_prefix), "--n-events", "25", "--seed", "17"
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

        summary = json.loads(out_prefix.with_suffix(".summary.json").read_text())
        if summary["events_written"] != 25:
            raise RuntimeError("Expected 25 written events")
        if summary["model_flux_stage"] != "accepted":
            raise RuntimeError("Synthetic model stage was not preserved")

    print("Synthetic accepted-stage sampler: OK")
    print("Flux-tool smoke test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
