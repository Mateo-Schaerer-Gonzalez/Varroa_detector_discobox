"""Peak memory for one 90-frame recording: python memory.py app|original. Windows peak working set."""
import ctypes, json, os, sys
from ctypes import wintypes
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO)); os.chdir(REPO)

class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
def mem():
    c = PMC(); c.cb = ctypes.sizeof(PMC)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c.PeakWorkingSetSize / 1e6, c.WorkingSetSize / 1e6, c.PeakPagefileUsage / 1e6
import numpy as np, cv2
which = sys.argv[1]
DATA = REPO / "sample_data"
names = sorted(p.name for p in DATA.iterdir() if p.is_dir() and "fps" in p.name)
if which == "app":
    from classes.scoring.motion_analysis import MotionAnalysis
    from pipeline import plate_zones
else:
    from classes.scoring.benchmark import Benchmark
frames = [cv2.imread(str(f), cv2.IMREAD_GRAYSCALE) for n in names[:3] for f in sorted((DATA / n).glob("*.bmp"))]
before = mem()
if which == "app":
    analysis = MotionAnalysis(plate_zones.zones_of(DATA))
    analysis.detect(type("F", (), {"image": frames[0], "recording": type("R", (), {"start": 0})()})())
    analysis.analyzer.score_pool(analysis.mites, frames); analysis.blobs_on(frames[0], frames[-1])
else:
    Benchmark.circles(frames)
after = mem()
out = {"which": which, "frames": len(frames), "frames_mb": sum(f.nbytes for f in frames) / 1e6,
       "after_load_ws_mb": before[1], "peak_ws_mb": after[0], "peak_commit_mb": after[2], "before_peak_commit_mb": before[2],
       "extra_peak_mb": after[0] - before[1], "extra_commit_mb": after[2] - before[2]}
print(json.dumps(out))
