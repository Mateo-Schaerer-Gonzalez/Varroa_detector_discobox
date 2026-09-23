"""Which frames are scored together: the only pooling code, used by folder mode
and live mode alike.

By default a pool is a whole recording, i.e. every frame of one recording folder
(one burst), which is how folder mode has always scored: one score per mite per
recording. With `pool_size` N each recording is split instead into consecutive,
non-overlapping pools of N frames. A pool never spans two recordings, and the
frames left at the end of a recording, fewer than N, are not scored.
"""

from dataclasses import dataclass

from classes.frame_source import Frame, RecordingEnd

MIN_POOL_SIZE = 2  # a motion score compares frames, so it needs at least two


@dataclass
class Pool:
    """Frames scored together: consecutive frames of one recording, in order."""

    frames: list

    @property
    def recording(self):
        return self.frames[0].recording

    @property
    def first_index(self):
        return self.frames[0].index


def check_pool_size(pool_size):
    """None (a pool is a whole recording) or a whole number of frames, at least 2."""
    if pool_size is None:
        return None
    if isinstance(pool_size, bool) or int(pool_size) != pool_size or pool_size < MIN_POOL_SIZE:
        raise ValueError(f"The pool size must be a whole number of frames, at least {MIN_POOL_SIZE}, not {pool_size!r}.")
    return int(pool_size)


def describe_pool_size(pool_size):
    return "whole recording" if pool_size is None else f"{pool_size} frames"


def pools(events, pool_size=None):
    """Group a stream of Frames and RecordingEnds (see classes/frame_source.py)
    into Pools, each as soon as it is complete.

    A stream that stops without a RecordingEnd ends its last recording there.
    """
    pool_size = check_pool_size(pool_size)
    current = []
    for event in events:
        if isinstance(event, RecordingEnd):
            if current and pool_size is None:
                yield Pool(current)
            current = []  # with a pool size, a partial pool is left unscored
            continue
        if not isinstance(event, Frame):
            raise TypeError(f"Expected a Frame or a RecordingEnd, got {event!r}")
        if current and event.recording != current[0].recording:
            raise ValueError(f"A frame of {event.recording.name} came before {current[0].recording.name} ended.")
        current.append(event)
        if pool_size is not None and len(current) == pool_size:
            yield Pool(current)
            current = []
    if current and pool_size is None:
        yield Pool(current)
