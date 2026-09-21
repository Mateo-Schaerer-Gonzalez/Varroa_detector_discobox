from classes.data_loader import DataLoader
from classes.analyzer import Analyzer
from classes.zones import ZoneManager, Zone
import cv2
import matplotlib.pyplot as plt
import numpy as np


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




# plot the distribution of the variability scores
variabilities = [score for mite in valid_mites for score in mite.motion_scores]

plt.figure()
plt.hist(variabilities, bins=30, edgecolor="black")
plt.xlabel("Mite variability (mean per-pixel std over frames)")
plt.ylabel("Count (mite x recording)")
plt.title(f"Mite variability distribution (n={len(variabilities)})")

# plot the variability of each mite over time (x = start time of each burst)
burst_minutes = np.array([times[0] for _frames, times in recording_bursts]) / 60
scores = np.array([mite.motion_scores for mite in valid_mites])  # (n_mites, n_bursts)

plt.figure()
for mite_scores in scores:
    plt.plot(burst_minutes, mite_scores, color="tab:blue", alpha=0.25, linewidth=1)
plt.plot(burst_minutes, scores.mean(axis=0), color="black", linewidth=2.5, marker="o", label="mean over mites")
plt.xlabel("Time (min)")
plt.ylabel("Mite variability (mean per-pixel std over frames)")
plt.title(f"Mite variability over time (n={len(valid_mites)} mites)")
plt.legend()
plt.show()


#resize the output image
DISPLAY_WIDTH = 1000
scale = DISPLAY_WIDTH / output.shape[1]
display_image = cv2.resize(output, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)


cv2.imshow("pipeline result", display_image)
cv2.waitKey(0)
cv2.destroyAllWindows()

