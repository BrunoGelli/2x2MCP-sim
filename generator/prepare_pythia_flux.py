#!/usr/bin/env python3
"""Convert 2x2MCP-PythiaGen mcp_spectra rows into EDepSim HEPEVT input.

The Pythia generator uses a beam-frame convention with +z from the NuMI target
toward the detector.  This adapter:

  1. selects one MCP mass from a Pythia ROOT file;
  2. optionally applies/recomputes the 2x2 geometric acceptance;
  3. propagates each retained MCP back from the detector plane to a configurable
     injection plane just upstream of the detector;
  4. rotates the beam frame by the NuMI downward beam angle into the EDepSim
     global frame;
  5. writes EDepSim's built-in HEPEVT ``pbomb`` flavor plus CSV/JSON provenance.

No production normalization is applied here.  The input ROOT file remains the
source of the production/acceptance normalization, while EDepSim handles detector
transport for the retained particles.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import ROOT
except ImportError as exc:
    raise SystemExit(
        "PyROOT is required. Run this in the same ROOT-enabled environment used "
        "for EDepSim."
    ) from exc


EDEPSIM_MCP_PDG = 9000001
PYTHIA_MCP_ABS_PDG = 1000222
DEFAULT_BASELINE_M = 1040.0
DEFAULT_BEAM_ANGLE_DEG = 3.0
DEFAULT_INJECTION_DISTANCE_M = 1.5
DEFAULT_MASS_TOL_GEV = 1.0e-8

# Geometry used by 2x2MCP-PythiaGen for geometry_id=1.
DEFAULT_X_RANGES_M = ((-0.65, -0.05), (0.05, 0.65))
DEFAULT_Y_RANGE_M = (-0.70, 0.70)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Prepare realistic MCP HEPEVT input for EDepSim from mcp_spectra."
    )
    p.add_argument("input_root", type=Path, help="2x2MCP-PythiaGen ROOT file")
    p.add_argument("output_prefix", type=Path, help="Prefix for .hepevt/.csv/.json/.mac")
    p.add_argument(
        "--mass-gev",
        type=float,
        default=None,
        help="MCP mass to select. If omitted, require exactly one mass in mcp_spectra.",
    )
    p.add_argument("--mass-tol-gev", type=float, default=DEFAULT_MASS_TOL_GEV)
    p.add_argument(
        "--selection",
        choices=("accepted", "recompute", "all"),
        default="recompute",
        help=(
            "accepted: trust passed_geometry/accepted from the ROOT file; "
            "recompute: recompute the documented 2x2 projection cut; "
            "all: retain every selected-mass spectrum row."
        ),
    )
    p.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Maximum number of retained MCPs to write (after selection).",
    )
    p.add_argument(
        "--baseline-m",
        type=float,
        default=DEFAULT_BASELINE_M,
        help="Target-to-detector distance along the Pythia beam axis.",
    )
    p.add_argument(
        "--beam-angle-deg",
        type=float,
        default=DEFAULT_BEAM_ANGLE_DEG,
        help="Downward NuMI beam angle; positive means beam points toward -global-y.",
    )
    p.add_argument(
        "--injection-distance-m",
        type=float,
        default=DEFAULT_INJECTION_DISTANCE_M,
        help="Distance upstream of the detector-center beam plane for EDepSim injection.",
    )
    p.add_argument("--detector-center-x-m", type=float, default=0.0)
    p.add_argument("--detector-center-y-m", type=float, default=0.0)
    p.add_argument("--detector-center-z-m", type=float, default=0.0)
    p.add_argument(
        "--time-ns",
        type=float,
        default=0.0,
        help="Primary-vertex time written to HEPEVT for this first integration stage.",
    )
    p.add_argument(
        "--allow-nonunit-spectra-prescale",
        action="store_true",
        help=(
            "Allow source files whose mcp_summary reports spectra_prescale != 1. "
            "This is unsafe if you intend to derive acceptance from mcp_spectra itself."
        ),
    )
    return p


def rotate_beam_to_global(x: float, y: float, z: float, theta: float) -> Tuple[float, float, float]:
    """Rotate about global +x so beam +z points downward by theta.

    Local +z maps to (0, -sin(theta), cos(theta)).
    """
    c = math.cos(theta)
    s = math.sin(theta)
    return x, c * y - s * z, s * y + c * z


def recompute_projection(px: float, py: float, pz: float, baseline_m: float) -> Tuple[bool, float, float]:
    if pz <= 0.0:
        return False, math.nan, math.nan
    x = (px / pz) * baseline_m
    y = (py / pz) * baseline_m
    in_x = any(lo <= x <= hi for lo, hi in DEFAULT_X_RANGES_M)
    in_y = DEFAULT_Y_RANGE_M[0] <= y <= DEFAULT_Y_RANGE_M[1]
    return in_x and in_y, x, y


def unique_masses(tree) -> List[float]:
    values = set()
    for row in tree:
        values.add(round(float(row.mcp_mass_GeV), 12))
    return sorted(values)


def matching_summary_rows(summary, mass_gev: float, tol: float) -> List[Dict[str, object]]:
    if not summary:
        return []
    names = [b.GetName() for b in summary.GetListOfBranches()]
    wanted = [
        "run_id", "job_id", "thread_id", "seed", "mcp_mass_GeV",
        "emitter_pdg", "emitter_type", "production_mode", "geometry_id",
        "n_events_generated", "n_mcp_total", "n_mcp_accepted",
        "acceptance_fraction", "acceptance_uncertainty_binomial",
        "sigma_gen_mb", "sigma_err_mb", "weight_per_event_mb",
        "spectra_prescale",
    ]
    out: List[Dict[str, object]] = []
    for row in summary:
        if abs(float(row.mcp_mass_GeV) - mass_gev) > tol:
            continue
        data: Dict[str, object] = {}
        for name in wanted:
            if name in names:
                value = getattr(row, name)
                try:
                    value = value.item()
                except AttributeError:
                    pass
                data[name] = value
        out.append(data)
    return out


def main() -> int:
    args = parser().parse_args()

    if args.baseline_m <= 0.0:
        raise SystemExit("--baseline-m must be positive")
    if args.injection_distance_m <= 0.0:
        raise SystemExit("--injection-distance-m must be positive")

    root_file = ROOT.TFile.Open(str(args.input_root), "READ")
    if not root_file or root_file.IsZombie():
        raise SystemExit(f"Could not open ROOT file: {args.input_root}")

    spectra = root_file.Get("mcp_spectra")
    if not spectra:
        raise SystemExit("Input ROOT file has no mcp_spectra tree")
    summary = root_file.Get("mcp_summary")

    masses = unique_masses(spectra)
    if args.mass_gev is None:
        if len(masses) != 1:
            raise SystemExit(
                "Input contains multiple MCP masses. Choose one with --mass-gev. "
                f"Available masses: {masses}"
            )
        mass_gev = masses[0]
    else:
        mass_gev = args.mass_gev
        if not any(abs(m - mass_gev) <= args.mass_tol_gev for m in masses):
            raise SystemExit(
                f"Requested mass {mass_gev:g} GeV not found. Available masses: {masses}"
            )

    # Current EDepSim MCP uses G4hIonisation, which requires mass > 10 MeV.
    if mass_gev <= 0.010:
        raise SystemExit(
            f"Selected mass is {mass_gev:g} GeV. The current EDepSim MCP model "
            "requires mass > 0.010 GeV. Choose a heavier first test point or update "
            "the MCP transport model before using this mass."
        )

    summary_rows = matching_summary_rows(summary, mass_gev, args.mass_tol_gev)
    prescales = {
        int(r["spectra_prescale"])
        for r in summary_rows
        if "spectra_prescale" in r
    }
    if prescales and prescales != {1} and not args.allow_nonunit_spectra_prescale:
        raise SystemExit(
            "mcp_summary reports spectra_prescale values other than 1: "
            f"{sorted(prescales)}. Use an unprescaled spectrum for exact event-level "
            "integration, or pass --allow-nonunit-spectra-prescale knowingly."
        )

    output_prefix = args.output_prefix
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    hepevt_path = output_prefix.with_suffix(".hepevt")
    csv_path = output_prefix.with_suffix(".manifest.csv")
    json_path = output_prefix.with_suffix(".summary.json")
    macro_path = output_prefix.with_suffix(".mac")

    theta = math.radians(args.beam_angle_deg)
    center = (
        args.detector_center_x_m,
        args.detector_center_y_m,
        args.detector_center_z_m,
    )

    rows_total_mass = 0
    rows_source_accepted = 0
    rows_recomputed_accepted = 0
    rows_written = 0
    pythia_sign_counts = {"positive": 0, "negative": 0, "other": 0}

    fieldnames = [
        "edepsim_event_id", "source_entry", "source_event_index", "source_seed",
        "source_mcp_pdg", "edepsim_pdg", "mcp_mass_GeV", "emitter_pdg",
        "mother_pdg", "mother_index", "source_accepted", "recomputed_accepted",
        "px_beam_GeV", "py_beam_GeV", "pz_beam_GeV", "E_source_GeV",
        "x_detector_beam_m", "y_detector_beam_m",
        "x_injection_beam_m", "y_injection_beam_m", "z_injection_beam_m",
        "x_injection_global_m", "y_injection_global_m", "z_injection_global_m",
        "px_global_GeV", "py_global_GeV", "pz_global_GeV",
    ]

    with hepevt_path.open("w") as hepevt, csv_path.open("w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()

        for source_entry, row in enumerate(spectra):
            row_mass = float(row.mcp_mass_GeV)
            if abs(row_mass - mass_gev) > args.mass_tol_gev:
                continue
            rows_total_mass += 1

            source_accepted = bool(int(getattr(row, "passed_geometry", getattr(row, "accepted", 0))))
            if source_accepted:
                rows_source_accepted += 1

            px_b = float(row.px_GeV)
            py_b = float(row.py_GeV)
            pz_b = float(row.pz_GeV)
            E_source = float(row.E_GeV)
            recomputed_accepted, x_det_re, y_det_re = recompute_projection(
                px_b, py_b, pz_b, args.baseline_m
            )
            if recomputed_accepted:
                rows_recomputed_accepted += 1

            # Prefer the generator's recorded detector-plane projection when finite;
            # it is exactly the quantity documented in 2x2MCP-PythiaGen.
            x_det = float(getattr(row, "x_at_detector_m", x_det_re))
            y_det = float(getattr(row, "y_at_detector_m", y_det_re))
            if not math.isfinite(x_det) or not math.isfinite(y_det):
                x_det, y_det = x_det_re, y_det_re

            if args.selection == "accepted" and not source_accepted:
                continue
            if args.selection == "recompute" and not recomputed_accepted:
                continue

            if pz_b <= 0.0:
                # It cannot reach an upstream-to-downstream detector plane.
                continue

            d = args.injection_distance_m
            x_inj_b = x_det - (px_b / pz_b) * d
            y_inj_b = y_det - (py_b / pz_b) * d
            z_inj_b = -d

            x_rel_g, y_rel_g, z_rel_g = rotate_beam_to_global(
                x_inj_b, y_inj_b, z_inj_b, theta
            )
            x_g = center[0] + x_rel_g
            y_g = center[1] + y_rel_g
            z_g = center[2] + z_rel_g
            px_g, py_g, pz_g = rotate_beam_to_global(px_b, py_b, pz_b, theta)

            source_pdg = int(row.mcp_pdg)
            if source_pdg > 0:
                pythia_sign_counts["positive"] += 1
            elif source_pdg < 0:
                pythia_sign_counts["negative"] += 1
            else:
                pythia_sign_counts["other"] += 1

            # Current EDepSim defines a single particle named mcp at +9000001.
            # For detector response without magnetic bending, chi/chibar have the
            # same |q|-dependent ionisation. Preserve the original sign in the CSV.
            edepsim_pdg = EDEPSIM_MCP_PDG

            event_id = rows_written
            # HEPEVT header, five-token form: N x[cm] y[cm] z[cm] t[ns]
            hepevt.write(
                f"1 {100.0*x_g:.12g} {100.0*y_g:.12g} {100.0*z_g:.12g} {args.time_ns:.12g}\n"
            )
            # pbomb particle row:
            # status pid mother1 mother2 daughter1 daughter2 px py pz E mass
            hepevt.write(
                f"1 {edepsim_pdg} 0 0 0 0 "
                f"{px_g:.12g} {py_g:.12g} {pz_g:.12g} {E_source:.12g} {mass_gev:.12g}\n"
            )

            writer.writerow({
                "edepsim_event_id": event_id,
                "source_entry": source_entry,
                "source_event_index": int(row.event_index),
                "source_seed": int(row.seed),
                "source_mcp_pdg": source_pdg,
                "edepsim_pdg": edepsim_pdg,
                "mcp_mass_GeV": row_mass,
                "emitter_pdg": int(row.emitter_pdg),
                "mother_pdg": int(row.mother_pdg),
                "mother_index": int(row.mother_index),
                "source_accepted": int(source_accepted),
                "recomputed_accepted": int(recomputed_accepted),
                "px_beam_GeV": px_b,
                "py_beam_GeV": py_b,
                "pz_beam_GeV": pz_b,
                "E_source_GeV": E_source,
                "x_detector_beam_m": x_det,
                "y_detector_beam_m": y_det,
                "x_injection_beam_m": x_inj_b,
                "y_injection_beam_m": y_inj_b,
                "z_injection_beam_m": z_inj_b,
                "x_injection_global_m": x_g,
                "y_injection_global_m": y_g,
                "z_injection_global_m": z_g,
                "px_global_GeV": px_g,
                "py_global_GeV": py_g,
                "pz_global_GeV": pz_g,
            })
            rows_written += 1
            if args.max_events is not None and rows_written >= args.max_events:
                break

    macro = f"""# Auto-generated by generator/prepare_pythia_flux.py
# Source: {args.input_root}
# Selected MCP mass: {mass_gev:.12g} GeV
# Beam geometry: baseline={args.baseline_m:.12g} m, downward angle={args.beam_angle_deg:.12g} deg

/edep/phys/ionizationModel 0
/edep/hitSeparation volTPCActive -1 mm

# Construct the custom MCP before reading PDG 9000001 from HEPEVT.
/edep/update

/generator/kinematics/hepevt/input {hepevt_path}
/generator/kinematics/hepevt/flavor pbomb
/generator/kinematics/hepevt/verbose 0
/generator/kinematics/set hepevt

# HEPEVT supplies event-by-event vertices and times; do not override them.
/generator/position/set free
/generator/time/set free
/generator/count/fixed/number 1
/generator/count/set fixed
/generator/add

# Zero-hit MCPs remain part of detector-efficiency bookkeeping.
/edep/db/set/requireEventsWithHits false
"""
    macro_path.write_text(macro)

    summary_out = {
        "source_root": str(args.input_root),
        "source_tree": "mcp_spectra",
        "selected_mass_GeV": mass_gev,
        "selection": args.selection,
        "mass_tolerance_GeV": args.mass_tol_gev,
        "baseline_m": args.baseline_m,
        "beam_angle_deg_downward": args.beam_angle_deg,
        "detector_center_global_m": list(center),
        "injection_distance_upstream_m": args.injection_distance_m,
        "rows_for_selected_mass_seen": rows_total_mass,
        "rows_marked_accepted_by_source": rows_source_accepted,
        "rows_accepted_by_recomputed_2x2_cut": rows_recomputed_accepted,
        "rows_written_to_edepsim": rows_written,
        "pythia_mcp_sign_counts_written": pythia_sign_counts,
        "pythia_abs_mcp_pdg_expected": PYTHIA_MCP_ABS_PDG,
        "edepsim_mcp_pdg": EDEPSIM_MCP_PDG,
        "summary_rows_for_mass": summary_rows,
        "outputs": {
            "hepevt": str(hepevt_path),
            "manifest_csv": str(csv_path),
            "macro": str(macro_path),
        },
        "notes": [
            "Production normalization is not applied by this adapter.",
            "The source ROOT mcp_summary remains authoritative for generated/accepted counts.",
            "Current EDepSim defines only +9000001; chi/chibar sign is preserved in the manifest but both are transported as the same MCP species in this first integration stage.",
            "One retained MCP becomes one EDepSim event; source_event_index is preserved so physical pair grouping can be added later.",
        ],
    }
    json_path.write_text(json.dumps(summary_out, indent=2, sort_keys=True) + "\n")

    root_file.Close()

    print(f"Selected mass: {mass_gev:g} GeV")
    print(f"Mass-matched spectra rows seen: {rows_total_mass}")
    print(f"Source-accepted rows seen: {rows_source_accepted}")
    print(f"Recomputed-accepted rows seen: {rows_recomputed_accepted}")
    print(f"EDepSim events written: {rows_written}")
    print(f"HEPEVT: {hepevt_path}")
    print(f"Manifest: {csv_path}")
    print(f"Summary: {json_path}")
    print(f"Macro: {macro_path}")
    print()
    print("Run EDepSim with a mass/charge matching this sample, e.g.:")
    print(f"  export EDEPSIM_MCP_MASS_MEV={1000.0*mass_gev:.12g}")
    print("  export EDEPSIM_MCP_CHARGE=0.3")
    print(f"  edep-sim -g <2x2.gdml> -o <output.root> -e {rows_written} {macro_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
