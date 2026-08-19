#!/usr/bin/env python3
"""Sample a reusable MCP flux model and prepare realistic EDepSim input.

The model is sampled in the Pythia beam frame, rotated into the 2x2 global
coordinate convention, propagated with the explicit straight_line_v0 beamline
transport model, intersected with the approximate 2x2 detector face, and
written as EDepSim HEPEVT/pbomb primaries.

This script intentionally separates source-flux physics from detector response:
the sampled kinematics are reusable for multiple EDepSim charge points.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:
    raise SystemExit("matplotlib is required for sampling diagnostic plots.") from exc


EDEPSIM_MCP_PDG = 9000001
SAMPLER_SCHEMA_VERSION = 1
TRANSPORT_MODEL = "straight_line_v0"

# Official 2x2_sim analysis convention:
# beam_dir = [0, -0.05836, 1], approximately -3.34 deg vertically.
DEFAULT_BEAM_Y_OVER_Z = -0.05836
DEFAULT_BASELINE_M = 1040.0

# MiniRun5 GNuMIFlux convention places the beam axis at y=-0.42 m when it
# reaches detector z=0. Keep this configurable because geometry versions can
# change.
DEFAULT_BEAM_CENTER_M = (0.0, -0.42, 0.0)

# Approximate 2x2 face used by 2x2MCP-PythiaGen, interpreted here in the 2x2
# global detector plane after coordinate rotation.
DEFAULT_X_RANGES_M = ((-0.65, -0.05), (0.05, 0.65))
DEFAULT_Y_RANGE_M = (-0.70, 0.70)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Sample a multi-emitter MCP flux model, apply straight-line NuMI "
            "transport and 2x2 acceptance, and write EDepSim HEPEVT input."
        )
    )
    p.add_argument("model", type=Path, help="flux_model.npz from build_pythia_flux_model.py")
    p.add_argument(
        "--output-prefix",
        required=True,
        type=Path,
        help="Output prefix for .hepevt, .manifest.csv, .summary.json, .mac, and plots.",
    )
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--n-accepted",
        type=int,
        help="Continue source sampling until this many MCPs pass the 2x2 face cut.",
    )
    target.add_argument(
        "--n-source",
        type=int,
        help=(
            "Draw exactly this many source MCPs. Only accepted MCPs are written to "
            "HEPEVT, while the fixed source count defines the acceptance estimate."
        ),
    )
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--batch-size", type=int, default=100000)
    p.add_argument(
        "--max-source-trials",
        type=int,
        default=100000000,
        help="Safety ceiling when --n-accepted is used.",
    )
    p.add_argument("--baseline-m", type=float, default=DEFAULT_BASELINE_M)
    p.add_argument(
        "--beam-y-over-z",
        type=float,
        default=DEFAULT_BEAM_Y_OVER_Z,
        help=(
            "2x2 global nominal beam slope py/pz. Default -0.05836 follows "
            "DUNE/2x2_sim validation/converter code."
        ),
    )
    p.add_argument("--beam-center-x-m", type=float, default=DEFAULT_BEAM_CENTER_M[0])
    p.add_argument("--beam-center-y-m", type=float, default=DEFAULT_BEAM_CENTER_M[1])
    p.add_argument("--beam-center-z-m", type=float, default=DEFAULT_BEAM_CENTER_M[2])
    p.add_argument(
        "--injection-upstream-z-m",
        type=float,
        default=1.5,
        help=(
            "Injection plane distance upstream in global z from the detector-plane z. "
            "The primary is analytically propagated to this plane before EDepSim."
        ),
    )
    p.add_argument("--time-ns", type=float, default=0.0)
    p.add_argument(
        "--no-plots",
        action="store_true",
        help="Skip sampled-source/accepted diagnostic plots.",
    )
    return p.parse_args()


def git_sha_here() -> str:
    try:
        root = Path(__file__).resolve().parents[1]
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def load_model(path: Path):
    if not path.is_file():
        raise SystemExit(f"Flux model not found: {path}")
    data = np.load(path, allow_pickle=False)
    if "metadata_json" not in data:
        raise SystemExit("Flux model has no metadata_json.")
    metadata = json.loads(str(data["metadata_json"].item()))
    if int(metadata.get("schema_version", -1)) != 1:
        raise SystemExit(f"Unsupported flux model schema: {metadata.get('schema_version')}")
    return data, metadata


def rotation_x_for_beam_slope(y_over_z: float) -> Tuple[float, np.ndarray]:
    # With R_x(theta) = [[1,0,0],[0,c,-s],[0,s,c]], the beam-frame
    # vector (0,0,1) maps to (0,-sin(theta),cos(theta)), hence y/z=-tan(theta).
    theta = math.atan(-y_over_z)
    c, s = math.cos(theta), math.sin(theta)
    matrix = np.array(
        [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]],
        dtype=float,
    )
    return theta, matrix


def sample_component(rng: np.random.Generator, data, component_index: int, n: int):
    prefix = f"c{component_index:03d}"
    hist = np.asarray(data[f"{prefix}_hist"], dtype=float)
    e_edges = np.asarray(data[f"{prefix}_logE_edges"], dtype=float)
    tx_edges = np.asarray(data[f"{prefix}_tx_edges"], dtype=float)
    ty_edges = np.asarray(data[f"{prefix}_ty_edges"], dtype=float)

    flat = hist.ravel()
    total = flat.sum()
    if total <= 0.0:
        raise RuntimeError(f"Component {component_index} has zero flux.")
    idx = rng.choice(flat.size, size=n, p=flat / total)
    ie, ix, iy = np.unravel_index(idx, hist.shape)
    loge = rng.uniform(e_edges[ie], e_edges[ie + 1])
    tx = rng.uniform(tx_edges[ix], tx_edges[ix + 1])
    ty = rng.uniform(ty_edges[iy], ty_edges[iy + 1])
    return np.power(10.0, loge), tx, ty


def sample_source_batch(rng: np.random.Generator, data, metadata: Dict[str, object], n: int):
    components = metadata["components"]
    fractions = np.asarray(
        [float(c["mixture_fraction_source"]) for c in components], dtype=float
    )
    fractions /= fractions.sum()
    comp_idx = rng.choice(len(components), size=n, p=fractions)

    E = np.empty(n, dtype=float)
    tx = np.empty(n, dtype=float)
    ty = np.empty(n, dtype=float)
    for i in range(len(components)):
        mask = comp_idx == i
        count = int(np.count_nonzero(mask))
        if count == 0:
            continue
        Ei, txi, tyi = sample_component(rng, data, i, count)
        E[mask], tx[mask], ty[mask] = Ei, txi, tyi
    return comp_idx, E, tx, ty


def kinematics_from_energy_slopes(E: np.ndarray, tx: np.ndarray, ty: np.ndarray, mass_gev: float):
    p2 = np.maximum(E * E - mass_gev * mass_gev, 0.0)
    p = np.sqrt(p2)
    denom = np.sqrt(1.0 + tx * tx + ty * ty)
    pz = p / denom
    px = tx * pz
    py = ty * pz
    return np.column_stack([px, py, pz])


def ray_intersection_at_z(origin: np.ndarray, directions: np.ndarray, z_plane: float):
    dz = directions[:, 2]
    valid = dz > 0.0
    s = np.full(len(directions), np.nan, dtype=float)
    s[valid] = (z_plane - origin[2]) / dz[valid]
    valid &= s > 0.0
    pos = origin[None, :] + s[:, None] * directions
    return valid, pos, s


def acceptance_mask(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    in_x = np.zeros(len(x), dtype=bool)
    for lo, hi in DEFAULT_X_RANGES_M:
        in_x |= (x >= lo) & (x <= hi)
    in_y = (y >= DEFAULT_Y_RANGE_M[0]) & (y <= DEFAULT_Y_RANGE_M[1])
    return in_x & in_y


def write_macro(path: Path, hepevt_path: Path, mass_gev: float, n_events: int, provenance: Dict[str, object]):
    path.write_text(
        f"""# Auto-generated by generator/sample_pythia_flux.py
# MCP source model: {provenance['source_model']}
# Selected mass: {mass_gev:.12g} GeV
# Beamline transport: {TRANSPORT_MODEL}
# IMPORTANT: this model includes no beamline energy loss, scattering,
# magnetic deflection, attenuation, or material interactions.

/edep/phys/ionizationModel 0
/edep/hitSeparation volTPCActive -1 mm

# Construct custom MCP (PDG 9000001) before HEPEVT is consumed.
/edep/update

/generator/kinematics/hepevt/input {hepevt_path.resolve()}
/generator/kinematics/hepevt/flavor pbomb
/generator/kinematics/hepevt/verbose 0
/generator/kinematics/set hepevt

/generator/position/set free
/generator/time/set free
/generator/count/fixed/number 1
/generator/count/set fixed
/generator/add

# Keep zero-hit events for detector-efficiency bookkeeping.
/edep/db/set/requireEventsWithHits false

# Expected number of HEPEVT events: {n_events}
"""
    )


def make_sample_plot(path: Path, source_plot, accepted_plot, components):
    if not source_plot:
        return
    src_E = np.concatenate([x[0] for x in source_plot])
    src_tx = np.concatenate([x[1] for x in source_plot])
    src_ty = np.concatenate([x[2] for x in source_plot])

    if accepted_plot:
        acc_E = np.concatenate([x[0] for x in accepted_plot])
        acc_tx = np.concatenate([x[1] for x in accepted_plot])
        acc_ty = np.concatenate([x[2] for x in accepted_plot])
        acc_comp = np.concatenate([x[3] for x in accepted_plot])
    else:
        acc_E = acc_tx = acc_ty = acc_comp = np.array([])

    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    variables = [
        (src_E, acc_E, "E [GeV]"),
        (src_tx, acc_tx, r"$t_x$ (Pythia beam frame)"),
        (src_ty, acc_ty, r"$t_y$ (Pythia beam frame)"),
    ]
    for ax, (src, acc, label) in zip(axes[0], variables):
        ax.hist(src, bins=70, density=True, histtype="step", label="source draws")
        if len(acc):
            ax.hist(acc, bins=70, density=True, histtype="step", label="accepted")
        ax.set_xlabel(label)
        ax.set_ylabel("Probability density")
        ax.legend(fontsize=8)

    axes[1, 0].hist2d(src_tx, src_ty, bins=70)
    axes[1, 0].set_title("Source draws")
    axes[1, 0].set_xlabel(r"$t_x$")
    axes[1, 0].set_ylabel(r"$t_y$")

    if len(acc_E):
        axes[1, 1].hist2d(acc_tx, acc_ty, bins=70)
        axes[1, 1].set_title("Accepted draws")
        axes[1, 1].set_xlabel(r"$t_x$")
        axes[1, 1].set_ylabel(r"$t_y$")
    else:
        axes[1, 1].axis("off")

    axes[1, 2].axis("off")
    lines = ["accepted emitter composition:"]
    if len(acc_comp):
        for i, c in enumerate(components):
            n = int(np.count_nonzero(acc_comp == i))
            lines.append(f"{c['emitter_name']:>6s}: {n:8d}")
    axes[1, 2].text(0.0, 1.0, "\n".join(lines), va="top", family="monospace")

    fig.suptitle("Sampled MCP source and Level-0 accepted spectrum")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive.")
    if args.baseline_m <= 0.0:
        raise SystemExit("--baseline-m must be positive.")
    if args.injection_upstream_z_m <= 0.0:
        raise SystemExit("--injection-upstream-z-m must be positive.")
    if args.n_accepted is not None and args.n_accepted <= 0:
        raise SystemExit("--n-accepted must be positive.")
    if args.n_source is not None and args.n_source <= 0:
        raise SystemExit("--n-source must be positive.")

    data, model = load_model(args.model)
    mass_gev = float(model["selected_mass_GeV"])
    if mass_gev <= 0.010:
        raise SystemExit(
            f"Model mass {mass_gev:g} GeV is <=10 MeV. The current EDepSim MCP "
            "G4hIonisation model requires mass >10 MeV."
        )

    components = model["components"]
    total_source_flux = float(model["total_source_flux_per_pot_epsilon2"])
    rng = np.random.default_rng(args.seed)

    theta, rotation = rotation_x_for_beam_slope(args.beam_y_over_z)
    nominal_beam = rotation @ np.array([0.0, 0.0, 1.0])
    nominal_beam /= np.linalg.norm(nominal_beam)

    beam_center = np.array(
        [args.beam_center_x_m, args.beam_center_y_m, args.beam_center_z_m], dtype=float
    )
    target_position = beam_center - args.baseline_m * nominal_beam
    detector_plane_z = args.beam_center_z_m
    injection_plane_z = detector_plane_z - args.injection_upstream_z_m

    out = args.output_prefix
    out.parent.mkdir(parents=True, exist_ok=True)
    hepevt_path = out.with_suffix(".hepevt")
    manifest_path = out.with_suffix(".manifest.csv")
    summary_path = out.with_suffix(".summary.json")
    macro_path = out.with_suffix(".mac")
    plot_path = out.with_suffix(".sampled_flux.png")

    accepted_records: List[Dict[str, object]] = []
    source_trials = 0
    accepted_total = 0
    source_component_counts = np.zeros(len(components), dtype=np.int64)
    accepted_component_counts = np.zeros(len(components), dtype=np.int64)

    plot_source = []
    plot_accepted = []
    plot_source_cap = 200000
    plot_accepted_cap = 200000
    plotted_source = 0
    plotted_accepted = 0

    while True:
        if args.n_source is not None:
            remaining = args.n_source - source_trials
            if remaining <= 0:
                break
            n_batch = min(args.batch_size, remaining)
        else:
            if accepted_total >= args.n_accepted:
                break
            if source_trials >= args.max_source_trials:
                raise SystemExit(
                    f"Reached --max-source-trials={args.max_source_trials} with only "
                    f"{accepted_total}/{args.n_accepted} accepted MCPs."
                )
            n_batch = min(args.batch_size, args.max_source_trials - source_trials)

        batch_start_trial = source_trials
        comp_idx, E, tx, ty = sample_source_batch(rng, data, model, n_batch)

        p_beam = kinematics_from_energy_slopes(E, tx, ty, mass_gev)
        # Apply the one fixed software-coordinate rotation. Magnitudes are unchanged.
        p_global = p_beam @ rotation.T
        p_mag = np.linalg.norm(p_global, axis=1)
        directions = p_global / p_mag[:, None]

        # Explicit beamline transport layer, Level 0:
        # no change to E or momentum after the coordinate rotation.
        valid, detector_pos, _ = ray_intersection_at_z(target_position, directions, detector_plane_z)
        accepted = valid & acceptance_mask(detector_pos[:, 0], detector_pos[:, 1])

        # In target-accepted mode, only count source trials through the Nth accepted
        # MCP in the final batch. This keeps the acceptance denominator and event
        # normalization exact even though sampling is vectorized in large batches.
        n_effective = n_batch
        acc_indices = np.flatnonzero(accepted)
        if args.n_accepted is not None:
            need = args.n_accepted - accepted_total
            if len(acc_indices) >= need:
                n_effective = int(acc_indices[need - 1]) + 1
                acc_indices = acc_indices[:need]

        source_trials += n_effective
        source_component_counts += np.bincount(comp_idx[:n_effective], minlength=len(components))

        accepted_total += len(acc_indices)
        if len(acc_indices):
            accepted_component_counts += np.bincount(comp_idx[acc_indices], minlength=len(components))

            inj_valid, injection_pos_all, _ = ray_intersection_at_z(
                target_position, directions[acc_indices], injection_plane_z
            )
            if not np.all(inj_valid):
                raise RuntimeError("Accepted forward MCP failed to reach injection plane.")

            for local_j, source_j in enumerate(acc_indices):
                c = components[int(comp_idx[source_j])]
                accepted_records.append(
                    {
                        "edepsim_event_id": len(accepted_records),
                        "source_trial_id": batch_start_trial + int(source_j),
                        "component_index": int(comp_idx[source_j]),
                        "emitter_pdg": int(c["emitter_pdg"]),
                        "emitter_name": str(c["emitter_name"]),
                        "production_mode": int(c["production_mode"]),
                        "production_mode_name": str(c["production_mode_name"]),
                        "mcp_mass_GeV": mass_gev,
                        "E_GeV": float(E[source_j]),
                        "tx_pythia": float(tx[source_j]),
                        "ty_pythia": float(ty[source_j]),
                        "px_pythia_GeV": float(p_beam[source_j, 0]),
                        "py_pythia_GeV": float(p_beam[source_j, 1]),
                        "pz_pythia_GeV": float(p_beam[source_j, 2]),
                        "px_2x2_GeV": float(p_global[source_j, 0]),
                        "py_2x2_GeV": float(p_global[source_j, 1]),
                        "pz_2x2_GeV": float(p_global[source_j, 2]),
                        "x_detector_m": float(detector_pos[source_j, 0]),
                        "y_detector_m": float(detector_pos[source_j, 1]),
                        "z_detector_m": float(detector_pos[source_j, 2]),
                        "x_injection_m": float(injection_pos_all[local_j, 0]),
                        "y_injection_m": float(injection_pos_all[local_j, 1]),
                        "z_injection_m": float(injection_pos_all[local_j, 2]),
                    }
                )

        if plotted_source < plot_source_cap:
            take = min(n_effective, plot_source_cap - plotted_source)
            plot_source.append((E[:take], tx[:take], ty[:take], comp_idx[:take]))
            plotted_source += take
        if len(acc_indices) and plotted_accepted < plot_accepted_cap:
            take_idx = acc_indices[: max(0, plot_accepted_cap - plotted_accepted)]
            plot_accepted.append((E[take_idx], tx[take_idx], ty[take_idx], comp_idx[take_idx]))
            plotted_accepted += len(take_idx)

    if source_trials <= 0:
        raise SystemExit("No source MCPs were sampled.")

    accepted_fraction = accepted_total / source_trials
    accepted_flux = total_source_flux * accepted_fraction
    event_weight = accepted_flux / accepted_total if accepted_total > 0 else 0.0

    with hepevt_path.open("w") as hepevt, manifest_path.open("w", newline="") as mf:
        fields = [
            "edepsim_event_id", "source_trial_id", "component_index", "emitter_pdg",
            "emitter_name", "production_mode", "production_mode_name", "mcp_mass_GeV",
            "E_GeV", "tx_pythia", "ty_pythia", "px_pythia_GeV", "py_pythia_GeV",
            "pz_pythia_GeV", "px_2x2_GeV", "py_2x2_GeV", "pz_2x2_GeV",
            "x_detector_m", "y_detector_m", "z_detector_m", "x_injection_m",
            "y_injection_m", "z_injection_m", "event_weight_per_POT_per_epsilon2",
        ]
        writer = csv.DictWriter(mf, fieldnames=fields)
        writer.writeheader()
        for rec in accepted_records:
            hepevt.write(
                f"1 {100.0*float(rec['x_injection_m']):.12g} "
                f"{100.0*float(rec['y_injection_m']):.12g} "
                f"{100.0*float(rec['z_injection_m']):.12g} {args.time_ns:.12g}\n"
            )
            hepevt.write(
                f"1 {EDEPSIM_MCP_PDG} 0 0 0 0 "
                f"{float(rec['px_2x2_GeV']):.12g} {float(rec['py_2x2_GeV']):.12g} "
                f"{float(rec['pz_2x2_GeV']):.12g} {float(rec['E_GeV']):.12g} "
                f"{mass_gev:.12g}\n"
            )
            writer.writerow({**rec, "event_weight_per_POT_per_epsilon2": event_weight})

    provenance = {
        "schema_version": SAMPLER_SCHEMA_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_model": str(args.model.resolve()),
        "source_model_metadata": model,
        "mcp_sim_git_sha": git_sha_here(),
        "sampling": {
            "seed": args.seed,
            "mode": "target_accepted" if args.n_accepted is not None else "fixed_source",
            "requested_n_accepted": args.n_accepted,
            "requested_n_source": args.n_source,
            "n_source_trials": source_trials,
            "n_accepted_written": accepted_total,
            "acceptance_fraction_level0": accepted_fraction,
            "total_source_flux_per_POT_per_epsilon2": total_source_flux,
            "accepted_flux_per_POT_per_epsilon2": accepted_flux,
            "event_weight_per_POT_per_epsilon2": event_weight,
        },
        "coordinate_system": {
            "pythia_frame": {
                "+z": "nominal target-to-detector beam direction",
                "+x": "same signed x convention as 2x2",
                "+y": "same signed y convention as 2x2 before beam-angle rotation",
            },
            "two_by_two_global_nominal_beam_vector": nominal_beam.tolist(),
            "beam_y_over_z": args.beam_y_over_z,
            "rotation_about_global_x_rad": theta,
            "rotation_about_global_x_deg": math.degrees(theta),
            "rotation_matrix_pythia_to_2x2": rotation.tolist(),
            "beam_axis_at_detector_m": beam_center.tolist(),
            "target_position_level0_m": target_position.tolist(),
            "baseline_m": args.baseline_m,
        },
        "beamline_transport": {
            "model": TRANSPORT_MODEL,
            "description": (
                "Straight-line propagation from a pointlike target to the detector. "
                "Energy and momentum are unchanged after the coordinate rotation."
            ),
            "energy_loss": False,
            "multiple_scattering": False,
            "magnetic_deflection": False,
            "attenuation": False,
            "material_interactions": False,
            "target_position_model": "point_target_v0",
        },
        "acceptance": {
            "order": "coordinate_rotation -> straight_line_v0 -> detector_intersection -> face_cut",
            "detector_plane_global_z_m": detector_plane_z,
            "x_ranges_global_m": [list(x) for x in DEFAULT_X_RANGES_M],
            "y_range_global_m": list(DEFAULT_Y_RANGE_M),
            "reference_note": (
                "Face dimensions follow the existing 2x2MCP-PythiaGen approximate "
                "2x2 acceptance, now evaluated after rotation in 2x2 global coordinates."
            ),
        },
        "injection": {
            "plane_global_z_m": injection_plane_z,
            "upstream_z_distance_m": args.injection_upstream_z_m,
            "transport_from_target_to_injection": TRANSPORT_MODEL,
        },
        "component_counts_source": {
            str(c["emitter_name"]): int(source_component_counts[i])
            for i, c in enumerate(components)
        },
        "component_counts_accepted": {
            str(c["emitter_name"]): int(accepted_component_counts[i])
            for i, c in enumerate(components)
        },
        "outputs": {
            "hepevt": str(hepevt_path),
            "manifest_csv": str(manifest_path),
            "macro": str(macro_path),
            "sampled_flux_plot": None if args.no_plots else str(plot_path),
        },
        "edepsim": {
            "pdg": EDEPSIM_MCP_PDG,
            "mass_MeV": 1000.0 * mass_gev,
            "charge": (
                "NOT encoded in the flux model; set EDEPSIM_MCP_CHARGE before EDepSim. "
                "The same sampled kinematics should be reused across charge scans."
            ),
            "chi_chibar_note": (
                "The first detector-response implementation transports both production "
                "charge signs as the single custom EDepSim MCP species. Source flux "
                "normalization is for MCP particles, not pairs."
            ),
        },
    }
    summary_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    write_macro(macro_path, hepevt_path, mass_gev, accepted_total, provenance)

    if not args.no_plots:
        make_sample_plot(plot_path, plot_source, plot_accepted, components)

    print("Coordinate sanity check:")
    print("  Pythia on-axis (0,0,+1) -> 2x2", nominal_beam)
    print(
        f"  rotation about +x = {math.degrees(theta):.6f} deg; "
        f"beam axis at detector = {beam_center.tolist()} m"
    )
    print()
    print(f"Source trials: {source_trials}")
    print(f"Accepted MCPs written: {accepted_total}")
    print(f"Level-0 acceptance: {accepted_fraction:.8g}")
    print(f"Source flux / POT / epsilon^2: {total_source_flux:.12g}")
    print(f"Accepted flux / POT / epsilon^2: {accepted_flux:.12g}")
    print(f"Per-accepted-event weight / POT / epsilon^2: {event_weight:.12g}")
    print(f"HEPEVT: {hepevt_path}")
    print(f"Manifest: {manifest_path}")
    print(f"Summary/provenance: {summary_path}")
    print(f"Macro: {macro_path}")
    print()
    print("Run EDepSim with:")
    print(f"  export EDEPSIM_MCP_MASS_MEV={1000.0*mass_gev:.12g}")
    print("  export EDEPSIM_MCP_CHARGE=<charge in units of e>")
    print(f"  edep-sim -g <2x2.gdml> -o <output.root> -e {accepted_total} {macro_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
