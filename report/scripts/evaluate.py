"""Score every labelled dataset copy with the current code (and the original software) and keep the rows."""
import json, os, sys, time
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.chdir(REPO)
from pipeline.calibration import calibration_report
from pipeline import output_files

ROOT = Path(os.environ["TEMP"]) / "zzrc" / "perf"
OUT = Path(__file__).parent / "eval"
OUT.mkdir(exist_ok=True)
names = sys.argv[1:] or ["sample_data", "ground_truth_60min", "ground_truth_90min", "GT_oct_2",
                         "poke_test_oct", "long_run"]
for name in names:
    t = time.time()
    r = calibration_report.evaluate_calibration(OUT / name, [name], recordings_root=ROOT,
                                                benchmark=True)
    keep = {k: r.get(k) for k in ("current", "best", "suggested", "threshold", "average_precision",
                                  "benchmark", "death_error", "datasets", "suggested_threshold", "n_moving", "n_still", "n_mites", "times")}
    keep["rows"] = [{k: v for k, v in row.items() if isinstance(v, (str, int, float, bool, type(None)))}
                    for row in r["observations"]]
    (OUT / f"{name}.json").write_text(json.dumps(keep, default=str, indent=0))
    print(name, f"{time.time() - t:.0f}s", "keys:", sorted(r), flush=True)
output_files.files_later.wait() if hasattr(output_files.files_later, "wait") else None
