"""Files written a moment after the change that needs them: only the latest job
of a key runs, and finish() waits for it."""

import threading

from classes.deferred_files import DeferredFiles


def test_only_the_latest_job_of_a_key_is_run_and_finish_waits_for_it():
    files = DeferredFiles(delay=60)  # nothing runs by itself within the test
    ran = []
    for number in range(3):
        files.later("a", lambda number=number: ran.append(("a", number)))
    files.later("b", lambda: ran.append(("b", 0)))
    files.finish("a")
    assert ran == [("a", 2)]
    files.finish()
    assert ran == [("a", 2), ("b", 0)]
    files.finish()  # nothing left: returns at once


def test_a_job_runs_by_itself_once_the_changes_pause():
    files = DeferredFiles(delay=0.05)
    done = threading.Event()
    files.later("a", done.set)
    assert done.wait(5)


def test_a_job_still_waiting_can_be_forgotten():
    files = DeferredFiles(delay=60)
    ran = []
    files.later("a", lambda: ran.append("a"))
    files.later("b", lambda: ran.append("b"))
    files.forget("a")
    files.finish()
    assert ran == ["b"]
    files.later("a", lambda: ran.append("a"))
    files.forget()
    files.finish()
    assert ran == ["b"]


def test_a_job_that_fails_holds_up_nothing():
    files = DeferredFiles(delay=0)
    ran = []
    files.later("a", lambda: 1 / 0)
    files.finish()
    files.later("a", lambda: ran.append(1))
    files.finish()
    assert ran == [1]


def test_a_job_can_have_a_delay_of_its_own():
    files = DeferredFiles(delay=60)
    done = threading.Event()
    files.later("a", done.set, delay=0)
    assert done.wait(5)
