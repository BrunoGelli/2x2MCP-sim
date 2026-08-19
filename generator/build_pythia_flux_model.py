#!/usr/bin/env python3
"""Build a reusable, physically normalized MCP flux model from Pythia ROOT spectra.

The source kinematics are represented non-parametrically as one weighted 3D
histogram per emitter in (log10(E/GeV), tx=px/pz, ty=py/pz).  The histograms
encode shapes; their absolute normalization comes from the same aggregate
summary convention used by 2x2MCP-PythiaGen's normalized-yield/toy-MC tools.

The saved model is normalized per POT per epsilon^2.  Charge-dependent detector
response is intentionally not part of this model.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import math
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np

try:
    import ROOT
except ImportError as exc:
    raise SystemExit(
        "PyROOT is required. Run this in a ROOT-enabled environment."
    ) from exc

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm
except ImportError as exc:
    raise SystemExit("matplotlib is required to build validation plots.") from exc


ALPHA = 1.0 / 137.0
MODEL_SCHEMA_VERSION = 1
MODEL_TYPE = "weighted_histogram_logE_tx_ty_v1"

# Keep these constants synchronized with
# 2x2MCP-PythiaGen/scripts/export_toymc_spectra.py.
PARENTS = {
    111: ("pi0", 0, 0.1349768, 0.98823),
    221: ("eta", 0, 0.5478620, 0.39410),
    331: ("etap", 0, 0.9577800, 0.0220),
    113: ("rho0", 1, 0.7752600, 4.72e-5),
    223: ("omega", 1, 0.7826500, 7.36e-5),
    333: ("phi", 1, 1.0194610, 2.973e-4),
    443: ("jpsi", 1, 3.0969000, 5.971e-2),
}
MODE_NAME = {0: "light_mesons", 1: "charmonium", 2: "dy_reserved"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Build a multi-emitter non-parametric MCP flux model from "
            "2x2MCP-PythiaGen mcp_spectra ROOT files."
        )
    )
    p.add_argument(
        "inputs",
        nargs="+",
        help="ROOT files, directories, or shell-style glob patterns containing mcp_spectra.",
    )
    p.add_argument(
        "--summary",
        required=True,
        type=Path,
        help=(
            "Aggregate summary CSV from 2x2MCP-PythiaGen/scripts/aggregate_outputs.py. "
            "This is the authoritative normalization input."
        ),
    )
    p.add_argument("--mass-gev", required=True, type=float, help="MCP mass to model.")
    p.add_argument(
        "--geometry-id",
        type=int,
        default=1,
        help="Pythia generator geometry_id to use (default 1 = 2x2).",
    )
    p.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory for flux_model.npz, provenance, tables, and plots.",
    )
    p.add_argument("--energy-bins", type=int, default=24)
    p.add_argument("--tx-bins", type=int, default=28)
    p.add_argument("--ty-bins", type=int, default=28)
    p.add_argument(
        "--mass-tol-gev",
        type=float,
        default=1.0e-8,
        help="Tolerance when matching mass rows.",
    )
    p.add_argument(
        "--validation-samples",
        type=int,
        default=200000,
        help="Number of model draws used for resampling-validation plots.",
    )
    p.add_argument("--validation-seed", type=int, default=12345)
    p.add_argument(
        "--allow-missing-emitters",
        action="store_true",
        help="Allow a kinematically open supported emitter to be missing from the model.",
    )
    p.add_argument(
        "--allow-accepted-only-spectra",
        action="store_true",
        help=(
            "Allow spectra that look accepted-only. This is NOT recommended for a source "
            "flux model and is recorded prominently in provenance."
        ),
    )
    p.add_argument(
        "--production-tag",
        default="",
        help="Optional human-readable Pythia production tag/name.",
    )
    p.add_argument(
        "--pythia-gen-git-sha",
        default="",
        help="Optional 2x2MCP-PythiaGen git SHA if known externally.",
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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_provenance(path: Path) -> Dict[str, object]:
    st = path.stat()
    return {
        "path": str(path.resolve()),
        "name": path.name,
        "size_bytes": st.st_size,
        "mtime_utc": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
        "sha256": sha256_file(path),
    }


def expand_inputs(items: Sequence[str]) -> List[Path]:
    found: List[Path] = []
    for text in items:
        p = Path(text).expanduser()
        if p.is_file():
            found.append(p)
        elif p.is_dir():
            found.extend(sorted(p.rglob("*.root")))
        else:
            found.extend(Path(x) for x in sorted(glob.glob(text, recursive=True)))
    unique: List[Path] = []
    seen = set()
    for p in found:
        if p.suffix.lower() != ".root" or not p.is_file():
            continue
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    if not unique:
        raise SystemExit("No ROOT input files found.")
    return unique


def br_per_epsilon2(pdg: int, mass_gev: float) -> float:
    _, typ, parent_mass, br_ref = PARENTS[pdg]
    if parent_mass <= 0.0 or 2.0 * mass_gev >= parent_mass:
        return 0.0
    r = (mass_gev / parent_mass) ** 2
    if typ == 0:
        phase_space = max(0.0, 1.0 - 4.0 * r) ** 3
    else:
        beta = math.sqrt(max(0.0, 1.0 - 4.0 * r))
        phase_space = beta * (1.0 + 2.0 * r)
    return ALPHA * br_ref * phase_space


def read_aggregate_summary(path: Path):
    rows: Dict[Tuple[float, int, int, int], Dict[str, str]] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            key = (
                round(float(row["mcp_mass_GeV"]), 12),
                int(row["emitter_pdg"]),
                int(row["production_mode"]),
                int(row["geometry_id"]),
            )
            rows[key] = row

    soft = [
        float(r.get("sigma_gen_mb_mean") or 0.0)
        for r in rows.values()
        if int(r["production_mode"]) == 0
        and float(r.get("sigma_gen_mb_mean") or 0.0) > 0.0
    ]
    charm = [
        float(r.get("sigma_gen_mb_mean") or 0.0)
        for r in rows.values()
        if int(r["production_mode"]) == 1
        and float(r.get("sigma_gen_mb_mean") or 0.0) > 0.0
    ]
    sigma_soft = sum(soft) / len(soft) if soft else 1.0
    sigma_charm = sum(charm) / len(charm) if charm else 0.0
    charm_scale = sigma_charm / sigma_soft if sigma_soft > 0.0 else 0.0
    return rows, sigma_soft, sigma_charm, charm_scale


def weighted_quantile_edges(
    values: np.ndarray, weights: np.ndarray, nbins: int
) -> np.ndarray:
    if nbins < 1:
        raise ValueError("Number of bins must be positive.")
    order = np.argsort(values)
    v = np.asarray(values[order], dtype=float)
    w = np.asarray(weights[order], dtype=float)
    positive = w > 0
    v, w = v[positive], w[positive]
    if len(v) < 2:
        center = float(v[0]) if len(v) else 0.0
        span = max(abs(center) * 1.0e-6, 1.0e-9)
        return np.array([center - span, center + span])

    cumulative = np.cumsum(w)
    cumulative /= cumulative[-1]
    q = np.linspace(0.0, 1.0, nbins + 1)
    edges = np.interp(q, cumulative, v)
    edges[0] = v[0]
    edges[-1] = v[-1]
    edges = np.unique(edges)

    if len(edges) < 2:
        center = float(v[0])
        span = max(abs(center) * 1.0e-6, 1.0e-9)
        edges = np.array([center - span, center + span])
    else:
        span = edges[-1] - edges[0]
        pad = max(span * 1.0e-9, 1.0e-12)
        edges[0] -= pad
        edges[-1] += pad
    return edges


def sample_component_hist(
    rng: np.random.Generator,
    hist: np.ndarray,
    e_edges: np.ndarray,
    tx_edges: np.ndarray,
    ty_edges: np.ndarray,
    n: int,
):
    flat = hist.ravel()
    total = flat.sum()
    if total <= 0.0:
        raise RuntimeError("Cannot sample a zero-integral histogram.")
    idx = rng.choice(flat.size, size=n, p=flat / total)
    ie, ix, iy = np.unravel_index(idx, hist.shape)
    loge = rng.uniform(e_edges[ie], e_edges[ie + 1])
    tx = rng.uniform(tx_edges[ix], tx_edges[ix + 1])
    ty = rng.uniform(ty_edges[iy], ty_edges[iy + 1])
    return np.power(10.0, loge), tx, ty


def save_component_table(path: Path, components: List[Dict[str, object]]) -> None:
    fields = [
        "component_index",
        "emitter_pdg",
        "emitter_name",
        "production_mode",
        "geometry_id",
        "n_events_generated",
        "n_mcp_total",
        "n_mcp_accepted_pythia",
        "n_spectra_rows",
        "spectra_prescale",
        "spectra_equivalent_mcp",
        "spectra_total_coverage",
        "process_scale",
        "br_per_epsilon2",
        "source_flux_per_pot_epsilon2",
        "pythia_accepted_flux_per_pot_epsilon2",
        "mixture_fraction_source",
        "histogram_pre_rescale_flux",
        "histogram_rescale_factor",
    ]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for c in components:
            w.writerow({k: c.get(k, "") for k in fields})


def make_overview_plot(out: Path, source_by_component, components):
    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    ax_e, ax_tx, ax_ty, ax_txty, ax_etx, ax_ety = axes.ravel()

    all_e, all_tx, all_ty, all_w = [], [], [], []
    for c, data in zip(components, source_by_component):
        label = str(c["emitter_name"])
        E, tx, ty, w = data
        all_e.append(E)
        all_tx.append(tx)
        all_ty.append(ty)
        all_w.append(w)
        ax_e.hist(E, bins=70, weights=w, histtype="step", label=label)
        ax_tx.hist(tx, bins=70, weights=w, histtype="step", label=label)
        ax_ty.hist(ty, bins=70, weights=w, histtype="step", label=label)

    E = np.concatenate(all_e)
    tx = np.concatenate(all_tx)
    ty = np.concatenate(all_ty)
    w = np.concatenate(all_w)

    ax_e.set_xlabel("MCP total energy [GeV]")
    ax_e.set_ylabel(r"Flux / POT / $\epsilon^2$")
    ax_e.set_yscale("log")
    ax_e.legend(fontsize=8)

    ax_tx.set_xlabel(r"$t_x=p_x/p_z$")
    ax_tx.set_ylabel(r"Flux / POT / $\epsilon^2$")
    ax_tx.set_yscale("log")

    ax_ty.set_xlabel(r"$t_y=p_y/p_z$")
    ax_ty.set_ylabel(r"Flux / POT / $\epsilon^2$")
    ax_ty.set_yscale("log")

    h = ax_txty.hist2d(tx, ty, bins=80, weights=w, norm=LogNorm())
    fig.colorbar(h[3], ax=ax_txty, label=r"Flux / POT / $\epsilon^2$")
    ax_txty.set_xlabel(r"$t_x$")
    ax_txty.set_ylabel(r"$t_y$")

    h = ax_etx.hist2d(E, tx, bins=80, weights=w, norm=LogNorm())
    fig.colorbar(h[3], ax=ax_etx, label=r"Flux / POT / $\epsilon^2$")
    ax_etx.set_xlabel("E [GeV]")
    ax_etx.set_ylabel(r"$t_x$")

    h = ax_ety.hist2d(E, ty, bins=80, weights=w, norm=LogNorm())
    fig.colorbar(h[3], ax=ax_ety, label=r"Flux / POT / $\epsilon^2$")
    ax_ety.set_xlabel("E [GeV]")
    ax_ety.set_ylabel(r"$t_y$")

    fig.suptitle("Physically normalized Pythia source flux model")
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def make_resampling_plot(out: Path, source_by_component, components, arrays, n_samples: int, seed: int):
    if n_samples <= 0:
        return
    rng = np.random.default_rng(seed)
    fractions = np.array([float(c["mixture_fraction_source"]) for c in components])
    counts = rng.multinomial(n_samples, fractions / fractions.sum())

    sample_E, sample_tx, sample_ty = [], [], []
    for i, count in enumerate(counts):
        if count <= 0:
            continue
        E, tx, ty = sample_component_hist(
            rng,
            arrays[f"c{i:03d}_hist"],
            arrays[f"c{i:03d}_logE_edges"],
            arrays[f"c{i:03d}_tx_edges"],
            arrays[f"c{i:03d}_ty_edges"],
            int(count),
        )
        sample_E.append(E)
        sample_tx.append(tx)
        sample_ty.append(ty)

    sample_E = np.concatenate(sample_E)
    sample_tx = np.concatenate(sample_tx)
    sample_ty = np.concatenate(sample_ty)

    src_E = np.concatenate([d[0] for d in source_by_component])
    src_tx = np.concatenate([d[1] for d in source_by_component])
    src_ty = np.concatenate([d[2] for d in source_by_component])
    src_w = np.concatenate([d[3] for d in source_by_component])
    src_w = src_w / src_w.sum()

    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    variables = [
        (src_E, sample_E, "E [GeV]"),
        (src_tx, sample_tx, r"$t_x$"),
        (src_ty, sample_ty, r"$t_y$"),
    ]
    for ax, (src, samp, label) in zip(axes[0], variables):
        lo = min(float(np.min(src)), float(np.min(samp)))
        hi = max(float(np.max(src)), float(np.max(samp)))
        bins = np.linspace(lo, hi, 80)
        ax.hist(src, bins=bins, weights=src_w, histtype="step", density=True, label="weighted Pythia")
        ax.hist(samp, bins=bins, histtype="step", density=True, label="resampled model")
        ax.set_xlabel(label)
        ax.set_ylabel("Probability density")
        ax.legend(fontsize=8)

    h = axes[1, 0].hist2d(src_tx, src_ty, bins=70, weights=src_w, norm=LogNorm())
    fig.colorbar(h[3], ax=axes[1, 0])
    axes[1, 0].set_title("Weighted Pythia")
    axes[1, 0].set_xlabel(r"$t_x$")
    axes[1, 0].set_ylabel(r"$t_y$")

    h = axes[1, 1].hist2d(sample_tx, sample_ty, bins=70, norm=LogNorm())
    fig.colorbar(h[3], ax=axes[1, 1])
    axes[1, 1].set_title("Resampled model")
    axes[1, 1].set_xlabel(r"$t_x$")
    axes[1, 1].set_ylabel(r"$t_y$")

    axes[1, 2].axis("off")
    lines = [f"validation draws: {n_samples:,}", f"seed: {seed}", "", "source emitter fractions:"]
    lines += [
        f"{c['emitter_name']}: {100.0*float(c['mixture_fraction_source']):.3f}%"
        for c in components
    ]
    axes[1, 2].text(0.0, 1.0, "\n".join(lines), va="top", family="monospace")

    fig.suptitle("Flux-model resampling validation")
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    if args.mass_gev <= 0.0:
        raise SystemExit("--mass-gev must be positive.")
    for name in ("energy_bins", "tx_bins", "ty_bins"):
        if getattr(args, name) < 1:
            raise SystemExit(f"--{name.replace('_', '-')} must be positive.")

    root_files = expand_inputs(args.inputs)
    if not args.summary.is_file():
        raise SystemExit(f"Summary CSV not found: {args.summary}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    plots_dir = args.output_dir / "plots"
    plots_dir.mkdir(exist_ok=True)

    summary, sigma_soft, sigma_charm, charm_scale = read_aggregate_summary(args.summary)
    mass_key = round(args.mass_gev, 12)

    selected_summary = {
        key: row
        for key, row in summary.items()
        if abs(key[0] - mass_key) <= args.mass_tol_gev
        and key[3] == args.geometry_id
        and key[1] in PARENTS
        and br_per_epsilon2(key[1], args.mass_gev) > 0.0
    }
    if not selected_summary:
        raise SystemExit(
            f"No kinematically open supported summary rows found at m_chi={args.mass_gev:g} GeV."
        )

    expected_open = {pdg for pdg in PARENTS if br_per_epsilon2(pdg, args.mass_gev) > 0.0}
    summary_emitters = {key[1] for key in selected_summary}
    missing_summary = sorted(expected_open - summary_emitters)
    if missing_summary and not args.allow_missing_emitters:
        names = [PARENTS[p][0] for p in missing_summary]
        raise SystemExit(
            "Aggregate summary is missing kinematically open emitters: "
            + ", ".join(names)
            + ". Pass --allow-missing-emitters only if this is intentional."
        )

    records = {key: {"E": [], "tx": [], "ty": [], "passed": []} for key in selected_summary}
    spectra_rows = defaultdict(int)

    ROOT.gROOT.SetBatch(True)
    for fn in root_files:
        f = ROOT.TFile.Open(str(fn), "READ")
        if not f or f.IsZombie():
            print(f"WARNING: could not open {fn}", file=sys.stderr)
            continue
        tree = f.Get("mcp_spectra")
        if not tree:
            f.Close()
            continue
        for row in tree:
            if abs(float(row.mcp_mass_GeV) - args.mass_gev) > args.mass_tol_gev:
                continue
            key = (mass_key, int(row.emitter_pdg), int(row.production_mode), int(row.geometry_id))
            if key not in records:
                continue
            pz = float(row.pz_GeV)
            E = float(row.E_GeV)
            if pz <= 0.0 or E <= args.mass_gev:
                continue
            records[key]["E"].append(E)
            records[key]["tx"].append(float(row.px_GeV) / pz)
            records[key]["ty"].append(float(row.py_GeV) / pz)
            records[key]["passed"].append(int(getattr(row, "passed_geometry", getattr(row, "accepted", 0))))
            spectra_rows[key] += 1
        f.Close()

    missing_spectra = [PARENTS[key[1]][0] for key in selected_summary if spectra_rows[key] == 0]
    if missing_spectra and not args.allow_missing_emitters:
        raise SystemExit(
            "No mcp_spectra rows found for open emitters: "
            + ", ".join(sorted(set(missing_spectra)))
        )

    arrays: Dict[str, np.ndarray] = {}
    components: List[Dict[str, object]] = []
    source_by_component = []

    for key in sorted(selected_summary, key=lambda k: k[1]):
        if spectra_rows[key] == 0:
            continue
        row = selected_summary[key]
        pdg, mode, geometry_id = key[1], key[2], key[3]
        emitter_name = PARENTS[pdg][0]
        nev = int(row["n_events_generated"])
        n_total = int(row["n_mcp_total"])
        n_acc = int(row["n_mcp_accepted"])
        prescale = int(row.get("spectra_prescale_max") or row.get("spectra_prescale") or 1)
        if nev <= 0 or n_total <= 0:
            print(f"WARNING: skipping zero-normalization component {emitter_name}", file=sys.stderr)
            continue

        process_scale = charm_scale if mode == 1 else 1.0
        br0 = br_per_epsilon2(pdg, args.mass_gev)
        expected_source_flux = process_scale * br0 * (n_total / nev)
        expected_accepted_flux = process_scale * br0 * (n_acc / nev)

        E = np.asarray(records[key]["E"], dtype=float)
        tx = np.asarray(records[key]["tx"], dtype=float)
        ty = np.asarray(records[key]["ty"], dtype=float)
        passed = np.asarray(records[key]["passed"], dtype=bool)

        # Reproduce the current 2x2MCP-PythiaGen toy-MC weighting convention,
        # with N_POT=1 and epsilon^2 divided out.
        row_weight = np.full(E.shape, process_scale * br0 * prescale / nev, dtype=float)
        equivalent_mcp = float(len(E) * prescale)
        coverage = equivalent_mcp / n_total if n_total else 0.0
        accepted_equivalent = float(np.count_nonzero(passed) * prescale)

        # Detect the common mistake of feeding accepted-only spectra into a
        # source-flux model. For realistic 2x2 acceptance this is usually obvious.
        looks_accepted_only = (
            n_acc > 0
            and n_total > 2 * n_acc
            and equivalent_mcp < 0.5 * n_total
            and 0.4 <= accepted_equivalent / n_acc <= 2.5
        )
        if looks_accepted_only and not args.allow_accepted_only_spectra:
            raise SystemExit(
                f"{emitter_name} spectra look accepted-only: {len(E)} stored rows "
                f"(prescale {prescale}) versus n_mcp_total={n_total}, "
                f"n_mcp_accepted={n_acc}. Use the unlimited/all-MCP Pythia spectrum "
                "for the source model."
            )

        logE = np.log10(E)
        e_edges = weighted_quantile_edges(logE, row_weight, args.energy_bins)
        tx_edges = weighted_quantile_edges(tx, row_weight, args.tx_bins)
        ty_edges = weighted_quantile_edges(ty, row_weight, args.ty_bins)

        hist, _ = np.histogramdd(
            np.column_stack([logE, tx, ty]),
            bins=(e_edges, tx_edges, ty_edges),
            weights=row_weight,
        )
        pre_scale_flux = float(hist.sum())
        if pre_scale_flux <= 0.0:
            raise SystemExit(f"Zero histogram integral for {emitter_name}.")
        scale = expected_source_flux / pre_scale_flux
        hist *= scale
        plot_w = row_weight * scale

        i = len(components)
        arrays[f"c{i:03d}_hist"] = hist.astype(np.float64)
        arrays[f"c{i:03d}_logE_edges"] = e_edges.astype(np.float64)
        arrays[f"c{i:03d}_tx_edges"] = tx_edges.astype(np.float64)
        arrays[f"c{i:03d}_ty_edges"] = ty_edges.astype(np.float64)

        accepted_row_flux = float(plot_w[passed].sum())
        component = {
            "component_index": i,
            "emitter_pdg": pdg,
            "emitter_name": emitter_name,
            "emitter_type": "pseudoscalar" if PARENTS[pdg][1] == 0 else "vector",
            "production_mode": mode,
            "production_mode_name": MODE_NAME.get(mode, str(mode)),
            "geometry_id": geometry_id,
            "n_events_generated": nev,
            "n_mcp_total": n_total,
            "n_mcp_accepted_pythia": n_acc,
            "n_spectra_rows": len(E),
            "spectra_prescale": prescale,
            "spectra_equivalent_mcp": equivalent_mcp,
            "spectra_total_coverage": coverage,
            "looks_accepted_only": bool(looks_accepted_only),
            "process_scale": process_scale,
            "br_per_epsilon2": br0,
            "source_flux_per_pot_epsilon2": expected_source_flux,
            "pythia_accepted_flux_per_pot_epsilon2": expected_accepted_flux,
            "weighted_spectra_accepted_flux_before_new_geometry": accepted_row_flux,
            "histogram_pre_rescale_flux": pre_scale_flux,
            "histogram_rescale_factor": scale,
            "mixture_fraction_source": 0.0,
        }
        components.append(component)
        source_by_component.append((E, tx, ty, plot_w))

    if not components:
        raise SystemExit("No flux components were built.")

    total_flux = sum(float(c["source_flux_per_pot_epsilon2"]) for c in components)
    if total_flux <= 0.0:
        raise SystemExit("Total source flux normalization is zero.")
    for c in components:
        c["mixture_fraction_source"] = float(c["source_flux_per_pot_epsilon2"]) / total_flux

    metadata = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "model_type": MODEL_TYPE,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "selected_mass_GeV": args.mass_gev,
        "selected_geometry_id": args.geometry_id,
        "normalization_basis": "per_POT_per_epsilon2",
        "normalization_reference": (
            "2x2MCP-PythiaGen aggregate summary + export_toymc_spectra.py convention"
        ),
        "normalization_constants": {
            "alpha": ALPHA,
            "parents": {
                str(pdg): {
                    "name": v[0],
                    "type": v[1],
                    "mass_GeV": v[2],
                    "reference_branching_normalization": v[3],
                }
                for pdg, v in PARENTS.items()
            },
            "sigma_softqcd_mb_mean": sigma_soft,
            "sigma_charmonium_mb_mean": sigma_charm,
            "charm_process_scale": charm_scale,
        },
        "variables": {
            "energy": "log10(total_energy_GeV)",
            "tx": "px/pz in Pythia beam frame",
            "ty": "py/pz in Pythia beam frame",
        },
        "histogram_binning": {
            "energy_quantile_bins_requested": args.energy_bins,
            "tx_quantile_bins_requested": args.tx_bins,
            "ty_quantile_bins_requested": args.ty_bins,
            "bin_sampling": "uniform_inside_selected_3d_bin",
        },
        "total_source_flux_per_pot_epsilon2": total_flux,
        "components": components,
        "source_files": [file_provenance(p) for p in root_files],
        "aggregate_summary_file": file_provenance(args.summary),
        "production_tag": args.production_tag,
        "pythia_gen_git_sha": args.pythia_gen_git_sha,
        "mcp_sim_git_sha": git_sha_here(),
        "assumptions": {
            "source_flux": "Pythia target-production spectrum before detector acceptance",
            "all_open_emitters_required_by_default": not args.allow_missing_emitters,
            "accepted_only_spectra_allowed": args.allow_accepted_only_spectra,
            "charge_dependence": (
                "Kinematic shape and emitter mixture are stored per epsilon^2; "
                "detector charge is applied later in EDepSim."
            ),
            "beamline_transport": (
                "Not applied while building the source model. The first sampler "
                "implementation uses explicit straight_line_v0 transport."
            ),
        },
    }

    arrays["metadata_json"] = np.asarray(json.dumps(metadata, sort_keys=True))
    model_path = args.output_dir / "flux_model.npz"
    np.savez_compressed(model_path, **arrays)

    provenance_path = args.output_dir / "provenance.json"
    provenance_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    save_component_table(args.output_dir / "component_normalization.csv", components)

    make_overview_plot(plots_dir / "flux_model_overview.png", source_by_component, components)
    make_resampling_plot(
        plots_dir / "flux_model_resampling_validation.png",
        source_by_component,
        components,
        arrays,
        args.validation_samples,
        args.validation_seed,
    )

    print(f"Built flux model: {model_path}")
    print(f"Selected mass: {args.mass_gev:g} GeV")
    print(f"Total source flux / POT / epsilon^2: {total_flux:.12g}")
    print("Emitter mixture:")
    for c in components:
        print(
            f"  {c['emitter_name']:>6s}: "
            f"{100.0*float(c['mixture_fraction_source']):9.5f}%  "
            f"flux={float(c['source_flux_per_pot_epsilon2']):.6g}"
        )
    print(f"Provenance: {provenance_path}")
    print(f"Plots: {plots_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
