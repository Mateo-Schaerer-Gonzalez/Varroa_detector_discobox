"""Time per recording: the app's scoring vs the original software, on sample_data's whole frames in memory.
python speed.py app|original [threads]   (threads: 'shipped' or '1')"""
import json, os, sys, time
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO)); os.chdir(REPO)
import numpy as np, cv2
which, threads = sys.argv[1], sys.argv[2]
DATA = REPO / "sample_data"
names = sorted(p.name for p in DATA.iterdir() if p.is_dir() and "fps" in p.name)
recs = []
for n in names:
    files = sorted((DATA / n).glob("*.bmp"))
    recs.append([cv2.imread(str(f), cv2.IMREAD_GRAYSCALE) for f in files])
lengths = {30: recs, 90: [recs[0] + recs[1] + recs[2], recs[3] + recs[4] + recs[5]]}
out = {"which": which, "threads": threads, "frame_shape": list(recs[0][0].shape), "cpus": os.cpu_count()}

def timed(fn, frames, repeat):
    best_wall = best_cpu = None
    for _ in range(repeat):
        w0, c0 = time.perf_counter(), time.process_time(); fn(frames); w, c = time.perf_counter() - w0, time.process_time() - c0
        best_wall = w if best_wall is None else min(best_wall, w); best_cpu = c if best_cpu is None else min(best_cpu, c)
    return best_wall, best_cpu

if which == "app":
    if threads == "1":
        os.environ["_"] = ""; import classes.scoring.workers as wk; wk.WORKERS = 1
    from classes.scoring.motion_analysis import MotionAnalysis
    from classes.storage.frame_source import Frame, Recording
    from pipeline import plate_zones
    import classes.scoring.workers as wk
    out["workers"] = wk.WORKERS
    analysis = MotionAnalysis(plate_zones.zones_of(DATA))
    first = recs[0][0]
    w0 = time.perf_counter(); analysis.detect(Frame(first, Recording.from_name(names[0], 30), 0) if False else type("F", (), {"image": first, "recording": type("R", (), {"start": 0})()})()); out["detect_s"] = time.perf_counter() - w0
    mites = analysis.mites; out["mites"] = len(mites)
    def app(frames):
        analysis.analyzer.score_pool(mites, frames); analysis.blobs_on(frames[0], frames[-1])
    for n, rs in lengths.items():
        t = [timed(app, r, 3) for r in rs]
        out[f"{n}_wall"] = float(np.median([x[0] for x in t])); out[f"{n}_cpu"] = float(np.median([x[1] for x in t]))
else:
    if threads == "1": cv2.setNumThreads(1)
    out["cv2_threads"] = cv2.getNumThreads()
    from classes.scoring.benchmark import Benchmark
    for n, rs in lengths.items():
        t = [timed(Benchmark.circles, r, 1) for r in rs[:2]]
        out[f"{n}_wall"] = float(np.median([x[0] for x in t])); out[f"{n}_cpu"] = float(np.median([x[1] for x in t]))
print(json.dumps(out))
with open(Path(__file__).parent / "speed.jsonl", "a") as f: f.write(json.dumps(out) + "\n")
