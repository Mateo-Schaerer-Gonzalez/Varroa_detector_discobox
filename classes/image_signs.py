"""Two signs of death the movement score does not have, read off each mite's
mean image in every recording (notebooks/alive_dead_shrinkage.ipynb and
notebooks/dead_mite_change.ipynb, on the long run):

    shrinkage   a dead mite's outline draws in by a fraction of a pixel, so its
                silhouette (the sum of how much of the plate's light it takes
                away) falls below the highest level it has had. Slow: it
                confirms a death hours later, it does not time it.
    change      a live mite's image changes from one recording to the next even
                when it is still in both (it moved in the minutes between); a
                dead one's does not, beyond the camera's noise.

ImageSigns measures both, a recording at a time, from the mean images of the
mites' patches; ImageDeaths turns them into a death per mite, in recordings
as calibration.death_recording() counts them: the recording from which the mite
is dead, the number of recordings for one not dead by the end.
"""

import numpy as np
from scipy.ndimage import median_filter

from classes.recording_change import RecordingChange


class ImageSigns:
    PAD = 16    # pixels around a mite's box its patch is cut with: its legs and the plate around them
    MARGIN = 8  # pixels around the box that still count as the mite (legs)
    EDGE = 6    # the outermost pixels of a patch: the plate, never the mite

    def __init__(self, mite_ids):
        self.mite_ids = list(mite_ids)
        self.silhouettes = {mite_id: [] for mite_id in self.mite_ids}
        self.changes = {mite_id: [] for mite_id in self.mite_ids}
        self._before = None
        self._compare = RecordingChange(self.MARGIN)

    @staticmethod
    def mean_image(patch):
        """A mite's image in one recording: the mean of its frames `patch`
        (frames, h, w) or (frames, h, w, channels), in grey, float32."""
        patch = np.asarray(patch, dtype=np.float32)
        if patch.ndim == 4:
            patch = patch.mean(axis=-1)
        return np.ascontiguousarray(patch.mean(axis=0))

    @classmethod
    def silhouette(cls, image):
        """The pixels the mite would cover if it were black all over: each
        pixel's darkness, the share of the plate's light it takes away, summed
        over the box and MARGIN around it. The plate's light is the median of
        the patch's outermost EDGE pixels, so a lamp a little brighter or darker
        in one recording changes nothing."""
        image = np.asarray(image, dtype=np.float32)
        outer = np.ones(image.shape, dtype=bool)
        outer[cls.EDGE:-cls.EDGE, cls.EDGE:-cls.EDGE] = False
        plate = float(np.median(image[outer]))
        if plate <= 0:
            return 0.0
        inside = cls.PAD - cls.MARGIN
        dark = np.clip(1 - image[inside:image.shape[0] - inside, inside:image.shape[1] - inside] / plate, 0, None)
        return float(dark.sum())

    def add(self, images):
        """One recording: {mite id: its mean_image() of its box grown by PAD}.
        The change to the recording before has the plate's shift between the two
        taken out, measured on every mite (RecordingChange)."""
        inside = self.PAD - self.MARGIN
        cut = [np.ascontiguousarray(images[mite_id][inside:-inside, inside:-inside]) for mite_id in self.mite_ids]
        for mite_id in self.mite_ids:
            self.silhouettes[mite_id].append(round(self.silhouette(images[mite_id]), 3))
        if self._before is None:
            changes = [None] * len(self.mite_ids)
        else:
            changes = [round(value, 3) for value in self._compare.pair_changes(self._before, cut)]
        for mite_id, change in zip(self.mite_ids, changes):
            self.changes[mite_id].append(change)
        self._before = cut

    def measured(self):
        """{mite id: {silhouette, change}}, one value per recording each; the
        change None in the first recording, which has none before it."""
        return {mite_id: {"silhouette": self.silhouettes[mite_id], "change": self.changes[mite_id]}
                for mite_id in self.mite_ids}


class ImageDeaths:
    # Each limit as the long run set it (the notebooks): the one that best told the
    # recordings up to a mite's last labelled movement from those long after it.
    SHRINK_LIMIT = -0.042  # a silhouette this far below its highest is shrunk...
    SHRINK_RUN = 5         # ...once it stays there this many recordings in a row
    LEVEL_WINDOW = 5       # recordings in the running median the highest level is taken over
    CHANGE_LIMIT = 0.75    # grey levels: a still recording's noise reaches it 1 time in 1000

    @classmethod
    def below_highest(cls, silhouette):
        """Per recording, the silhouette against the highest level it has had so
        far (the highest of its running medians over the last LEVEL_WINDOW
        recordings), as a share: 0 at its highest, negative below. It only looks
        back, and a mite whose first recordings were not its usual self (it
        stood up, it was turned) is not held to them."""
        values = np.asarray(silhouette, dtype=float)
        if not len(values):
            return values
        level = median_filter(values, cls.LEVEL_WINDOW, mode="nearest", origin=cls.LEVEL_WINDOW // 2)
        with np.errstate(divide="ignore", invalid="ignore"):
            return values / np.maximum.accumulate(level) - 1

    @classmethod
    def shrinkage(cls, silhouette):
        """The recording from which a mite is dead by its silhouette: the first
        of SHRINK_RUN in a row below SHRINK_LIMIT; the number of recordings when
        it never is."""
        shrunk = np.nan_to_num(cls.below_highest(silhouette), nan=0.0) < cls.SHRINK_LIMIT
        for at in range(len(shrunk) - cls.SHRINK_RUN + 1):
            if shrunk[at:at + cls.SHRINK_RUN].all():
                return at
        return len(shrunk)

    @classmethod
    def change(cls, change):
        """The recording from which a mite is dead by its image: the one after
        the last whose image changed from the one before by more than
        CHANGE_LIMIT, the one before having changed too (one change alone may be
        anything: a mite walking past, a speck of dust); 0 when there is none."""
        changed = [value is not None and value > cls.CHANGE_LIMIT for value in change]
        for at in range(len(changed) - 1, 0, -1):
            if changed[at] and changed[at - 1]:
                return at + 1
        return 0

    @classmethod
    def deaths(cls, measured):
        """{shrinkage, change}: both deaths of one mite from ImageSigns.measured()'s row."""
        return {"shrinkage": cls.shrinkage(measured["silhouette"]), "change": cls.change(measured["change"])}
