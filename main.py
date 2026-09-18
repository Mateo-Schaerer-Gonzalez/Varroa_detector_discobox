from classes.data_loader import DataLoader
from classes.detector import Detector
from classes.zones import ZoneManager, Zone
import cv2


# initialize objects
data_manager = DataLoader("sample_data", grayscale=False)
zone_manager = ZoneManager.from_coords_file(filepath= "coords_pixel.txt",
                                            zone_types= {
                                                "0": "label",
                                                "1": "mite",
                                            },
                                            excluded_types=["label"])

detector = Detector()


# load the data
recording_bursts = data_manager.load_bursts()

# get the first frame
first_frame = data_manager.get_first_frame()

# mask the frame

masked = zone_manager.mask_image_to_valid_rois(first_frame)

#detect mites
mites = detector.detect(masked)

# add mites to zones
zone_manager.assign_mites(mites)




output = zone_manager.draw(masked)

#resize the output image
DISPLAY_WIDTH = 1000
scale = DISPLAY_WIDTH / output.shape[1]
display_image = cv2.resize(output, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)


cv2.imshow("pipeline result", display_image)
cv2.waitKey(0)
cv2.destroyAllWindows()

