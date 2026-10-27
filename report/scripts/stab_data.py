"""Intermediates of the stabiliser and the score for one mite-recording, for figures."""
import os, pickle, sys, warnings
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "scripts")); os.chdir(REPO)
import numpy as np, cv2
import shaky_recordings as sr
from classes.scoring.plate_stabilizer import PlateStabilizer, _patches, _gray, _RIM
from classes.scoring.analyzer import Analyzer

ROOT = Path(os.environ["TEMP"]) / "zzrc" / "perf"
MITE, INDEX = sys.argv[1], int(sys.argv[2])
dataset, loader, mites, labels = sr._dataset("long_run", ROOT)
number = dict(mites)[MITE]
recording = dataset["recordings"][INDEX]["name"]
box = sr._box_in_roi(loader, recording, number)
frames = loader.read_mite(recording, number).astype(np.float32)
out = {"box": box, "frames": frames, "mite": MITE, "recording": INDEX}

# stabiliser: crop box +- 8, rim 6
pad = 8
crop = _gray(_patches(frames, box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad))
h, w = crop.shape[1:]
rim = np.ones((h, w), bool); rim[_RIM:-_RIM, _RIM:-_RIM] = False
plate = np.median(crop[:, rim], axis=1)
dark = np.clip(1 - crop / plate[:, None, None], 0, None)
still = dark.mean(axis=0)
dark_enough = (still > 0.3 * still[~rim].max()) & ~rim
pieces = cv2.connectedComponents(dark_enough.astype(np.uint8))[1]
yy, xx = np.ogrid[:h, :w]
from_middle = np.hypot(yy - (h - 1) / 2, xx - (w - 1) / 2)
chosen = pieces == pieces.ravel()[np.where(dark_enough, from_middle, np.inf).argmin()]
body = cv2.dilate(chosen.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=2)
shifts = PlateStabilizer()._mite_shifts(frames, box)
out.update(crop=crop, rim=rim, plate=plate, still=still, dark_enough=dark_enough, pieces=pieces, chosen=chosen,
           body=body, shifts=shifts)

# score patches: unstabilised and stabilised, pad 16
P = 16
x1, y1, x2, y2 = box
raw = frames[:, max(0, y1 - P):y2 + P, max(0, x1 - P):x2 + P]
cut = PlateStabilizer.cut(frames, box, P, shifts)[..., 0]
warnings.simplefilter("ignore")
for name, roi in (("raw", raw), ("cut", cut)):
    g = Analyzer.grey(roi).astype(np.float32)
    lit, light, edge = Analyzer._lit(g)
    out[name] = {"roi": g, "std": lit.std(axis=0), "score": float(Analyzer._motion_score(roi, "outline_variability", {"relative": 0.0, "width": 1.5, "pad": 16})),
                 "noise": Analyzer.plate_noise(g), "edge_mask": edge, "rays": Analyzer._outline_rays(g, 16),
                 "profile": Analyzer.outline_variability_profile(g, 1.5, 16)}
    print(name, out[name]["score"], out[name]["noise"])
print("shift max", np.abs(shifts).max(), "plate light range", plate.min(), plate.max())
pickle.dump(out, open(Path(__file__).parent / f"stab_{MITE}_{INDEX}.pkl", "wb"))
