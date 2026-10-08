"""Work shared out among threads, and a load started ahead (classes/workers.py):
the results are what doing it one after the other gives, in that order."""

import threading
import time

import pytest

from classes import workers
from classes.workers import one_ahead, side_by_side


@pytest.fixture
def several(monkeypatch):
    """Threads to share the work among, whatever this machine has."""
    monkeypatch.setattr(workers, "WORKERS", 4)
    monkeypatch.setattr(workers, "_threads", None)


def test_side_by_side_gives_the_results_in_order(several):
    def work(item):
        time.sleep(0.001 * (item % 3))  # so that they finish out of order
        return item * item

    assert side_by_side(work, range(50)) == [item * item for item in range(50)]
    assert side_by_side(work, []) == [] and side_by_side(work, [7]) == [49]


def test_the_work_is_done_on_several_threads(several):
    seen = set()
    barrier = threading.Barrier(2, timeout=5)  # met only if two items are in work at once

    def work(item):
        seen.add(threading.current_thread().name)
        if item < 2:
            barrier.wait()
        return item

    assert side_by_side(work, range(8)) == list(range(8))
    assert len(seen) > 1


def test_work_that_shares_out_work_of_its_own_does_not_wait_for_itself(several):
    def inner(item):
        return item + 1

    def outer(item):
        return sum(side_by_side(inner, range(item, item + 20)))

    assert side_by_side(outer, range(40)) == [sum(range(item + 1, item + 21)) for item in range(40)]


def test_an_error_in_the_work_is_raised(several):
    def work(item):
        if item == 5:
            raise ValueError("five")
        return item

    with pytest.raises(ValueError, match="five"):
        side_by_side(work, range(10))


def test_one_worker_does_it_all_itself(monkeypatch):
    monkeypatch.setattr(workers, "WORKERS", 1)
    names = set()
    side_by_side(lambda item: names.add(threading.current_thread().name), range(10))
    assert names == {threading.current_thread().name}


def test_one_ahead_gives_the_results_in_order_and_loads_one_ahead():
    loaded = []

    def load(number):
        loaded.append(number)
        return number * 10

    results = one_ahead((lambda number=number: load(number)) for number in range(5))
    assert next(results) == 0
    time.sleep(0.2)  # the one after it is loaded meanwhile, and no further
    assert loaded == [0, 1]
    assert list(results) == [10, 20, 30, 40]
    assert list(one_ahead([])) == []


def test_a_load_that_fails_raises_where_its_result_is_due():
    def load(number):
        if number == 2:
            raise FileNotFoundError("no third")
        return number

    results = one_ahead((lambda number=number: load(number)) for number in range(4))
    assert [next(results), next(results)] == [0, 1]
    with pytest.raises(FileNotFoundError, match="no third"):
        next(results)
