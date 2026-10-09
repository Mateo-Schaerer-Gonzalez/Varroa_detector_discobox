"""What the result pages draw over a mite (classes/outline_view.py): the dots
round its outline and the arrow toward the side its outline changes on."""

import numpy as np

from classes.outline_view import OutlineView
from detector_test import _mite_frames

LEG = [0, 3, 0, 3, 0, 3]  # a leg on the mite's left, out in every other frame


def test_the_arrow_points_to_the_side_of_the_leg_that_moves():
    seen = OutlineView.describe(_mite_frames(LEG), x0=100, y0=200)
    assert abs(seen["x"] - 123) < 1.5 and abs(seen["y"] - 223) < 1.5  # the middle of the 46 pixel patch, in the image
    assert len(seen["dots"]) == 64
    assert seen["share"] > 0.5
    assert seen["arrow"][0] < seen["x"] - 3                             # to the left
    darkest = max(seen["dots"], key=lambda dot: dot[2])
    assert darkest[2] == 1.0 and darkest[0] < seen["x"]


def test_a_mite_that_does_not_move_has_next_to_no_arrow():
    noise = np.random.default_rng(0).normal(0, 1, (6, 46, 46, 1)).astype(np.float32)
    seen = OutlineView.describe(_mite_frames([0] * 6) + noise)
    assert seen["share"] < 0.2
    assert np.hypot(seen["arrow"][0] - seen["x"], seen["arrow"][1] - seen["y"]) < 2.5


def test_a_patch_without_a_mite_has_no_outline():
    assert OutlineView.describe(np.full((6, 46, 46, 1), 115, dtype=np.float32)) is None
