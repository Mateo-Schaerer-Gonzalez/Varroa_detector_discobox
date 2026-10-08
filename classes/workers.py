"""Work shared out, so that a run does not wait where it need not.

Scoring a recording is the same work for every mite: measure its shift, cut its
patch, score it. Nearly all of it is OpenCV's and numpy's, which work outside
Python's lock, so threads do it for several mites at once (side_by_side()). The
threads are shared by everything in the process, on half the processors and at
most 8, so that a live run's capture keeps the rest. A process that is itself
one of several workers (the scripts' process pools) works alone: its siblings
have the other processors.

Reading the frames of a recording waits for the disk and the decoder, not for
the scoring, so the next recording is read while this one is scored (one_ahead()).

Neither changes a number: the same calls are made on the same values, only not
one after the other.
"""

import multiprocessing
import os
import threading
from concurrent.futures import ThreadPoolExecutor

WORKERS = 1 if multiprocessing.parent_process() is not None else max(1, min(8, (os.cpu_count() or 2) // 2))

_threads = None
_starting = threading.Lock()
_here = threading.local()  # .working: this thread is one of the shared ones


def _shared():
    global _threads
    with _starting:
        if _threads is None:
            _threads = ThreadPoolExecutor(WORKERS, thread_name_prefix="mites",
                                          initializer=lambda: setattr(_here, "working", True))
    return _threads


def side_by_side(work, items):
    """[work(item) for item in items], in that order, the items shared out among
    the threads. Work that shares out work of its own does that part alone,
    rather than wait for threads that wait for it."""
    items = list(items)
    if WORKERS < 2 or len(items) < 2 or getattr(_here, "working", False):
        return [work(item) for item in items]
    # a few items per thread at a time: handing each one over on its own would
    # cost as much as the smallest of them take
    size = max(1, -(-len(items) // (4 * WORKERS)))
    parts = [items[start:start + size] for start in range(0, len(items), size)]
    done = _shared().map(lambda part: [work(item) for item in part], parts)
    return [result for part in done for result in part]


def one_ahead(loads):
    """The results of the calls `loads`, in order, each started when the one
    before it is handed over, so that it loads while that one is worked on. Two
    are held at most: the one in work and the one loaded ahead. A call that
    fails raises where its result is due."""
    with ThreadPoolExecutor(1, thread_name_prefix="ahead") as loader:
        waiting = None
        for load in loads:
            following = loader.submit(load)
            if waiting is not None:
                yield waiting.result()
            waiting = following
        if waiting is not None:
            yield waiting.result()
