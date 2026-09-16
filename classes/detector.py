from typing import Optional
import cv2
from classes.app_config import AppConfig, get_default_config


class Detector:

    def __init__(self, config: Optional[AppConfig] = None):
        config = config or get_default_config()
        self.config = config.detector
        self.blob_detector = cv2.SimpleBlobDetector_create(self._build_params(self.config))

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

    def detector(self, image):
        """Returns the keypoints detected in the image using the configured blob detector."""
        return self.blob_detector.detect(image) 

