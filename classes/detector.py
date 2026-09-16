from typing import Optional
import cv2
from classes.app_config import AppConfig, get_default_config
from classes.mite import Mite


class Detector:

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

    def detect(self, image):
        """Returns the keypoints detected in the image using the configured blob detector."""
        return self.blob_detector.detect(image) 

    def process_frame(self, image, zone_manager):
        """
        Integrated pipeline:
        1. Applies zone masks (inclusion or exclusion) to the image
        2. Runs detection only on valid areas
        3. Assigns detected mites to their respective zones (optional)
        """
        # Mask the image
        mites_added = [] # for optimization
        
        processed_img = zone_manager.mask_image_to_valid_rois(image, fill_color=255)


        #  Run detection on the clean/masked image
        keypoints = self.detect(processed_img)

        # Populate zones with detected mites
        for kp in keypoints:
            for zone in zone_manager.zones:
                if zone.contains_point(kp.pt[0], kp.pt[1]): # kp is a CV keypoint object with pt tuple

                    mite = Mite(kp.pt[0] - kp.size/2,
                                kp.pt[1] + kp.size/2,
                                kp.pt[0] + kp.size/2,
                                kp.pt[1] - kp.size/2,
                                config = self.config)
                    zone.add_mite(mite)
                    mites_added.append(mite)
                    break
        return mites_added

        