"""Manual smoke test: mask out everything except the mite (inclusion) zones."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2

from classes.zones import Zone, ZoneManager
from classes.detector import Detector

SCRIPT_DIR = Path(__file__).resolve().parent
IMAGE_PATH = SCRIPT_DIR / "sample_image.bmp"
COORDINATES_PATH = SCRIPT_DIR.parent / "coords_pixel.txt"

# Maps the leading class id in coordinates1.txt to a Zone type name.
# 1 = full chamber (dot-counting area), 0 = the handwritten Alive/Dead label strip.
ZONE_TYPES = {
    "0": "label",
    "1": "mite",
}

# Zone types that should be masked out; everything else is kept ("valid").
EXCLUDED_TYPES = ["label"]


def load_zones(path):
    zones = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            type_id, x1, y1, x2, y2 = line.split()
            zone_type = ZONE_TYPES.get(type_id, type_id)
            zones.append(Zone(int(float(x1)), int(float(y1)), int(float(x2)), int(float(y2)), type=zone_type))
    return zones


image = cv2.imread(str(IMAGE_PATH))
if image is None:
    raise FileNotFoundError(f"Could not load {IMAGE_PATH}")

zones = load_zones(COORDINATES_PATH)
zone_manager = ZoneManager(zones, excluded_types=EXCLUDED_TYPES)

masked_image = zone_manager.mask_image_to_valid_rois(image, fill_color=255)

# run through detector
detector = Detector()  # Assuming mite_Zones is not needed for this test
keypoints = detector.detect(masked_image)
image_with_keypoints = cv2.drawKeypoints(masked_image, keypoints, None, (0, 255, 0), cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)




# Draw the valid (inclusion) zone outlines on top so the kept regions are obvious.
for zone in zone_manager.valid_zones:
    zone.draw(image_with_keypoints)

DISPLAY_WIDTH = 1000
scale = DISPLAY_WIDTH / image_with_keypoints.shape[1]
display_image = cv2.resize(image_with_keypoints, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

cv2.imshow("Inclusion-masked image (mite zones only)", display_image)
cv2.waitKey(0)
cv2.destroyAllWindows()
