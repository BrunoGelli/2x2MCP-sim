#!/usr/bin/env python3
"""Empirical donor + adaptive local-jitter MCP flux model (schema v3).

This module supersedes the v2 histogram-cell resampler while deliberately
reusing the v2 normalization, coordinate, mass-scan, and provenance helpers.

Accepted-stage models store the actual accepted Pythia detector-plane donor
rows (E, x_det, y_det). Sampling selects a real donor with the appropriate
spectra-prescale weight and applies conservative adaptive local jitter inside
nearest-neighbour midpoint cells. Left/right module populations are handled
separately and hard-clipped to the original Pythia geometry_id=1 acceptance.
This prevents interpolation through the central module gap and avoids the broad
first/last histogram cells that distorted low/high-energy tails in v2.

Source-stage models use the same empirical-donor idea in
(logE, theta_x, theta_y) without accepted-window conditioning.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np

import flux_model_core as base
from flux_geometry import acceptance_mask_global

MODEL_SCHEMA_VERSION = 3
MODEL_TYPE = "weighted_empirical_donor_local_jitter_v3"
SAMPLER_SCHEMA_VERSION = 3
PYTHIA_PROJECTION_BASELINE_M = 1040.0


def _midpoint_bounds(values: np.ndarray, groups: np.ndarray | None = None,
                     hard_bounds: Dict[int, Tuple[float, float]] | None = None):
    """Return no-extrapolation nearest-neighbour midpoint cells per donor."""
    values = np.asarray(values, dtype=float)
    n = len(values)
    lo = values.copy()
    hi = values.copy()
    if groups is None:
        groups = np.zeros(n, dtype=np.int8)
    groups = np.asarray(groups)
    for g in np.unique(groups):
        idx = np.flatnonzero(groups == g)
        if len(idx) == 0:
            continue
        order_local = np.argsort(values[idx], kind="mergesort")
        order = idx[order_local]
        v = values[order]
        if len(v) > 1:
            mids = 0.5 * (v[:-1] + v[1:])
            lo[order[1:]] = mids
            hi[order[:-1]] = mids
        if hard_bounds and int(g) in hard_bounds:
            h_lo, h_hi = hard_bounds[int(g)]
            lo[order] = np.maximum(lo[order], h_lo)
            hi[order] = np.minimum(hi[order], h_hi)
        lo[order] = np.minimum(lo[order], v)
        hi[order] = np.maximum(hi[order], v)
    return lo, hi


def _jitter_from_bounds(rng: np.random.Generator, center: np.ndarray,
                        lo: np.ndarray, hi: np.ndarray, scale: float) -> np.ndarray:
    if not (0.0 <= scale <= 1.0):
        raise ValueError("jitter scale must be in [0,1]")
    center = np.asarray(center, dtype=float)
    low = center + scale * (np.asarray(lo, dtype=float) - center)
    high = center + scale * (np.asarray(hi, dtype=float) - center)
    u = rng.random(len(center))
    return low + u * (high - low)


def _accepted_domain_mask(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    in_x = (
        ((x >= base.X_RANGES_M[0][0]) & (x <= base.X_RANGES_M[0][1]))
        | ((x >= base.X_RANGES_M[1][0]) & (x <= base.X_RANGES_M[1][1]))
    )
    in_y = (y >= base.Y_RANGE_M[0]) & (y <= base.Y_RANGE_M[1])
    return in_x & in_y


def _run_group(path: Path) -> str:
    """Best-effort provenance label such as base_4h/global_v2/endpoint_v1."""
    try:
        return path.parent.parent.parent.name
    except Exception:
        return ""


def _audit_input_summary(input_sums, selected_summary, allow_mismatch: bool):
    audits = []
    problems = []
    for key, summary_row in selected_summary.items():
        got = input_sums.get(key, {})
        entry = {
            "mcp_mass_GeV": key[0],
            "emitter_pdg": key[1],
            "production_mode": key[2],
            "geometry_id": key[3],
        }
        ok = True
        for field in ("n_events_generated", "n_mcp_total", "n_mcp_accepted"):
            expected = int(summary_row[field])
            observed = int(got.get(field, 0))
            entry[f"aggregate_{field}"] = expected
            entry[f"input_root_{field}"] = observed
            entry[f"matches_{field}"] = (expected == observed)
            ok &= (expected == observed)
        entry["n_input_root_files"] = int(got.get("n_files", 0))
        entry["all_counts_match"] = bool(ok)
        audits.append(entry)
        if not ok:
            problems.append(entry)
    if problems and not allow_mismatch:
        lines = ["Input ROOT mcp_summary totals do not match the aggregate summary CSV."]
        for p in problems:
            lines.append(
                f"  PDG {p['emitter_pdg']}: events {p['input_root_n_events_generated']}/{p['aggregate_n_events_generated']}, "
                f"total MCP {p['input_root_n_mcp_total']}/{p['aggregate_n_mcp_total']}, "
                f"accepted MCP {p['input_root_n_mcp_accepted']}/{p['aggregate_n_mcp_accepted']}"
            )
        lines.append("Pass --allow-summary-mismatch only if this mismatch is intentional.")
        raise SystemExit("\n".join(lines))
    return audits


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build a reusable multi-emitter MCP flux model (empirical v3).")
    p.add_argument("inputs", nargs="+", help="Pythia ROOT files/directories/globs containing mcp_spectra.")
    p.add_argument("--summary", required=True, type=Path, help="Matching aggregate summary CSV.")
    p.add_argument("--mass-gev", required=True, type=float)
    p.add_argument("--geometry-id", type=int, default=1)
    p.add_argument("--flux-stage", choices=("accepted", "source"), default="accepted")
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--mass-tol-gev", type=float, default=1e-8)
    p.add_argument("--validation-samples", type=int, default=200000)
    p.add_argument("--validation-seed", type=int, default=12345)
    p.add_argument("--validation-jitter-scale", type=float, default=0.5,
                   help="Local-cell jitter fraction used in validation plots (0=bootstrap, 1=full midpoint cell).")
    p.add_argument("--allow-missing-emitters", action="store_true")
    p.add_argument("--allow-accepted-only-spectra", action="store_true",
                   help="Only meaningful for --flux-stage source.")
    p.add_argument("--allow-summary-mismatch", action="store_true",
                   help="Allow input ROOT totals to differ from the normalization summary (unsafe by default).")
    p.add_argument("--production-tag", default="")
    p.add_argument("--pythia-gen-git-sha", default="")
    return p


def _draw_component(rng, data, i: int, n: int, stage: str, jitter_scale: float):
    prob = np.asarray(data[f"c{i:03d}_donor_prob"], dtype=float)
    prob = prob / prob.sum()
    donor = rng.choice(len(prob), size=n, p=prob)
    logE0 = np.asarray(data[f"c{i:03d}_donor_logE"], dtype=float)[donor]
    logE = _jitter_from_bounds(
        rng,
        logE0,
        np.asarray(data[f"c{i:03d}_logE_lo"], float)[donor],
        np.asarray(data[f"c{i:03d}_logE_hi"], float)[donor],
        jitter_scale,
    )
    E = np.power(10.0, logE)
    if stage == "accepted":
        x0 = np.asarray(data[f"c{i:03d}_donor_xdet"], float)[donor]
        y0 = np.asarray(data[f"c{i:03d}_donor_ydet"], float)[donor]
        x = _jitter_from_bounds(
            rng, x0,
            np.asarray(data[f"c{i:03d}_xdet_lo"], float)[donor],
            np.asarray(data[f"c{i:03d}_xdet_hi"], float)[donor], jitter_scale,
        )
        y = _jitter_from_bounds(
            rng, y0,
            np.asarray(data[f"c{i:03d}_ydet_lo"], float)[donor],
            np.asarray(data[f"c{i:03d}_ydet_hi"], float)[donor], jitter_scale,
        )
        thx = np.arctan2(x, PYTHIA_PROJECTION_BASELINE_M)
        thy = np.arctan2(y, PYTHIA_PROJECTION_BASELINE_M)
        return E, thx, thy, donor, x, y
    thx0 = np.asarray(data[f"c{i:03d}_donor_theta_x"], float)[donor]
    thy0 = np.asarray(data[f"c{i:03d}_donor_theta_y"], float)[donor]
    thx = _jitter_from_bounds(
        rng, thx0,
        np.asarray(data[f"c{i:03d}_theta_x_lo"], float)[donor],
        np.asarray(data[f"c{i:03d}_theta_x_hi"], float)[donor], jitter_scale,
    )
    thy = _jitter_from_bounds(
        rng, thy0,
        np.asarray(data[f"c{i:03d}_theta_y_lo"], float)[donor],
        np.asarray(data[f"c{i:03d}_theta_y_hi"], float)[donor], jitter_scale,
    )
    x = PYTHIA_PROJECTION_BASELINE_M * np.tan(thx)
    y = PYTHIA_PROJECTION_BASELINE_M * np.tan(thy)
    return E, thx, thy, donor, x, y


def draw_model(rng, data, meta, n: int, jitter_scale: float):
    comps = meta["components"]
    fractions = np.array([float(c["mixture_fraction"]) for c in comps], dtype=float)
    which = rng.choice(len(comps), size=n, p=fractions / fractions.sum())
    E = np.empty(n)
    thx = np.empty(n)
    thy = np.empty(n)
    donor = np.empty(n, dtype=np.int64)
    xdet = np.empty(n)
    ydet = np.empty(n)
    for i in range(len(comps)):
        idx = np.flatnonzero(which == i)
        if len(idx) == 0:
            continue
        a, b, c, d, e, f = _draw_component(rng, data, i, len(idx), meta["flux_stage"], jitter_scale)
        E[idx] = a
        thx[idx] = b
        thy[idx] = c
        donor[idx] = d
        xdet[idx] = e
        ydet[idx] = f
    return which, E, thx, thy, donor, xdet, ydet


def _validation_plots(outdir: Path, source_by_component, components, arrays, stage: str,
                      n_samples: int, seed: int, jitter_scale: float):
    if n_samples <= 0:
        return
    plt, LogNorm = base._mpl()
    rng = np.random.default_rng(seed)
    meta = {"components": components, "flux_stage": stage}
    _, sE, sx, sy, _, sxd, syd = draw_model(rng, arrays, meta, n_samples, jitter_scale)

    src_E = np.concatenate([d[0] for d in source_by_component])
    src_thx = np.concatenate([d[1] for d in source_by_component])
    src_thy = np.concatenate([d[2] for d in source_by_component])
    src_w = np.concatenate([d[3] for d in source_by_component])
    src_w = src_w / src_w.sum()
    src_x = np.concatenate([d[4] for d in source_by_component])
    src_y = np.concatenate([d[5] for d in source_by_component])

    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    elo = max(min(float(src_E.min()), float(sE.min())), 1e-9)
    ehi = max(float(src_E.max()), float(sE.max()))
    ebins = np.geomspace(elo, ehi, 90)
    axes[0, 0].hist(src_E, bins=ebins, weights=src_w, histtype="step", density=True, label="weighted Pythia")
    axes[0, 0].hist(sE, bins=ebins, histtype="step", density=True, label="empirical resample")
    axes[0, 0].set_xscale("log")
    axes[0, 0].set_yscale("log")
    axes[0, 0].set_xlabel("E [GeV]")
    axes[0, 0].set_ylabel("Probability density")
    axes[0, 0].legend(fontsize=8)
    for ax, src, samp, label in (
        (axes[0, 1], src_thx, sx, r"$\theta_x$ [mrad]"),
        (axes[0, 2], src_thy, sy, r"$\theta_y$ [mrad]"),
    ):
        lo = min(float(src.min()), float(samp.min())) * 1e3
        hi = max(float(src.max()), float(samp.max())) * 1e3
        bins = np.linspace(lo, hi, 90)
        ax.hist(src * 1e3, bins=bins, weights=src_w, histtype="step", density=True, label="weighted Pythia")
        ax.hist(samp * 1e3, bins=bins, histtype="step", density=True, label="empirical resample")
        ax.set_yscale("log")
        ax.set_xlabel(label)
        ax.set_ylabel("Probability density")
        ax.legend(fontsize=8)
    h = axes[1, 0].hist2d(src_thx * 1e3, src_thy * 1e3, bins=90, weights=src_w, norm=LogNorm())
    fig.colorbar(h[3], ax=axes[1, 0])
    axes[1, 0].set_title("Weighted Pythia")
    axes[1, 0].set_xlabel(r"$\theta_x$ [mrad]")
    axes[1, 0].set_ylabel(r"$\theta_y$ [mrad]")
    h = axes[1, 1].hist2d(sx * 1e3, sy * 1e3, bins=90, norm=LogNorm())
    fig.colorbar(h[3], ax=axes[1, 1])
    axes[1, 1].set_title("Empirical resample")
    axes[1, 1].set_xlabel(r"$\theta_x$ [mrad]")
    axes[1, 1].set_ylabel(r"$\theta_y$ [mrad]")
    axes[1, 2].axis("off")
    lines = [
        f"validation draws: {n_samples:,}",
        f"seed: {seed}",
        f"jitter scale: {jitter_scale:g}",
        "",
        "emitter fractions:",
    ]
    lines += [f"{c['emitter_name']}: {100 * float(c['mixture_fraction']):.3f}%" for c in components]
    axes[1, 2].text(0, 1, "\n".join(lines), va="top", family="monospace")
    fig.suptitle("Flux-model empirical resampling validation")
    fig.tight_layout()
    fig.savefig(outdir / "flux_model_resampling_validation.png", dpi=170)
    plt.close(fig)

    if stage == "accepted":
        fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), sharex=True, sharey=True)
        h = axes[0].hist2d(src_x, src_y, bins=100, weights=src_w, norm=LogNorm())
        fig.colorbar(h[3], ax=axes[0])
        axes[0].set_title("Weighted Pythia")
        h = axes[1].hist2d(sxd, syd, bins=100, norm=LogNorm())
        fig.colorbar(h[3], ax=axes[1])
        axes[1].set_title("Empirical resample")
        for ax in axes:
            for lo, hi in base.X_RANGES_M:
                ax.plot(
                    [lo, hi, hi, lo, lo],
                    [base.Y_RANGE_M[0], base.Y_RANGE_M[0], base.Y_RANGE_M[1], base.Y_RANGE_M[1], base.Y_RANGE_M[0]],
                    "--", lw=1,
                )
            ax.set_xlabel("Pythia x at detector plane [m]")
        axes[0].set_ylabel("Pythia y at detector plane [m]")
        fig.suptitle("Accepted conditioning-domain validation")
        fig.tight_layout()
        fig.savefig(outdir / "flux_model_projection_validation.png", dpi=170)
        plt.close(fig)


def _overview_plot(out: Path, stage: str, source_by_component, components):
    base.make_overview_plot(out, stage, source_by_component, components)


def build_main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mass_gev <= 0.0:
        raise SystemExit("--mass-gev must be positive")
    if not (0.0 <= args.validation_jitter_scale <= 1.0):
        raise SystemExit("--validation-jitter-scale must be in [0,1]")
    root_files = base.expand_inputs(args.inputs)
    if not args.summary.is_file():
        raise SystemExit(f"Summary CSV not found: {args.summary}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plots = args.output_dir / "plots"
    plots.mkdir(exist_ok=True)

    summary, sigma_soft, sigma_charm, charm_scale = base.read_aggregate_summary(args.summary)
    base.write_mass_scan(summary, charm_scale, args.geometry_id, plots)
    mass_key = round(args.mass_gev, 12)
    selected = {
        key: row
        for key, row in summary.items()
        if abs(key[0] - mass_key) <= args.mass_tol_gev
        and key[3] == args.geometry_id
        and key[1] in base.PARENTS
        and base.br_per_epsilon2(key[1], args.mass_gev) > 0
    }
    if not selected:
        raise SystemExit(f"No open supported summary rows at m_chi={args.mass_gev:g} GeV")
    expected_open = {pdg for pdg in base.PARENTS if base.br_per_epsilon2(pdg, args.mass_gev) > 0}
    missing = expected_open - {k[1] for k in selected}
    if missing and not args.allow_missing_emitters:
        raise SystemExit("Aggregate summary missing open emitters: " + ", ".join(base.PARENTS[p][0] for p in sorted(missing)))

    try:
        import ROOT
    except ImportError as exc:
        raise SystemExit("PyROOT is required to build a flux model") from exc
    ROOT.gROOT.SetBatch(True)

    records = {
        key: {"E": [], "thx": [], "thy": [], "xdet": [], "ydet": [], "shape_w": [], "groups": []}
        for key in selected
    }
    input_sums = defaultdict(lambda: defaultdict(int))
    files_used = set()
    group_counts = defaultdict(int)

    for fn in root_files:
        f = ROOT.TFile.Open(str(fn), "READ")
        if not f or f.IsZombie():
            print(f"WARNING: could not open {fn}", file=sys.stderr)
            continue
        local_prescale = {}
        tsum = f.Get("mcp_summary")
        if tsum:
            for srow in tsum:
                key = (
                    round(float(srow.mcp_mass_GeV), 12),
                    int(srow.emitter_pdg),
                    int(srow.production_mode),
                    int(srow.geometry_id),
                )
                if key not in selected:
                    continue
                local_prescale[key] = int(getattr(srow, "spectra_prescale", 1))
                input_sums[key]["n_events_generated"] += int(getattr(srow, "n_events_generated", 0))
                input_sums[key]["n_mcp_total"] += int(getattr(srow, "n_mcp_total", 0))
                input_sums[key]["n_mcp_accepted"] += int(getattr(srow, "n_mcp_accepted", 0))
                input_sums[key]["n_files"] += 1
        tree = f.Get("mcp_spectra")
        used_here = False
        if tree:
            for row in tree:
                if abs(float(row.mcp_mass_GeV) - args.mass_gev) > args.mass_tol_gev:
                    continue
                key = (mass_key, int(row.emitter_pdg), int(row.production_mode), int(row.geometry_id))
                if key not in selected:
                    continue
                passed = bool(int(getattr(row, "passed_geometry", getattr(row, "accepted", 0))))
                if args.flux_stage == "accepted" and not passed:
                    continue
                pz = float(row.pz_GeV)
                E = float(row.E_GeV)
                if pz <= 0 or E <= args.mass_gev:
                    continue
                x = float(getattr(row, "x_at_detector_m", PYTHIA_PROJECTION_BASELINE_M * float(row.px_GeV) / pz))
                y = float(getattr(row, "y_at_detector_m", PYTHIA_PROJECTION_BASELINE_M * float(row.py_GeV) / pz))
                if args.flux_stage == "accepted" and not bool(_accepted_domain_mask(np.array([x]), np.array([y]))[0]):
                    continue
                rec = records[key]
                rec["E"].append(E)
                rec["thx"].append(math.atan2(float(row.px_GeV), pz))
                rec["thy"].append(math.atan2(float(row.py_GeV), pz))
                rec["xdet"].append(x)
                rec["ydet"].append(y)
                rec["shape_w"].append(float(local_prescale.get(key, int(selected[key].get("spectra_prescale_max") or 1))))
                rec["groups"].append(-1 if x < 0 else 1 if x > 0 else 0)
                used_here = True
        if used_here:
            files_used.add(str(fn.resolve()))
            group_counts[_run_group(fn)] += 1
        f.Close()

    audits = _audit_input_summary(input_sums, selected, args.allow_summary_mismatch)

    arrays = {}
    components = []
    source_by_component = []
    for key in sorted(selected, key=lambda k: k[1]):
        row = selected[key]
        pdg, mode, geom = key[1], key[2], key[3]
        name = base.PARENTS[pdg][0]
        rec = records[key]
        if not rec["E"]:
            if not args.allow_missing_emitters:
                raise SystemExit(f"No usable {args.flux_stage} spectrum rows for open emitter {name}")
            continue
        E = np.asarray(rec["E"], float)
        thx = np.asarray(rec["thx"], float)
        thy = np.asarray(rec["thy"], float)
        xdet = np.asarray(rec["xdet"], float)
        ydet = np.asarray(rec["ydet"], float)
        shape = np.asarray(rec["shape_w"], float)
        groups = np.asarray(rec["groups"], np.int8)
        flux = base.stage_flux_from_summary(row, pdg, mode, args.mass_gev, charm_scale, args.flux_stage)
        if flux <= 0:
            continue
        prob = shape / shape.sum()
        logE = np.log10(E)
        if args.flux_stage == "accepted":
            log_lo, log_hi = _midpoint_bounds(logE, groups)
            x_lo, x_hi = _midpoint_bounds(xdet, groups, {-1: base.X_RANGES_M[0], 1: base.X_RANGES_M[1]})
            y_lo, y_hi = _midpoint_bounds(ydet, groups, {-1: base.Y_RANGE_M, 1: base.Y_RANGE_M})
        else:
            log_lo, log_hi = _midpoint_bounds(logE)
            tx_lo, tx_hi = _midpoint_bounds(thx)
            ty_lo, ty_hi = _midpoint_bounds(thy)
        i = len(components)
        prefix = f"c{i:03d}_"
        arrays[prefix + "donor_logE"] = logE
        arrays[prefix + "donor_theta_x"] = thx
        arrays[prefix + "donor_theta_y"] = thy
        arrays[prefix + "donor_xdet"] = xdet
        arrays[prefix + "donor_ydet"] = ydet
        arrays[prefix + "donor_prob"] = prob
        arrays[prefix + "donor_side"] = groups
        arrays[prefix + "logE_lo"] = log_lo
        arrays[prefix + "logE_hi"] = log_hi
        if args.flux_stage == "accepted":
            arrays[prefix + "xdet_lo"] = x_lo
            arrays[prefix + "xdet_hi"] = x_hi
            arrays[prefix + "ydet_lo"] = y_lo
            arrays[prefix + "ydet_hi"] = y_hi
        else:
            arrays[prefix + "theta_x_lo"] = tx_lo
            arrays[prefix + "theta_x_hi"] = tx_hi
            arrays[prefix + "theta_y_lo"] = ty_lo
            arrays[prefix + "theta_y_hi"] = ty_hi
        stage_target = int(row["n_mcp_accepted"] if args.flux_stage == "accepted" else row["n_mcp_total"])
        c = {
            "component_index": i,
            "emitter_pdg": pdg,
            "emitter_name": name,
            "production_mode": mode,
            "production_mode_name": base.MODE_NAME.get(mode, str(mode)),
            "geometry_id": geom,
            "flux_stage": args.flux_stage,
            "n_events_generated": int(row["n_events_generated"]),
            "n_mcp_total": int(row["n_mcp_total"]),
            "n_mcp_accepted_pythia": int(row["n_mcp_accepted"]),
            "stage_target_mcp": stage_target,
            "n_donor_rows": len(E),
            "spectra_equivalent_mcp": float(shape.sum()),
            "spectra_stage_coverage": float(shape.sum() / stage_target) if stage_target else 0.0,
            "process_scale": base.process_scale(mode, charm_scale),
            "br_per_epsilon2": base.br_per_epsilon2(pdg, args.mass_gev),
            "stage_flux_per_pot_epsilon2": flux,
            "left_donors": int(np.count_nonzero(groups < 0)),
            "right_donors": int(np.count_nonzero(groups > 0)),
        }
        components.append(c)
        source_by_component.append((E, thx, thy, prob * flux, xdet, ydet))

    total_flux = sum(float(c["stage_flux_per_pot_epsilon2"]) for c in components)
    if total_flux <= 0:
        raise SystemExit("Total model flux is zero")
    for c in components:
        c["mixture_fraction"] = float(c["stage_flux_per_pot_epsilon2"]) / total_flux

    fields = [
        "component_index", "emitter_pdg", "emitter_name", "production_mode_name", "flux_stage",
        "n_events_generated", "n_mcp_total", "n_mcp_accepted_pythia", "stage_target_mcp",
        "n_donor_rows", "spectra_equivalent_mcp", "spectra_stage_coverage", "process_scale",
        "br_per_epsilon2", "stage_flux_per_pot_epsilon2", "mixture_fraction", "left_donors", "right_donors",
    ]
    with (args.output_dir / "component_normalization.csv").open("w", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields)
        w.writeheader()
        for c in components:
            w.writerow({k: c.get(k, "") for k in fields})
    with (args.output_dir / "input_summary_audit.csv").open("w", newline="") as h:
        fields_a = list(audits[0].keys()) if audits else []
        if fields_a:
            w = csv.DictWriter(h, fieldnames=fields_a)
            w.writeheader()
            w.writerows(audits)

    _overview_plot(plots / "flux_model_overview.png", args.flux_stage, source_by_component, components)
    base.make_projection_plot(plots / "pythia_detector_projection.png", source_by_component, components)
    _validation_plots(
        plots,
        source_by_component,
        components,
        arrays,
        args.flux_stage,
        args.validation_samples,
        args.validation_seed,
        args.validation_jitter_scale,
    )

    provenance = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "model_type": MODEL_TYPE,
        "created_utc": base.utc_now(),
        "flux_stage": args.flux_stage,
        "selected_mass_GeV": args.mass_gev,
        "geometry_id": args.geometry_id,
        "normalization_units": "MCP / POT / epsilon^2",
        "total_stage_flux_per_pot_epsilon2": total_flux,
        "normalization_convention": "same aggregate-summary convention as 2x2MCP-PythiaGen export_toymc_spectra.py; donor rows control shape only",
        "sigma_softqcd_mb_mean": sigma_soft,
        "sigma_charmonium_mb_mean": sigma_charm,
        "charmonium_process_scale": charm_scale,
        "resampling": {
            "method": "weighted empirical donor + adaptive nearest-neighbour midpoint jitter",
            "default_recommended_jitter_scale": 0.5,
            "no_extrapolation": True,
            "accepted_stage_coordinates": "logE + x_at_detector + y_at_detector; left/right modules separated",
            "source_stage_coordinates": "logE + theta_x + theta_y",
            "pythia_projection_baseline_m": PYTHIA_PROJECTION_BASELINE_M,
        },
        "beamline_transport_assumption": {
            "model": base.TRANSPORT_MODEL,
            "energy_loss": False,
            "multiple_scattering": False,
            "magnetic_deflection": False,
            "attenuation": False,
            "material_interactions": False,
        },
        "production_tag": args.production_tag,
        "pythia_gen_git_sha": args.pythia_gen_git_sha,
        "mcp_sim_git_sha": base.git_sha_here(),
        "summary_file": base.file_provenance(args.summary),
        "source_root_files": [base.file_provenance(Path(p)) for p in sorted(files_used)],
        "input_run_groups": dict(sorted(group_counts.items())),
        "input_summary_audit": audits,
        "components": components,
    }
    arrays["metadata_json"] = np.array(json.dumps(provenance, sort_keys=True))
    arrays["mcp_mass_GeV"] = np.array(args.mass_gev, float)
    arrays["component_pdg"] = np.array([int(c["emitter_pdg"]) for c in components], np.int32)
    arrays["component_flux"] = np.array([float(c["stage_flux_per_pot_epsilon2"]) for c in components], float)
    arrays["component_fraction"] = np.array([float(c["mixture_fraction"]) for c in components], float)
    np.savez_compressed(args.output_dir / "flux_model.npz", **arrays)
    (args.output_dir / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")

    print(f"Built empirical-v3 {args.flux_stage} flux model: {args.output_dir / 'flux_model.npz'}")
    print(f"Selected mass: {args.mass_gev:g} GeV")
    print(f"Total {args.flux_stage} flux / POT / epsilon^2: {total_flux:.12g}")
    print("Input run groups used:")
    for g, n in sorted(group_counts.items()):
        print(f"  {g or '(unlabeled)'}: {n} ROOT files")
    print("Aggregate-summary audit: PASS" if all(a["all_counts_match"] for a in audits) else "Aggregate-summary audit: OVERRIDDEN MISMATCH")
    print("Emitter mixture:")
    for c in components:
        print(
            f"  {c['emitter_name']:>6s}: {100 * float(c['mixture_fraction']):9.5f}%  "
            f"flux={float(c['stage_flux_per_pot_epsilon2']):.6g}  donors={int(c['n_donor_rows'])}"
        )
    print(f"Provenance: {args.output_dir / 'provenance.json'}")
    print(f"Plots: {plots}")
    return 0


def sampler_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Sample empirical-v3 MCP flux model and prepare EDepSim input")
    p.add_argument("model", type=Path)
    p.add_argument("output_prefix", type=Path)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--n-events", type=int)
    g.add_argument("--n-accepted", type=int)
    g.add_argument("--n-source", type=int)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--jitter-scale", type=float, default=0.5, help="0=weighted bootstrap; 1=full adaptive midpoint cells")
    p.add_argument("--baseline-m", type=float, default=base.DEFAULT_BASELINE_M)
    p.add_argument("--beam-slope-y", type=float, default=base.DEFAULT_BEAM_SLOPE_Y)
    p.add_argument("--beam-axis-x-m", type=float, default=base.DEFAULT_BEAM_AXIS_AT_DETECTOR_M[0])
    p.add_argument("--beam-axis-y-m", type=float, default=base.DEFAULT_BEAM_AXIS_AT_DETECTOR_M[1])
    p.add_argument("--detector-z-m", type=float, default=base.DEFAULT_BEAM_AXIS_AT_DETECTOR_M[2])
    p.add_argument("--injection-distance-m", type=float, default=base.DEFAULT_INJECTION_DISTANCE_M)
    p.add_argument("--time-ns", type=float, default=0.0)
    p.add_argument("--allow-low-mass", action="store_true")
    return p


def load_model(path: Path):
    data = np.load(path, allow_pickle=False)
    meta = json.loads(str(data["metadata_json"].item()))
    if int(meta.get("schema_version", 0)) < 3 or "empirical" not in str(meta.get("model_type", "")):
        raise SystemExit("This sampler expects an empirical v3 model. Rebuild with current build_pythia_flux_model.py")
    return data, meta


def _sample_plot(path: Path, rows, meta):
    if not rows:
        return
    plt, _ = base._mpl()
    E = np.array([r["E_GeV"] for r in rows])
    thx = np.array([r["theta_x_pythia_rad"] for r in rows])
    thy = np.array([r["theta_y_pythia_rad"] for r in rows])
    xd = np.array([r["x_pythia_detector_m"] for r in rows])
    yd = np.array([r["y_pythia_detector_m"] for r in rows])
    names = np.array([r["emitter_name"] for r in rows])
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    axes[0, 0].hist(E, bins=np.geomspace(max(E.min(), 1e-9), E.max(), 60), histtype="step")
    axes[0, 0].set_xscale("log")
    axes[0, 0].set_yscale("log")
    axes[0, 0].set_xlabel("E [GeV]")
    axes[0, 1].hist(thx * 1e3, bins=60, histtype="step", label="theta_x")
    axes[0, 1].hist(thy * 1e3, bins=60, histtype="step", label="theta_y")
    axes[0, 1].set_yscale("log")
    axes[0, 1].set_xlabel("Pythia angle [mrad]")
    axes[0, 1].legend()
    axes[1, 0].scatter(xd, yd, s=3, alpha=.4)
    axes[1, 0].set_xlabel("Pythia x at detector [m]")
    axes[1, 0].set_ylabel("Pythia y at detector [m]")
    comps = [c["emitter_name"] for c in meta["components"]]
    counts = [np.count_nonzero(names == n) for n in comps]
    axes[1, 1].bar(comps, counts)
    axes[1, 1].set_yscale("log")
    axes[1, 1].set_ylabel("written events")
    fig.suptitle("Sampled empirical-v3 MCP flux")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def sampler_main(argv: Sequence[str] | None = None) -> int:
    args = sampler_parser().parse_args(argv)
    if not args.model.is_file():
        raise SystemExit(f"Model not found: {args.model}")
    if not (0 <= args.jitter_scale <= 1):
        raise SystemExit("--jitter-scale must be in [0,1]")
    data, meta = load_model(args.model)
    stage = meta["flux_stage"]
    mass = float(meta["selected_mass_GeV"])
    if mass <= 0.010 and not args.allow_low_mass:
        raise SystemExit(f"Model mass {mass:g} GeV is <=10 MeV; current EDepSim MCP requires >10 MeV")
    if stage == "accepted":
        if args.n_source is not None:
            raise SystemExit("--n-source is only valid for source-stage models")
        target_n = args.n_events if args.n_events is not None else args.n_accepted if args.n_accepted is not None else 100
        fixed_source = None
    else:
        if args.n_events is not None:
            raise SystemExit("For source-stage models use --n-source or --n-accepted")
        target_n = args.n_accepted
        fixed_source = args.n_source
        if target_n is None and fixed_source is None:
            target_n = 100
    rng = np.random.default_rng(args.seed)
    beam_axis = np.array([args.beam_axis_x_m, args.beam_axis_y_m, args.detector_z_m], float)
    onaxis = base.rotate_pythia_to_2x2(np.array([[0., 0., 1.]]), args.beam_slope_y)[0]
    onaxis /= np.linalg.norm(onaxis)
    target = beam_axis - args.baseline_m * onaxis
    inj_z = args.detector_z_m - args.injection_distance_m
    chunks = []
    source_trials = 0

    def process(n):
        nonlocal source_trials
        which, E, thx, thy, donor, xdet, ydet = draw_model(rng, data, meta, n, args.jitter_scale)
        source_trials += n
        p_b, dir_b = base.kinematics_from_angles(E, thx, thy, mass)
        p_g = base.rotate_pythia_to_2x2(p_b, args.beam_slope_y)
        dir_g = base.rotate_pythia_to_2x2(dir_b, args.beam_slope_y)
        hit, sdet = base.line_at_z(target, dir_g, args.detector_z_m)
        geom = (sdet > 0) & acceptance_mask_global(hit, beam_axis)
        inj, sinj = base.line_at_z(target, dir_g, inj_z)
        valid = (sinj > 0) & np.isfinite(inj).all(axis=1) & np.isfinite(hit).all(axis=1)
        keep = (geom & valid) if stage == "source" else valid
        return {
            "which": which[keep], "E": E[keep], "thx": thx[keep], "thy": thy[keep],
            "donor": donor[keep], "xdet": xdet[keep], "ydet": ydet[keep],
            "p_b": p_b[keep], "p_g": p_g[keep], "hit": hit[keep], "inj": inj[keep], "geom": geom[keep],
        }

    if stage == "accepted":
        chunks = [process(target_n)]
    elif fixed_source is not None:
        chunks = [process(fixed_source)]
    else:
        have = 0
        while have < target_n:
            batch = max(10000, min(500000, (target_n - have) * 5000))
            c = process(batch)
            if len(c["E"]):
                take = min(len(c["E"]), target_n - have)
                chunks.append({k: v[:take] for k, v in c.items()})
                have += take
            if source_trials > 100_000_000 and have == 0:
                raise SystemExit("No accepted trajectories after 100 million source throws")
    keys = chunks[0].keys() if chunks else []
    acc = {k: np.concatenate([c[k] for c in chunks]) for k in keys}
    n = len(acc.get("E", []))
    if n == 0:
        raise SystemExit("No events written")
    flux = float(meta["total_stage_flux_per_pot_epsilon2"])
    event_weight = flux / n if stage == "accepted" else flux / source_trials
    acc_flux = flux if stage == "accepted" else event_weight * n
    geom_cons = float(np.mean(acc["geom"])) if stage == "accepted" else 1.0
    prefix = args.output_prefix
    prefix.parent.mkdir(parents=True, exist_ok=True)
    hepevt = prefix.with_suffix(".hepevt")
    manifest = prefix.with_suffix(".manifest.csv")
    summaryp = prefix.with_suffix(".summary.json")
    macro = prefix.with_suffix(".mac")
    plot = prefix.with_suffix(".sampled_flux.png")
    comps = meta["components"]
    rows = []
    with hepevt.open("w") as h:
        for i in range(n):
            ci = int(acc["which"][i])
            comp = comps[ci]
            x, y, z = acc["inj"][i]
            px, py, pz = acc["p_g"][i]
            E = float(acc["E"][i])
            hit = acc["hit"][i]
            h.write(f"1 {100 * x:.12g} {100 * y:.12g} {100 * z:.12g} {args.time_ns:.12g}\n")
            h.write(f"1 {base.EDEPSIM_MCP_PDG} 0 0 0 0 {px:.12g} {py:.12g} {pz:.12g} {E:.12g} {mass:.12g}\n")
            rows.append({
                "edepsim_event_id": i,
                "component_index": ci,
                "emitter_pdg": int(comp["emitter_pdg"]),
                "emitter_name": comp["emitter_name"],
                "production_mode": comp["production_mode_name"],
                "donor_index": int(acc["donor"][i]),
                "mcp_mass_GeV": mass,
                "E_GeV": E,
                "theta_x_pythia_rad": float(acc["thx"][i]),
                "theta_y_pythia_rad": float(acc["thy"][i]),
                "x_pythia_detector_m": float(acc["xdet"][i]),
                "y_pythia_detector_m": float(acc["ydet"][i]),
                "px_pythia_GeV": float(acc["p_b"][i, 0]),
                "py_pythia_GeV": float(acc["p_b"][i, 1]),
                "pz_pythia_GeV": float(acc["p_b"][i, 2]),
                "px_2x2_GeV": float(px),
                "py_2x2_GeV": float(py),
                "pz_2x2_GeV": float(pz),
                "x_hit_global_m": float(hit[0]),
                "y_hit_global_m": float(hit[1]),
                "z_hit_global_m": float(hit[2]),
                "geometry_consistent_with_current_face": int(bool(acc["geom"][i])),
                "x_injection_m": float(x),
                "y_injection_m": float(y),
                "z_injection_m": float(z),
                "event_weight_per_pot_epsilon2": event_weight,
            })
    with manifest.open("w", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    macro.write_text(
        f"""# Auto-generated by generator/sample_pythia_flux.py
# Model: {args.model.resolve()}
# Schema: empirical donor + local jitter v3
# Flux stage: {stage}
# Jitter scale: {args.jitter_scale}
# Beamline transport: {base.TRANSPORT_MODEL}
# Level 0: no energy loss, multiple scattering, magnetic deflection, attenuation, or material interactions.

/edep/phys/ionizationModel 0
/edep/hitSeparation volTPCActive -1 mm
/edep/update
/generator/kinematics/hepevt/input {hepevt}
/generator/kinematics/hepevt/flavor pbomb
/generator/kinematics/set hepevt
/generator/position/set free
/generator/time/set free
/generator/count/fixed/number 1
/generator/count/set fixed
/generator/add
/edep/db/set/requireEventsWithHits false
"""
    )
    out = {
        "schema_version": SAMPLER_SCHEMA_VERSION,
        "created_utc": base.utc_now(),
        "model_file": base.file_provenance(args.model),
        "model_flux_stage": stage,
        "mcp_mass_GeV": mass,
        "seed": args.seed,
        "jitter_scale": args.jitter_scale,
        "resampling_method": "weighted empirical donor + adaptive local midpoint jitter",
        "beamline_transport": {
            "model": base.TRANSPORT_MODEL,
            "energy_loss": False,
            "multiple_scattering": False,
            "magnetic_deflection": False,
            "attenuation": False,
            "material_interactions": False,
        },
        "coordinates": {
            "pythia_nominal_beam": [0, 0, 1],
            "beam_slope_y": args.beam_slope_y,
            "onaxis_2x2_unit": onaxis.tolist(),
            "beam_axis_at_detector_m": beam_axis.tolist(),
            "target_level0_m": target.tolist(),
            "baseline_m": args.baseline_m,
            "injection_global_z_m": inj_z,
        },
        "source_trials": source_trials,
        "events_written": n,
        "geometry_consistency_fraction": geom_cons,
        "stage_flux_per_pot_epsilon2": flux,
        "accepted_flux_estimate_per_pot_epsilon2": acc_flux,
        "event_weight_per_pot_epsilon2": event_weight,
        "outputs": {
            "hepevt": str(hepevt),
            "manifest_csv": str(manifest),
            "macro": str(macro),
            "plot": str(plot),
        },
    }
    summaryp.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    _sample_plot(plot, rows, meta)
    print("Coordinate cross-check:")
    print(f"  Pythia (0,0,+1) -> 2x2 ({onaxis[0]:+.8f}, {onaxis[1]:+.8f}, {onaxis[2]:+.8f})")
    print(f"Flux stage: {stage}")
    print(f"Resampling: empirical donor + local jitter, scale={args.jitter_scale:g}")
    print(f"Beamline transport: {base.TRANSPORT_MODEL}")
    print(f"Source trials: {source_trials:,}")
    print(f"Events written: {n:,}")
    if stage == "accepted":
        print(f"Geometry consistency diagnostic: {100 * geom_cons:.3f}%")
    else:
        print(f"Empirical acceptance: {n / source_trials:.6g}")
    print(f"Accepted flux estimate / POT / epsilon^2: {acc_flux:.12g}")
    print(f"Per-event weight / POT / epsilon^2: {event_weight:.12g}")
    print(f"HEPEVT: {hepevt}")
    print(f"Manifest: {manifest}")
    print(f"Summary: {summaryp}")
    print(f"Macro: {macro}")
    return 0
