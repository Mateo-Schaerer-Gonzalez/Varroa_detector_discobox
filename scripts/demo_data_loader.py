"""Manual smoke test: load a session with DataLoader and inspect recordings/timing."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2

from classes.data_loader import DataLoader

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "sample_data"


loader = DataLoader(DATA_DIR, grayscale=True)

print(f"Session settings: {loader.settings}")
print(f"Found {len(loader.recording_dirs)} recordings:")
for d in loader.recording_dirs:
    fps = loader.get_fps(d.name)
    start = loader.get_start_time(d.name)
    print(f"  {d.name}: start={start}, fps={fps}")

frames, times = loader.load_folder()
print(f"\nStacked frames shape: {frames.shape}")
print(f"Time range: {times[0]:.2f}s -> {times[-1]:.2f}s ({len(times)} frames)")

# Show the first frame of each recording, labeled with its wall-clock time.
recording_lengths = [loader.load_recording(d.name).shape[0] for d in loader.recording_dirs]
first_frame_indices = [sum(recording_lengths[:i]) for i in range(len(recording_lengths))]


DISPLAY_WIDTH = 500
for idx in first_frame_indices:
    frame = frames[idx]
    scale = DISPLAY_WIDTH / frame.shape[1]
    display_frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    cv2.putText(display_frame, f"t={times[idx]:.1f}s", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    cv2.imshow("data_loader_demo", display_frame)
    cv2.waitKey(0)

cv2.destroyAllWindows()
