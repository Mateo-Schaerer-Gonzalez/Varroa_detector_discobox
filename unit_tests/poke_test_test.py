"""The poke test: what the pokes say about each mite's death, and the survival
curves of the poked mites by the pokes and by the detector."""

import pytest

from classes.poke_test import PokeSurvival, PokeTest

TIMES = [0.0, 10.0, 20.0, 30.0]


def mites(n=3):
    return [{"id": str(i), "zone_id": i % 2, "x": 20.0 * i + 10, "y": 10.0} for i in range(n)]


def poked(rounds, n=3):
    """A poke test with `rounds`: {after: {mite id: state}}."""
    poke = PokeTest(mites(n), len(TIMES))
    for after, states in rounds.items():
        poke.add(after)
        for mite_id, state in states.items():
            poke.set(after, mite_id, state)
    return poke


def test_a_poke_bounds_the_death_of_a_mite():
    poke = poked({1: {"0": "moved", "1": "moved"}, 3: {"0": "moved", "1": "unmoved"}})
    assert poke.bounds("0") == (4, None)   # alive through all four recordings
    assert poke.bounds("1") == (2, 4)      # died after the second recording, before the end
    assert poke.bounds("2") == (None, None)


def test_a_poke_before_the_first_recording():
    poke = poked({-1: {"0": "unmoved", "1": "moved"}})
    assert poke.bounds("0") == (None, 0) and poke.bounds("1") == (0, None)


def test_the_survival_of_the_poked_mites_by_the_pokes_and_by_the_detector():
    # mite 0 answers both pokes; mite 1 only the first; mite 2 fails the one after the last recording;
    # mite 3 answers a poke after not answering one, and is in neither curve; mite 4 is not poked
    poke = poked({1: {"0": "moved", "1": "moved", "3": "unmoved"},
                  3: {"0": "moved", "1": "unmoved", "2": "unmoved", "3": "moved"}}, n=5)
    moving = {
        "0": [True, True, True, True],      # moving to the end: censored at the last recording
        "1": [True, True, False, False],    # dead from the third recording
        "2": [False, False, False, False],  # never seen moving: dead from the first
        "3": [True, True, True, True],
        "4": [True, True, True, True],
    }
    rows = PokeSurvival(poke, TIMES, moving).mites()
    assert rows == [{"n_recordings": 4, "death": 4, "alive_until": 4, "dead_from": None},
                    {"n_recordings": 4, "death": 2, "alive_until": 2, "dead_from": 4},
                    {"n_recordings": 4, "death": 0, "alive_until": None, "dead_from": 4},
                    {"n_recordings": 4, "death": 4, "alive_until": 4, "dead_from": 2}]
    curves = PokeSurvival.curves(rows, TIMES)
    # one more time than recordings: the poke after the last one, which mites 1 and 2 did not answer
    assert curves["final_poke"] and curves["times"] == [0.0, 10.0, 20.0, 30.0, 40.0]
    assert (curves["poke"]["n_mites"], curves["poke"]["n_dead"], curves["n_left_out"]) == (3, 2, 1)
    # at the poke after the last recording mite 0 answers and the other two do not
    assert curves["poke"]["alive"] == [100, 100, 100, 100, pytest.approx(100 / 3)]
    # the detector saw nothing after the last recording
    assert (curves["detector"]["n_mites"], curves["detector"]["n_dead"]) == (3, 2)
    third = pytest.approx(100 / 3)
    assert curves["detector"]["alive"] == [pytest.approx(200 / 3), pytest.approx(200 / 3), third, third, None]


def test_without_a_poke_after_the_last_recording_the_curves_end_with_the_recordings():
    poke = poked({1: {"0": "unmoved", "1": "moved"}})
    moving = {"0": [True, False, False, False], "1": [True, True, False, False], "2": [True] * 4}
    curves = PokeSurvival.curves(PokeSurvival(poke, TIMES, moving).mites(), TIMES)
    assert not curves["final_poke"] and curves["times"] == TIMES
    assert curves["poke"]["alive"] == [100, 100, 50, 50]     # mite 0 dead from the third recording, where mite 1 is censored
    assert curves["detector"]["alive"] == [100, 50, 0, 0]  # mite 0 dead from the second, mite 1 from the third
    assert PokeSurvival.curves([], TIMES) is None


def test_filling_leaves_the_mites_already_poked():
    poke = poked({3: {"0": "moved"}})
    poke.fill(3, "unmoved", zone_id=0)   # mites 0 and 2 are in zone 0
    assert poke.view()["rounds"][0]["states"] == {"0": "moved", "2": "unmoved"}
    poke.fill(3, "unmoved")
    assert poke.view()["rounds"][0]["counts"] == {"moved": 1, "unmoved": 2, "unset": 0}
    poke.fill(3, None, zone_id=0)        # taking the pokes of a zone back
    assert poke.view()["rounds"][0]["states"] == {"1": "unmoved"}


def test_rounds_are_kept_in_order_and_one_per_recording():
    poke = poked({3: {}, 1: {}})
    assert [poke_round["after"] for poke_round in poke.view()["rounds"]] == [1, 3]
    with pytest.raises(ValueError):
        poke.add(1)
    with pytest.raises(ValueError):
        poke.add(4)
    with pytest.raises(ValueError):
        poke.set(2, "0", "moved")  # no round there
    with pytest.raises(ValueError):
        poke.set(1, "0", "alive")
    poke.remove(1)
    assert [poke_round["after"] for poke_round in poke.view()["rounds"]] == [3]


def test_the_pokes_are_saved_by_position_and_survive_renumbered_mites():
    saved = poked({3: {"0": "moved", "2": "unmoved"}}).saved()
    assert saved == {"rounds": [{"after": 3, "mites": [{"x": 10.0, "y": 10.0, "state": "moved"},
                                                       {"x": 50.0, "y": 10.0, "state": "unmoved"}]}]}
    # detected again: other ids, a few pixels off, and the middle mite gone
    again = [{"id": "a", "zone_id": 0, "x": 52.0, "y": 11.0}, {"id": "b", "zone_id": 0, "x": 9.0, "y": 12.0}]
    reloaded = PokeTest(again, len(TIMES), saved)
    assert reloaded.view()["rounds"][0]["states"] == {"a": "unmoved", "b": "moved"}

    # a poke of no mite here, e.g. of a detection since marked not a mite, is kept as it is
    fewer = PokeTest(again[:1], len(TIMES), saved)
    assert fewer.view()["rounds"][0]["states"] == {"a": "unmoved"}
    assert {"x": 10.0, "y": 10.0, "state": "moved"} in fewer.saved()["rounds"][0]["mites"]
