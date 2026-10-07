"""How much a mite's image changes from one recording to another.

A dead mite lies as it is: its image in one recording is its image in the next,
but for the camera's noise. A live one shifts a leg or turns between two
recordings even when it is still in both.

Two things change every mite's image between recordings without the mite
doing anything, and are taken out first: the plate sits a fraction of a pixel
elsewhere (measured on every mite, the median is the plate's, as
classes/plate_stabilizer.py does within a recording), and the light is a
little brighter or darker (the later image is scaled to the mean of the
earlier one). What is left is the mean absolute difference of the two images,
in grey levels.

A mite's image in a recording is the mean of its frames, in grey: the noise of
the single frames averages out, and so does a movement within the recording.
"""

import cv2
import numpy as np

from classes.plate_stabilizer import PlateStabilizer


def recording_images(patches):
    """One mite's image in each recording: `patches` (recordings, frames, h, w)
    or (recordings, frames, h, w, channels) as (recordings, h, w) float32."""
    patches = np.asarray(patches, dtype=np.float32)
    if patches.ndim == 5:
        patches = patches.mean(axis=-1)
    return np.ascontiguousarray(patches.mean(axis=1))


def noise_floor(patches):
    """Per recording, the change() two recordings of a mite that did nothing
    would show, from the camera's noise alone: the difference between the mean
    of every other frame and the mean of the rest, brought to the noise of the
    mean of all the frames. A movement within the recording raises it."""
    patches = np.asarray(patches, dtype=np.float32)
    if patches.ndim == 5:
        patches = patches.mean(axis=-1)
    even, odd = patches[:, 0::2], patches[:, 1::2]
    # noise of a mean of n frames goes by 1/sqrt(n): the two halves differ by
    # sqrt(1/len(even) + 1/len(odd)), two whole recordings by sqrt(2/frames)
    scale = np.sqrt(2 / patches.shape[1]) / np.sqrt(1 / even.shape[1] + 1 / odd.shape[1])
    return np.abs(even.mean(axis=1) - odd.mean(axis=1)).mean(axis=(1, 2)) * scale


class RecordingChange:
    """`margin`: pixels around each mite's box in the images given. The plate's
    shift is measured with them, so the whole outline is in it; the images are
    compared without them."""

    def __init__(self, margin=8):
        self.margin = margin

    def plate_shifts(self, images, lag=1):
        """(recordings - lag, 2): how far (dx, dy) the plate moved from each
        recording to the one `lag` later. `images`: per mite, its
        recording_images()."""
        n_pairs = len(images[0]) - lag
        per_mite = [[PlateStabilizer._shift(mite[at], mite[at + lag]) for at in range(n_pairs)] for mite in images]
        return np.median(np.array(per_mite, dtype=float).reshape(len(images), n_pairs, 2), axis=0)

    def changes(self, images, lag=1):
        """(mites, recordings - lag): each mite's change() from each recording
        to the one `lag` later, the plate's shift between them taken out."""
        shifts = self.plate_shifts(images, lag)
        return np.array([[self.change(mite[at], mite[at + lag], shifts[at]) for at in range(len(shifts))]
                         for mite in images])

    def change(self, earlier, later, shift=(0.0, 0.0)):
        """The mean absolute difference between two images of a mite, the later
        one moved back by the plate's `shift` and scaled to the earlier one's
        brightness."""
        dx, dy = shift
        back = np.float32([[1, 0, -dx], [0, 1, -dy]])
        later = cv2.warpAffine(np.asarray(later, dtype=np.float32), back, later.shape[::-1],
                               flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT101)
        earlier, later = self._inside(np.asarray(earlier, dtype=np.float32)), self._inside(later)
        mean = float(later.mean())
        if mean > 0:
            later = later * (float(earlier.mean()) / mean)
        return float(np.abs(earlier - later).mean())

    def _inside(self, image):
        m = self.margin
        return image[m:image.shape[0] - m, m:image.shape[1] - m] if m else image


def groups(moving, times, death_minutes):
    """Which pairs of recordings (each with the next) show a mite alive, dead or
    in between, by its labels: {alive, waiting, dead}, each (mites, recordings - 1).

        alive     both recordings up to its last movement
        dead      both at least `death_minutes` after its last movement
        waiting   the others: after its last movement, not yet dead

    A mite that never moved is in none of them: it may have been dead from the
    start, or be no mite."""
    moving = np.asarray(moving, dtype=bool)
    times = np.asarray(times, dtype=float)
    moved = moving.any(axis=1)[:, None]
    last = moving.shape[1] - 1 - np.argmax(moving[:, ::-1], axis=1)
    since = times[None, :-1] - times[last][:, None]  # the earlier recording's time since the last movement
    alive = moved & (np.arange(moving.shape[1] - 1)[None] < last[:, None])
    dead = moved & (since >= death_minutes)
    return {"alive": alive, "waiting": moved & ~alive & ~dead, "dead": dead}
