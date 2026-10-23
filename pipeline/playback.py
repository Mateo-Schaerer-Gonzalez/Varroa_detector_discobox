"""The playback page: every mite of a zone in every frame of a recording, one
recording after the other.
"""

from pathlib import Path

import numpy as np

from classes.app_config import get_default_config
from classes.storage.files import write_jpeg
from classes.storage.roi_recordings import RoiRecordings, open_recordings
from pipeline import clips, paths


PLAYBACK_MAX_FRAMES = 100  # frames of one recording in its playback at most; a longer one is thinned to fit
PLAYBACK_MARGIN = 4  # pixels round a mite's box (its detector radius round its centre) in its playback square


def playback_reach():
    """Pixels from a mite's centre to the edge of its square in the playback:
    its box, the detector's radius round it, and PLAYBACK_MARGIN, so the mite
    fills it."""
    return int(get_default_config().mite.radius) + PLAYBACK_MARGIN


def _playback_step(loader, name):
    """Every how many frames of recording `name` the playback shows one."""
    return max(1, int(np.ceil(loader.count_frames(name) / PLAYBACK_MAX_FRAMES)))


def playback_timeline(data_dir, results):
    """What the playback page plays of the recordings of an analysis
    (`results`, as run_analysis() gives them), one after the other: per
    recording, how many frames it shows and the delay between them (ms) that
    plays them in real time; the side of a mite's picture (px); and the mites,
    by zone in their order (clips.with_fly_offs(), without where they are)."""
    loader = open_recordings(data_dir)
    recordings = []
    for name in loader.recording_names:
        step = _playback_step(loader, name)
        recordings.append({"frames": len(range(0, loader.count_frames(name), step)),
                           "interval_ms": int(round(1000 * step / loader.get_fps(name)))})
    mites = [{key: mite[key] for key in ("id", "zone_id", "flew_off")} for mite in clips.with_fly_offs(results)]
    return {"recordings": recordings, "tile": 2 * playback_reach(), "mites": mites}


def playback_sheet(data_dir, out_dir, recording, zone_id, results):
    """Every mite of one zone in every frame of one recording, for the playback
    page: one picture with a row per mite (clips.with_fly_offs(), the fly-offs
    too) and a column per frame (as playback_timeline() thins them), each
    2 * playback_reach() pixels square round the mite's centre where it was in
    that recording (clips.where_in()), black where nothing was saved (of a session
    saved as the mites' ROIs, beyond the mite's own there). `results` as
    run_analysis() gives them. Returns the picture's file (relative to `out_dir`), the mites in its rows, the side of a square
    and the frames. Written to out_dir/clips/ once, under a name that says
    where the mites are, and reused after."""
    mites = [mite for mite in clips.with_fly_offs(results) if mite["zone_id"] == zone_id]
    if not mites:
        raise ValueError(f"No mites in zone {zone_id}.")
    loader = open_recordings(data_dir)
    source = clips.recording_name(loader, recording)
    reach = playback_reach()
    placed = [clips.where_in(loader, source, mite) for mite in mites]
    name = f"playback_r{recording}_z{zone_id}_s{2 * reach}_{clips.where_key(placed)}"

    def make():
        step, side = _playback_step(loader, source), 2 * reach
        n_frames = len(range(0, loader.count_frames(source), step))
        sheet = np.zeros((len(mites) * side, n_frames * side), dtype=np.uint8)
        for row, (mite, here) in enumerate(zip(mites, placed)):
            x1, y1, x2, y2 = clips.square(here, reach)
            cut = [max(0, x1), max(0, y1), x2, y2]
            if isinstance(loader, RoiRecordings):
                roi = loader.roi_in(source, mite["x"], mite["y"])
                if roi is None:
                    continue
                cut = [max(cut[0], roi[0]), max(cut[1], roi[1]), min(cut[2], roi[2]), min(cut[3], roi[3])]
            frames = loader.load_recording_region(source, *cut, step=step)
            top, left = row * side + cut[1] - y1, cut[0] - x1
            height, width = frames.shape[1:3]
            for column, frame in enumerate(frames[:n_frames]):
                sheet[top:top + height, column * side + left:column * side + left + width] = frame
        picture = f"{paths.CLIPS_DIRNAME}/{name}.jpg"
        write_jpeg(Path(out_dir) / picture, sheet)
        return {"sheet": picture, "mites": [mite["id"] for mite in mites], "tile": side, "frames": n_frames}

    return clips.kept_clip(out_dir, name, make)
