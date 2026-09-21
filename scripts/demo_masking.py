import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from classes.data_loader import DataLoader
from classes.analyzer import Analyzer
from classes.zones import ZoneManager, Zone
import cv2
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "sample_image.bmp"
COORDS_dir = SCRIPT_DIR.parent / "coords_pixel.txt"



# initialize objects
zone_manager = ZoneManager.from_coords_file(filepath= COORDS_dir,
                                            zone_types= {
                                                "0": "label",
                                                "1": "mite",
                                            },
                                            excluded_types=["label"])



# mask the frame

first_frame = cv2.imread(DATA_DIR)

masked = zone_manager.mask_image_to_valid_rois(first_frame)




output = zone_manager.draw(masked)


#resize the output image
DISPLAY_WIDTH = 1000
scale = DISPLAY_WIDTH / output.shape[1]
display_image = cv2.resize(output, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)


cv2.imshow("pipeline result", display_image)
cv2.waitKey(0)
cv2.destroyAllWindows()