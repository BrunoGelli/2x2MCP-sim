"""Sampling-domain guards for accepted-stage MCP flux models.

A histogram cell that touches the Pythia geometry boundary can extend slightly
outside the conditioning domain.  Accepted-stage resampling therefore rejects
only *interpolation artifacts* that no longer satisfy the original Pythia
geometry_id=1 window.  This is distinct from the independent 2x2/global
geometry audit, which is never used to reject accepted-stage events.
"""

from __future__ import annotations

import numpy as np

BASELINE_M = 1040.0
X_RANGES_M = ((-0.65, -0.05), (0.05, 0.65))
Y_RANGE_M = (-0.70, 0.70)


def pythia_condition_mask(theta_x: np.ndarray, theta_y: np.ndarray) -> np.ndarray:
    x = np.tan(theta_x) * BASELINE_M
    y = np.tan(theta_y) * BASELINE_M
    in_x = (
        ((x >= X_RANGES_M[0][0]) & (x <= X_RANGES_M[0][1]))
        | ((x >= X_RANGES_M[1][0]) & (x <= X_RANGES_M[1][1]))
    )
    in_y = (y >= Y_RANGE_M[0]) & (y <= Y_RANGE_M[1])
    return in_x & in_y


def make_conditioned_draw(base_draw):
    """Return a draw_model-compatible function with accepted-stage support guard."""

    def draw(rng, data, meta, n: int):
        if meta.get("flux_stage") != "accepted":
            return base_draw(rng, data, meta, n)

        which_parts = []
        e_parts = []
        tx_parts = []
        ty_parts = []
        have = 0
        attempts = 0
        while have < n:
            need = n - have
            # Mild oversampling is normally enough because the training sample
            # itself is accepted.  A large rejection fraction is a model-quality
            # warning rather than something to hide.
            batch = max(256, int(need * 1.25))
            which, energy, thx, thy = base_draw(rng, data, meta, batch)
            mask = pythia_condition_mask(thx, thy)
            if np.any(mask):
                which_parts.append(which[mask])
                e_parts.append(energy[mask])
                tx_parts.append(thx[mask])
                ty_parts.append(thy[mask])
                have += int(np.count_nonzero(mask))
            attempts += batch
            if attempts > max(1_000_000, 1000 * n) and have == 0:
                raise RuntimeError(
                    "Accepted-stage histogram produced no samples inside the original "
                    "Pythia conditioning window. Check model binning/coordinates."
                )

        which = np.concatenate(which_parts)[:n]
        energy = np.concatenate(e_parts)[:n]
        thx = np.concatenate(tx_parts)[:n]
        thy = np.concatenate(ty_parts)[:n]
        return which, energy, thx, thy

    return draw
