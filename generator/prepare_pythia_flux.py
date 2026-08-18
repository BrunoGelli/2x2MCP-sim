#!/usr/bin/env python3
"""Convert 2x2MCP-PythiaGen ``mcp_spectra`` rows into EDepSim HEPEVT input.

The Pythia generator uses a beam-frame convention with +z from the NuMI target
toward the detector.  The validated 2x2 EDepSim gun instead uses global -x as
the incoming beam direction.  This adapter therefore uses the explicit,
right-handed mapping

    Pythia +z_beam -> EDepSim -x_global
    Pythia +y_beam -> EDepSim +y_global
    Pythia +x_beam -> EDepSim +z_global

with the detector beam-plane reference point defaulting to (0, -0.2, 0.3) m.
For an on-axis particle and the default 1.5 m injection distance this exactly
reproduces the frozen validation gun position (1.5, -0.2, 0.3) m and direction
(-1, 0, 0).

The physical NuMI target-to-2x2 geometry (1.04 km baseline and approximately
3 degree downward beam angle) is recorded as provenance.  The 3 degree civil-
engineering/elevation angle is *not* applied as an additional rotation inside
the EDepSim detector frame: the validated EDepSim geometry already has its own
global coordinate convention, and applying another tilt without an explicit
GDML survey transform would double-count/guess that relationship.

No production normalization is applied here.  The input ROOT ``mcp_summary``
remains authoritative for generated/accepted counts and production weights,
while EDepSim handles detector transport for the retained particles.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Tuple

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
DEFAULT_DETECTOR_CENTER_GLOBAL_M = (0.0, -0.2, 0.3)

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
        "--mass-gev", type=float, default=None,
        help="MCP mass to select. If omitted, require exactly one mass in mcp_spectra.",
    )
    p.add_argument("--mass-tol-gev", type=float, default=DEFAULT_MASS_TOL_GEV)
    p.add_argument(
        "--selection", choices=("accepted", "recompute", "all"), default="recompute",
        help=(
            "accepted: trust passed_geometry/accepted from the ROOT file; "
            "recompute: recompute the documented 2x2 projection cut; "
            "all: retain every selected-mass spectrum row."
        ),
    )
    p.add_argument(
        "--max-events", type=int, default=None,
        help="Maximum number of retained MCPs to write after selection.",
    )
    p.add_argument(
        "--baseline-m", type=float, default=DEFAULT_BASELINE_M,
        help="Target-to-detector distance along the Pythia beam axis.",
    )
    p.add_argument(
        "--beam-angle-deg", type=float, default=DEFAULT_BEAM_ANGLE_DEG,
        help=(
            "Physical NuMI downward beam angle stored as provenance only; it is "
            "not additionally rotated into the already-defined EDepSim frame."
        ),
    )
    p.add_argument(
        "--injection-distance-m", type=float, default=DEFAULT_INJECTION_DISTANCE_M,
        help="Distance upstream of the detector beam plane for EDepSim injection.",
    )
    p.add_argument("--detector-center-x-m", type=float, default=DEFAULT_DETECTOR_CENTER_GLOBAL_M[0])
    p.add_argument("--detector-center-y-m", type=float, default=DEFAULT_DETECTOR_CENTER_GLOBAL_M[1])
    p.add_argument("--detector-center-z-m", type=float, default=DEFAULT_DETECTOR_CENTER_GLOBAL_M[2])
    p.add_argument(
        "--time-ns", type=float, default=0.0,
        help="Primary-vertex time written to HEPEVT for this first integration stage.",
    )
    p.add_argument(
        "--allow-nonunit-spectra-prescale", action="store_true",
        help=(
            "Allow source files whose mcp_summary reports spectra_prescale != 1. "
            "This is unsafe if you intend to derive acceptance from mcp_spectra itself."
        ),
    )
    return p


def beam_to_edepsim(x_beam: float, y_beam: float, z_beam: float) -> Tuple[float, float, float]:
    """Map Pythia beam-frame vector components into EDepSim global axes."""
    return -z_beam, y_beam, x_beam


def recompute_projection(
    px: float, py: float, pz: float, baseline_m: float
) -> Tuple[bool, float, float]:
    """Reproduce the current 2x2MCP-PythiaGen geometry_id=1 projection."""
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
        "sigma_gen_mb", "sigma_err_mb", "weight_per_event_mb", "spectra_prescale",
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
                if not isinstance(value, (str, int, float, bool)):
                    try:
                        value = float(value)
                    except (TypeError, ValueError):
                        value = str(value)
                data[name] = value
        out.append(data)
    return out


def main() -> int:
    args = parser().parse_args()

    if args.baseline_m <= 0.0:
        raise SystemExit("--baseline-m must be positive")
    if args.injection_distance_m <= 0.0:
        raise SystemExit("--injection-distance-m must be positive")
    if args.max_events is not None and args.max_events <= 0:
        raise SystemExit("--max-events must be positive when supplied")

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
        for r in summary_rows if "spectra_prescale" in r
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

    center = (
        args.detector_center_x_m, args.detector_center_y_m, args.detector_center_z_m
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

            source_accepted = bool(
                int(getattr(row, "passed_geometry", getattr(row, "accepted", 0)))
            )
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

            x_det = float(getattr(row, "x_at_detector_m", x_det_re))
            y_det = float(getattr(row, "y_at_detector_m", y_det_re))
            if not math.isfinite(x_det) or not math.isfinite(y_det):
                x_det, y_det = x_det_re, y_det_re

            if args.selection == "accepted" and not source_accepted:
                continue
            if args.selection == "recompute" and not recomputed_accepted:
                continue
            if pz_b <= 0.0:
                continue

            # Move upstream from the Pythia detector plane along the same ray.
            d = args.injection_distance_m
            x_inj_b = x_det - (px_b / pz_b) * d
            y_inj_b = y_det - (py_b / pz_b) * d
            z_inj_b = -d

            x_rel_g, y_rel_g, z_rel_g = beam_to_edepsim(x_inj_b, y_inj_b, z_inj_b)
            x_g = center[0] + x_rel_g
            y_g = center[1] + y_rel_g
            z_g = center[2] + z_rel_g
            px_g, py_g, pz_g = beam_to_edepsim(px_b, py_b, pz_b)

            source_pdg = int(row.mcp_pdg)
            if source_pdg > 0:
                pythia_sign_counts["positive"] += 1
            elif source_pdg < 0:
                pythia_sign_counts["negative"] += 1
            else:
                pythia_sign_counts["other"] += 1

            # Current EDepSim has one MCP species. Preserve source sign in the
            # sidecar manifest and transport both signs with the configured |q|.
            edepsim_pdg = EDEPSIM_MCP_PDG

            event_id = rows_written
            # Five-token HEPEVT header: N x[cm] y[cm] z[cm] t[ns].
            hepevt.write(
                f"1 {100.0*x_g:.12g} {100.0*y_g:.12g} "
                f"{100.0*z_g:.12g} {args.time_ns:.12g}\n"
            )
            # pbomb row: status pid m1 m2 d1 d2 px py pz E mass (GeV).
            hepevt.write(
                f"1 {edepsim_pdg} 0 0 0 0 "
                f"{px_g:.12g} {py_g:.12g} {pz_g:.12g} "
                f"{E_source:.12g} {mass_gev:.12g}\n"
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

    if rows_written == 0:
        for path in (hepevt_path, csv_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise SystemExit(
            "No MCP rows survived the requested mass/selection. No EDepSim input written."
        )

    macro = f"""# Auto-generated by generator/prepare_pythia_flux.py
# Source: {args.input_root}
# Selected MCP mass: {mass_gev:.12g} GeV
# Physical beamline provenance: baseline={args.baseline_m:.12g} m, downward angle={args.beam_angle_deg:.12g} deg
# EDepSim mapping: +z_beam -> -x_global, +y_beam -> +y_global, +x_beam -> +z_global
# Detector beam-plane reference: ({center[0]:.12g}, {center[1]:.12g}, {center[2]:.12g}) m

/edep/phys/ionizationModel 0
/edep/hitSeparation volTPCActive -1 mm
/edep/update

/generator/kinematics/hepevt/input {hepevt_path}
/generator/kinematics/hepevt/flavor pbomb
/generator/kinematics/hepevt/verbose 0
/generator/kinematics/set hepevt
/generator/position/set free
/generator/time/set free
/generator/count/fixed/number 1
/generator/count/set fixed
/generator/add

/edep/db/set/requireEventsWithHits false
"""
    macro_path.write_text(macro)

    nominal_pos_rel = beam_to_edepsim(0.0, 0.0, -args.injection_distance_m)
    nominal_pos = tuple(center[i] + nominal_pos_rel[i] for i in range(3))
    nominal_dir = beam_to_edepsim(0.0, 0.0, 1.0)

    summary_out = {
        "source_root": str(args.input_root),
        "source_tree": "mcp_spectra",
        "selected_mass_GeV": mass_gev,
        "selection": args.selection,
        "mass_tolerance_GeV": args.mass_tol_gev,
        "physical_beamline": {
            "target_to_detector_baseline_m": args.baseline_m,
            "downward_angle_deg": args.beam_angle_deg,
            "angle_application": "provenance_only_not_additional_edepsim_rotation",
        },
        "edepsim_frame": {
            "beam_axis_mapping": {
                "+z_beam": "-x_global",
                "+y_beam": "+y_global",
                "+x_beam": "+z_global",
            },
            "detector_beam_plane_reference_m": list(center),
            "injection_distance_upstream_m": args.injection_distance_m,
            "nominal_on_axis_injection_m": list(nominal_pos),
            "nominal_on_axis_direction": list(nominal_dir),
            "frozen_gun_crosscheck_expected": {
                "position_m": [1.5, -0.2, 0.3],
                "direction": [-1.0, 0.0, 0.0],
            },
        },
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
            "The physical 3 degree NuMI elevation angle is recorded but not double-applied inside the EDepSim detector frame.",
            "Current EDepSim defines only +9000001; chi/chibar sign is preserved in the manifest but both are transported as the same MCP species in this first integration stage.",
            "One retained MCP becomes one EDepSim event; source_event_index and mother_index are preserved so pair grouping can be added later.",
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
    print("Nominal-axis cross-check:")
    print(f"  injection position = {nominal_pos} m")
    print(f"  direction          = {nominal_dir}")
    print()
    print("Run EDepSim with a mass/charge matching this sample, e.g.:")
    print(f"  export EDEPSIM_MCP_MASS_MEV={1000.0*mass_gev:.12g}")
    print("  export EDEPSIM_MCP_CHARGE=0.3")
    print(f"  edep-sim -g <2x2.gdml> -o <output.root> -e {rows_written} {macro_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
