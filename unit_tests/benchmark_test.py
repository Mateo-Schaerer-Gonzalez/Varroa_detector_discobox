"""The Discobox's original software, asked whether each mite moved."""

import numpy as np

from classes.benchmark import Benchmark


def frames_with_mites(moving_shift):
    """Six noisy frames of a light plate with two dark mites: the one at (20, 20)
    stays, the one at (60, 20) is `moving_shift` pixels further right in every
    frame after the first."""
    rng = np.random.default_rng(0)
    frames = []
    for index in range(6):
        frame = np.full((40, 90), 160, np.int16)
        frame[17:23, 17:23] = 60
        x = 57 + (moving_shift if index else 0)
        frame[17:23, x:x + 6] = 60
        frames.append(np.clip(frame + rng.integers(-4, 5, frame.shape), 0, 255).astype(np.uint8))
    return np.stack(frames)


BOXES = {"still": (16, 16, 24, 24), "moving": (56, 16, 64, 24)}


def test_a_mite_that_shifts_is_called_moving_and_a_still_one_is_not():
    assert Benchmark.calls(frames_with_mites(4), BOXES) == {"still": False, "moving": True}


def test_camera_noise_alone_moves_no_mite():
    assert Benchmark.calls(frames_with_mites(0), BOXES) == {"still": False, "moving": False}


def test_movement_just_beside_a_box_reaches_it():
    """The spots are grown by 5 pixels, as in the original."""
    differential = np.zeros((40, 40), np.uint8)
    differential[20, 20] = 200
    mask = Benchmark.mask(differential)
    assert mask[20, 25] and not mask[20, 27]


def test_a_box_over_the_edge_of_the_image_is_cut_there():
    assert Benchmark.calls(frames_with_mites(4), {"edge": (-5, -5, 3, 3)}) == {"edge": False}


def test_the_circles_are_the_spots_of_the_mask_wherever_they_are():
    """One circle around the mite that shifts, none around the still one: the
    original draws on movement, it knows no mite."""
    circles = Benchmark.circles(frames_with_mites(4))
    assert len(circles) == 1
    x, y = circles[0]
    assert 56 <= x <= 68 and 16 <= y <= 24
    assert Benchmark.circles(frames_with_mites(0)) == []
