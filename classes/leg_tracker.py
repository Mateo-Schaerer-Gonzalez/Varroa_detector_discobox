"""Finds a mite's legs in each frame and follows them.

A mite is about 14 pixels long and a leg 1 to 2 pixels wide and 2 to 4 long:
too little to see a leg's joints, enough to see where it ends. The body is
smooth and wide, a leg is thin, and that is what tells them apart:

    leg image   the mite's darkness (the share of the plate's light it takes
                away), enlarged, minus its morphological opening with a disc
                wider than a leg. The opening keeps what the disc fits into,
                the body; what is left is what is thinner than the disc.
    legs        the local maxima of the leg image outside the body, close to
                it and dark enough. Each is one leg, or two lying side by
                side; its place is the centre of the darkness around the
                maximum, to a fraction of a pixel. Where it ends (its tip) is
                kept too, but is less sure: see the notebook.
    tracks      the legs of one frame are matched to those of the frames
                before, each to the nearest (the smallest total distance,
                none further than `link`), relative to the body's centre: a
                mite moved as a whole keeps its legs where they were.

notebooks/leg_tracking.ipynb shows what it sees.
"""

from dataclasses import dataclass

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

EDGE = 6  # the outermost pixels of a patch: the plate, never the mite


@dataclass
class Legs:
    """What one frame shows. Positions are in pixels of the patch."""
    centre: np.ndarray  # (2,): the body's centre, (x, y)
    axis: float         # the direction of the body's long axis, radians, in [0, pi)
    xy: np.ndarray      # (legs, 2): where each leg is, (x, y): the centre of its darkness
    tip: np.ndarray     # (legs, 2): where it ends, (x, y)
    length: np.ndarray  # (legs,): how far its end is from the body's edge, pixels
    mass: np.ndarray    # (legs,): the pixels it would cover if it were black

    def __len__(self):
        return len(self.xy)


@dataclass
class Tracks:
    """The legs of one mite followed through its frames. A leg not seen in a
    frame is nan there."""
    xy: np.ndarray      # (legs, frames, 2): each leg's place relative to the body's centre, (x, y)
    tip: np.ndarray     # (legs, frames, 2): its end, relative to the body's centre
    length: np.ndarray  # (legs, frames): how far its end is from the body's edge, pixels
    mass: np.ndarray    # (legs, frames)
    centre: np.ndarray  # (frames, 2): the body's centre in the patch
    axis: np.ndarray    # (frames,): the body's long axis, radians
    count: np.ndarray   # (frames,): the legs found in each frame, followed or not

    def __len__(self):
        return len(self.xy)

    @property
    def seen(self):
        """(legs, frames): whether the leg was found in the frame."""
        return np.isfinite(self.xy[..., 0])

    def frames(self, first, end):
        """The same tracks over the frames first to end only (the legs not
        seen in them are kept, all nan)."""
        return Tracks(self.xy[:, first:end], self.tip[:, first:end], self.length[:, first:end], self.mass[:, first:end],
                      self.centre[first:end], self.axis[first:end], self.count[first:end])


class LegTracker:
    """`scale`: how much the patch is enlarged before anything is measured.
    `leg_width`: the disc's diameter in pixels; what is thinner is a leg.
    `threshold`: how dark a leg has to be, as a share of the body's darkness.
    `reach`: how far from the body's edge a leg can be, in pixels.
    `window`: the pixels around a leg's maximum its place is measured in.
    `link`: how far a leg can go from one frame to the next, in pixels.
    `patience`: the frames a leg can go unseen and still be the same leg.
    `at_least`: the frames a leg has to be seen in to count as one."""

    def __init__(self, scale=4, leg_width=5.0, threshold=0.12, reach=4.0, window=1.5, link=1.5, patience=20, at_least=5):
        self.scale = scale
        self.leg_width = leg_width
        self.threshold = threshold
        self.reach = reach
        self.link = link
        self.patience = patience
        self.at_least = at_least
        self.window = window
        side = int(round(leg_width * scale)) | 1
        self._disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (side, side))
        near = int(round(1.0 * scale)) * 2 + 1  # a leg's own neighbourhood: one pixel around its maximum
        self._near = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (near, near))

    # ---- one frame ----

    def leg_image(self, grey):
        """(darkness, body, legs) of one grey frame (height, width), each
        enlarged `scale` times: the mite's darkness, what of it the disc fits
        into, and the rest."""
        grey = np.asarray(grey, dtype=np.float32)
        edge = np.ones(grey.shape, dtype=bool)
        edge[EDGE:-EDGE, EDGE:-EDGE] = False
        plate = float(np.median(grey[edge]))
        if plate <= 0:
            empty = np.zeros((grey.shape[0] * self.scale, grey.shape[1] * self.scale), dtype=np.float32)
            return empty, empty, empty
        dark = np.clip(1 - grey / plate, 0, None)
        dark = cv2.resize(dark, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_CUBIC)
        dark = np.clip(dark, 0, None)
        body = cv2.morphologyEx(dark, cv2.MORPH_OPEN, self._disc)
        return dark, body, dark - body

    def detect(self, grey):
        """The legs in one grey frame (height, width): a Legs."""
        dark, body, legs = self.leg_image(grey)
        none = Legs(np.full(2, np.nan), np.nan, np.zeros((0, 2)), np.zeros((0, 2)), np.zeros(0), np.zeros(0))
        peak = float(body.max())
        if peak <= 0:
            return none
        # the body: the largest piece at least half as dark as its darkest
        _n, labels, stats, _centres = cv2.connectedComponentsWithStats((body > 0.5 * peak).astype(np.uint8))
        if len(stats) < 2:
            return none
        inside = labels == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        weight = body * inside
        total = float(weight.sum())
        yy, xx = np.mgrid[:dark.shape[0], :dark.shape[1]].astype(np.float32)
        x, y = float((weight * xx).sum() / total), float((weight * yy).sum() / total)
        dx, dy = xx - x, yy - y
        mxx, myy, mxy = (float((weight * product).sum() / total) for product in (dx * dx, dy * dy, dx * dy))
        axis = (0.5 * np.arctan2(2 * mxy, mxx - myy)) % np.pi

        outside = cv2.distanceTransform((~inside).astype(np.uint8), cv2.DIST_L2, 5) / self.scale  # pixels from the body's edge
        smooth = cv2.GaussianBlur(legs, (0, 0), 0.4 * self.scale)
        centre = (np.array([x, y]) + 0.5) / self.scale - 0.5
        none = Legs(centre, axis, np.zeros((0, 2)), np.zeros((0, 2)), np.zeros(0), np.zeros(0))
        dark_enough = (outside > 0) & (outside <= self.reach) & (smooth > self.threshold * peak)
        ys, xs = np.nonzero(dark_enough & (smooth >= cv2.dilate(smooth, self._near)))
        if not len(xs):
            return none
        # two maxima on one flat top are one leg: keep the darker, drop what is within a pixel of it
        kept = []
        for index in np.argsort(-smooth[ys, xs]):
            if all(np.hypot(xs[index] - xs[k], ys[index] - ys[k]) > self.scale for k in kept):
                kept.append(index)
        tops = np.stack([xs[kept], ys[kept]], axis=1).astype(np.float32)
        # each leg is what is dark enough around its maximum: every such point goes to the nearest maximum
        py, px = np.nonzero(dark_enough)
        owner = np.argmin(((np.stack([px, py], axis=1)[:, None].astype(np.float32) - tops[None]) ** 2).sum(axis=-1), axis=1)
        weight, away = np.clip(legs[py, px], 0, None), outside[py, px]
        xy, tip, length, mass = [], [], [], []
        for leg in range(len(tops)):
            mine = owner == leg
            w = weight[mine]
            if w.sum() <= 0:
                continue
            # its place: the centre of the darkness close to its maximum (the whole of what is dark enough
            # grows and shrinks with the noise, and its centre with it)
            close = mine & ((px - tops[leg, 0]) ** 2 + (py - tops[leg, 1]) ** 2 <= (self.window * self.scale) ** 2)
            xy.append((np.average(px[close], weights=weight[close] + 1e-6), np.average(py[close], weights=weight[close] + 1e-6)))
            # where it ends: its points within half a pixel of its furthest from the body
            end = mine & (away >= away[mine].max() - 0.5)
            tip.append((np.average(px[end], weights=weight[end] + 1e-6), np.average(py[end], weights=weight[end] + 1e-6)))
            length.append(away[mine].max())
            mass.append(w.sum() / self.scale ** 2)
        if not xy:
            return none
        to_pixels = lambda points: (np.array(points, dtype=float) + 0.5) / self.scale - 0.5
        return Legs(centre, axis, to_pixels(xy), to_pixels(tip), np.array(length), np.array(mass))

    # ---- through the frames ----

    def track(self, frames):
        """The legs of one mite through `frames` (frames, height, width), in
        the order they were taken: a Tracks."""
        return self.link_up([self.detect(frame) for frame in frames])

    def link_up(self, detections):
        """A Tracks from each frame's Legs."""
        n_frames = len(detections)
        tracks = []   # each {"at": {frame: index of the leg in that frame}, "xy": where it was last, "last": frame}
        for frame, legs in enumerate(detections):
            if not len(legs):
                continue
            here = legs.xy - legs.centre
            open_tracks = [track for track in tracks if frame - track["last"] <= self.patience]
            taken = set()
            if open_tracks:
                apart = np.linalg.norm(np.array([track["xy"] for track in open_tracks])[:, None] - here[None], axis=-1)
                # nothing further than `link`: such a pair costs more than leaving both alone
                rows, columns = linear_sum_assignment(np.where(apart <= self.link, apart, 1e6))
                for row, column in zip(rows, columns):
                    if apart[row, column] <= self.link:
                        open_tracks[row]["at"][frame] = column
                        open_tracks[row]["xy"] = here[column]
                        open_tracks[row]["last"] = frame
                        taken.add(column)
            for column in range(len(legs)):
                if column not in taken:
                    tracks.append({"at": {frame: column}, "xy": here[column], "last": frame})
        tracks = [track for track in tracks if len(track["at"]) >= self.at_least]
        xy, tip = (np.full((len(tracks), n_frames, 2), np.nan) for _each in range(2))
        length, mass = (np.full((len(tracks), n_frames), np.nan) for _each in range(2))
        for leg, track in enumerate(tracks):
            for frame, index in track["at"].items():
                found = detections[frame]
                xy[leg, frame] = found.xy[index] - found.centre
                tip[leg, frame] = found.tip[index] - found.centre
                length[leg, frame] = found.length[index]
                mass[leg, frame] = found.mass[index]
        return Tracks(xy, tip, length, mass, np.array([found.centre for found in detections]).reshape(n_frames, 2),
                      np.array([found.axis for found in detections], dtype=float),
                      np.array([len(found) for found in detections]))

    # ---- what the legs did ----

    @staticmethod
    def _by_recording(points, frames_per_recording):
        """(legs, frames, 2) as (legs, recordings, frames of one, 2), and in
        how many of a recording's frames each leg was seen."""
        n_recordings = points.shape[1] // frames_per_recording
        points = points[:, :n_recordings * frames_per_recording].reshape(len(points), n_recordings, frames_per_recording, 2)
        return points, np.isfinite(points[..., 0]).sum(axis=2)

    @staticmethod
    def places(tracks, frames_per_recording, of="xy"):
        """Each leg's place in each recording: the mean of where it was in the
        recording's frames, (legs, recordings, 2), nan where it was not seen.
        `of`: "xy" for the leg's place, "tip" for its end."""
        points, seen = LegTracker._by_recording(getattr(tracks, of), frames_per_recording)
        return np.where(seen[..., None] > 0, np.nansum(points, axis=2) / np.maximum(seen, 1)[..., None], np.nan)

    @staticmethod
    def swings(tracks, frames_per_recording, at_least=3, of="xy"):
        """How far each leg moved within each recording, in pixels: how far it
        was from its mean place (root mean square over the frames, doubled:
        about its swing from side to side). (legs, recordings), nan where the
        leg was seen in fewer than `at_least` of the recording's frames."""
        points, seen = LegTracker._by_recording(getattr(tracks, of), frames_per_recording)
        mean = np.nansum(points, axis=2) / np.maximum(seen, 1)[..., None]
        away = np.nansum(((points - mean[:, :, None]) ** 2).sum(axis=-1), axis=2) / np.maximum(seen, 1)
        return np.where(seen >= at_least, 2 * np.sqrt(away), np.nan)

    @staticmethod
    def movement(tracks, frames_per_recording, at_least=3, of="xy"):
        """How far the legs moved within each recording, in pixels: the
        largest of the legs' swings(). 0 for a recording without a leg seen in
        `at_least` of its frames. Returns (recordings,)."""
        swing = LegTracker.swings(tracks, frames_per_recording, at_least, of)
        if not len(swing):
            return np.zeros(swing.shape[1])
        return np.nan_to_num(swing).max(axis=0)


# ---- a mite whose legs are known, to measure the tracker against ----

def synthetic_mite(legs, size=46, body=(4.5, 6.5), turn=20.0, darkness=0.85, leg_darkness=0.6, leg_width=1.3,
                   plate=110.0, noise=1.0, blur=0.7, shift=(0.0, 0.0), rng=None, fine=8):
    """One frame (size, size) float32 of a dark oval with legs on a bright
    plate, drawn `fine` times finer than a pixel and brought down, so a leg
    can be anywhere to a fraction of a pixel.

    `legs`: per leg (angle, length): the direction it leaves the body's centre
    in, in degrees (0: to the right, 90: down), and how far it reaches past
    the body's edge, in pixels. `shift` moves the whole mite, in pixels.
    `noise`: the camera's, in grey levels (standard deviation).

    Returns (frame, tips): tips (legs, 2) is where each leg ends, (x, y)."""
    side = size * fine
    centre = np.array([size / 2 + shift[0], size / 2 + shift[1]])
    canvas = np.zeros((side, side), dtype=np.float32)
    tips = []
    a, b = body
    for angle, length in legs:
        direction = np.array([np.cos(np.radians(angle)), np.sin(np.radians(angle))])
        # the body's edge in that direction: an ellipse turned by `turn`
        along = np.radians(angle - turn)
        edge = a * b / np.hypot(b * np.cos(along), a * np.sin(along))
        tip = centre + direction * (edge + length)
        tips.append(tip)
        start = centre + direction * (edge - 1.0)
        cv2.line(canvas, tuple(int(round(v)) for v in (start + 0.5) * fine - 0.5),
                 tuple(int(round(v)) for v in (tip + 0.5) * fine - 0.5), leg_darkness, max(int(round(leg_width * fine)), 1), cv2.LINE_AA)
    cv2.ellipse(canvas, tuple(int(round(v)) for v in (centre + 0.5) * fine - 0.5), (int(round(a * fine)), int(round(b * fine))),
                turn, 0, 360, darkness, -1, cv2.LINE_AA)
    dark = cv2.resize(canvas, (size, size), interpolation=cv2.INTER_AREA)
    dark = cv2.GaussianBlur(dark, (0, 0), blur)
    frame = plate * (1 - dark)
    if noise:
        frame = frame + (rng or np.random.default_rng()).normal(0, noise, frame.shape)
    return frame.astype(np.float32), np.array(tips).reshape(-1, 2)
