#!/usr/bin/env python3
"""Shared implementation for realistic MCP flux-model building and sampling.

Two flux stages are supported:

* ``accepted`` (default for current detector studies): model the Pythia MCP
  spectrum *conditioned on the existing geometry_id acceptance*.  The physical
  normalization is taken from n_mcp_accepted, and the sampler does not apply a
  second rejection cut.  It only reports a geometry-consistency diagnostic.

* ``source`` (future beamline studies): model the pre-acceptance spectrum using
  n_mcp_total.  The sampler rotates into 2x2 coordinates, applies the explicit
  ``straight_line_v0`` beamline transport model, and then applies the local
  detector acceptance.

The non-parametric kinematic model is one weighted 3-D histogram per emitter in
(log10(E/GeV), theta_x, theta_y), where

    theta_x = atan2(px, pz)
    theta_y = atan2(py, pz)

in the Pythia beam frame.  These bounded angles replace the old px/pz and py/pz
variables, which become pathological for small positive pz.
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
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

ALPHA = 1.0 / 137.0
MODEL_SCHEMA_VERSION = 2
MODEL_TYPE = "weighted_histogram_logE_thetaX_thetaY_v2"
SAMPLER_SCHEMA_VERSION = 2
TRANSPORT_MODEL = "straight_line_v0"
EDEPSIM_MCP_PDG = 9000001
PYTHIA_MCP_ABS_PDG = 1000222

# Keep synchronized with 2x2MCP-PythiaGen/scripts/export_toymc_spectra.py.
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

# Current Pythia geometry_id=1 approximation, expressed as offsets from the
# beam axis at the detector plane.
X_RANGES_M = ((-0.65, -0.05), (0.05, 0.65))
Y_RANGE_M = (-0.70, 0.70)

# 2x2_sim uses beam_dir ~ [0, -0.05836, 1].  This corresponds to an active
# +x-axis rotation of a Pythia on-axis vector (0,0,+1) by about +3.34 degrees.
DEFAULT_BEAM_SLOPE_Y = -0.05836
DEFAULT_BASELINE_M = 1040.0
DEFAULT_BEAM_AXIS_AT_DETECTOR_M = (0.0, -0.42, 0.0)
DEFAULT_INJECTION_DISTANCE_M = 1.5


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_provenance(path: Path) -> Dict[str, object]:
    st = path.stat()
    return {
        "path": str(path.resolve()),
        "name": path.name,
        "size_bytes": int(st.st_size),
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
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
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


def process_scale(mode: int, charm_scale: float) -> float:
    return charm_scale if mode == 1 else 1.0


def stage_flux_from_summary(
    row: Dict[str, str], pdg: int, mode: int, mass_gev: float,
    charm_scale: float, stage: str,
) -> float:
    nev = int(row["n_events_generated"])
    if nev <= 0:
        return 0.0
    count = int(row["n_mcp_accepted"] if stage == "accepted" else row["n_mcp_total"])
    return process_scale(mode, charm_scale) * br_per_epsilon2(pdg, mass_gev) * count / nev


def weighted_quantile_edges(values: np.ndarray, weights: np.ndarray, nbins: int) -> np.ndarray:
    if nbins < 1:
        raise ValueError("Number of bins must be positive.")
    order = np.argsort(values)
    v = np.asarray(values[order], dtype=float)
    w = np.asarray(weights[order], dtype=float)
    mask = np.isfinite(v) & np.isfinite(w) & (w > 0.0)
    v, w = v[mask], w[mask]
    if len(v) == 0:
        raise ValueError("Cannot make bin edges from an empty weighted sample.")
    if len(v) == 1:
        span = max(abs(float(v[0])) * 1.0e-6, 1.0e-9)
        return np.array([v[0] - span, v[0] + span], dtype=float)
    cumulative = np.cumsum(w)
    cumulative /= cumulative[-1]
    q = np.linspace(0.0, 1.0, nbins + 1)
    edges = np.interp(q, cumulative, v)
    edges[0], edges[-1] = v[0], v[-1]
    edges = np.unique(edges)
    if len(edges) < 2:
        span = max(abs(float(v[0])) * 1.0e-6, 1.0e-9)
        return np.array([v[0] - span, v[0] + span], dtype=float)
    pad = max((edges[-1] - edges[0]) * 1.0e-9, 1.0e-12)
    edges[0] -= pad
    edges[-1] += pad
    return edges


def sample_component_hist(
    rng: np.random.Generator, hist: np.ndarray, e_edges: np.ndarray,
    thx_edges: np.ndarray, thy_edges: np.ndarray, n: int,
):
    flat = np.asarray(hist, dtype=float).ravel()
    total = float(flat.sum())
    if total <= 0.0:
        raise RuntimeError("Cannot sample a zero-integral histogram.")
    idx = rng.choice(flat.size, size=n, p=flat / total)
    ie, ix, iy = np.unravel_index(idx, hist.shape)
    loge = rng.uniform(e_edges[ie], e_edges[ie + 1])
    thx = rng.uniform(thx_edges[ix], thx_edges[ix + 1])
    thy = rng.uniform(thy_edges[iy], thy_edges[iy + 1])
    return np.power(10.0, loge), thx, thy


def _mpl():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import LogNorm
    except ImportError as exc:
        raise SystemExit("matplotlib is required for flux-model plots.") from exc
    return plt, LogNorm


def _safe_lognorm(values: np.ndarray, LogNorm):
    positive = values[np.isfinite(values) & (values > 0.0)]
    if len(positive) == 0:
        return None
    return LogNorm(vmin=max(float(np.min(positive)), float(np.max(positive)) * 1.0e-12),
                   vmax=float(np.max(positive)))


def make_overview_plot(out: Path, stage: str, source_by_component, components):
    plt, LogNorm = _mpl()
    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    ax_e, ax_thx, ax_thy, ax_xy, ax_ethx, ax_ethy = axes.ravel()

    all_e, all_thx, all_thy, all_w = [], [], [], []
    for c, data in zip(components, source_by_component):
        label = str(c["emitter_name"])
        E, thx, thy, w, _, _ = data
        all_e.append(E); all_thx.append(thx); all_thy.append(thy); all_w.append(w)
        ax_e.hist(E, bins=70, weights=w, histtype="step", label=label)
        ax_thx.hist(1e3 * thx, bins=70, weights=w, histtype="step", label=label)
        ax_thy.hist(1e3 * thy, bins=70, weights=w, histtype="step", label=label)

    E = np.concatenate(all_e); thx = np.concatenate(all_thx)
    thy = np.concatenate(all_thy); w = np.concatenate(all_w)

    ax_e.set_xscale("log"); ax_e.set_yscale("log")
    ax_e.set_xlabel("MCP total energy [GeV]")
    ax_e.set_ylabel(r"Flux / POT / $\epsilon^2$")
    ax_e.legend(fontsize=8)
    for ax, label in ((ax_thx, r"$\theta_x$ [mrad]"), (ax_thy, r"$\theta_y$ [mrad]")):
        ax.set_yscale("log"); ax.set_xlabel(label)
        ax.set_ylabel(r"Flux / POT / $\epsilon^2$")

    h = ax_xy.hist2d(1e3*thx, 1e3*thy, bins=80, weights=w, norm=LogNorm())
    fig.colorbar(h[3], ax=ax_xy, label=r"Flux / POT / $\epsilon^2$")
    ax_xy.set_xlabel(r"$\theta_x$ [mrad]"); ax_xy.set_ylabel(r"$\theta_y$ [mrad]")

    h = ax_ethx.hist2d(E, 1e3*thx, bins=80, weights=w, norm=LogNorm())
    fig.colorbar(h[3], ax=ax_ethx, label=r"Flux / POT / $\epsilon^2$")
    ax_ethx.set_xscale("log"); ax_ethx.set_xlabel("E [GeV]")
    ax_ethx.set_ylabel(r"$\theta_x$ [mrad]")

    h = ax_ethy.hist2d(E, 1e3*thy, bins=80, weights=w, norm=LogNorm())
    fig.colorbar(h[3], ax=ax_ethy, label=r"Flux / POT / $\epsilon^2$")
    ax_ethy.set_xscale("log"); ax_ethy.set_xlabel("E [GeV]")
    ax_ethy.set_ylabel(r"$\theta_y$ [mrad]")

    fig.suptitle(f"Physically normalized Pythia {stage} flux model")
    fig.tight_layout(); fig.savefig(out, dpi=160); plt.close(fig)


def make_projection_plot(out: Path, source_by_component, components):
    plt, LogNorm = _mpl()
    xs, ys, ws = [], [], []
    for _, data in zip(components, source_by_component):
        _, _, _, w, x, y = data
        if len(x):
            xs.append(x); ys.append(y); ws.append(w)
    if not xs:
        return
    x = np.concatenate(xs); y = np.concatenate(ys); w = np.concatenate(ws)
    fig, ax = plt.subplots(figsize=(7, 6))
    h = ax.hist2d(x, y, bins=100, weights=w, norm=LogNorm())
    fig.colorbar(h[3], ax=ax, label=r"Flux / POT / $\epsilon^2$")
    for lo, hi in X_RANGES_M:
        ax.plot([lo, hi, hi, lo, lo], [Y_RANGE_M[0], Y_RANGE_M[0], Y_RANGE_M[1], Y_RANGE_M[1], Y_RANGE_M[0]], "--", linewidth=1)
    ax.set_xlabel("Pythia x at detector plane [m]")
    ax.set_ylabel("Pythia y at detector plane [m]")
    ax.set_title("Stored Pythia detector-plane projection")
    fig.tight_layout(); fig.savefig(out, dpi=160); plt.close(fig)


def make_resampling_plot(out: Path, source_by_component, components, arrays, n_samples: int, seed: int):
    if n_samples <= 0:
        return
    plt, LogNorm = _mpl()
    rng = np.random.default_rng(seed)
    fractions = np.array([float(c["mixture_fraction"]) for c in components], dtype=float)
    counts = rng.multinomial(n_samples, fractions / fractions.sum())
    se, sx, sy = [], [], []
    for i, count in enumerate(counts):
        if count <= 0:
            continue
        E, thx, thy = sample_component_hist(
            rng, arrays[f"c{i:03d}_hist"], arrays[f"c{i:03d}_logE_edges"],
            arrays[f"c{i:03d}_theta_x_edges"], arrays[f"c{i:03d}_theta_y_edges"], int(count)
        )
        se.append(E); sx.append(thx); sy.append(thy)
    sample_E = np.concatenate(se); sample_thx = np.concatenate(sx); sample_thy = np.concatenate(sy)

    src_E = np.concatenate([d[0] for d in source_by_component])
    src_thx = np.concatenate([d[1] for d in source_by_component])
    src_thy = np.concatenate([d[2] for d in source_by_component])
    src_w = np.concatenate([d[3] for d in source_by_component])
    src_w = src_w / src_w.sum()

    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    variables = [
        (src_E, sample_E, "E [GeV]", True, 1.0),
        (src_thx, sample_thx, r"$\theta_x$ [mrad]", False, 1e3),
        (src_thy, sample_thy, r"$\theta_y$ [mrad]", False, 1e3),
    ]
    for ax, (src, samp, label, logx, scale) in zip(axes[0], variables):
        a = src * scale; b = samp * scale
        if logx:
            lo = max(min(float(np.min(a)), float(np.min(b))), 1e-12)
            hi = max(float(np.max(a)), float(np.max(b)))
            bins = np.geomspace(lo, hi, 80)
            ax.set_xscale("log")
        else:
            lo = min(float(np.min(a)), float(np.min(b))); hi = max(float(np.max(a)), float(np.max(b)))
            bins = np.linspace(lo, hi, 80)
        ax.hist(a, bins=bins, weights=src_w, histtype="step", density=True, label="weighted Pythia")
        ax.hist(b, bins=bins, histtype="step", density=True, label="resampled model")
        ax.set_yscale("log"); ax.set_xlabel(label); ax.set_ylabel("Probability density")
        ax.legend(fontsize=8)

    h = axes[1, 0].hist2d(1e3*src_thx, 1e3*src_thy, bins=80, weights=src_w, norm=LogNorm())
    fig.colorbar(h[3], ax=axes[1, 0]); axes[1, 0].set_title("Weighted Pythia")
    axes[1, 0].set_xlabel(r"$\theta_x$ [mrad]"); axes[1, 0].set_ylabel(r"$\theta_y$ [mrad]")
    h = axes[1, 1].hist2d(1e3*sample_thx, 1e3*sample_thy, bins=80, norm=LogNorm())
    fig.colorbar(h[3], ax=axes[1, 1]); axes[1, 1].set_title("Resampled model")
    axes[1, 1].set_xlabel(r"$\theta_x$ [mrad]"); axes[1, 1].set_ylabel(r"$\theta_y$ [mrad]")

    axes[1, 2].axis("off")
    lines = [f"validation draws: {n_samples:,}", f"seed: {seed}", "", "emitter fractions:"]
    lines += [f"{c['emitter_name']}: {100*float(c['mixture_fraction']):.3f}%" for c in components]
    axes[1, 2].text(0, 1, "\n".join(lines), va="top", family="monospace")
    fig.suptitle("Flux-model resampling validation")
    fig.tight_layout(); fig.savefig(out, dpi=160); plt.close(fig)


def write_mass_scan(summary, charm_scale: float, geometry_id: int, outdir: Path) -> None:
    rows_out = []
    grouped: Dict[float, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for key, row in summary.items():
        mass, pdg, mode, geom = key
        if geom != geometry_id or pdg not in PARENTS:
            continue
        br0 = br_per_epsilon2(pdg, mass)
        if br0 <= 0.0:
            continue
        nev = int(row["n_events_generated"])
        if nev <= 0:
            continue
        scale = process_scale(mode, charm_scale)
        source = scale * br0 * int(row["n_mcp_total"]) / nev
        accepted = scale * br0 * int(row["n_mcp_accepted"]) / nev
        name = PARENTS[pdg][0]
        acc = accepted / source if source > 0 else 0.0
        rows_out.append({
            "mcp_mass_GeV": mass, "emitter_pdg": pdg, "emitter_name": name,
            "production_mode": MODE_NAME.get(mode, str(mode)),
            "source_flux_per_pot_epsilon2": source,
            "accepted_flux_per_pot_epsilon2": accepted,
            "effective_acceptance": acc,
        })
        grouped[mass][f"source_{name}"] += source
        grouped[mass][f"accepted_{name}"] += accepted
        grouped[mass]["source_total"] += source
        grouped[mass]["accepted_total"] += accepted

    csv_path = outdir / "flux_vs_mass.csv"
    fields = ["mcp_mass_GeV", "emitter_pdg", "emitter_name", "production_mode",
              "source_flux_per_pot_epsilon2", "accepted_flux_per_pot_epsilon2", "effective_acceptance"]
    with csv_path.open("w", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=fields); w.writeheader(); w.writerows(sorted(rows_out, key=lambda r:(r["mcp_mass_GeV"], r["emitter_pdg"])))

    if not grouped:
        return
    plt, _ = _mpl()
    masses = np.array(sorted(grouped), dtype=float)
    fig, axes = plt.subplots(3, 1, figsize=(9, 12), sharex=True)
    for pdg, (name, _, _, _) in PARENTS.items():
        src = np.array([grouped[m].get(f"source_{name}", 0.0) for m in masses])
        acc = np.array([grouped[m].get(f"accepted_{name}", 0.0) for m in masses])
        mask = src > 0
        if np.any(mask): axes[0].plot(masses[mask], src[mask], marker=".", linewidth=1, label=name)
        mask = acc > 0
        if np.any(mask): axes[1].plot(masses[mask], acc[mask], marker=".", linewidth=1, label=name)
    st = np.array([grouped[m]["source_total"] for m in masses])
    at = np.array([grouped[m]["accepted_total"] for m in masses])
    axes[0].plot(masses, st, linewidth=2.0, label="total")
    axes[1].plot(masses, at, linewidth=2.0, label="total")
    eff = np.divide(at, st, out=np.zeros_like(at), where=st>0)
    axes[2].plot(masses[eff>0], eff[eff>0], marker=".")
    for ax in axes:
        ax.set_xscale("log"); ax.grid(alpha=0.2)
    axes[0].set_yscale("log"); axes[1].set_yscale("log"); axes[2].set_yscale("log")
    axes[0].set_ylabel(r"Source flux / POT / $\epsilon^2$")
    axes[1].set_ylabel(r"Accepted flux / POT / $\epsilon^2$")
    axes[2].set_ylabel("Physically weighted acceptance"); axes[2].set_xlabel(r"$m_\chi$ [GeV]")
    axes[0].legend(ncol=4, fontsize=8); axes[1].legend(ncol=4, fontsize=8)
    fig.suptitle("MCP flux normalization versus mass")
    fig.tight_layout(); fig.savefig(outdir / "flux_vs_mass.png", dpi=170); plt.close(fig)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build a reusable multi-emitter MCP flux model.")
    p.add_argument("inputs", nargs="+", help="Pythia ROOT files/directories/globs containing mcp_spectra.")
    p.add_argument("--summary", required=True, type=Path, help="Aggregate summary CSV from 2x2MCP-PythiaGen.")
    p.add_argument("--mass-gev", required=True, type=float)
    p.add_argument("--geometry-id", type=int, default=1)
    p.add_argument("--flux-stage", choices=("accepted", "source"), default="accepted",
                   help="accepted: model post-geometry flux (current default); source: pre-acceptance flux.")
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--energy-bins", type=int, default=24)
    p.add_argument("--theta-x-bins", type=int, default=28)
    p.add_argument("--theta-y-bins", type=int, default=28)
    p.add_argument("--mass-tol-gev", type=float, default=1e-8)
    p.add_argument("--validation-samples", type=int, default=200000)
    p.add_argument("--validation-seed", type=int, default=12345)
    p.add_argument("--allow-missing-emitters", action="store_true")
    p.add_argument("--allow-accepted-only-spectra", action="store_true",
                   help="Only meaningful with --flux-stage source; permits a known-biased source model.")
    p.add_argument("--production-tag", default="")
    p.add_argument("--pythia-gen-git-sha", default="")
    return p


def build_main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mass_gev <= 0.0:
        raise SystemExit("--mass-gev must be positive.")
    root_files = expand_inputs(args.inputs)
    if not args.summary.is_file():
        raise SystemExit(f"Summary CSV not found: {args.summary}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plots_dir = args.output_dir / "plots"; plots_dir.mkdir(exist_ok=True)

    summary, sigma_soft, sigma_charm, charm_scale = read_aggregate_summary(args.summary)
    write_mass_scan(summary, charm_scale, args.geometry_id, plots_dir)
    mass_key = round(args.mass_gev, 12)
    selected_summary = {
        key: row for key, row in summary.items()
        if abs(key[0] - mass_key) <= args.mass_tol_gev and key[3] == args.geometry_id
        and key[1] in PARENTS and br_per_epsilon2(key[1], args.mass_gev) > 0.0
    }
    if not selected_summary:
        raise SystemExit(f"No open supported summary rows at m_chi={args.mass_gev:g} GeV.")
    expected_open = {pdg for pdg in PARENTS if br_per_epsilon2(pdg, args.mass_gev) > 0.0}
    missing = expected_open - {k[1] for k in selected_summary}
    if missing and not args.allow_missing_emitters:
        raise SystemExit("Aggregate summary missing open emitters: " + ", ".join(PARENTS[p][0] for p in sorted(missing)))

    try:
        import ROOT
    except ImportError as exc:
        raise SystemExit("PyROOT is required to build a flux model.") from exc
    ROOT.gROOT.SetBatch(True)

    # Each stored spectrum row carries a shape weight equal to its file-local
    # spectra_prescale.  Absolute normalization is imposed from aggregate summary.
    records = {key: {"E": [], "thx": [], "thy": [], "xdet": [], "ydet": [], "shape_w": [], "passed_all": [], "n_all": 0} for key in selected_summary}
    input_files_used = set()
    for fn in root_files:
        f = ROOT.TFile.Open(str(fn), "READ")
        if not f or f.IsZombie():
            print(f"WARNING: could not open {fn}", file=sys.stderr); continue
        local_prescale: Dict[Tuple[float,int,int,int], int] = {}
        tsum = f.Get("mcp_summary")
        if tsum:
            for srow in tsum:
                key = (round(float(srow.mcp_mass_GeV),12), int(srow.emitter_pdg), int(srow.production_mode), int(srow.geometry_id))
                if key in records:
                    local_prescale[key] = int(getattr(srow, "spectra_prescale", 1))
        tree = f.Get("mcp_spectra")
        if not tree:
            f.Close(); continue
        file_used = False
        for row in tree:
            if abs(float(row.mcp_mass_GeV) - args.mass_gev) > args.mass_tol_gev:
                continue
            key = (mass_key, int(row.emitter_pdg), int(row.production_mode), int(row.geometry_id))
            if key not in records:
                continue
            rec = records[key]; rec["n_all"] += 1
            passed = bool(int(getattr(row, "passed_geometry", getattr(row, "accepted", 0))))
            rec["passed_all"].append(passed)
            if args.flux_stage == "accepted" and not passed:
                continue
            pz = float(row.pz_GeV); E = float(row.E_GeV)
            if pz <= 0.0 or E <= args.mass_gev:
                continue
            rec["E"].append(E)
            rec["thx"].append(math.atan2(float(row.px_GeV), pz))
            rec["thy"].append(math.atan2(float(row.py_GeV), pz))
            rec["xdet"].append(float(getattr(row, "x_at_detector_m", math.nan)))
            rec["ydet"].append(float(getattr(row, "y_at_detector_m", math.nan)))
            rec["shape_w"].append(float(local_prescale.get(key, int(selected_summary[key].get("spectra_prescale_max") or 1))))
            file_used = True
        if file_used: input_files_used.add(str(fn.resolve()))
        f.Close()

    components: List[Dict[str, object]] = []
    arrays: Dict[str, np.ndarray] = {}
    source_by_component = []
    for key in sorted(selected_summary, key=lambda k:k[1]):
        row = selected_summary[key]; pdg, mode, geom = key[1], key[2], key[3]
        name = PARENTS[pdg][0]; rec = records[key]
        if len(rec["E"]) == 0:
            if not args.allow_missing_emitters:
                raise SystemExit(f"No usable {args.flux_stage} spectrum rows for open emitter {name}.")
            continue
        nev = int(row["n_events_generated"]); ntot = int(row["n_mcp_total"]); nacc = int(row["n_mcp_accepted"])
        stage_target = nacc if args.flux_stage == "accepted" else ntot
        E = np.asarray(rec["E"], float); thx = np.asarray(rec["thx"], float); thy = np.asarray(rec["thy"], float)
        xdet = np.asarray(rec["xdet"], float); ydet = np.asarray(rec["ydet"], float); shape_w = np.asarray(rec["shape_w"], float)
        equiv = float(shape_w.sum()); coverage = equiv / stage_target if stage_target else 0.0

        if args.flux_stage == "source":
            all_passed = bool(rec["passed_all"]) and all(rec["passed_all"])
            looks_accepted_only = all_passed and nacc > 0 and ntot > 2*nacc and equiv < 0.7*ntot
            if looks_accepted_only and not args.allow_accepted_only_spectra:
                raise SystemExit(f"{name} looks accepted-only but --flux-stage source was requested. Use --flux-stage accepted or a full pre-acceptance spectrum.")

        flux = stage_flux_from_summary(row, pdg, mode, args.mass_gev, charm_scale, args.flux_stage)
        if flux <= 0.0:
            continue
        physical_row_w = shape_w * (flux / shape_w.sum())
        logE = np.log10(E)
        e_edges = weighted_quantile_edges(logE, physical_row_w, args.energy_bins)
        x_edges = weighted_quantile_edges(thx, physical_row_w, args.theta_x_bins)
        y_edges = weighted_quantile_edges(thy, physical_row_w, args.theta_y_bins)
        hist, _ = np.histogramdd(np.column_stack([logE, thx, thy]), bins=(e_edges, x_edges, y_edges), weights=physical_row_w)
        if hist.sum() <= 0.0:
            raise SystemExit(f"Zero histogram integral for {name}.")
        hist *= flux / hist.sum()
        idx = len(components)
        arrays[f"c{idx:03d}_hist"] = hist
        arrays[f"c{idx:03d}_logE_edges"] = e_edges
        arrays[f"c{idx:03d}_theta_x_edges"] = x_edges
        arrays[f"c{idx:03d}_theta_y_edges"] = y_edges
        c = {
            "component_index": idx, "emitter_pdg": pdg, "emitter_name": name,
            "production_mode": mode, "production_mode_name": MODE_NAME.get(mode,str(mode)),
            "geometry_id": geom, "n_events_generated": nev, "n_mcp_total": ntot,
            "n_mcp_accepted_pythia": nacc, "flux_stage": args.flux_stage,
            "stage_target_mcp": stage_target, "n_spectra_rows_used": len(E),
            "spectra_equivalent_mcp": equiv, "spectra_stage_coverage": coverage,
            "process_scale": process_scale(mode, charm_scale),
            "br_per_epsilon2": br_per_epsilon2(pdg, args.mass_gev),
            "stage_flux_per_pot_epsilon2": flux,
        }
        components.append(c)
        source_by_component.append((E, thx, thy, physical_row_w, xdet, ydet))

    total_flux = sum(float(c["stage_flux_per_pot_epsilon2"]) for c in components)
    if total_flux <= 0.0:
        raise SystemExit("Total model flux is zero.")
    for c in components:
        c["mixture_fraction"] = float(c["stage_flux_per_pot_epsilon2"]) / total_flux

    # Save component table.
    table_fields = ["component_index","emitter_pdg","emitter_name","production_mode_name","flux_stage",
                    "n_events_generated","n_mcp_total","n_mcp_accepted_pythia","stage_target_mcp",
                    "n_spectra_rows_used","spectra_equivalent_mcp","spectra_stage_coverage","process_scale",
                    "br_per_epsilon2","stage_flux_per_pot_epsilon2","mixture_fraction"]
    with (args.output_dir/"component_normalization.csv").open("w",newline="") as handle:
        w=csv.DictWriter(handle,fieldnames=table_fields); w.writeheader();
        for c in components: w.writerow({k:c.get(k,"") for k in table_fields})

    make_overview_plot(plots_dir/"flux_model_overview.png", args.flux_stage, source_by_component, components)
    make_resampling_plot(plots_dir/"flux_model_resampling_validation.png", source_by_component, components, arrays, args.validation_samples, args.validation_seed)
    make_projection_plot(plots_dir/"pythia_detector_projection.png", source_by_component, components)

    provenance = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "model_type": MODEL_TYPE,
        "created_utc": utc_now(),
        "flux_stage": args.flux_stage,
        "flux_stage_description": (
            "post_geometric_acceptance; normalized with n_mcp_accepted; no second acceptance cut is part of model building"
            if args.flux_stage == "accepted" else
            "pre_acceptance source flux; normalized with n_mcp_total; acceptance is applied only after beamline transport"
        ),
        "selected_mass_GeV": args.mass_gev,
        "geometry_id": args.geometry_id,
        "normalization_units": "MCP / POT / epsilon^2",
        "total_stage_flux_per_pot_epsilon2": total_flux,
        "normalization_convention": "matches 2x2MCP-PythiaGen export_toymc_spectra.py with N_POT=1 and epsilon^2 divided out",
        "sigma_softqcd_mb_mean": sigma_soft,
        "sigma_charmonium_mb_mean": sigma_charm,
        "charmonium_process_scale": charm_scale,
        "kinematic_coordinates": {"energy":"total E [GeV]", "theta_x":"atan2(px,pz) [rad]", "theta_y":"atan2(py,pz) [rad]", "frame":"Pythia beam frame"},
        "beamline_transport_assumption": {
            "model": TRANSPORT_MODEL,
            "energy_loss": False, "multiple_scattering": False,
            "magnetic_deflection": False, "attenuation": False,
            "material_interactions": False,
            "note": "Recorded now even for accepted-stage models so the conditioning assumption is explicit. Future nontrivial transport requires a pre-acceptance source model."
        },
        "acceptance_conditioning": ({"stage":"already accepted by 2x2MCP-PythiaGen", "geometry_id":args.geometry_id} if args.flux_stage=="accepted" else {"stage":"none in training spectrum"}),
        "histogram_bins_requested": {"logE":args.energy_bins, "theta_x":args.theta_x_bins, "theta_y":args.theta_y_bins},
        "production_tag": args.production_tag,
        "pythia_gen_git_sha": args.pythia_gen_git_sha,
        "mcp_sim_git_sha": git_sha_here(),
        "summary_file": file_provenance(args.summary),
        "source_root_files": [file_provenance(Path(p)) for p in sorted(input_files_used)],
        "components": components,
        "mass_scan_outputs": {"csv":str((plots_dir/"flux_vs_mass.csv").resolve()), "plot":str((plots_dir/"flux_vs_mass.png").resolve())},
    }
    arrays["metadata_json"] = np.array(json.dumps(provenance, sort_keys=True))
    arrays["component_pdg"] = np.array([int(c["emitter_pdg"]) for c in components], dtype=np.int32)
    arrays["component_flux"] = np.array([float(c["stage_flux_per_pot_epsilon2"]) for c in components], dtype=float)
    arrays["component_fraction"] = np.array([float(c["mixture_fraction"]) for c in components], dtype=float)
    arrays["mcp_mass_GeV"] = np.array(args.mass_gev, dtype=float)
    np.savez_compressed(args.output_dir/"flux_model.npz", **arrays)
    (args.output_dir/"provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True)+"\n")

    print(f"Built {args.flux_stage} flux model: {args.output_dir/'flux_model.npz'}")
    print(f"Selected mass: {args.mass_gev:g} GeV")
    print(f"Total {args.flux_stage} flux / POT / epsilon^2: {total_flux:.12g}")
    print("Emitter mixture:")
    for c in components:
        print(f"  {c['emitter_name']:>6s}: {100*float(c['mixture_fraction']):9.5f}%  flux={float(c['stage_flux_per_pot_epsilon2']):.6g}  rows={int(c['n_spectra_rows_used'])}")
    print(f"Provenance: {args.output_dir/'provenance.json'}")
    print(f"Plots: {plots_dir}")
    return 0


def rotate_pythia_to_2x2(v: np.ndarray, beam_slope_y: float) -> np.ndarray:
    # Active Rx(alpha), alpha chosen so (0,0,1) -> (0, beam_slope_y, 1) normalized.
    alpha = math.atan2(-beam_slope_y, 1.0)
    c, s = math.cos(alpha), math.sin(alpha)
    out = np.empty_like(v, dtype=float)
    out[...,0] = v[...,0]
    out[...,1] = c*v[...,1] - s*v[...,2]
    out[...,2] = s*v[...,1] + c*v[...,2]
    return out


def acceptance_mask(hit: np.ndarray, beam_axis_at_detector: np.ndarray) -> np.ndarray:
    x = hit[:,0] - beam_axis_at_detector[0]
    y = hit[:,1] - beam_axis_at_detector[1]
    in_x = ((x>=X_RANGES_M[0][0])&(x<=X_RANGES_M[0][1])) | ((x>=X_RANGES_M[1][0])&(x<=X_RANGES_M[1][1]))
    in_y = (y>=Y_RANGE_M[0])&(y<=Y_RANGE_M[1])
    return in_x & in_y


def load_model(path: Path):
    data = np.load(path, allow_pickle=False)
    meta = json.loads(str(data["metadata_json"].item()))
    return data, meta


def draw_model(rng, data, meta, n: int):
    comps = meta["components"]
    fractions = np.array([float(c["mixture_fraction"]) for c in comps], float)
    which = rng.choice(len(comps), size=n, p=fractions/fractions.sum())
    E = np.empty(n); thx=np.empty(n); thy=np.empty(n)
    for i in range(len(comps)):
        idx=np.flatnonzero(which==i)
        if len(idx)==0: continue
        a,b,c = sample_component_hist(rng, data[f"c{i:03d}_hist"], data[f"c{i:03d}_logE_edges"], data[f"c{i:03d}_theta_x_edges"], data[f"c{i:03d}_theta_y_edges"], len(idx))
        E[idx]=a; thx[idx]=b; thy[idx]=c
    return which,E,thx,thy


def kinematics_from_angles(E, thx, thy, mass):
    tx=np.tan(thx); ty=np.tan(thy)
    denom=np.sqrt(1.0+tx*tx+ty*ty)
    direction=np.column_stack([tx/denom,ty/denom,1.0/denom])
    p=np.sqrt(np.maximum(E*E-mass*mass,0.0))
    return direction*p[:,None], direction


def line_at_z(origin: np.ndarray, direction: np.ndarray, zplane: float):
    s=(zplane-origin[2])/direction[:,2]
    return origin[None,:]+s[:,None]*direction, s


def sampler_parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description="Sample an MCP flux model and prepare EDepSim HEPEVT input.")
    p.add_argument("model",type=Path); p.add_argument("output_prefix",type=Path)
    g=p.add_mutually_exclusive_group()
    g.add_argument("--n-events",type=int,help="Accepted-stage: number of conditioned events to write.")
    g.add_argument("--n-accepted",type=int,help="Accepted-stage alias; source-stage: sample until this many pass acceptance.")
    g.add_argument("--n-source",type=int,help="Source-stage only: throw exactly this many source MCPs.")
    p.add_argument("--seed",type=int,default=12345)
    p.add_argument("--baseline-m",type=float,default=DEFAULT_BASELINE_M)
    p.add_argument("--beam-slope-y",type=float,default=DEFAULT_BEAM_SLOPE_Y)
    p.add_argument("--beam-axis-x-m",type=float,default=DEFAULT_BEAM_AXIS_AT_DETECTOR_M[0])
    p.add_argument("--beam-axis-y-m",type=float,default=DEFAULT_BEAM_AXIS_AT_DETECTOR_M[1])
    p.add_argument("--detector-z-m",type=float,default=DEFAULT_BEAM_AXIS_AT_DETECTOR_M[2])
    p.add_argument("--injection-distance-m",type=float,default=DEFAULT_INJECTION_DISTANCE_M,
                   help="Global-z distance upstream of detector plane used for the local EDepSim injection plane.")
    p.add_argument("--time-ns",type=float,default=0.0)
    p.add_argument("--allow-low-mass",action="store_true",help="Allow <=10 MeV output even though current EDepSim MCP transport rejects it.")
    return p


def make_sample_plot(path: Path, rows: List[Dict[str, object]], meta):
    if not rows: return
    plt,_=_mpl()
    E=np.array([r["E_GeV"] for r in rows]); thx=np.array([r["theta_x_pythia_rad"] for r in rows]); thy=np.array([r["theta_y_pythia_rad"] for r in rows])
    hx=np.array([r["x_hit_rel_beam_m"] for r in rows]); hy=np.array([r["y_hit_rel_beam_m"] for r in rows]); emit=np.array([r["emitter_name"] for r in rows])
    fig,axes=plt.subplots(2,2,figsize=(12,9))
    axes[0,0].hist(E,bins=60,histtype="step"); axes[0,0].set_xscale("log"); axes[0,0].set_yscale("log"); axes[0,0].set_xlabel("E [GeV]")
    axes[0,1].hist(1e3*thx,bins=60,histtype="step",label="theta_x"); axes[0,1].hist(1e3*thy,bins=60,histtype="step",label="theta_y"); axes[0,1].set_yscale("log"); axes[0,1].set_xlabel("angle [mrad]"); axes[0,1].legend()
    axes[1,0].scatter(hx,hy,s=4,alpha=0.5); axes[1,0].set_xlabel("x relative to beam axis [m]"); axes[1,0].set_ylabel("y relative to beam axis [m]")
    names=[c["emitter_name"] for c in meta["components"]]; counts=[np.count_nonzero(emit==n) for n in names]
    axes[1,1].bar(names,counts); axes[1,1].set_yscale("log"); axes[1,1].set_ylabel("written events")
    fig.suptitle(f"Sampled MCP flux ({meta['flux_stage']} model)"); fig.tight_layout(); fig.savefig(path,dpi=160); plt.close(fig)


def sampler_main(argv: Sequence[str] | None = None) -> int:
    args=sampler_parser().parse_args(argv)
    if not args.model.is_file(): raise SystemExit(f"Model not found: {args.model}")
    data,meta=load_model(args.model); stage=meta["flux_stage"]; mass=float(meta["selected_mass_GeV"])
    if mass<=0.010 and not args.allow_low_mass:
        raise SystemExit(f"Model mass {mass:g} GeV is <=10 MeV; current EDepSim G4hIonisation MCP requires >10 MeV. Choose the next mass point or pass --allow-low-mass for non-EDepSim diagnostics only.")
    if args.baseline_m<=0 or args.injection_distance_m<=0: raise SystemExit("baseline and injection distance must be positive")
    if stage=="accepted":
        if args.n_source is not None: raise SystemExit("--n-source is only valid for a source-stage model.")
        target_n=args.n_events if args.n_events is not None else (args.n_accepted if args.n_accepted is not None else 100)
    else:
        if args.n_events is not None: raise SystemExit("For source-stage models use --n-source or --n-accepted.")
        target_n=args.n_accepted if args.n_accepted is not None else None
        fixed_source=args.n_source if args.n_source is not None else None
        if target_n is None and fixed_source is None: target_n=100

    rng=np.random.default_rng(args.seed)
    beam_axis=np.array([args.beam_axis_x_m,args.beam_axis_y_m,args.detector_z_m],float)
    onaxis=rotate_pythia_to_2x2(np.array([[0.,0.,1.]]),args.beam_slope_y)[0]
    onaxis/=np.linalg.norm(onaxis)
    target=beam_axis-args.baseline_m*onaxis
    inj_z=args.detector_z_m-args.injection_distance_m

    accepted_chunks=[]; source_trials=0
    def process_batch(n):
        nonlocal source_trials
        which,E,thx,thy=draw_model(rng,data,meta,n); source_trials+=n
        p_b,dir_b=kinematics_from_angles(E,thx,thy,mass)
        p_g=rotate_pythia_to_2x2(p_b,args.beam_slope_y); dir_g=rotate_pythia_to_2x2(dir_b,args.beam_slope_y)
        hit,sdet=line_at_z(target,dir_g,args.detector_z_m)
        geom=(sdet>0)&acceptance_mask(hit,beam_axis)
        inj,sinj=line_at_z(target,dir_g,inj_z)
        valid=(sinj>0)&np.isfinite(inj).all(axis=1)&np.isfinite(hit).all(axis=1)
        if stage=="source": keep=geom&valid
        else: keep=valid  # conditioned sample: do not reject again
        return {"which":which[keep],"E":E[keep],"thx":thx[keep],"thy":thy[keep],"p_b":p_b[keep],"p_g":p_g[keep],"hit":hit[keep],"inj":inj[keep],"geom":geom[keep]}

    if stage=="accepted":
        accepted_chunks=[process_batch(target_n)]
    elif fixed_source is not None:
        accepted_chunks=[process_batch(fixed_source)]
    else:
        have=0
        while have<target_n:
            remaining=target_n-have
            batch=max(10000,min(500000,remaining*5000))
            chunk=process_batch(batch)
            if len(chunk["E"]):
                take=min(len(chunk["E"]),remaining)
                chunk={k:v[:take] for k,v in chunk.items()}; accepted_chunks.append(chunk); have+=take
            if source_trials>100_000_000 and have==0:
                raise SystemExit("No accepted trajectories after 100 million source throws; check coordinates/acceptance.")

    keys=accepted_chunks[0].keys() if accepted_chunks else []
    accepted={k:np.concatenate([c[k] for c in accepted_chunks]) for k in keys}
    n_written=len(accepted.get("E",[]))
    if n_written==0: raise SystemExit("No events written.")
    total_stage_flux=float(meta["total_stage_flux_per_pot_epsilon2"])
    if stage=="accepted":
        event_weight=total_stage_flux/n_written
        accepted_flux_est=total_stage_flux
        geometry_consistency=float(np.mean(accepted["geom"]))
    else:
        event_weight=total_stage_flux/source_trials
        accepted_flux_est=event_weight*n_written
        geometry_consistency=1.0

    prefix=args.output_prefix; prefix.parent.mkdir(parents=True,exist_ok=True)
    hepevt=prefix.with_suffix(".hepevt"); manifest=prefix.with_suffix(".manifest.csv"); summary_path=prefix.with_suffix(".summary.json"); macro=prefix.with_suffix(".mac"); plot=prefix.with_suffix(".sampled_flux.png")
    components=meta["components"]
    rows=[]
    with hepevt.open("w") as hout:
        for i in range(n_written):
            ci=int(accepted["which"][i]); comp=components[ci]
            src_sign=PYTHIA_MCP_ABS_PDG if rng.random()<0.5 else -PYTHIA_MCP_ABS_PDG
            x,y,z=accepted["inj"][i]; px,py,pz=accepted["p_g"][i]
            E=float(accepted["E"][i]); hit=accepted["hit"][i]
            hout.write(f"1 {100*x:.12g} {100*y:.12g} {100*z:.12g} {args.time_ns:.12g}\n")
            hout.write(f"1 {EDEPSIM_MCP_PDG} 0 0 0 0 {px:.12g} {py:.12g} {pz:.12g} {E:.12g} {mass:.12g}\n")
            rows.append({
                "edepsim_event_id":i,"source_trial_index":i if stage=="accepted" else "", "component_index":ci,
                "emitter_pdg":int(comp["emitter_pdg"]),"emitter_name":comp["emitter_name"],"production_mode":comp["production_mode_name"],
                "sampled_source_mcp_pdg":src_sign,"edepsim_pdg":EDEPSIM_MCP_PDG,"mcp_mass_GeV":mass,"E_GeV":E,
                "theta_x_pythia_rad":float(accepted["thx"][i]),"theta_y_pythia_rad":float(accepted["thy"][i]),
                "px_pythia_GeV":float(accepted["p_b"][i,0]),"py_pythia_GeV":float(accepted["p_b"][i,1]),"pz_pythia_GeV":float(accepted["p_b"][i,2]),
                "px_2x2_GeV":float(px),"py_2x2_GeV":float(py),"pz_2x2_GeV":float(pz),
                "x_hit_global_m":float(hit[0]),"y_hit_global_m":float(hit[1]),"z_hit_global_m":float(hit[2]),
                "x_hit_rel_beam_m":float(hit[0]-beam_axis[0]),"y_hit_rel_beam_m":float(hit[1]-beam_axis[1]),
                "geometry_consistent_with_current_face":int(bool(accepted["geom"][i])),
                "x_injection_m":float(x),"y_injection_m":float(y),"z_injection_m":float(z),
                "event_weight_per_pot_epsilon2":event_weight,
            })
    fields=list(rows[0].keys())
    with manifest.open("w",newline="") as handle:
        w=csv.DictWriter(handle,fieldnames=fields); w.writeheader(); w.writerows(rows)

    macro.write_text(f"""# Auto-generated by generator/sample_pythia_flux.py
# Flux model: {args.model.resolve()}
# Flux stage: {stage}
# Beamline transport: {TRANSPORT_MODEL}
# Level 0 means no beamline energy loss, multiple scattering, magnetic deflection,
# attenuation, or material interactions.
# MCP mass: {mass:.12g} GeV

/edep/phys/ionizationModel 0
/edep/hitSeparation volTPCActive -1 mm
/edep/update
/generator/kinematics/hepevt/input {hepevt}
/generator/kinematics/hepevt/flavor pbomb
/generator/kinematics/hepevt/verbose 0
/generator/kinematics/set hepevt
/generator/position/set free
/generator/time/set free
/generator/count/fixed/number 1
/generator/count/set fixed
/generator/add
/edep/db/set/requireEventsWithHits false
""")

    out_summary={
        "schema_version":SAMPLER_SCHEMA_VERSION,"created_utc":utc_now(),"model_file":file_provenance(args.model),
        "model_flux_stage":stage,"mcp_mass_GeV":mass,"seed":args.seed,"beamline_transport":{"model":TRANSPORT_MODEL,"energy_loss":False,"multiple_scattering":False,"magnetic_deflection":False,"attenuation":False,"material_interactions":False},
        "coordinates":{"pythia_nominal_beam":[0,0,1],"beam_slope_y":args.beam_slope_y,"onaxis_2x2_unit":onaxis.tolist(),"beam_axis_at_detector_m":beam_axis.tolist(),"target_level0_m":target.tolist(),"baseline_m":args.baseline_m,"injection_global_z_m":inj_z},
        "source_trials":source_trials,"events_written":n_written,"geometry_consistency_fraction":geometry_consistency,
        "stage_flux_per_pot_epsilon2":total_stage_flux,"accepted_flux_estimate_per_pot_epsilon2":accepted_flux_est,
        "event_weight_per_pot_epsilon2":event_weight,
        "acceptance_behavior":("not reapplied; geometry check is diagnostic only because model is already post-acceptance" if stage=="accepted" else "applied after straight_line_v0 transport"),
        "outputs":{"hepevt":str(hepevt),"manifest_csv":str(manifest),"macro":str(macro),"plot":str(plot)},
    }
    summary_path.write_text(json.dumps(out_summary,indent=2,sort_keys=True)+"\n")
    make_sample_plot(plot,rows,meta)

    print("Coordinate cross-check:")
    print(f"  Pythia (0,0,+1) -> 2x2 ({onaxis[0]:+.8f}, {onaxis[1]:+.8f}, {onaxis[2]:+.8f})")
    print(f"Flux stage: {stage}")
    print(f"Beamline transport: {TRANSPORT_MODEL}")
    print(f"Source trials: {source_trials:,}")
    print(f"Events written: {n_written:,}")
    if stage=="accepted": print(f"Geometry consistency diagnostic: {100*geometry_consistency:.3f}%")
    else: print(f"Empirical acceptance: {n_written/source_trials:.6g}")
    print(f"Accepted flux estimate / POT / epsilon^2: {accepted_flux_est:.12g}")
    print(f"Per-event weight / POT / epsilon^2: {event_weight:.12g}")
    print(f"HEPEVT: {hepevt}")
    print(f"Manifest: {manifest}")
    print(f"Summary: {summary_path}")
    print(f"Macro: {macro}")
    return 0
