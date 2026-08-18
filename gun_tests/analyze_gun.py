#!/usr/bin/env python3

import sys
import os
import statistics
from collections import Counter

import ROOT

ROOT.gROOT.SetBatch(True)

# Explicitly load the EDepSim ROOT dictionaries.
if ROOT.gSystem.Load("libedepsim_io") < 0:
    raise RuntimeError(
        "Could not load libedepsim_io. "
        "Check that edep-sim_install/lib is in LD_LIBRARY_PATH."
    )


def mean_std(values):
    if not values:
        return float("nan"), float("nan")
    if len(values) == 1:
        return values[0], 0.0
    return statistics.mean(values), statistics.stdev(values)


def get_primary(event):
    """Return the primary trajectory.

    For this gun test there should be exactly one trajectory with ParentId < 0.
    """
    primaries = [
        traj for traj in event.Trajectories
        if traj.GetParentId() < 0
    ]

    if len(primaries) != 1:
        raise RuntimeError(
            f"Expected exactly one primary trajectory; found {len(primaries)}"
        )

    return primaries[0]


def get_tpc_segments(event):
    """Return the volTPCActive hit-segment vector."""
    detectors = event.SegmentDetectors

    try:
        return detectors["volTPCActive"]
    except Exception:
        return []


def analyze(filename):
    f = ROOT.TFile.Open(filename)

    if not f or f.IsZombie():
        raise RuntimeError(f"Could not open {filename}")

    tree = f.Get("EDepSimEvents")
    if not tree:
        raise RuntimeError(f"{filename}: EDepSimEvents tree not found")

    ntraj = []
    nsegments = []

    total_edep = []
    total_track_length = []

    primary_edep = []
    primary_track_length = []
    primary_dedx = []

    secondary_species = Counter()

    primary_names = Counter()
    primary_pdgs = Counter()

    first_primary_info = None

    for i in range(tree.GetEntries()):
        tree.GetEntry(i)
        event = tree.Event

        trajectories = event.Trajectories
        primary = get_primary(event)

        primary_id = int(primary.GetTrackId())
        primary_name = str(primary.GetName())
        primary_pdg = int(primary.GetPDGCode())

        primary_names[primary_name] += 1
        primary_pdgs[primary_pdg] += 1

        if first_primary_info is None:
            p4 = primary.GetInitialMomentum()
            first_primary_info = {
                "name": primary_name,
                "pdg": primary_pdg,
                "track_id": primary_id,
                "p": p4.P(),
                "E": p4.E(),
                "mass": p4.M(),
            }

        ntraj.append(len(trajectories))

        # What are all those extra trajectories?
        for traj in trajectories:
            if traj.GetParentId() >= 0:
                secondary_species[str(traj.GetName())] += 1

        segments = get_tpc_segments(event)
        nsegments.append(len(segments))

        evt_total_edep = 0.0
        evt_total_length = 0.0

        evt_primary_edep = 0.0
        evt_primary_length = 0.0

        for seg in segments:
            edep = float(seg.GetEnergyDeposit())
            length = float(seg.GetTrackLength())

            evt_total_edep += edep
            evt_total_length += length

            # With hitSeparation = -1 mm, this should be a particularly
            # clean way to identify segments belonging to our primary.
            contributors = [
                int(c) for c in seg.GetContributors()
            ]

            if primary_id in contributors:
                evt_primary_edep += edep
                evt_primary_length += length

        total_edep.append(evt_total_edep)
        total_track_length.append(evt_total_length)

        primary_edep.append(evt_primary_edep)
        primary_track_length.append(evt_primary_length)

        if evt_primary_length > 0:
            primary_dedx.append(
                evt_primary_edep / evt_primary_length
            )

    print()
    print("=" * 72)
    print(os.path.basename(filename))
    print("=" * 72)

    print(f"Events stored             : {tree.GetEntries()}")

    if first_primary_info:
        print()
        print("Primary")
        print(f"  name                    : {first_primary_info['name']}")
        print(f"  PDG                     : {first_primary_info['pdg']}")
        print(f"  mass                    : {first_primary_info['mass']:.6f} MeV")
        print(f"  initial momentum        : {first_primary_info['p']:.6f} MeV/c")
        print(f"  initial total energy    : {first_primary_info['E']:.6f} MeV")

    quantities = [
        ("trajectories/event", ntraj),
        ("TPC segments/event", nsegments),
        ("total TPC Edep [MeV]", total_edep),
        ("total track length [mm]", total_track_length),
        ("primary TPC Edep [MeV]", primary_edep),
        ("primary track length [mm]", primary_track_length),
        ("primary dE/dx [MeV/mm]", primary_dedx),
    ]

    print()
    print("Event statistics")
    for label, values in quantities:
        mean, std = mean_std(values)
        print(f"  {label:28s}: {mean:12.6g} +/- {std:12.6g}")

    print()
    print("Most common secondary trajectories")
    for name, count in secondary_species.most_common(12):
        per_event = count / tree.GetEntries()
        print(f"  {name:18s}: {count:7d}   ({per_event:8.2f}/event)")

    print()

    f.Close()


if len(sys.argv) < 2:
    print(
        f"Usage: {sys.argv[0]} FILE.root [FILE2.root ...]",
        file=sys.stderr,
    )
    sys.exit(1)

for filename in sys.argv[1:]:
    analyze(filename)
