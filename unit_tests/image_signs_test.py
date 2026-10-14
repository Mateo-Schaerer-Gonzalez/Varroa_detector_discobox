"""The signs of death in a mite's mean images: its silhouette shrinking, and its
image no longer changing between recordings."""

import numpy as np
import pytest

from classes.image_signs import ImageDeaths, ImageSigns

SIDE = 10  # the mite's box, in pixels


def mite_image(radius=4.0, plate=120.0, dark=0.8):
    """A mite's mean image as ImageSigns takes it: a dark disc on the plate, in
    its box grown by ImageSigns.PAD."""
    size = SIDE + 2 * ImageSigns.PAD
    yy, xx = np.mgrid[:size, :size]
    centre = (size - 1) / 2
    inside = np.clip(radius + 0.5 - np.hypot(xx - centre, yy - centre), 0, 1)  # part-covered pixels count by their part
    return (plate * (1 - dark * inside)).astype(np.float32)


def test_the_silhouette_counts_the_pixels_a_black_mite_would_cover():
    disc = np.pi * 4.0 ** 2
    assert ImageSigns.silhouette(mite_image(dark=1.0)) == pytest.approx(disc, rel=0.05)
    # a brighter lamp changes nothing, a smaller mite does
    assert ImageSigns.silhouette(mite_image(plate=150.0)) == pytest.approx(ImageSigns.silhouette(mite_image()), rel=1e-4)
    assert ImageSigns.silhouette(mite_image(radius=3.8)) < ImageSigns.silhouette(mite_image())


def test_the_mean_image_is_grey_and_over_the_frames():
    frames = np.stack([np.full((3, 4, 3), value, dtype=np.uint8) for value in (10, 30)])
    image = ImageSigns.mean_image(frames)
    assert image.shape == (3, 4) and image.dtype == np.float32 and np.allclose(image, 20)


def test_signs_are_measured_a_recording_at_a_time():
    signs = ImageSigns(["a", "b"])
    for radius in (4.0, 4.0, 3.5):
        signs.add({"a": mite_image(radius), "b": mite_image()})
    measured = signs.measured()
    assert measured["a"]["change"][0] is None and measured["b"]["change"][0] is None
    assert measured["b"]["change"][1:] == [pytest.approx(0, abs=0.05)] * 2
    assert measured["a"]["change"][2] > 1
    assert measured["a"]["silhouette"][2] < measured["a"]["silhouette"][0]


def test_a_mite_is_dead_by_its_silhouette_once_it_stays_shrunk():
    level = [100.0] * 6
    assert ImageDeaths.shrinkage(level + [94.0] * 6) == 6
    # a dip shorter than the run is a mite turning, not shrinking
    assert ImageDeaths.shrinkage(level + [94.0] * 3 + level) == 15
    # the highest level counts, not the first
    assert ImageDeaths.shrinkage([90.0] * 3 + level + [94.0] * 6) == 9
    assert ImageDeaths.below_highest(level)[-1] == 0


def test_a_mite_is_dead_by_its_image_after_its_last_change():
    assert ImageDeaths.change([None, 2.0, 2.0, 0.3, 2.0, 0.3]) == 3   # a lone change later is not counted
    assert ImageDeaths.change([None, 2.0, 2.0, 2.0]) == 4            # changing to the end: past the last recording
    assert ImageDeaths.change([None, 0.3, 0.3]) == 0
