"""Per mite and recording of the poke run copy: outline profile, noise floor, score, mean image, rays.
python outline_data.py [dataset]   (default poke_test_oct, what fig_outline.py draws)"""
import os, pickle, sys, warnings
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "scripts")); os.chdir(REPO)
import numpy as np
from pipeline.calibration import dataset_library, score_cache
from classes.app_config import get_default_config
from classes.scoring.analyzer import Analyzer
import script_data

ROOT = Path(os.environ["TEMP"]) / "zzrc" / "perf"
name = sys.argv[1] if len(sys.argv) > 1 else "poke_test_oct"
dataset = dataset_library.read_dataset(name, ROOT)
mite = get_default_config().mite
params = mite.params_for(mite.metric)

def measure(roi):
    grey = Analyzer.grey(roi).astype(np.float32)
    rays = Analyzer._outline_rays(grey, params["pad"])
    noise = Analyzer.plate_noise(grey)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        score = float(Analyzer._motion_score(roi, mite.metric, params))
    profile = Analyzer.outline_variability_profile(grey, params["width"], params["pad"])
    return {"score": score, "noise": noise, "profile": profile, "mean": grey.mean(axis=0),
            "var": grey.var(axis=0), "rays": rays, "first": grey[0], "brightness": float(grey.mean())}

mites, moving, labelled = script_data.labels_of(dataset)
ids = [m["id"] for m in mites]
measured = score_cache._measure_mites(dataset, Path(dataset["data_dir"]), measure, Analyzer.roi_padding(mite.metric, params),
                                      mite.stabilize_plate)
out = {"ids": ids, "moving": moving, "labelled": labelled, "times": dataset["times"],
       "data": [{k: rec.get(k) for k in ids} for rec in measured]}
pickle.dump(out, open(Path(__file__).parent / f"outline_{name}.pkl", "wb"))
print("done", len(out["data"]), "recordings")
