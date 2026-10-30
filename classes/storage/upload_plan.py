"""Which files of a folder dropped into the page are copied to the server, and
where they go.

Only the frames (.bmp, or of a session saved as the mites' ROIs its first frame,
its index and the mites' videos, see classes/storage/roi_recordings.py), the Discobox
settings (.settings.txt) and the app's own files (labels, negative controls,
ground truth, poke test, run.json) matter; everything else
stays on the user's disk. A single recording folder (..._fps-30) dropped on its
own becomes a one-recording session named after it. A file already on the
server with the same size is not copied again, so dropping the same folder twice
is instant, and the app's labels, controls and ground truth already on the
server are never replaced: they hold what was entered in this app, which is
newer than the copy in the dropped folder. Once copied, the frames are shrunk
to the mites' surroundings (classes/storage/roi_conversion.py); dropping the folder
again sends none of the frames shrunk already.
"""

import re
from pathlib import PurePosixPath

# labels_2.json and controls_2.json: those of two zones per plate (classes/plate/zone_layout.py)
KEPT = ("labels.json", "controls.json", "labels_2.json", "controls_2.json", "ground_truth.json", "corrections.json",
        "poke_test.json", "mites_by_hand.json")
FRAME = re.compile(r"\.bmp$", re.IGNORECASE)
# a session saved as the mites' ROIs: its index says it is one
ROI_INDEX = re.compile(r"^rois/index\.json$")
ROI_FILE = re.compile(r"^(first_frame\.png|rois/index\.json|rois/(parts/[^/]+(?<!\.part)/)?mite_\d+\.mkv)$")
APP_FILE = re.compile(r"(^|/)(\.settings\.txt|(labels|controls)(_2)?\.json|(ground_truth|corrections|poke_test|run|mites_by_hand)\.json)$")
SINGLE_RECORDING = re.compile(r"_fps-\d+")


class UploadPlan:
    def __init__(self, name, files):
        """`name`: the folder dropped; `files`: [{path (relative to it, with /), size}]."""
        self.check_part(name)
        single = SINGLE_RECORDING.search(name)
        self.name = f"{name}_session" if single else name
        prefix = f"{name}/" if single else ""
        self.files = []
        for file in files:
            target = prefix + file["path"]
            self.check_path(target)
            if UploadPlan.wanted(target):
                self.files.append({"path": file["path"], "target": target, "size": int(file["size"])})
        if not any(FRAME.search(file["target"]) or ROI_INDEX.search(file["target"]) for file in self.files):
            raise ValueError(f"No .bmp images found in “{self.name}”. Drop the folder that holds the ..._fps-30 folders.")

    @staticmethod
    def wanted(path):
        """Whether a file matters to the app: a frame, a file of a session saved
        as ROIs, or one of its own files by its exact name."""
        return bool(FRAME.search(path) or ROI_FILE.search(path) or APP_FILE.search(path))

    @staticmethod
    def check_part(name):
        if not name or name in (".", "..") or "/" in name or "\\" in name or ":" in name:
            raise ValueError(f"Bad folder name: {name}")

    @staticmethod
    def check_path(path):
        parts = PurePosixPath(path.replace("\\", "/")).parts
        if not parts or ".." in parts or ":" in path or path.startswith("/"):
            raise ValueError(f"Bad path: {path}")

    def missing(self, size_of, converted=()):
        """The files to copy: [{path (as dropped), target (in the folder on the
        server)}]. `size_of(target)` is the size of the file already there, or None.
        `converted`: the recordings whose frames were shrunk to the mites'
        surroundings on the server; their frames are not sent again."""
        missing = []
        for file in self.files:
            if FRAME.search(file["target"]) and file["target"].split("/")[0] in converted:
                continue
            size = size_of(file["target"])
            if PurePosixPath(file["target"]).name in KEPT and size is not None:
                continue
            if size != file["size"]:
                missing.append({"path": file["path"], "target": file["target"]})
        return missing
