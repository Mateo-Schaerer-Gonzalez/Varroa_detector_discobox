import inspect
from typing import Optional
import cv2
from classes.app_config import AppConfig, get_default_config
from classes.mite import Mite
import numpy as np


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
            for mite in mites:
                mite_roi = mite.get_ROI(recording)
                mite.record_motion(self._motion_score(mite_roi, mite.metric, mite.metric_params))

    def score_pool(self, mites, frames):
        """Records one motion score on each mite for one pool of frames: `frames`
        is a list of (H, W, C) frames, in order.

        Each mite's ROI is cut from each frame and the cuts stacked, which gives
        the same (N, h, w, C) array classify_motility() cuts from a stack of the
        frames, without ever holding a second copy of the frames."""
        for mite in mites:
            mite_roi = np.stack([mite.get_ROI(frame) for frame in frames])
            mite.record_motion(self._motion_score(mite_roi, mite.metric, mite.metric_params))

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
        signature = inspect.signature(Analyzer._metrics()[metric])
        return {name: p.default for name, p in signature.parameters.items() if name != "roi"}

    @staticmethod
    def check_metric_params(metric, params):
        """The metric's parameters: its defaults, overridden by `params`.

        Each value is converted to the type of its default (so n stays an int) and
        must be positive; a name the metric does not take is refused.
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
            if not value > 0:
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
        vx = (pixel_max * dx / dist).mean()
        vy = (pixel_max * dy / dist).mean()
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
        vx = (pixel_variance * dx / dist).mean()
        vy = (pixel_variance * dy / dist).mean()
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
    def dense_optical_flow(roi, window=5, n=10):
        """Local Farneback flow strength (pixels/frame), averaged over every pair
        of consecutive frames.

        Flow vectors are summed inside a `window` x `window` neighbourhood before
        taking their length: pixel noise points every which way and cancels, a
        moving leg pushes its neighbourhood one way. Summing only locally keeps
        legs moving in opposite directions from cancelling each other. The score
        per frame pair is the mean of the `n` strongest neighbourhoods, so a small
        leg isn't diluted by the still body and background."""
       
        # Farneback wants 8-bit single-channel frames
        gray = np.clip(roi.mean(axis=-1), 0, 255).astype(np.uint8)
        # The ROI is only a few mite-widths across, so keep the pyramid shallow
        # and the averaging window small or the flow is smeared over the edges.
        magnitudes = []
        for prev, nxt in zip(gray[:-1], gray[1:]):
            flow = cv2.calcOpticalFlowFarneback(
                prev, nxt, None,
                pyr_scale=0.5, levels=1, winsize=5,
                iterations=3, poly_n=5, poly_sigma=1.1, flags=0,
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


