from classes.data_loader import DataLoader
from classes.analyzer import Analyzer
from classes.zones import ZoneManager, Zone
import cv2
import numpy as np
from classes.plotter import Plotter


# initialize objects
data_manager = DataLoader("sample_data", grayscale=False)
zone_manager = ZoneManager.from_coords_file(filepath= "coords_pixel.txt",
                                            zone_types= {
                                                "0": "label",
                                                "1": "mite",
                                            },
                                            excluded_types=["label"])

analyzer = Analyzer()


# load the data
recording_bursts = data_manager.load_bursts()

# get the first frame
first_frame = data_manager.get_first_frame()

# mask the frame
masked = zone_manager.mask_image_to_valid_rois(first_frame)

#detect mites
mites = analyzer.detect(masked)

# add mites to zones
valid_mites = zone_manager.assign_mites(mites)


# get the mite variability (one score per mite per recording burst)
analyzer.classify_motility(valid_mites, recording_bursts)


output = zone_manager.draw(masked)


# plot the variability of each mite over time (x = start time of each burst)
burst_minutes = np.array([times[0] for _frames, times in recording_bursts]) / 60
mite_data = zone_manager.get_mite_scores(burst_minutes)

plotter = Plotter(mite_data)
plotter.plot_score_distribution()
plotter.plot_score_over_time()
plotter.show()

#resize the output image
DISPLAY_WIDTH = 1000
scale = DISPLAY_WIDTH / output.shape[1]
display_image = cv2.resize(output, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)


cv2.imshow("pipeline result", display_image)
cv2.waitKey(0)
cv2.destroyAllWindows()

