import cv2
import numpy as np
import pytest

from classes.app_config import AppConfig, DetectorConfig
from classes.detector import Detector


class FakeConfig:
    def __init__(self, detector):
        self.detector = detector


class FakeBlobDetector:
    def __init__(self, return_value=()):
        self.received_image = None
        self.return_value = return_value

    def detect(self, image):
        self.received_image = image
        return self.return_value


@pytest.fixture
def custom_detector_config():
    return DetectorConfig(
        min_threshold=10,
        max_threshold=220,
        threshold_step=5,
        filter_by_color=True,
        blob_color=255,
        filter_by_area=True,
        min_area=20,
        max_area=500,
        filter_by_circularity=True,
        min_circularity=0.7,
        filter_by_convexity=True,
        min_convexity=0.9,
        filter_by_inertia=True,
        min_inertia_ratio=0.3,
    )


class TestBuildParams:
    def test_maps_all_fields_from_config(self, custom_detector_config):
        params = Detector._build_params(custom_detector_config)

        assert params.minThreshold == pytest.approx(10)
        assert params.maxThreshold == pytest.approx(220)
        assert params.thresholdStep == pytest.approx(5)
        assert params.filterByColor is True
        assert params.blobColor == 255
        assert params.filterByArea is True
        assert params.minArea == pytest.approx(20)
        assert params.maxArea == pytest.approx(500)
        assert params.filterByCircularity is True
        assert params.minCircularity == pytest.approx(0.7)
        assert params.filterByConvexity is True
        assert params.minConvexity == pytest.approx(0.9)
        assert params.filterByInertia is True
        assert params.minInertiaRatio == pytest.approx(0.3)


class TestInit:
    def test_default_config_matches_yaml(self):
        detector = Detector()
        assert detector.config == AppConfig().detector

    def test_custom_config_overrides_default(self, custom_detector_config):
        detector = Detector(config=FakeConfig(detector=custom_detector_config))
        assert detector.config == custom_detector_config

    def test_builds_blob_detector_instance(self):
        detector = Detector()
        assert isinstance(detector.blob_detector, cv2.SimpleBlobDetector)


class TestDetect:
    def test_delegates_to_blob_detector(self):
        detector = Detector()
        fake = FakeBlobDetector(return_value=["kp1", "kp2"])
        detector.blob_detector = fake
        image = np.zeros((10, 10, 3), dtype=np.uint8)

        result = detector.detect(image)

        assert result == ["kp1", "kp2"]
        assert fake.received_image is image

    def test_no_blobs_on_blank_image(self):
        detector = Detector()
        image = np.full((100, 100, 3), 255, dtype=np.uint8)

        keypoints = detector.detect(image)

        assert len(keypoints) == 0

    def test_detects_dark_blob_on_light_background(self):
        detector = Detector()
        image = np.full((200, 200, 3), 255, dtype=np.uint8)
        cv2.circle(image, (100, 100), 12, (0, 0, 0), -1)

        keypoints = detector.detect(image)

        assert len(keypoints) == 1
        assert keypoints[0].pt[0] == pytest.approx(100, abs=5)
        assert keypoints[0].pt[1] == pytest.approx(100, abs=5)

    def test_detects_multiple_separate_blobs(self):
        detector = Detector()
        image = np.full((300, 300, 3), 255, dtype=np.uint8)
        cv2.circle(image, (75, 75), 12, (0, 0, 0), -1)
        cv2.circle(image, (220, 220), 12, (0, 0, 0), -1)

        keypoints = detector.detect(image)

        centers = sorted((round(kp.pt[0]), round(kp.pt[1])) for kp in keypoints)
        assert centers == [(75, 75), (220, 220)]

    def test_ignores_blob_below_min_area(self):
        detector = Detector()
        image = np.full((100, 100, 3), 255, dtype=np.uint8)
        cv2.circle(image, (50, 50), 2, (0, 0, 0), -1)  # area well under min_area=40

        keypoints = detector.detect(image)

        assert len(keypoints) == 0

    def test_ignores_light_blob_when_configured_for_dark(self):
        detector = Detector()
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.circle(image, (50, 50), 12, (255, 255, 255), -1)  # light blob, blob_color=0 wants dark

        keypoints = detector.detect(image)

        assert len(keypoints) == 0
