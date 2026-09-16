from pathlib import Path
import cv2
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from classes.detector import Detector


SCRIPT_DIR = Path(__file__).resolve().parent
IMAGE_PATH = SCRIPT_DIR / "sample_image.bmp"
COORDINATES_PATH = SCRIPT_DIR.parent / "coords_pixel.txt"



image = cv2.imread(str(IMAGE_PATH))
detector = Detector()  # Assuming mite_Zones is not needed for this test


keypoints = detector.detect(image)

#overlay on image
image_with_keypoints = cv2.drawKeypoints(image, keypoints, None, (0, 255, 0), cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)

#resize for display:
DISPLAY_WIDTH = 1000
scale = DISPLAY_WIDTH / image_with_keypoints.shape[1]
display_image = cv2.resize(image_with_keypoints, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

cv2.imshow("Detected Keypoints", display_image)
cv2.waitKey(0)
cv2.destroyAllWindows()