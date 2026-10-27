"""Does dividing outline_variability by each recording's noise floor separate moving from still better?

Every (mite, recording) of every recording folder with ground truth is
cut as an analysis run cuts it (stabilized, the metric's pad) and measured
three ways:

    raw     outline_variability in grey levels squared, as it was until
            23 October 2026 (the score in use times the noise floor)
    noise   the recording's noise floor at the mite (Analyzer.plate_noise()):
            the variance over the frames of the bare plate at the patch's edge
    score   outline_variability as it is now, raw / noise

    python scripts/noise_floor.py               # every dataset with ground truth
    python scripts/noise_floor.py --datasets sample_data ground_truth_60min
    python scripts/noise_floor.py --root %TEMP%/zzrc/gt --add   # datasets kept elsewhere, added to the table

Writes results/scripts/noise_floor.csv.gz (one row per mite and recording, its
label in `moving` where `labelled`; read by notebooks/noise_floor.ipynb).
"""
import argparse
import os
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# The defaults everyone has, not this machine's config.yaml (only read).
os.environ.setdefault("DISCOBOX_CONFIG", str(ROOT / "config.default.yaml"))

import pandas as pd  # noqa: E402

import pipeline  # noqa: E402
from pipeline.calibration import dataset_library, score_cache  # noqa: E402
from classes.app_config import get_default_config  # noqa: E402
from classes.scoring.analyzer import Analyzer, NoNoiseWarning  # noqa: E402
import script_data  # noqa: E402

OUT = pipeline.SCRIPTS_OUTPUT / "noise_floor.csv.gz"


def measure(roi, metric, params):
    """(raw, noise, score) of one mite's patch."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NoNoiseWarning)   # kept as noise 0, raw = score
        score = float(Analyzer._motion_score(roi, metric, params))
    noise = Analyzer.plate_noise(Analyzer.grey(roi))
    return score * noise if noise > 0 else score, noise, score


def dataset_rows(name, root=pipeline.RECORDINGS_ROOT):
    """One row per mite and recording of the dataset `name` in `root`, the
    mites marked not a mite left out."""
    dataset = dataset_library.read_dataset(name, root)
    mite = get_default_config().mite
    metric = mite.metric
    params = mite.params_for(metric)
    mites, moving, labelled = script_data.labels_of(dataset)
    ids = [m["id"] for m in mites]
    measured = score_cache._measure_mites(dataset, Path(dataset["data_dir"]), lambda roi: measure(roi, metric, params),
                                          Analyzer.roi_padding(metric, params), mite.stabilize_plate)
    rows = []
    for at, recording in enumerate(measured):
        for index, mite_id in enumerate(ids):
            raw, noise, score = recording[mite_id]
            rows.append({"dataset": name, "mite": mite_id, "recording": at, "minutes": dataset["times"][at],
                         "fps": dataset["recordings"][at].get("fps"), "labelled": bool(labelled[index, at]),
                         "moving": bool(moving[index, at]),
                         "raw": raw, "noise": noise, "score": score})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--datasets", nargs="+", help="recording folders (default: every one with ground truth)")
    parser.add_argument("--root", type=Path, default=pipeline.RECORDINGS_ROOT, help="the folder the datasets are in")
    parser.add_argument("--add", action="store_true", help="keep the other datasets' rows already in --out")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    names = args.datasets or [d["id"] for d in pipeline.list_calibration_datasets(args.root)]
    rows, started = [], time.perf_counter()
    for name in names:
        rows += dataset_rows(name, args.root)
        print(f"  {name}: {len(rows)} rows so far, {time.perf_counter() - started:.0f} s")
    table = pd.DataFrame(rows)
    if args.add and args.out.is_file():
        kept = pd.read_csv(args.out)
        table = pd.concat([kept[~kept["dataset"].isin(names)], table], ignore_index=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out, index=False)
    print(f"{len(table)} rows -> {args.out}")


if __name__ == "__main__":
    main()
