"""Everything cut from the frames for the pages to play or draw: a zone's or the
whole plate's clip, a mite's own clip with its variation picture, and what the
score sees of each mite. Each is worked out once and kept in out_dir/clips/.
"""

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from classes.analyzer import Analyzer
from classes.app_config import get_default_config
from classes.files import read_json, write_image, write_jpeg, write_json
from classes.outline_view import OutlineView
from classes.roi_recordings import RoiRecordings, open_recordings
from pipeline import paths, plate_zones, refusals, scoring


CLIP_MARGIN = 20        # pixels around a zone in its clip
CLIP_MAX_FRAMES = 15    # frames per clip; a recording is thinned out to this


def kept_clip(out_dir, name, make):
    """What `make()` works out from the frames (a clip, the mites' outlines, a
    playback sheet), kept in out_dir/clips/ as `name`.json and read back from
    there after: the frames are read once. make() writes its pictures into
    clips/, which is there when it is called."""
    manifest = Path(out_dir) / paths.CLIPS_DIRNAME / f"{name}.json"
    kept = read_json(manifest)
    if kept is not None:
        return kept
    manifest.parent.mkdir(parents=True, exist_ok=True)
    made = make()
    write_json(manifest, made)
    return made


def square(mite, reach):
    """(x1, y1, x2, y2): `reach` pixels round the whole pixel nearest a mite's
    centre ({x, y}); x1 and y1 may be negative."""
    x, y = int(round(mite["x"])), int(round(mite["y"]))
    return x - reach, y - reach, x + reach, y + reach


def bounds(boxes, margin=0):
    """(x0, y0, x_end, y_end): the region holding every one of `boxes` grown by
    `margin`, cut at the image's top left."""
    boxes = list(boxes)
    return (max(0, min(box[0] for box in boxes) - margin), max(0, min(box[1] for box in boxes) - margin),
            max(box[2] for box in boxes) + margin, max(box[3] for box in boxes) + margin)


def local(boxes, x0, y0):
    """`boxes` (id to (x1, y1, x2, y2)) in a region whose top left is (x0, y0)."""
    return {key: (x1 - x0, y1 - y0, x2 - x0, y2 - y0) for key, (x1, y1, x2, y2) in boxes.items()}


def clip_key(dataset):
    """A short name for `dataset` in its clips' file names: the clips sit in a
    session folder already named after it, and Windows (without long paths)
    refuses a path of more than 259 characters, which a long dataset name
    repeated in both reached."""
    return hashlib.sha1(str(dataset).encode("utf-8")).hexdigest()[:10]


MITE_CLIP_REACH = 40            # pixels from a mite's centre to the edge of its own clip
MITE_VARIATION = (1.0, 8.0)     # grey levels: the standard deviations the variation picture draws black and brightest


def _variation_picture(frames):
    """How much each pixel of `frames` (frames, height, width), grey, varies
    over them, as a picture: its standard deviation, from black at the
    first of MITE_VARIATION (the camera's noise) through orange to nearly
    white at the second."""
    variation = frames.astype(np.float32).std(axis=0)
    least, most = MITE_VARIATION
    shade = np.clip((variation - least) / (most - least), 0, 1)
    colours = np.array([[0, 0, 0], [52, 104, 235], [224, 244, 255]], dtype=np.float32)  # BGR; one hue, growing lighter
    return np.stack([np.interp(shade, [0.0, 0.5, 1.0], colours[:, channel]) for channel in range(3)], axis=-1).astype(np.uint8)


def where_in(loader, name, mite):
    """`mite` ({x, y}: where it was found) where it was in recording `name`:
    where a live run followed it to (RoiRecordings.centre_in()), else where it
    was found. What is cut round a mite from its frames is cut there."""
    if not isinstance(loader, RoiRecordings):
        return mite
    x, y = loader.centre_in(name, mite["x"], mite["y"])
    return {**mite, "x": x, "y": y}


def mite_clip(recordings_dir, source, mite, out_dir, name):
    """Every frame of one recording (`source`: {name, fps}) cut MITE_CLIP_REACH
    pixels around `mite` ({x, y}, where it was found) where it was in that
    recording (where_in()) and kept as it is (PNG), to judge by eye whether
    the mite moves, and one picture of how much each pixel varies over them
    (_variation_picture()). Written to out_dir/clips/ once, with a manifest
    `name`_x_y.json that later calls reuse; the name says where the cut is, so
    a mite detected anew elsewhere gets a new clip. Returns the files
    (relative to `out_dir`), where the cut sits in the image, the mite's centre
    in it ("mite": {x, y}, in image pixels) and the delay between frames that
    plays them in real time."""
    loader = open_recordings(recordings_dir)
    here = where_in(loader, source["name"], mite)
    x1, y1, x2, y2 = square(here, MITE_CLIP_REACH)
    x1, y1 = max(0, x1), max(0, y1)
    name = f"{name}_x{x1}_y{y1}"

    def make():
        frames = loader.load_recording_region(source["name"], x1, y1, x2, y2)
        names = [f"{paths.CLIPS_DIRNAME}/{name}_{index:02d}.png" for index in range(len(frames))]
        for frame, frame_name in zip(frames, names):
            write_image(Path(out_dir) / frame_name, frame)
        variation = f"{paths.CLIPS_DIRNAME}/{name}_variation.png"
        write_image(Path(out_dir) / variation, _variation_picture(frames))
        return {
            "frames": names,
            "variation": variation,
            "x": x1,
            "y": y1,
            "width": int(frames.shape[2]),
            "height": int(frames.shape[1]),
            "mite": {"x": here["x"], "y": here["y"]},
            "interval_ms": int(round(1000 / source["fps"])),
        }

    return kept_clip(out_dir, name, make)


def write_clip(loader, recording_name, fps, box, out_dir, name, max_width=None):
    """Write up to CLIP_MAX_FRAMES JPEGs of the region `box` = (x1, y1, x2, y2) of
    one recording, and a manifest `name`.json that later calls reuse, to
    out_dir/clips/ (kept_clip()). `loader` reads the recordings, or is called
    for the one that does when the clip is not kept yet.

    Returns the frame files (relative to `out_dir`), where the region sits in the
    full image (in full image pixels, even when `max_width` scales the frames
    down), and the delay between frames that plays them back in real time.
    """
    def make():
        reader = loader() if callable(loader) else loader
        _check_saved(reader, *box)
        n_frames = reader.count_frames(recording_name)
        step = max(1, int(np.ceil(n_frames / CLIP_MAX_FRAMES)))
        x1, y1 = max(0, int(box[0])), max(0, int(box[1]))
        frames = reader.load_recording_region(recording_name, x1, y1, int(box[2]), int(box[3]), step=step)
        height, width = frames.shape[1:3]
        scale = min(1.0, max_width / width) if max_width else 1.0

        names = []
        for index, frame in enumerate(frames):
            if scale < 1:
                frame = cv2.resize(frame, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
            names.append(f"{paths.CLIPS_DIRNAME}/{name}_{index:02d}.jpg")
            write_jpeg(Path(out_dir) / names[-1], frame)
        return {
            "frames": names,
            "x": x1,
            "y": y1,
            "width": int(width),
            "height": int(height),
            "interval_ms": int(round(1000 * step / fps)),
        }

    return kept_clip(out_dir, name, make)


PLATE_CLIP_WIDTH = 1400  # the whole plate is scaled down to this width in its clip


def _check_saved(loader, x1, y1, x2, y2):
    """Refuse a clip of more than was saved: of a session saved as the mites'
    ROIs, only a mite's own clip can be played."""
    if not loader.covers(int(x1), int(y1), int(x2), int(y2)):
        raise ValueError("Only the mites' surroundings of these recordings were saved, so only a mite's own clip can be played.")


def recording_name(loader, recording):
    """The name of recording `recording` of an analysis, counted from 0."""
    recordings = loader.recording_names
    refusals.check_recording(recording, len(recordings))
    return recordings[recording]


def analysis_outlines(data_dir, out_dir, recording, zone_id, results):
    """What the score sees of each mite of one zone in one recording of an
    analysis, where it was in that recording (where_in()), for the result
    pages to draw over the mites: mite id to
    OutlineView.describe(), None for a mite it finds no outline of; the
    fly-offs' too (with_fly_offs()). `results` as run_analysis() gives them.
    Like analysis_clip(), worked out from the frames once, kept in `out_dir`
    under a name that says where the mites are, and reused after."""
    loader = open_recordings(data_dir)
    source = recording_name(loader, recording)
    mites = [where_in(loader, source, mite) for mite in with_fly_offs(results) if mite["zone_id"] == zone_id]
    if not mites:
        return {}

    def make():
        mite = get_default_config().mite
        pad = scoring.metric_pad(mite)
        width = Analyzer.check_metric_params(mite.metric, mite.params_for(mite.metric)).get("width", 1.5)
        boxes = {m["id"]: square(m, int(mite.radius) + pad) for m in mites}
        x0, y0, x_end, y_end = bounds(boxes.values())
        frames = loader.load_recording_region(source, x0, y0, x_end, y_end)
        outlines = {}
        for mite_id, (x1, y1, x2, y2) in boxes.items():
            x1, y1 = max(x1, x0), max(y1, y0)
            outlines[mite_id] = OutlineView.describe(frames[:, y1 - y0:y2 - y0, x1 - x0:x2 - x0], x1, y1, width, pad)
        return outlines

    return kept_clip(out_dir, f"outline_r{recording}_z{zone_id}_{where_key(mites)}", make)


def analysis_clip(data_dir, out_dir, recording, zone_id=None, coords_file=None):
    """Frames of one recording of an analysis session: of one zone, or with no
    `zone_id` of the whole plate, scaled down. Like calibration_clip(), written
    to `out_dir` once and reused after."""
    loader = open_recordings(data_dir)
    source = recording_name(loader, recording)

    if zone_id is None:
        box, name, max_width = (0, 0, 10**6, 10**6), f"clip_r{recording}_plate", PLATE_CLIP_WIDTH
    else:
        zone = next((z for z in plate_zones.zones_of(data_dir, coords_file).labelled_zones if z.id == zone_id), None)
        if zone is None:
            raise ValueError(f"No zone {zone_id} in this session.")
        box = (zone.x1 - CLIP_MARGIN, zone.y1 - CLIP_MARGIN, zone.x2 + CLIP_MARGIN, zone.y2 + CLIP_MARGIN)
        name, max_width = f"clip_r{recording}_z{zone_id}", None
    return write_clip(loader, source, loader.get_fps(source), box, out_dir, name, max_width)


def analysis_mite_clip(data_dir, out_dir, recording, mite_id, mites):
    """Frames of one mite during one recording of an analysis, cut close around
    it, for the mite page of a session saved as the mites' ROIs, which has no
    zone clip (see mite_clip()). `mites` are the results' ({id, x, y})."""
    mite = refusals.find(mites, mite_id, "these results")
    loader = open_recordings(data_dir)
    name = recording_name(loader, recording)
    return mite_clip(data_dir, {"name": name, "fps": loader.get_fps(name)}, mite, out_dir, f"mite_r{recording}")


def with_fly_offs(results):
    """The mites of `results` (as run_analysis() gives them), then the
    fly-offs, which the analysis leaves out, in that order: [{id, zone_id, x,
    y, flew_off}], `flew_off` the recording a fly-off left its place in, None
    for the others. The playback shows them all, the drift squares the
    fly-offs' outlines too."""
    mites = [{"id": mite["id"], "zone_id": mite["zone_id"], "x": mite["x"], "y": mite["y"], "flew_off": None}
             for mite in results["mites"]]
    known = {mite["id"] for mite in mites}
    mites += [{"id": fly_off["id"], "zone_id": fly_off["zone"], "x": fly_off["x"], "y": fly_off["y"], "flew_off": fly_off["from"]}
              for fly_off in (results.get("activity") or {}).get("fly_offs", []) if fly_off["id"] not in known]
    return mites


def where_key(mites):
    """A short name for where `mites` ({id, x, y}) are, for the file names of
    what is cut round them: mites detected anew elsewhere get new files."""
    where = json.dumps([[mite["id"], round(mite["x"]), round(mite["y"])] for mite in mites])
    return hashlib.sha1(where.encode("utf-8")).hexdigest()[:8]
