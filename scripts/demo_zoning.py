"""Manual smoke test: draw zones parsed from coordinates1.txt on the sample image."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2

from classes.zones import Zone

SCRIPT_DIR = Path(__file__).resolve().parent
IMAGE_PATH = SCRIPT_DIR / "sample_image.bmp"
COORDINATES_PATH = SCRIPT_DIR.parent / "coordinates1.txt"

# Maps the leading class id in coordinates1.txt to a Zone type name.
# 1 = full chamber (dot-counting area), 0 = the handwritten Alive/Dead label strip.
# These names must match the "<type>_zone" style entries under visual_styles.Zones in config.yaml.
ZONE_TYPES = {
    "0": "label",
    "1": "mite",
}


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
for zone in zones:
    zone.draw(image)

DISPLAY_WIDTH = 1000
scale = DISPLAY_WIDTH / image.shape[1]
display_image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

cv2.imshow("sample_image.bmp", display_image)
cv2.waitKey(0)
cv2.destroyAllWindows()
