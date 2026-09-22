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
        recording on each mite; the mite's alive state follows from those scores."""
        for recording, _times in image_bursts:
            for mite in mites:
                mite_roi = mite.get_ROI(recording)
                mite.record_motion(self._motion_score(mite_roi, mite.metric))

    @staticmethod
    def _motion_score(roi, metric):
        """Reduces an (N, H, W, C) ROI stack to one scalar using the named metric."""
        metrics = {
            "max_diff": Analyzer._max_diff,
            "mean_diff": Analyzer._mean_diff,
            "variability": Analyzer._variability,
            "topN_variability": Analyzer._topN_variability,
        }
        if metric not in metrics:
            raise ValueError(f"Unknown motility metric: {metric!r}")
        return metrics[metric](roi.astype(np.float32))

    @staticmethod
    def _max_diff(roi):
        """Largest absolute pixel change between consecutive frames."""
        return float(np.abs(np.diff(roi, axis=0)).max())

    @staticmethod
    def _mean_diff(roi):
        """Mean absolute pixel change between consecutive frames."""
        return float(np.abs(np.diff(roi, axis=0)).mean())

    @staticmethod
    def _variability(roi):
        """Per-pixel standard deviation over the frames, averaged over the ROI."""
        return float(roi.var(axis=0).mean())

    @staticmethod
    def _topN_variability(roi, n=10):
        """Mean of the n highest per-pixel standard deviations over the frames."""
        pixel_std = roi.var(axis=0).ravel()
        return float(np.sort(pixel_std)[-n:].mean())


