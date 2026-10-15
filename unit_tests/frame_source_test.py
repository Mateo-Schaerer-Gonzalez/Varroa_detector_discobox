from datetime import datetime, timedelta

import cv2
import numpy as np
import pytest

from classes.data_loader import DataLoader
from classes.frame_source import Frame, FolderSource, Recording, RecordingEnd, frame_times, recordings

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
    return [(frames[0].recording.name[11:19], [frame.index for frame in frames]) for frames in result]


def test_the_frames_are_grouped_by_recording_every_one_of_them():
    assert shape(recordings(stream(30, 28, 31))) == [
        ("09-28-17", list(range(30))), ("09-33-17", list(range(28))), ("09-38-17", list(range(31)))]


def test_a_stream_that_stops_without_an_end_ends_its_recording():
    assert shape(recordings(stream(5)[:-1])) == [("09-28-17", list(range(5)))]


def test_frames_of_a_new_recording_before_the_end_of_the_last_are_refused():
    events = stream(3, 3)
    del events[3]  # the first recording's end
    with pytest.raises(ValueError):
        list(recordings(events))


def test_frame_times_are_those_folder_mode_gives_each_frame():
    events = [event for event in stream(4, 4) if isinstance(event, Frame)]
    expected = [0, 1 / 30, 2 / 30, 3 / 30, 300, 300 + 1 / 30, 300 + 2 / 30, 300 + 3 / 30]
    assert frame_times(events, START) == expected


def test_a_saved_grey_frame_reads_back_as_it_was_and_as_each_channel_of_a_colour_read(tmp_path):
    gray = np.random.default_rng(0).integers(0, 256, (6, 8), dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "frame.bmp"), gray)
    read = FolderSource._read(tmp_path / "frame.bmp")
    assert read.shape == (6, 8) and np.array_equal(read, gray)
    colour = cv2.imread(str(tmp_path / "frame.bmp"), cv2.IMREAD_COLOR)
    assert all(np.array_equal(colour[..., channel], read) for channel in range(3))


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
    loaded, times = DataLoader(root).load_folder()
    assert np.array_equal(np.stack([frame.image for frame in frames]), loaded)
    assert frame_times(frames, frames[0].recording.start) == list(times)
    assert [type(event).__name__ for event in events] == ["Frame"] * 3 + ["RecordingEnd"] + ["Frame"] * 2 + ["RecordingEnd"]


def test_the_folder_source_needs_recordings(tmp_path):
    with pytest.raises(FileNotFoundError):
        list(FolderSource(tmp_path).events())


def test_a_clip_plays_every_frame_of_its_recording(tmp_path):
    import pipeline

    root = write_session(tmp_path / "session", [5, 4])
    (tmp_path / "out").mkdir()  # a session's output folder, as the app makes it
    clip = pipeline.analysis_clip(root, tmp_path / "out", 1)
    assert len(clip["frames"]) == 4 and clip["frames"][0].startswith("clips/clip_r1_plate_")
    frames = [cv2.imread(str(tmp_path / "out" / name), cv2.IMREAD_GRAYSCALE) for name in clip["frames"]]
    assert [int(np.median(frame)) for frame in frames] == [10, 11, 12, 13]
    with pytest.raises(ValueError):
        pipeline.analysis_clip(root, tmp_path / "out", 2)


def test_the_folder_source_can_decode_the_first_frame_alone(tmp_path):
    root = write_session(tmp_path, [3, 2])
    whole = list(FolderSource(root).events())
    events = list(FolderSource(root).events(decode=FolderSource.FIRST))
    frames = [event for event in events if isinstance(event, Frame)]
    assert [type(event).__name__ for event in events] == [type(event).__name__ for event in whole]
    assert [(frame.recording, frame.index, frame.filename) for frame in frames] == [
        (frame.recording, frame.index, frame.filename) for frame in whole if isinstance(frame, Frame)]
    assert np.array_equal(frames[0].image, whole[0].image) and all(frame.image is None for frame in frames[1:])
    assert all(frame.image is None for frame in FolderSource(root).events(decode=False) if isinstance(frame, Frame))


def test_a_frame_that_cannot_be_read_stops_the_stream_at_its_recording(tmp_path):
    root = write_session(tmp_path, [2, 2, 2])
    second = sorted(d for d in root.iterdir() if d.is_dir())[1]
    sorted(second.glob("*.bmp"))[1].write_bytes(b"not a picture")
    events = FolderSource(root).events()
    assert [type(next(events)).__name__ for _ in range(3)] == ["Frame", "Frame", "RecordingEnd"]  # the first recording is whole
    with pytest.raises(ValueError, match="Could not read"):
        next(events)


def test_a_recording_without_frames_stops_the_stream_there(tmp_path):
    root = write_session(tmp_path, [2, 2])
    (root / "2025-09-04-09-40-17_fps-30").mkdir()
    events = FolderSource(root).events()
    assert len([next(events) for _ in range(6)]) == 6  # the two recordings with frames
    with pytest.raises(FileNotFoundError, match="No .bmp"):
        next(events)
