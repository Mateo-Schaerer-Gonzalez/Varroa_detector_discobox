"""Sessions saved as the mites' ROIs (classes/roi_recordings.py): what is written
reads back exactly, before and after the recordings are stitched into each
mite's video, whatever stops a stitch half way; and the pages get only the
clips that were saved."""

import json
import os
import shutil
import stat
from datetime import datetime, timedelta

import cv2
import numpy as np
import pytest

import folder_camera
import pipeline
import reference
from classes.frame_source import Frame, Recording, RoiSource, open_source
from classes.live.recorder import Recorder
from classes.roi_recordings import (FIRST_FRAME_NAME, INDEX_NAME, PARTS_DIRNAME, ROI_DIRNAME, ROI_MARGIN,
                                    RoiRecordings, RoiVideo, RoiWriter, remove_tree, roi_rect)

START = datetime(2025, 9, 4, 9, 28, 17)
WIDTH, HEIGHT = 300, 200
# one mite well inside, one at the image's corner, one of an odd size
BOXES = [(100, 80, 117, 97), (0, 0, 13, 13), (250, 150, 270, 171)]


def recording(number, fps=30):
    start = START + timedelta(minutes=5 * number)
    return Recording(f"{start:%Y-%m-%d-%H-%M-%S}_fps-{fps}", start, fps)


def frames(number, count=4):
    return np.random.default_rng(number).integers(0, 256, (count, HEIGHT, WIDTH), dtype=np.uint8)


def write_session(folder, counts=(4, 3, 5), stitch=True):
    """A session of len(counts) recordings, each of that many random frames;
    returns the frames, per recording."""
    writer = RoiWriter(folder)
    every = [frames(number, count) for number, count in enumerate(counts)]
    writer.start(every[0][0], BOXES)
    for number, stack in enumerate(every):
        for image in stack:
            writer.add(recording(number), image)
        writer.end(recording(number), blobs=[[number, 1.5]])
    if stitch:
        RoiRecordings(folder).stitch()
    return every


def assert_reads_back(folder, every):
    loader = RoiRecordings(folder)
    assert loader.recording_names == [recording(number).name for number in range(len(every))]
    for number, stack in enumerate(every):
        name = recording(number).name
        assert loader.count_frames(name) == len(stack)
        whole = loader.load_recording(name)
        for x1, y1, x2, y2 in loader.rois:
            assert np.array_equal(whole[:, y1:y2, x1:x2], stack[:, y1:y2, x1:x2])
        outside = np.ones((HEIGHT, WIDTH), bool)
        for x1, y1, x2, y2 in loader.rois:
            outside[y1:y2, x1:x2] = False
        assert not whole[:, outside].any()


def test_an_roi_is_the_box_grown_by_the_margin_and_even_sized_inside_the_image():
    assert roi_rect((100, 80, 117, 97), WIDTH, HEIGHT) == [100 - ROI_MARGIN, 80 - ROI_MARGIN, 118 + ROI_MARGIN, 98 + ROI_MARGIN]
    for box in BOXES:
        x1, y1, x2, y2 = roi_rect(box, WIDTH, HEIGHT)
        assert 0 <= x1 <= box[0] and 0 <= y1 <= box[1] and box[2] <= x2 <= WIDTH and box[3] <= y2 <= HEIGHT
        assert (x2 - x1) % 2 == 0 and (y2 - y1) % 2 == 0


def test_the_videos_read_back_exactly(tmp_path):
    RoiVideo.check_codec(tmp_path)
    assert not list(tmp_path.iterdir())


def test_what_is_written_reads_back_exactly_before_and_after_the_stitch(tmp_path):
    every = write_session(tmp_path, stitch=False)
    assert (tmp_path / ROI_DIRNAME / PARTS_DIRNAME).is_dir()
    assert_reads_back(tmp_path, every)
    RoiRecordings(tmp_path).stitch()
    assert not (tmp_path / ROI_DIRNAME / PARTS_DIRNAME).exists()
    assert sorted(path.name for path in (tmp_path / ROI_DIRNAME).iterdir()) == [
        INDEX_NAME, "mite_000.mkv", "mite_001.mkv", "mite_002.mkv"]
    assert_reads_back(tmp_path, every)
    assert len(RoiVideo.read(tmp_path / ROI_DIRNAME / "mite_000.mkv")) == 12  # every recording, one after the other


def test_recordings_added_after_a_stitch_are_stitched_onto_the_end(tmp_path):
    every = write_session(tmp_path, counts=(4, 3))
    writer = RoiWriter(tmp_path)
    writer.index = RoiRecordings(tmp_path).index
    extra = frames(7, 2)
    for image in extra:
        writer.add(recording(2), image)
    writer.end(recording(2))
    every.append(extra)
    assert_reads_back(tmp_path, every)
    RoiRecordings(tmp_path).stitch()
    assert_reads_back(tmp_path, every)


def test_a_stitch_cut_short_after_the_videos_were_replaced_reads_the_same(tmp_path):
    every = write_session(tmp_path, stitch=False)
    index = (tmp_path / ROI_DIRNAME / INDEX_NAME).read_text(encoding="utf-8")
    parts = tmp_path / "parts_kept"
    shutil.copytree(tmp_path / ROI_DIRNAME / PARTS_DIRNAME, parts)
    RoiRecordings(tmp_path).stitch()
    # as if it stopped before the index said so: the old index, the parts still there
    (tmp_path / ROI_DIRNAME / INDEX_NAME).write_text(index, encoding="utf-8")
    shutil.copytree(parts, tmp_path / ROI_DIRNAME / PARTS_DIRNAME)
    assert_reads_back(tmp_path, every)
    RoiRecordings(tmp_path).stitch()
    assert_reads_back(tmp_path, every)


def test_a_recording_never_ended_is_not_in_the_session(tmp_path):
    every = write_session(tmp_path, counts=(4,), stitch=False)
    writer = RoiWriter(tmp_path)
    writer.index = RoiRecordings(tmp_path).index
    writer.add(recording(1), frames(1, 1)[0])
    assert_reads_back(tmp_path, every)
    writer.abandon()
    assert [path.name for path in (tmp_path / ROI_DIRNAME / PARTS_DIRNAME).iterdir()] == [recording(0).name]


def test_a_region_holds_the_rois_in_it_black_elsewhere_and_only_an_roi_covers_a_clip(tmp_path):
    every = write_session(tmp_path)
    loader = RoiRecordings(tmp_path)
    region = loader.load_recording_region(recording(1).name, 90, 70, 160, 140, step=2)
    x1, y1, x2, y2 = loader.rois[0]
    assert region.shape == (2, 70, 70)
    assert np.array_equal(region[:, :y2 - 70, :x2 - 90], every[1][::2, 70:y2, 90:x2])
    assert loader.covers(100, 80, 117, 97) and not loader.covers(0, 0, WIDTH, HEIGHT)


def test_reading_past_the_margin_is_refused(tmp_path):
    write_session(tmp_path, counts=(2,))
    RoiRecordings(tmp_path).check_margin(ROI_MARGIN)
    with pytest.raises(ValueError, match="pad"):
        RoiRecordings(tmp_path).check_margin(ROI_MARGIN + 1)


def test_the_source_gives_the_first_frame_whole_the_others_as_rois_and_the_saved_blobs(tmp_path):
    every = write_session(tmp_path, counts=(3, 2))
    source = open_source(tmp_path)
    assert isinstance(source, RoiSource) and source.boxes == BOXES
    assert source.blobs() == {recording(0).name: [[0, 1.5]], recording(1).name: [[1, 1.5]]}
    images = [event.image for event in source.events() if isinstance(event, Frame)]
    assert len(images) == 5 and np.array_equal(images[0], every[0][0])
    x1, y1, x2, y2 = source.loader.rois[0]
    assert np.array_equal(images[3][y1:y2, x1:x2], every[1][0][y1:y2, x1:x2]) and images[3][0, WIDTH - 1] == 0
    first = [event.image for event in source.events(decode=RoiSource.FIRST) if isinstance(event, Frame)]
    assert np.array_equal(first[0], every[0][0]) and all(image is None for image in first[1:])
    assert (tmp_path / FIRST_FRAME_NAME).is_file()


def test_the_recorder_saves_from_its_thread_once_given_the_mites(tmp_path):
    recorder = Recorder(tmp_path)
    stack = frames(0, 3)
    recorder.start(stack[0], BOXES)
    for index, image in enumerate(stack):
        recorder.save(Frame(recording(0), index, f"{index:06}", image))
    recorder.end_recording(recording(0), [[1, 2]])
    assert recorder.flush(recording(0).name, timeout=30)
    assert RoiRecordings(tmp_path).recording_names == [recording(0).name]  # readable while the run goes on
    recorder.close()
    assert recorder.error is None and recorder.written == 3
    assert not (tmp_path / ROI_DIRNAME / PARTS_DIRNAME).exists()
    assert_reads_back(tmp_path, [stack])


@pytest.fixture(scope="module")
def live_session(tmp_path_factory):
    """A small session recorded live, so saved as ROIs, and its results."""
    tmp_path = tmp_path_factory.mktemp("live")
    small = reference.make_small_session(tmp_path / "small")
    monkeypatch = pytest.MonkeyPatch()
    try:
        folder_camera.open_live(monkeypatch, "rois", tmp_path / "out", "rois", small,
                                recordings_root=tmp_path / "recordings")
        pipeline.start_live("rois")
        run = pipeline._live["rois"]
        assert run.session.finished.wait(120)
        pipeline._live.pop("rois")
    finally:
        monkeypatch.undo()
    results = pipeline.run_analysis(run.run_dir, tmp_path / "folder_out")
    return run.run_dir, tmp_path / "folder_out", results, small


def test_a_live_run_saves_rois_and_one_whole_frame_much_smaller_than_the_frames(live_session):
    run_dir, _out, results, small = live_session
    assert results["frames"] == "rois"
    assert not list(run_dir.rglob("*.bmp")) and (run_dir / FIRST_FRAME_NAME).is_file()
    saved = sum(path.stat().st_size for path in run_dir.rglob("*") if path.is_file())
    whole = sum(path.stat().st_size for path in small.rglob("*.bmp"))
    assert saved < whole / 3


def test_of_a_session_of_rois_only_the_mites_clips_play(live_session):
    run_dir, out_dir, results, _small = live_session
    with pytest.raises(ValueError, match="only a mite's own clip"):
        pipeline.analysis_clip(run_dir, out_dir, 0, results["zones"][0]["id"])
    with pytest.raises(ValueError, match="only a mite's own clip"):
        pipeline.analysis_clip(run_dir, out_dir, 0)
    mite = results["mites"][0]
    clip = pipeline.analysis_mite_clip(run_dir, out_dir, 1, mite["id"], results["mites"])
    assert len(clip["frames"]) == 6 and clip["width"] == clip["height"] == 2 * pipeline.MITE_CLIP_REACH
    assert all((out_dir / name).is_file() for name in clip["frames"])
    assert pipeline.analysis_outlines(run_dir, out_dir, 0, mite["zone_id"], results)
    recording = pipeline.describe_recording(run_dir)
    assert recording["n_recordings"] == 3 and recording["frames"] == 6


def test_the_playback_shows_each_mite_of_a_zone_in_every_frame_as_saved(live_session):
    run_dir, out_dir, results, small = live_session
    timeline = pipeline.playback_timeline(run_dir, results)
    assert [r["frames"] for r in timeline["recordings"]] == [6, 6, 6] and timeline["tile"] == 2 * pipeline.playback_reach() < 40
    assert [m["id"] for m in timeline["mites"]] == [m["id"] for m in results["mites"]]
    zone = results["mites"][0]["zone_id"]
    sheet = pipeline.playback_sheet(run_dir, out_dir, 1, zone, results)
    mites = [m for m in results["mites"] if m["zone_id"] == zone]
    assert sheet["mites"] == [m["id"] for m in mites] and sheet["frames"] == 6
    picture = cv2.imread(str(out_dir / sheet["sheet"]), cv2.IMREAD_GRAYSCALE)
    side, reach = sheet["tile"], pipeline.playback_reach()
    assert picture.shape == (len(mites) * side, 6 * side)
    loader = RoiRecordings(run_dir)
    for row, mite in enumerate(mites):
        x, y = round(mite["x"]), round(mite["y"])
        x1, y1, x2, y2 = loader.roi_at(mite["x"], mite["y"])
        x1, y1, x2, y2 = max(x1, x - reach), max(y1, y - reach), min(x2, x + reach), min(y2, y + reach)
        saved = loader.load_recording_region(loader.recording_names[1], x1, y1, x2, y2)
        for column in (0, 5):
            tile = picture[row * side:(row + 1) * side, column * side:(column + 1) * side].astype(int)
            shown = tile[y1 - (y - reach):y2 - (y - reach), x1 - (x - reach):x2 - (x - reach)]
            assert np.abs(shown - saved[column]).mean() < 3      # as saved, but for the JPEG
    assert pipeline.playback_sheet(run_dir, out_dir, 1, zone, results) == sheet
    with pytest.raises(ValueError):
        pipeline.playback_sheet(run_dir, out_dir, 1, 999, results)


def test_the_playback_of_whole_frames_is_cut_round_each_mite(live_session, tmp_path):
    _run_dir, _out, results, small = live_session
    mite = results["mites"][0]
    sheet = pipeline.playback_sheet(small, tmp_path, 0, mite["zone_id"], results)
    picture = cv2.imread(str(tmp_path / sheet["sheet"]), cv2.IMREAD_GRAYSCALE)
    x, y, reach, side = round(mite["x"]), round(mite["y"]), pipeline.playback_reach(), sheet["tile"]
    name = sorted(path.name for path in small.iterdir() if path.is_dir())[0]
    first = cv2.imread(str(sorted((small / name).glob("*.bmp"))[0]), cv2.IMREAD_GRAYSCALE)
    row = sheet["mites"].index(mite["id"])
    tile = picture[row * side:(row + 1) * side, :side].astype(int)
    assert np.abs(tile - first[y - reach:y + reach, x - reach:x + reach]).mean() < 3


def test_the_playback_shows_the_fly_offs_too(live_session, tmp_path):
    _run_dir, _out, results, small = live_session
    mite = results["mites"][0]
    flown = {**results, "mites": results["mites"][1:],
             "activity": {"fly_offs": [{"id": mite["id"], "zone": mite["zone_id"], "x": mite["x"], "y": mite["y"], "from": 1}]}}
    timeline = pipeline.playback_timeline(small, flown)
    assert timeline["mites"][-1] == {"id": mite["id"], "zone_id": mite["zone_id"], "flew_off": 1}
    assert mite["id"] in pipeline.playback_sheet(small, tmp_path, 0, mite["zone_id"], flown)["mites"]


def test_a_session_of_rois_opened_by_its_path_is_linked_into_recordings_once(live_session, tmp_path):
    run_dir, _out, _results, _small = live_session
    recordings = tmp_path / "elsewhere"
    copy = pipeline.calibration_folder(run_dir, recordings)
    assert copy.parent == recordings and copy.name == run_dir.name
    assert (copy / ROI_DIRNAME / "mite_000.mkv").samefile(run_dir / ROI_DIRNAME / "mite_000.mkv")
    assert json.loads((copy / ROI_DIRNAME / INDEX_NAME).read_text()) == RoiRecordings(run_dir).index
    assert pipeline.calibration_folder(run_dir, recordings) == copy  # opened again: the same copy
    assert pipeline.calibration_folder(copy, recordings) == copy  # one in recordings/ is its own


def test_read_only_files_and_folders_are_removed_too(tmp_path):
    folder = tmp_path / "frames" / "inner"
    folder.mkdir(parents=True)
    (folder / "frame.bmp").write_bytes(b"x")
    os.chmod(folder / "frame.bmp", stat.S_IREAD)  # as OneDrive leaves them
    remove_tree(tmp_path / "frames")
    assert not (tmp_path / "frames").exists()
    remove_tree(tmp_path / "frames")  # nothing there: nothing to do
