"""Geometry helpers for realistic MCP flux sampling.

The Pythia generator's geometry_id=1 acceptance is a beam-frame approximation.
For an independent post-rotation diagnostic, the 2x2 detector face must be
checked in detector/global coordinates rather than recentered on the NuMI beam
axis.  In MiniRun5 the beam axis crosses near y=-0.42 m, while the approximate
2x2 active boxes are centered on the detector coordinate origin.
"""

from __future__ import annotations

import numpy as np

X_RANGES_M = ((-0.65, -0.05), (0.05, 0.65))
Y_RANGE_M = (-0.70, 0.70)


def acceptance_mask_global(hit: np.ndarray, _beam_axis_at_detector: np.ndarray) -> np.ndarray:
    """Return the approximate 2x2 face mask in detector/global coordinates.

    ``beam_axis_at_detector`` is accepted for API compatibility but is
    deliberately not subtracted: the detector face is centered in detector
    coordinates, while the beam can be offset vertically.
    """
    x = hit[:, 0]
    y = hit[:, 1]
    in_x = (
        ((x >= X_RANGES_M[0][0]) & (x <= X_RANGES_M[0][1]))
        | ((x >= X_RANGES_M[1][0]) & (x <= X_RANGES_M[1][1]))
    )
    in_y = (y >= Y_RANGE_M[0]) & (y <= Y_RANGE_M[1])
    return in_x & in_y
