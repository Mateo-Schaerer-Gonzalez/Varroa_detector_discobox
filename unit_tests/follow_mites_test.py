"""A live run follows its mites (classes/scoring/motion_analysis.py): each moves to its blob
from recording to recording, mites can be added while it goes on, and a mite
counted dead is no longer scored nor saved. Analysing the saved run again must
give exactly what the live run gave."""

import time

import numpy as np
import pandas as pd
import pytest

import folder_camera
import pipeline
from pipeline import plate_zones
from pipeline.live import live_runs
import reference
from classes.scoring.analyzer import Analyzer
from classes.scoring.follow_up import FollowUp
from classes.storage.frame_source import Frame, Recording, RecordingEnd
from classes.scoring.motion_analysis import MotionAnalysis
from classes.storage.roi_recordings import ROI_MARGIN, CENTRE_REACH, placed_rect, roi_size


class Blobs(Analyzer):
    """The detector, but for the blobs: those given, per recording."""

    def __init__(self, per_recording):
        super().__init__()
        self.per_recording = list(per_recording)
        self.called = 0

    def blobs(self, masked_image):
        found = self.per_recording[min(self.called, len(self.per_recording) - 1)]
        self.called += 1
        return found


def stream(n_recordings, frames=3):
    image = np.full((1544, 2064), 200, dtype=np.uint8)
    for number in range(n_recordings):
        recording = Recording.from_name(f"2026-10-20-10-{number:02d}-00_fps-10", 10)
        for index in range(frames):
            yield Frame(recording, index, f"{index}.bmp", image)
        yield RecordingEnd(recording)


def analysis(blobs, follow=50):
    """`blobs`: per recording from the second on, those found on its first frame."""
    # The blobs of the first and last frames, for the fly-offs, are none: only following asks the detector.
    return MotionAnalysis(plate_zones.build_zone_manager(pipeline.DEFAULT_COORDS_FILE), Blobs(blobs), follow=follow,
                          boxes=[(300, 300, 310, 310), (400, 300, 410, 310)], known_blobs={})


def test_each_mite_moves_to_the_nearest_blob_in_its_zone_and_stays_without_one():
    # Recording 1: the first mite's blob 20 px right, the second's 80 px away (too far).
    # Recording 2: one pixel off (the detector's jitter): no move.
    run = analysis([[[325.0, 305.0], [485.0, 305.0]], [[326.0, 305.0]]])
    run.run(stream(3))
    first, second = run.mites
    assert run.boxes_of(first) == [(300, 300, 310, 310), (320, 300, 330, 310), (320, 300, 330, 310)]
    assert run.boxes_of(second) == [(400, 300, 410, 310)] * 3
    assert tuple(first) == (300, 300, 310, 310)  # its own box stays where it was found: its key


def test_a_mite_added_is_numbered_after_its_zone_and_scored_from_the_next_recording():
    run = analysis([[]])
    events = stream(3)
    run.run(event for event in _add_after_first(run, events, [(500, 350, 510, 360), (5, 5, 15, 15)]))
    added = run.mites[-1]
    assert len(run.mites) == 3  # the one outside every zone is left out
    zone = run.mites[0].text.split(".")[0]
    assert (added.text, added.start) == (f"{zone}.3", 1)
    assert added.motion_scores[0] is None and added.motion_scores[1] is not None
    assert run.boxes_of(added) == [None, (500, 350, 510, 360), (500, 350, 510, 360)]



def test_mites_added_together_are_numbered_in_reading_order_and_keep_the_order_they_were_added_in():
    run = analysis([[]])
    # given scrambled: lower right, upper left, upper right, lower left (all in the first mites' zone)
    boxes = [(470, 345, 480, 355), (330, 320, 340, 330), (470, 320, 480, 330), (330, 345, 340, 355)]
    run.run(event for event in _add_after_first(run, stream(3), boxes))
    zone = run.mites[0].text.split(".")[0]
    added = run.mites[2:]
    assert [tuple(mite) for mite in added] == boxes  # the order of a saved run's index
    # left to right, line by line, after the zone's two
    assert [mite.text for mite in added] == [f"{zone}.6", f"{zone}.3", f"{zone}.4", f"{zone}.5"]

def _add_after_first(run, events, boxes):
    for event in events:
        yield event
        if isinstance(event, RecordingEnd) and not run.recording_times[1:]:
            run.add_mites(boxes)


def test_a_mite_stopped_is_no_longer_scored():
    run = analysis([[]])
    events = stream(3)

    def stop_after_first():
        for event in events:
            yield event
            if isinstance(event, RecordingEnd) and len(run.recording_times) == 1:
                run.stop([run.mites[0]], 1)

    run.run(stop_after_first())
    assert run.mites[0].motion_scores[1:] == [None, None] and None not in run.mites[1].motion_scores
    assert run.boxes_of(run.mites[0])[1:] == [None, None]


def test_a_followed_roi_keeps_its_size_and_holds_what_is_read_round_the_box():
    size = roi_size((100, 100, 112, 110), 2064, 1544)
    assert all(side % 2 == 0 for side in size)
    for box in [(100, 100, 112, 110), (101, 99, 113, 109), (0, 0, 12, 10), (2052, 1534, 2064, 1544)]:
        x1, y1, x2, y2 = placed_rect(box, size, 2064, 1544)
        assert (x2 - x1, y2 - y1) == size and 0 <= x1 and 0 <= y1 and x2 <= 2064 and y2 <= 1544
        bx1, by1, bx2, by2 = box
        cx, cy = (bx1 + bx2) // 2, (by1 + by2) // 2
        assert x1 <= max(0, min(bx1 - ROI_MARGIN, cx - CENTRE_REACH)) and y1 <= max(0, min(by1 - ROI_MARGIN, cy - CENTRE_REACH))
        assert x2 >= min(2064, max(bx2 + ROI_MARGIN, cx + CENTRE_REACH)) and y2 >= min(1544, max(by2 + ROI_MARGIN, cy + CENTRE_REACH))


def test_the_results_set_aside_a_mite_before_it_was_added_and_keep_it_still_once_stopped():
    rows = pd.DataFrame([{"mite_ID": mite, "time": t, "motion_score": score, "moving": moving}
                         for mite, scores in (("1.1", [9, 9, None]), ("1.2", [None, 9, 9]))
                         for t, score, moving in zip([0, 5, 10], scores, [True, True, True])])
    data, changes = FollowUp({"1.2": 1}, {"1.1": 2}).censor(rows, {})
    assert list(data["moving"]) == [True, True, False, False, True, True]
    assert list(data["censored"]) == [False, False, False, True, False, False]
    assert changes == {"censored": {"1.2": [0]}, "started": {"1.2": 1}, "stopped": {"1.1": 2}}
    assert FollowUp({}, {}).censor(rows, {}) == (rows, {})  # a folder's mites: nothing changes


@pytest.mark.slow
def test_mites_added_and_stopped_live_score_the_same_from_the_saved_run(tmp_path, monkeypatch):
    session = reference.make_small_session(tmp_path / "small")
    first = reference.load("folder_sample_data")["results"]["mites"][0]
    status = folder_camera.open_live(monkeypatch, "follow", tmp_path / "out", "follow", session, gap=3,
                                     recordings_root=tmp_path / "recordings", settings={"death_minutes": 5})
    pipeline.start_live("follow")
    run = live_runs.open_runs["follow"]
    try:
        deadline = time.monotonic() + 60
        while pipeline.live_status("follow")["analysed"] < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        x, y = first["x"] + 30, first["y"]  # an empty spot of its zone
        pipeline.live_add_mites("follow", [[x - 5, y - 5, x + 5, y + 5]])
        assert run.session.finished.wait(120)
    finally:
        live_runs.open_runs.pop("follow")
    live = reference.plain(run.session.results)
    assert live["started"] and live["stopped"]  # a mite added, and mites counted dead and no longer followed
    # the pages' numbers skip the recordings without a score
    pipeline.describe_movement(live)
    pipeline.describe_survival(live, 5)
    again = reference.run_folder(run.run_dir, tmp_path / "folder_out", pipeline.load_labels(run.run_dir) or None)
    found = reference.differences(again["results"], live)
    assert not found, "The live results differ from the saved run's:\n  " + "\n  ".join(found)
    assert status["run_dir"]
