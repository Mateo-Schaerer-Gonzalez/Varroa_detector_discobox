"""Manual smoke test: draw a few mites on a blank image and show the result."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from classes.mite import Mite

OUTPUT_PATH = Path(__file__).resolve().parent / "demo_mites_output.png"

image = np.full((400, 400, 3), 40, dtype=np.uint8)

mites = [
    Mite(50, 50, 120, 120),
    Mite(180, 90, 260, 170),
    Mite(100, 220, 190, 300),
]

for mite in mites:
    mite.draw(image)

cv2.imwrite(OUTPUT_PATH, image)
print(f"Saved result to {OUTPUT_PATH}")

cv2.imshow("Mites", image)
cv2.waitKey(0)
cv2.destroyAllWindows()
