#!/usr/bin/env python3

"""Validate a Pythia-sampler manifest against an EDepSim ROOT file.

This is intended as the first realistic-generator regression check. It verifies
that event identity, primary PDG, mass, injection vertex, and initial momentum
survive the HEPEVT -> EDepSim interface event-by-event, and it summarizes the
active-LAr response before ROOT -> HDF5 conversion can drop empty events.
"""

import csv
import math
import statistics
import sys

import ROOT

ROOT.gROOT.SetBatch(True)

if ROOT.gSystem.Load("libedepsim_io") < 0:
    raise RuntimeError("Could not load libedepsim_io")


POSITION_TOL_MM = 1e-3
MOMENTUM_TOL_MEV = 1e-3
ENERGY_TOL_MEV = 1e-3
MASS_TOL_MEV = 1e-3
EXPECTED_PDG = 9000001


def usage() -> None:
    print(
        f"Usage: {sys.argv[0]} MANIFEST.csv EDEPSIM.root",
        file=sys.stderr,
    )


def main() -> int:
    if len(sys.argv) != 3:
        usage()
        return 1

    manifest_file = sys.argv[1]
    root_file = sys.argv[2]

    with open(manifest_file, newline="") as f:
        rows = list(csv.DictReader(f))

    manifest = {
        int(row["edepsim_event_id"]): row
        for row in rows
    }

    f = ROOT.TFile.Open(root_file)
    if not f or f.IsZombie():
        raise RuntimeError(f"Could not open {root_file}")

    tree = f.Get("EDepSimEvents")
    if not tree:
        raise RuntimeError("EDepSimEvents tree not found")

    print("=" * 72)
    print("Pythia/HEPEVT -> EDepSim validation")
    print("=" * 72)
    print(f"Manifest events : {len(rows)}")
    print(f"ROOT events     : {tree.GetEntries()}")

    if tree.GetEntries() != len(rows):
        raise RuntimeError("Manifest and ROOT event counts differ")

    max_pos_diff_mm = 0.0
    max_p_diff_mev = 0.0
    max_E_diff_mev = 0.0
    max_mass_diff_mev = 0.0

    dir_x = []
    dir_y = []
    dir_z = []
    energies_gev = []

    n_tpc_any = 0
    n_tpc_primary = 0
    n_segments_total = 0
    total_tpc_edep = 0.0

    primary_lengths = []
    primary_edeps = []
    primary_dedx = []

    bad_pdg = []
    bad_primary_count = []
    missing_manifest = []
    seen_event_ids = set()

    for i in range(tree.GetEntries()):
        tree.GetEntry(i)
        event = tree.Event

        event_id = int(event.EventId)
        seen_event_ids.add(event_id)

        if event_id not in manifest:
            missing_manifest.append(event_id)
            continue

        row = manifest[event_id]

        primaries = [
            traj for traj in event.Trajectories
            if traj.GetParentId() < 0
        ]

        if len(primaries) != 1:
            bad_primary_count.append((event_id, len(primaries)))
            continue

        primary = primaries[0]

        if int(primary.GetPDGCode()) != EXPECTED_PDG:
            bad_pdg.append((event_id, int(primary.GetPDGCode())))

        # Manifest momenta are GeV; EDepSim ROOT stores MeV.
        p4 = primary.GetInitialMomentum()
        root_p = [float(p4.X()), float(p4.Y()), float(p4.Z())]
        expected_p = [
            1000.0 * float(row["px_2x2_GeV"]),
            1000.0 * float(row["py_2x2_GeV"]),
            1000.0 * float(row["pz_2x2_GeV"]),
        ]

        for got, expected in zip(root_p, expected_p):
            max_p_diff_mev = max(max_p_diff_mev, abs(got - expected))

        expected_E = 1000.0 * float(row["E_GeV"])
        max_E_diff_mev = max(
            max_E_diff_mev,
            abs(float(p4.E()) - expected_E),
        )

        expected_mass = 1000.0 * float(row["mcp_mass_GeV"])
        max_mass_diff_mev = max(
            max_mass_diff_mev,
            abs(float(p4.M()) - expected_mass),
        )

        p = math.sqrt(sum(x * x for x in root_p))
        dir_x.append(root_p[0] / p)
        dir_y.append(root_p[1] / p)
        dir_z.append(root_p[2] / p)
        energies_gev.append(float(p4.E()) / 1000.0)

        # Manifest injection coordinates are metres; EDepSim ROOT stores mm.
        if len(event.Primaries) != 1:
            raise RuntimeError(
                f"Event {event_id}: expected one primary vertex, "
                f"found {len(event.Primaries)}"
            )

        pos = event.Primaries[0].GetPosition()
        root_pos = [float(pos.X()), float(pos.Y()), float(pos.Z())]
        expected_pos = [
            1000.0 * float(row["x_injection_m"]),
            1000.0 * float(row["y_injection_m"]),
            1000.0 * float(row["z_injection_m"]),
        ]

        for got, expected in zip(root_pos, expected_pos):
            max_pos_diff_mm = max(max_pos_diff_mm, abs(got - expected))

        try:
            segments = event.SegmentDetectors["volTPCActive"]
        except Exception:
            segments = []

        n_segments_total += len(segments)
        if len(segments) > 0:
            n_tpc_any += 1

        primary_id = int(primary.GetTrackId())
        evt_primary_length = 0.0
        evt_primary_edep = 0.0

        for seg in segments:
            edep = float(seg.GetEnergyDeposit())
            total_tpc_edep += edep

            contributors = [int(c) for c in seg.GetContributors()]
            if primary_id in contributors:
                evt_primary_length += float(seg.GetTrackLength())
                evt_primary_edep += edep

        primary_lengths.append(evt_primary_length)
        primary_edeps.append(evt_primary_edep)

        if evt_primary_length > 0:
            n_tpc_primary += 1
            primary_dedx.append(evt_primary_edep / evt_primary_length)

    expected_ids = set(manifest.keys())

    print()
    print("Identity")
    print(f"  Missing ROOT->manifest IDs : {missing_manifest}")
    print(f"  Missing manifest->ROOT IDs : {sorted(expected_ids - seen_event_ids)}")
    print(f"  Bad primary counts         : {bad_primary_count}")
    print(f"  Bad PDGs                   : {bad_pdg}")

    print()
    print("Maximum generator -> ROOT differences")
    print(f"  position component : {max_pos_diff_mm:.6g} mm")
    print(f"  momentum component : {max_p_diff_mev:.6g} MeV/c")
    print(f"  total energy       : {max_E_diff_mev:.6g} MeV")
    print(f"  mass               : {max_mass_diff_mev:.6g} MeV")

    print()
    print("Primary kinematics")
    print(f"  E range [GeV]      : {min(energies_gev):.6g} -> {max(energies_gev):.6g}")
    print(
        "  mean direction     : "
        f"({statistics.mean(dir_x):+.8f}, "
        f"{statistics.mean(dir_y):+.8f}, "
        f"{statistics.mean(dir_z):+.8f})"
    )
    print(f"  py/p range         : {min(dir_y):+.8f} -> {max(dir_y):+.8f}")
    print(f"  pz/p range         : {min(dir_z):+.8f} -> {max(dir_z):+.8f}")

    print()
    print("Active LAr")
    print(f"  events with any TPC segment     : {n_tpc_any}/{tree.GetEntries()}")
    print(f"  events with primary TPC segment : {n_tpc_primary}/{tree.GetEntries()}")
    print(f"  total TPC segments              : {n_segments_total}")
    print(f"  total TPC Edep [MeV]            : {total_tpc_edep:.9g}")

    if primary_dedx:
        print(
            "  mean primary dE/dx [MeV/mm]    : "
            f"{statistics.mean(primary_dedx):.9g}"
        )

    print()

    identity_ok = (
        not missing_manifest
        and not (expected_ids - seen_event_ids)
        and not bad_primary_count
        and not bad_pdg
    )

    numerics_ok = (
        max_pos_diff_mm < POSITION_TOL_MM
        and max_p_diff_mev < MOMENTUM_TOL_MEV
        and max_E_diff_mev < ENERGY_TOL_MEV
        and max_mass_diff_mev < MASS_TOL_MEV
    )

    f.Close()

    if identity_ok and numerics_ok:
        print("VALIDATION: PASS")
        return 0

    print("VALIDATION: FAIL")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
