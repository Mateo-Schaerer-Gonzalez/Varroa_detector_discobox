"""Intermediates of the stabiliser and the score for one mite-recording, for figures.
python stab_data.py <mite> <recording index>   (fig_mask.py and fig_stab.py use 9.1 123)"""
import os, pickle, sys, warnings
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "scripts")); os.chdir(REPO)
import numpy as np, cv2
import shaky_recordings as sr
from classes.app_config import get_default_config
from classes.scoring.plate_stabilizer import PlateStabilizer, _patches, _gray, _RIM, PAD, BODY_SHARE, DARKEST_N, BODY_GROW
from classes.scoring.analyzer import Analyzer

ROOT = Path(os.environ["TEMP"]) / "zzrc" / "perf"
MITE, INDEX = sys.argv[1], int(sys.argv[2])
dataset, loader, mites, labels = sr._dataset("long_run", ROOT)
number = dict(mites)[MITE]
recording = dataset["recordings"][INDEX]["name"]
box = sr._box_in_roi(loader, recording, number)
frames = loader.read_mite(recording, number).astype(np.float32)
out = {"box": box, "frames": frames, "mite": MITE, "recording": INDEX}

# stabiliser: crop box +- PAD, rim _RIM, as plate_stabilizer._centres()
crop = _gray(_patches(frames, box[0] - PAD, box[1] - PAD, box[2] + PAD, box[3] + PAD))
h, w = crop.shape[1:]
rim = np.ones((h, w), bool); rim[_RIM:-_RIM, _RIM:-_RIM] = False
plate = np.median(crop[:, rim], axis=1)
dark = np.clip(1 - crop / plate[:, None, None], 0, None)
still = dark.mean(axis=0)
darkest = np.sort(still[~rim])[-DARKEST_N:].mean()
dark_enough = (still > BODY_SHARE * darkest) & ~rim
pieces = cv2.connectedComponents(dark_enough.astype(np.uint8))[1]
yy, xx = np.ogrid[:h, :w]
from_middle = np.hypot(yy - (h - 1) / 2, xx - (w - 1) / 2)
chosen = pieces == pieces.ravel()[np.where(dark_enough, from_middle, np.inf).argmin()]
body = cv2.dilate(chosen.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=BODY_GROW)
shifts = PlateStabilizer()._mite_shifts(frames, box)
out.update(crop=crop, rim=rim, plate=plate, still=still, darkest=darkest, dark_enough=dark_enough, pieces=pieces,
           chosen=chosen, body=body, shifts=shifts)

# score patches: unstabilised and stabilised, pad 16, the parameters in use
mite = get_default_config().mite
params = mite.params_for(mite.metric)
P = params.get("pad", 16)
x1, y1, x2, y2 = box
raw = frames[:, max(0, y1 - P):y2 + P, max(0, x1 - P):x2 + P]
cut = PlateStabilizer.cut(frames, box, P, shifts)[..., 0]
warnings.simplefilter("ignore")
for name, roi in (("raw", raw), ("cut", cut)):
    g = Analyzer.grey(roi).astype(np.float32)
    lit, light, edge = Analyzer._lit(g)
    out[name] = {"roi": g, "std": lit.std(axis=0), "score": float(Analyzer._motion_score(roi, mite.metric, params)),
                 "noise": Analyzer.plate_noise(g), "edge_mask": edge, "rays": Analyzer._outline_rays(g, P),
                 "profile": Analyzer.outline_variability_profile(g, params["width"], P)}
    print(name, out[name]["score"], out[name]["noise"])
print("shift max", np.abs(shifts).max(), "plate light range", plate.min(), plate.max())
pickle.dump(out, open(Path(__file__).parent / f"stab_{MITE}_{INDEX}.pkl", "wb"))
