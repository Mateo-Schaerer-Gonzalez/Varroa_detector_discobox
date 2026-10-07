import cv2
import numpy as np
import pytest

from classes import recording_change
from classes.recording_change import RecordingChange


def mite_image(dx=0.0, dy=0.0, size=40, blob=((20, 20), 5)):
    """A dark mite on a grey plate with some texture, moved by (dx, dy)."""
    rng = np.random.default_rng(0)
    image = np.full((size, size), 120, dtype=np.float32) + cv2.GaussianBlur(
        rng.normal(0, 6, (size, size)).astype(np.float32), (0, 0), 2)
    cv2.circle(image, blob[0], blob[1], 30, -1, lineType=cv2.LINE_AA)
    image = cv2.GaussianBlur(image, (0, 0), 1)
    return cv2.warpAffine(image, np.float32([[1, 0, dx], [0, 1, dy]]), image.shape[::-1],
                          flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT101)


def test_the_same_image_does_not_change():
    assert RecordingChange().change(mite_image(), mite_image()) == pytest.approx(0, abs=1e-4)


def test_a_brighter_light_is_no_change():
    assert RecordingChange().change(mite_image(), 1.1 * mite_image()) == pytest.approx(0, abs=1e-3)


def test_a_mite_that_turned_changes():
    turned = mite_image(blob=((22, 20), 5))
    assert RecordingChange().change(mite_image(), turned) > 1


def test_a_plate_that_moved_is_no_change():
    """Every mite moved by the same: the plate's shift, taken out."""
    mites = [np.stack([mite_image(), mite_image(0.4, -0.3)]) for _mite in range(3)]
    change = RecordingChange()
    assert change.plate_shifts(mites)[0] == pytest.approx([0.4, -0.3], abs=0.05)
    assert change.changes(mites).max() < 0.2
    assert change.change(mites[0][0], mites[0][1]) > 2 * change.changes(mites).max()


def test_the_changes_are_per_mite_and_pair_of_recordings():
    still = np.stack([mite_image()] * 4)
    turns = np.stack([mite_image(), mite_image(), mite_image(blob=((22, 20), 5)), mite_image(blob=((22, 20), 5))])
    changes = RecordingChange().changes([still, still, turns])
    assert changes.shape == (3, 3)
    assert changes[2, 1] > 1 and changes[2, [0, 2]].max() < 0.2 and changes[:2].max() < 0.2
    assert RecordingChange().changes([still, still, turns], lag=2).shape == (3, 2)


def test_a_recording_s_image_is_the_mean_of_its_frames_in_grey():
    patches = np.zeros((2, 4, 3, 3, 3), dtype=np.float32)
    patches[0, :2] = 10
    patches[1, ..., 0] = 30
    images = recording_change.recording_images(patches)
    assert images.shape == (2, 3, 3)
    assert images[0] == pytest.approx(5) and images[1] == pytest.approx(10)


def test_the_noise_floor_is_what_two_recordings_of_noise_differ_by():
    rng = np.random.default_rng(1)
    patches = 100 + rng.normal(0, 4, (60, 10, 20, 20)).astype(np.float32)
    images = recording_change.recording_images(patches)
    between = np.abs(images[1:] - images[:-1]).mean()
    assert recording_change.noise_floor(patches).mean() == pytest.approx(between, rel=0.05)


def test_the_pairs_of_recordings_by_the_labels():
    moving = np.array([[1, 0, 1, 0, 0, 0, 0],
                       [0, 0, 0, 0, 0, 0, 0],
                       [1, 0, 0, 0, 0, 0, 0]], dtype=bool)
    groups = recording_change.groups(moving, times=[0, 10, 20, 30, 40, 50, 60], death_minutes=20)
    assert groups["alive"].tolist() == [[True, True, False, False, False, False], [False] * 6, [False] * 6]
    assert groups["waiting"][0].tolist() == [False, False, True, True, False, False]
    assert groups["dead"][0].tolist() == [False, False, False, False, True, True]
    assert groups["dead"][2].tolist() == [False, False, True, True, True, True]
    assert not any(groups[name][1].any() for name in groups)  # never moved
