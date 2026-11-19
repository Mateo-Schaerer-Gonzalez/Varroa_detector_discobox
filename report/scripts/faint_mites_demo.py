"""A demo of mites the detector misses, for the user manual's screenshots of
placing a mite by hand (report/scripts/manual_screenshots.mjs, stage "hand").

    python report/scripts/faint_mites_demo.py <copy>/recordings/demo_hand_mites <copy>/recordings/demo_faint_mites

demo_hand_mites (sample_data's frames with three mites painted in) was made for the
detector before 30 October 2026, which missed its mites; the detector chosen then
finds them. This one pastes a real mite (sample_data's 10.1, as on the first frame) at
a quarter of its contrast onto three empty places of slides 4, 10 and 16, in every
frame: faint, as a mite slightly out of focus, which the detector misses (it finds
them from about 35 % on) but the eye sees, and *Place a mite by hand* centres on.
Write it into a copy of the app (see manual_screenshots.mjs), never into recordings/.
"""
import argparse
import shutil
from pathlib import Path

import cv2
import numpy as np

# sample_data's mite 10.1, the box the detector gives it on the first frame
SOURCE_BOX = (938, 740, 951, 753)
PLACES = ((1040, 330), (1010, 790), (1060, 1150))
CONTRAST = 0.25
SMALL_FILES = (".settings.txt", "labels.json", "controls.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, help="a session of whole frames: demo_hand_mites")
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    recordings = sorted(path for path in args.source.iterdir() if path.is_dir())
    first = cv2.imread(str(sorted(recordings[0].glob("*.bmp"))[0]), cv2.IMREAD_GRAYSCALE)
    x1, y1, x2, y2 = SOURCE_BOX
    patch = first[y1 - 4:y2 + 4, x1 - 4:x2 + 4].astype(float)
    darker = CONTRAST * np.minimum(patch - np.median(patch), 0)
    height, width = patch.shape
    for recording in recordings:
        (args.out / recording.name).mkdir(parents=True, exist_ok=True)
        for frame in sorted(recording.glob("*.bmp")):
            image = cv2.imread(str(frame), cv2.IMREAD_GRAYSCALE).astype(float)
            for cx, cy in PLACES:
                top, left = cy - height // 2, cx - width // 2
                image[top:top + height, left:left + width] += darker
            cv2.imwrite(str(args.out / recording.name / frame.name), np.clip(image, 0, 255).astype(np.uint8))
    for name in SMALL_FILES:
        if (args.source / name).is_file():
            shutil.copy2(args.source / name, args.out / name)
    print("wrote", args.out, "with faint mites at", PLACES)


if __name__ == "__main__":
    main()
