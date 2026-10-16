"""One-off: bring what earlier versions kept in calibration_data/ home to
recordings/ and results/ (pipeline.dissolve_calibration_library()), then shrink
every recording folder in recordings/ from whole frames to what a live run
saves, the mites' surroundings (classes/roi_conversion.py). The results stay
the same; the frames' space goes.

start.bat and start.sh run it before the server starts, so nothing reads a
folder while it changes. The first time takes a few minutes per ten GB of
frames; after that there is nothing left to do and it takes a moment. Once
every computer the app runs on has started it once, delete this script, the
lines that run it and pipeline's one-off block (dissolve_calibration_library()).

    python scripts/convert_stored_recordings.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline  # noqa: E402
from classes.data_loader import DataLoader  # noqa: E402


def main():
    library = pipeline.OLD_LIBRARY.is_dir()
    folders = [folder for folder in pipeline.RECORDINGS_ROOT.glob("*") if folder.is_dir()]
    if not library and not any(DataLoader(folder).recording_names for folder in folders):
        return  # nothing left to do: quiet
    if shutil.which("notify-send"):  # the Discobox starts the app from an icon, with no terminal to read
        subprocess.run(["notify-send", "Varroa discobox",
                        "Moving the calibration data into recordings/ and shrinking the stored recordings, once. "
                        "This can take a few minutes."], check=False)
    if library:
        print(f"Bringing {pipeline.OLD_LIBRARY} home to recordings/ and results/, once.")
        pipeline.dissolve_calibration_library(report=lambda text: print(f"  {text}", flush=True))
    print("Shrinking the stored recordings to the mites' surroundings, once (scripts/convert_stored_recordings.py).")
    done = pipeline.convert_stored_recordings(report=lambda text: print(text, flush=True))
    failed = [folder for folder, result in done.items() if isinstance(result, str)]
    if failed:
        print(f"Could not shrink {len(failed)} folder(s), left as they were: {', '.join(failed)}")


if __name__ == "__main__":
    main()
