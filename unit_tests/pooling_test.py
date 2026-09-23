from datetime import datetime, timedelta

import cv2
import numpy as np
import pytest

from classes.data_loader import DataLoader
from classes.frame_source import Frame, FolderSource, Recording, RecordingEnd, as_analysis_image, frame_times
from classes.pooling import check_pool_size, pools

START = datetime(2025, 9, 4, 9, 28, 17)


def recording(minutes=0, fps=30):
    start = START + timedelta(minutes=minutes)
    return Recording(f"{start:%Y-%m-%d-%H-%M-%S}_fps-{fps}", start, fps)


def stream(*lengths):
    """Frames and ends of recordings `lengths` frames long, 5 minutes apart."""
    events = []
    for number, length in enumerate(lengths):
        rec = recording(5 * number)
        events += [Frame(rec, index, f"{index:06}.bmp", None) for index in range(length)]
        events.append(RecordingEnd(rec))
    return events


def shape(result):
    return [(pool.recording.name[11:19], pool.first_index, len(pool.frames)) for pool in result]


def test_by_default_a_pool_is_a_whole_recording():
    assert shape(pools(stream(30, 28, 31))) == [("09-28-17", 0, 30), ("09-33-17", 0, 28), ("09-38-17", 0, 31)]


def test_a_pool_size_splits_each_recording_and_leaves_its_rest_unscored():
    assert shape(pools(stream(25, 10), pool_size=10)) == [
        ("09-28-17", 0, 10), ("09-28-17", 10, 10),  # frames 20-24 are left over
        ("09-33-17", 0, 10),
    ]


def test_a_pool_never_spans_two_recordings():
    for pool in pools(stream(7, 7, 7), pool_size=4):
        assert len({frame.recording for frame in pool.frames}) == 1


def test_a_stream_that_stops_without_an_end_ends_its_recording():
    events = stream(5)[:-1]
    assert shape(pools(events)) == [("09-28-17", 0, 5)]
    assert shape(pools(events, pool_size=2)) == [("09-28-17", 0, 2), ("09-28-17", 2, 2)]


def test_frames_of_a_new_recording_before_the_end_of_the_last_are_refused():
    events = stream(3, 3)
    del events[3]  # the first recording's end
    with pytest.raises(ValueError):
        list(pools(events))


@pytest.mark.parametrize("bad", [0, 1, -3, 2.5, "10", True])
def test_bad_pool_sizes_are_refused(bad):
    with pytest.raises((ValueError, TypeError)):
        check_pool_size(bad)


def test_pool_times_are_those_folder_mode_gives_each_frame():
    events = [event for event in stream(4, 4) if isinstance(event, Frame)]
    expected = [0, 1 / 30, 2 / 30, 3 / 30, 300, 300 + 1 / 30, 300 + 2 / 30, 300 + 3 / 30]
    assert frame_times(events, START) == expected


def test_a_grey_frame_becomes_what_folder_mode_decodes_from_its_file(tmp_path):
    gray = np.random.default_rng(0).integers(0, 256, (6, 8), dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "frame.bmp"), gray)
    assert np.array_equal(as_analysis_image(gray), cv2.imread(str(tmp_path / "frame.bmp"), cv2.IMREAD_COLOR))


def write_session(root, lengths):
    for number, length in enumerate(lengths):
        folder = root / f"2025-09-04-09-{28 + 5 * number:02d}-17_fps-30"
        folder.mkdir(parents=True)
        for index in range(length):
            frame = np.full((4, 6), 10 * number + index, dtype=np.uint8)
            cv2.imwrite(str(folder / f"{folder.name}_{1000 + index:06}.bmp"), frame)
    return root


def test_the_folder_source_reads_what_the_data_loader_reads(tmp_path):
    root = write_session(tmp_path, [3, 2])
    events = list(FolderSource(root).events())
    frames = [event for event in events if isinstance(event, Frame)]
    loaded, times = DataLoader(root, grayscale=False).load_folder()
    assert np.array_equal(np.stack([frame.image for frame in frames]), loaded)
    assert frame_times(frames, frames[0].recording.start) == list(times)
    assert [type(event).__name__ for event in events] == ["Frame"] * 3 + ["RecordingEnd"] + ["Frame"] * 2 + ["RecordingEnd"]


def test_the_folder_source_needs_recordings(tmp_path):
    with pytest.raises(FileNotFoundError):
        list(FolderSource(tmp_path).events())


def test_with_a_pool_size_a_clip_plays_its_pool(tmp_path):
    import pipeline

    root = write_session(tmp_path / "session", [5, 4])
    (tmp_path / "out").mkdir()  # a session's output folder, as the app makes it
    # pools of 2: frames 0-1 and 2-3 of the first recording (4 left over), 0-1 and 2-3 of the second
    clip = pipeline.analysis_clip(root, tmp_path / "out", 3, pool_size=2)
    assert len(clip["frames"]) == 2 and "_p2_" in clip["frames"][0]
    frames = [cv2.imread(str(tmp_path / "out" / name), cv2.IMREAD_GRAYSCALE) for name in clip["frames"]]
    assert [int(np.median(frame)) for frame in frames] == [12, 13]  # recording 1, frames 2 and 3
    with pytest.raises(ValueError):
        pipeline.analysis_clip(root, tmp_path / "out", 4, pool_size=2)
    # without a pool size, as always: one clip per recording, named as before
    assert pipeline.analysis_clip(root, tmp_path / "out", 1)["frames"][0].startswith("clip_r1_plate_")
