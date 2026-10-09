import inspect
from functools import lru_cache
from typing import Optional
import cv2
from classes.app_config import AppConfig, get_default_config
from classes.mite import Mite
from classes.plate_stabilizer import PlateStabilizer
from classes.workers import side_by_side
import numpy as np


@lru_cache(maxsize=None)
def _defaults_of(metric_function):
    """The parameters of a metric's function with their defaults, read from its
    signature once: every mite of every recording asks for them."""
    signature = inspect.signature(metric_function)
    return {name: p.default for name, p in signature.parameters.items() if name != "roi"}


class Analyzer:

    def __init__(self, config: Optional[AppConfig] = None):
        config = config or get_default_config()
        self.config = config
        self.blob_detector = cv2.SimpleBlobDetector_create(self._build_params(self.config.detector))

    @staticmethod
    def _build_params(cfg) -> cv2.SimpleBlobDetector_Params:
        params = cv2.SimpleBlobDetector_Params()

        params.minThreshold = cfg.min_threshold
        params.maxThreshold = cfg.max_threshold
        params.thresholdStep = cfg.threshold_step

        params.filterByColor = cfg.filter_by_color
        params.blobColor = cfg.blob_color

        params.filterByArea = cfg.filter_by_area
        params.minArea = cfg.min_area
        params.maxArea = cfg.max_area

        params.filterByCircularity = cfg.filter_by_circularity
        params.minCircularity = cfg.min_circularity

        params.filterByConvexity = cfg.filter_by_convexity
        params.minConvexity = cfg.min_convexity

        params.filterByInertia = cfg.filter_by_inertia
        params.minInertiaRatio = cfg.min_inertia_ratio

        return params

    def detect(self, masked_image):
        """Returns mites detected in the masked image as a list of Mite instances."""
        keypoints = self.blob_detector.detect(masked_image)
        mites= []
        for kp in keypoints:
            mites.append(Mite(kp.pt[0] - kp.size/2,
                                kp.pt[1] + kp.size/2,
                                kp.pt[0] + kp.size/2,
                                kp.pt[1] - kp.size/2,
                                config = self.config))
        return mites

    def classify_motility(self, mites, image_bursts):
        """Given mites and the frames (by recording), records one motion score per
        recording on each mite; whether it moved follows from those scores."""
        for recording, _times in image_bursts:
            self.score_pool(mites, recording)

    def score_pool(self, mites, frames):
        """Records one motion score on each mite for one pool of frames: `frames`
        is a list, or a stack, of (H, W, C) frames, in order.

        Each mite's ROI is cut from each frame and the cuts stacked, without
        ever holding a second copy of the frames. With mite.stabilize_plate the
        cuts follow the plate as it shakes (see PlateStabilizer). The mites are
        cut and scored side by side (classes/workers.py)."""
        shifts = None
        if self.config.mite.stabilize_plate:
            shifts = PlateStabilizer().shifts(frames, [tuple(mite) for mite in mites])

        def score(mite):
            pad = self.roi_padding(mite.metric, mite.metric_params)
            if shifts is None:
                mite_roi = np.stack([mite.get_ROI(frame, pad) for frame in frames])
            else:
                mite_roi = PlateStabilizer.cut(frames, tuple(mite), pad, shifts)
            return self._motion_score(mite_roi, mite.metric, mite.metric_params), float(mite_roi.mean())

        for mite, (motion, brightness) in zip(mites, side_by_side(score, mites)):
            mite.record_motion(motion, brightness=brightness)

    @staticmethod
    def _metrics():
        return {
            "max_diff": Analyzer._max_diff,
            "mean_diff": Analyzer._mean_diff,
            "vector_diff": Analyzer._vector_diff_min_max,
            "vector_variance": Analyzer._vector_variance,
            "variability": Analyzer._variability,
            "topN_variability": Analyzer._topN_variability,
            "optical_flow": Analyzer.dense_optical_flow,
            "topN_temporal_range": Analyzer._topN_temporal_range,
            "topN_vector_temporal_range": Analyzer._topN_vector_temporal_range,
            "topN_binary_flux": Analyzer._topN_binary_flux,
            "outline_movement": Analyzer._outline_movement,
            "outline_variability": Analyzer._outline_variability,
        }

    @staticmethod
    def metric_names():
        return list(Analyzer._metrics())

    @staticmethod
    def metric_description(metric):
        """First sentence of the metric's docstring."""
        doc = " ".join((inspect.getdoc(Analyzer._metrics()[metric]) or "").split())
        return doc.split(". ")[0].rstrip(".") + "."

    @staticmethod
    def metric_defaults(metric):
        """The tunable parameters of a metric and their default values, e.g.
        {"n": 10} for topN_variability."""
        if metric not in Analyzer._metrics():
            raise ValueError(f"Unknown motility metric: {metric!r}")
        return dict(_defaults_of(Analyzer._metrics()[metric]))

    @staticmethod
    def roi_padding(metric, params=None):
        """Pixels the metric looks beyond the mite's box on each side: its `pad`
        parameter, 0 for a metric without one."""
        return int(Analyzer.check_metric_params(metric, params).get("pad", 0))

    @staticmethod
    def check_metric_params(metric, params):
        """The metric's parameters: its defaults, overridden by `params`.

        Each value is converted to the type of its default (so n stays an int) and
        must be positive, or at least 0 where the default is 0; a name the metric
        does not take is refused.
        """
        defaults = Analyzer.metric_defaults(metric)
        checked = dict(defaults)
        for name, value in (params or {}).items():
            if name not in defaults:
                raise ValueError(f"{metric} has no parameter {name!r}; it takes {', '.join(defaults) or 'none'}.")
            try:
                value = type(defaults[name])(value)
            except (TypeError, ValueError):
                raise ValueError(f"{metric}: {name} must be a number, not {value!r}.")
            if isinstance(defaults[name], int) and float(params[name]) != value:
                raise ValueError(f"{metric}: {name} must be a whole number.")
            if defaults[name] == 0 and value < 0:
                raise ValueError(f"{metric}: {name} must not be negative.")
            if defaults[name] != 0 and not value > 0:
                raise ValueError(f"{metric}: {name} must be positive.")
            checked[name] = value
        return checked

    @staticmethod
    def _motion_score(roi, metric, params=None):
        """Reduces an (N, H, W, C) ROI stack to one scalar using the named metric,
        with `params` overriding its default parameters."""
        metrics = Analyzer._metrics()
        if metric not in metrics:
            raise ValueError(f"Unknown motility metric: {metric!r}")
        return metrics[metric](roi.astype(np.float32), **Analyzer.check_metric_params(metric, params))

    @staticmethod
    def _max_diff(roi):
        """Largest absolute pixel change between consecutive frames."""
        return float(np.abs(np.diff(roi, axis=0)).max())

    @staticmethod
    def _mean_diff(roi):
        """Mean absolute pixel change between consecutive frames."""
        return float(np.abs(np.diff(roi, axis=0)).mean())

    @staticmethod
    def _vector_diff_min_max(roi):
        pixel_max = np.abs(np.diff(roi, axis=0)).max(axis=(0, -1))
        h, w = pixel_max.shape
        dy, dx = np.mgrid[:h, :w].astype(np.float32)
        dy -= (h - 1) / 2
        dx -= (w - 1) / 2
        dist = np.hypot(dx, dy)
        dist[dist == 0] = np.inf  # the centre pixel has no direction
        vx = (pixel_max * dx / dist).sum()
        vy = (pixel_max * dy / dist).sum()
        return float(np.hypot(vx, vy))

    @staticmethod
    def _vector_variance(roi):
        """Magnitude of the spatial vector weighted by per-pixel variance."""
        pixel_variance = roi.var(axis=0).max(axis=-1)
        h, w = pixel_variance.shape
        dy, dx = np.mgrid[:h, :w].astype(np.float32)
        dy -= (h - 1) / 2
        dx -= (w - 1) / 2
        dist = np.hypot(dx, dy)
        dist[dist == 0] = np.inf
        vx = (pixel_variance * dx / dist).sum()
        vy = (pixel_variance * dy / dist).sum()
        return float(np.hypot(vx, vy))

    



    @staticmethod
    def _variability(roi):
        """Per-pixel standard deviation over the frames, averaged over the ROI."""
        return float(roi.var(axis=0).mean())

    @staticmethod
    def _topN_variability(roi, n=10):
        """Mean of the n highest per-pixel standard deviations over the frames."""
        pixel_std = roi.var(axis=0).ravel()
        return float(np.sort(pixel_std)[-n:].mean())


    @staticmethod
    def dense_optical_flow(roi, window=5, n=10, step=1, winsize=5, levels=1,
                           iterations=3, poly_n=5, poly_sigma=1.1, pad=0):
        """Local Farneback flow strength (pixels per `step` frames), averaged over
        every pair of frames `step` apart.

        Flow vectors are summed inside a `window` x `window` neighbourhood before
        taking their length: pixel noise points every which way and cancels, a
        moving leg pushes its neighbourhood one way. Summing only locally keeps
        legs moving in opposite directions from cancelling each other. The score
        per frame pair is the mean of the `n` strongest neighbourhoods, so a small
        leg isn't diluted by the still body and background.

        `winsize`, `levels`, `iterations`, `poly_n` and `poly_sigma` are passed to
        cv2.calcOpticalFlowFarneback; scripts/tune_optical_flow.py searches them.
        `pad` is not used here: the ROI is cut `pad` pixels larger on each side
        than the mite's box (see roi_padding()), since a patch only as wide as
        the mite leaves Farneback too few pixels around it to follow a leg.

        A stack of `step` frames or fewer has no pair `step` apart; its first and
        last frames are compared instead, so a short recording or pool still gets
        a score rather than NaN.

        A shaking plate is taken out before any metric sees the ROI, see
        PlateStabilizer."""

        # Farneback wants 8-bit single-channel frames
        gray = np.clip(roi.mean(axis=-1), 0, 255).astype(np.uint8)
        step = min(step, len(gray) - 1)
        # The ROI is only a few mite-widths across, so keep the pyramid shallow
        # and the averaging window small or the flow is smeared over the edges.
        magnitudes = []
        for prev, nxt in zip(gray[:-step], gray[step:]):
            flow = cv2.calcOpticalFlowFarneback(
                prev, nxt, None,
                pyr_scale=0.5, levels=levels, winsize=winsize,
                iterations=iterations, poly_n=poly_n, poly_sigma=poly_sigma, flags=0,
            )
            local = cv2.blur(flow, (window, window))
            strength = np.linalg.norm(local, axis=-1).ravel()
            magnitudes.append(np.sort(strength)[-n:].mean())
        return float(np.mean(magnitudes))

    @staticmethod
    def _topN_temporal_range(roi, n=10):
        """Mean of the n highest per-pixel dynamic ranges (max - min) over the frames."""
        pixel_range = (roi.max(axis=0) - roi.min(axis=0)).ravel()
        return float(np.sort(pixel_range)[-n:].mean())

    @staticmethod
    def _topN_vector_temporal_range(roi, n=10):
        """Length of the vector sum of the n highest per-pixel dynamic ranges, each
        pointing from the ROI centre to its pixel.

        A leg moving on one side of the mite adds up in one direction, while
        changes spread evenly around the centre (lighting, the whole body
        shifting) cancel out."""
        pixel_range = (roi.max(axis=0) - roi.min(axis=0)).max(axis=-1)
        h, w = pixel_range.shape
        dy, dx = np.mgrid[:h, :w].astype(np.float32)
        dy -= (h - 1) / 2
        dx -= (w - 1) / 2
        dist = np.hypot(dx, dy)
        dist[dist == 0] = np.inf  # the centre pixel has no direction
        top = np.argsort(pixel_range.ravel())[-n:]
        weight = pixel_range.ravel()[top] / dist.ravel()[top]
        vx = (weight * dx.ravel()[top]).sum()
        vy = (weight * dy.ravel()[top]).sum()
        return float(np.hypot(vx, vy))

    @staticmethod
    def _topN_binary_flux(roi, threshold=110, n=10):
        """Mean fluctuation across the n most active binary silhouette pixels."""
        # Binary mask: 1 where pixel is dark (mite body/leg), 0 where white
        binary_mask = (roi < threshold).astype(np.float32)
        # Compute temporal standard deviation of the binary transitions
        pixel_flux = binary_mask.std(axis=0).ravel()
        return float(np.sort(pixel_flux)[-n:].mean())

    @staticmethod
    def _outline_movement(roi, n=4, pad=16):
        """How far the mite's outline moves over the frames, in pixels.

        The outline is unrolled around the mite's centre: a ray goes out at
        each of 64 angles, and the darkness along it (the share of the plate's
        light the mite takes away, the plate's light read off the patch's
        outermost pixels) is summed. That is the length the mite would cover
        on that ray if it were black, and a leg makes the rays that cross it
        longer. Each frame's profile is set against the mean of the frames,
        and the score is the mean, over the `n` rays that move most, of how
        far each goes from its shortest to its longest.

        Two things change a picture without the mite changing shape and are
        kept out: the lamp (each frame's darkness is against the plate's light
        in that frame) and a shift of the whole mite, as when the plate shakes
        (each frame's rays start at the mite's centre in that frame). What they
        leave is the same all the way round, or longer on one side and shorter
        on the other: the first two harmonics in the angle, taken out as well.
        What is left is a change of shape, as a leg makes.

        `pad` is not used here: the ROI is cut `pad` pixels larger on each side
        than the mite's box (see roi_padding()), for the rays to reach past the
        legs and for bare plate at the patch's edge. It should be 12 or more.

        notebooks/alive_dead_legs.ipynb shows what it sees."""
        gray = roi.mean(axis=-1)
        height, width = gray.shape[1:]
        edge = np.ones((height, width), dtype=bool)
        edge[6:-6, 6:-6] = False               # the outermost pixels: the plate, never the mite
        plate = np.median(gray[:, edge], axis=1)  # per frame, so a lamp that flickers changes nothing
        if plate.min() <= 0:
            return 0.0
        dark = np.clip(1 - gray / plate[:, None, None], 0, None).astype(np.float32)

        # The mite's centre in each frame: where its darkness lies, the far
        # surroundings left out. The rays start there, so a mite that is moved
        # as a whole (the plate shaking) keeps its profile.
        near = np.zeros((height, width), dtype=np.float32)
        margin = max(pad - 8, 0)
        near[margin:height - margin, margin:width - margin] = 1
        weight = dark * near
        total = weight.sum(axis=(1, 2))
        if total.min() <= 0:
            return 0.0
        yy, xx = np.mgrid[:height, :width]
        centre_x, centre_y = (weight * xx).sum(axis=(1, 2)) / total, (weight * yy).sum(axis=(1, 2)) / total

        angles, ray_step = 64, 0.25
        # 13 pixels reach past a mite's legs; less where the patch ends sooner (a mite at the image's edge)
        reach = min(13.0, centre_x.min(), centre_y.min(), width - 1 - centre_x.max(), height - 1 - centre_y.max())
        if reach < 2:
            return 0.0
        angle = np.arange(angles) * (2 * np.pi / angles)
        along = np.arange(0, reach, ray_step)
        ray_x, ray_y = np.outer(np.cos(angle), along), np.outer(np.sin(angle), along)
        profiles = np.array([
            cv2.remap(frame, (x + ray_x).astype(np.float32), (y + ray_y).astype(np.float32), cv2.INTER_LINEAR).sum(axis=1)
            for frame, x, y in zip(dark, centre_x.tolist(), centre_y.tolist())
        ]) * ray_step

        harmonics = np.fft.rfft(profiles - profiles.mean(axis=0), axis=1)
        harmonics[:, :2] = 0                   # the same all round, and a shift of the whole mite
        shape = np.fft.irfft(harmonics, n=angles, axis=1)
        shape = (np.roll(shape, 1, axis=1) + shape + np.roll(shape, -1, axis=1)) / 3  # a leg is wider than one ray
        swing = shape.max(axis=0) - shape.min(axis=0)
        return float(np.sort(swing)[-n:].mean())

    @staticmethod
    def _outline_variability(roi, relative=0.0, width=1.5, pad=16):
        """Vector sum around the mite of the variance of the pixels on its outline: how much of that variance lies on one side.

        The variance over the frames is taken around the outline, one value
        for each of 64 directions from the mite's centre
        (outline_variability_profile()). Each value is a vector that points in
        its direction, and the score is the length of their sum, divided by
        the number of directions so that it stays in grey levels squared. A
        leg that moves varies the outline on its side, and all of that adds
        up. What varies the same all the way round (the camera's noise) or on
        two opposite sides cancels.

        `relative` takes the score relative to how much the outline varies: it
        is divided by the outline's mean variance to that power. At 1 it is
        the share of the variance that lies on one side, 0 to 1: how clustered
        the variance is, however little of it there is.

        `width` is how far the outline reaches on each side of the body's
        edge, in pixels.

        `pad` is not used here: the ROI is cut `pad` pixels larger on each side
        than the mite's box (see roi_padding()), for bare plate at the patch's
        edge. It should be 12 or more.

        notebooks/outline_variability.ipynb shows what it sees."""
        profile = Analyzer.outline_variability_profile(roi, width, pad)
        mean = float(profile.mean())
        if mean < 1e-6:                        # frames that are all the same: nothing varies
            return 0.0
        direction = np.exp(2j * np.pi * np.arange(len(profile)) / len(profile))
        one_sided = float(np.abs((profile * direction).mean()))
        return one_sided / mean ** relative

    @staticmethod
    def outline_variability_profile(roi, width=1.5, pad=16):
        """Where around the mite its pixels vary over the frames: the variance
        on the outline in each of 64 directions from the mite's centre, in
        grey levels squared, (64,). Direction 0 points right in the image and
        they go on clockwise. All 0 for a patch without a mite.

        On the ray in each direction the body's edge is found (_outline_rays()),
        and the outline is what lies within `width` pixels of it: that is
        where the pixels of a moving mite vary. The direction's value is the
        mean variance of the ray's points on the outline."""
        rays = Analyzer._outline_rays(roi, pad)
        if rays is None:
            return np.zeros(64)
        variance, edge, ray_step, _centre = rays
        away = np.abs(np.arange(variance.shape[1])[None] - edge[:, None]) * ray_step
        on_outline = away <= width
        return (variance * on_outline).sum(axis=1) / on_outline.sum(axis=1)

    @staticmethod
    def _outline_rays(roi, pad=16):
        """The mite unrolled around its centre: (variance, edge, ray_step,
        centre), or None for a patch without a mite. `variance` (64, points)
        is the variance over the frames at each point of each ray, the points
        `ray_step` pixels apart from the centre outwards; `edge` (64,) is the
        point of each ray at which the body ends, where the mite stops being
        half as dark as its darkest; `centre` is the mite's (x, y) in the
        patch, in the mean of the frames.

        Two things change the pixels without the mite moving and are kept out.
        The lamp: each frame is brought to the light the plate has in the mean
        of the frames, read off the patch's outermost pixels. A shift of the
        whole mite, as when the plate shakes: each frame's rays start at the
        mite's centre in that frame, the centre of the darkness of the body
        and the two pixels around it."""
        gray = roi.mean(axis=-1)
        height, width = gray.shape[1:]
        edge = np.ones((height, width), dtype=bool)
        edge[6:-6, 6:-6] = False               # the outermost pixels: the plate, never the mite
        plate = np.median(gray[:, edge], axis=1)
        if plate.min() <= 0:
            return None
        light = float(plate.mean())
        lit = (gray * (light / plate)[:, None, None]).astype(np.float32)  # a lamp that flickers changes nothing
        dark = np.clip(1 - lit / light, 0, None)
        still = dark.mean(axis=0)

        # The body: what is at least 30% as dark as the darkest of the mite, the
        # far surroundings left out, and two pixels around it. Of several
        # pieces it is the one closest to the middle of the patch, where the
        # mite's box is: the other is a neighbour, which may be walking past.
        margin = max(pad - 8, 0)
        near = np.zeros((height, width), dtype=bool)
        near[margin:height - margin, margin:width - margin] = True
        if not near.any() or still[near].max() <= 0:
            return None
        dark_enough = (still > 0.3 * still[near].max()) & near
        pieces = cv2.connectedComponents(dark_enough.astype(np.uint8))[1]
        yy, xx = np.mgrid[:height, :width]
        from_middle = np.hypot(yy - (height - 1) / 2, xx - (width - 1) / 2)
        body = (pieces == pieces.ravel()[np.where(dark_enough, from_middle, np.inf).argmin()]).astype(np.uint8)
        body = cv2.dilate(body, np.ones((3, 3), np.uint8), iterations=2)
        weight = dark * body
        total = weight.sum(axis=(1, 2))
        if total.min() <= 0:
            return None
        centre_x, centre_y = (weight * xx).sum(axis=(1, 2)) / total, (weight * yy).sum(axis=(1, 2)) / total

        angles, ray_step = 64, 0.5
        # 13 pixels reach past a mite's legs; less where the patch ends sooner (a mite at the image's edge)
        reach = min(13.0, centre_x.min(), centre_y.min(), width - 1 - centre_x.max(), height - 1 - centre_y.max())
        if reach < 2:
            return None
        angle = np.arange(angles) * (2 * np.pi / angles)
        along = np.arange(0, reach, ray_step)
        ray_x, ray_y = np.outer(np.cos(angle), along), np.outer(np.sin(angle), along)
        unrolled = np.array([
            cv2.remap(frame, (x + ray_x).astype(np.float32), (y + ray_y).astype(np.float32), cv2.INTER_LINEAR)
            for frame, x, y in zip(lit, centre_x.tolist(), centre_y.tolist())
        ])
        past_body = 1 - unrolled.mean(axis=0) / light < 0.5 * np.sort(still.ravel())[-30:].mean()
        body_ends = np.where(past_body.any(axis=1), past_body.argmax(axis=1), len(along) - 1)
        return unrolled.var(axis=0), body_ends, ray_step, (float(centre_x.mean()), float(centre_y.mean()))


