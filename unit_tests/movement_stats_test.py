"""The movement numbers of the result pages (classes/movement_stats.py), and the
run plan of the live page (Settings.plan)."""

import pytest

import pipeline
from classes.live.settings import Settings
from classes.movement_stats import MovementReport, MovementStats

TIMES = [0, 1, 2, 3, 4, 5, 6]


def test_a_rest_is_the_time_between_two_movements_with_stillness_between():
    moving = [True, False, False, True, True, False, True]
    # 0 -> 3 is a rest, 3 -> 4 is not (moving twice in a row), 4 -> 6 is.
    assert MovementStats.rest_periods(moving, TIMES) == [3, 2]
    # Stillness before the first and after the last movement has no known length.
    assert MovementStats.rest_periods([False, True, False, False], TIMES) == []


def test_quartiles_and_whiskers():
    values = [1, 2, 3, 4, 100]
    assert MovementStats.quartiles(values) == (2, 3, 4)
    box = MovementStats.box_stats(values)
    assert box == {"q1": 2, "median": 3, "q3": 4, "lo": 1, "hi": 4}  # 100 is past the whisker
    assert MovementStats.quantile([5], 0.5) == 5


def results():
    zones = [
        {"id": 1, "label": "venom", "n_mites": 2},
        {"id": 2, "label": "", "n_mites": 1},
        {"id": 3, "label": "venom", "n_mites": 0},
    ]
    mites = [
        {"id": "0", "zone_id": 1, "moving": [True, False, True], "scores": [4.0, 1.0, 6.0]},
        {"id": "1", "zone_id": 1, "moving": [False, False, False], "scores": [0.5, 0.5, 2.0]},
        {"id": "2", "zone_id": 2, "moving": [False, True, False], "scores": [1.0, 3.0, 1.0]},
    ]
    return {"times": [0, 10, 20], "zones": zones, "mites": mites}


def test_each_mite_gets_its_numbers():
    described = MovementReport(results()).describe()
    first = described["mites"][0]
    assert (first["n_moving"], first["mean_score"], first["max_score"], first["last_movement"]) == (2, 11 / 3, 6.0, 20)
    assert described["mites"][1]["last_movement"] is None
    assert first["scores"] == [4.0, 1.0, 6.0]  # what was there stays


def test_each_zone_gets_its_numbers_and_rests():
    zones = {zone["id"]: zone for zone in MovementReport(results()).describe()["zones"]}
    zone = zones[1]
    assert (zone["n_moving_observations"], zone["n_never_moved"]) == (2, 1)
    assert zone["n_moving"] == [1, 0, 1]
    assert zone["overall_mean_score"] == pytest.approx(14 / 6)
    assert zone["rests"] == {"values": [20], "n_mites": 1, "q1": 20, "median": 20, "q3": 20, "shortest": 20, "longest": 20}
    assert zones[2]["rests"] is None  # moved once: no rest
    assert zones[3]["n_never_moved"] is None and zones[3]["rests"] is None  # no mites


def test_the_groups_in_page_order_with_the_box_of_their_moving_scores():
    rows = MovementReport(results()).describe()["group_rows"]
    assert [(row["group"], row["zones"], row["n_mites"]) for row in rows] == [("venom", [1], 2), ("unlabeled", [2], 1)]
    assert rows[0]["moving_scores"] == {"n": 2, "n_mites": 1, "q1": 4.5, "median": 5.0, "q3": 5.5, "lo": 4.0, "hi": 6.0}


def test_a_group_never_seen_moving_has_no_box():
    still = results()
    for mite in still["mites"]:
        mite["moving"] = [False, False, False]
    assert all(row["moving_scores"] is None for row in MovementReport(still).describe()["group_rows"])


def test_the_pipeline_adds_the_numbers_to_the_results():
    described = pipeline.describe_movement(results())
    assert described["times"] == [0, 10, 20]
    assert described["group_rows"] == MovementReport(results()).describe()["group_rows"]


def test_the_plan_of_a_test_run():
    settings = Settings(run_minutes=25, death_minutes=12, recording_timeout=5, frame_count=30, fps=10,
                        vent_time=20, led1_time=5, led2_time=5)
    # 37 min of recordings every 5 min: 9 recordings, the last at 40 min.
    assert settings.plan() == {"recording_seconds": 3.0, "cycle_seconds": 21, "recordings": 9, "minutes": 40,
                               "until_all_dead": False, "can_run_until_all_dead": True}
    settings.death_reset = 1  # the mites alone decide: at least through the 12 min to count one dead
    assert settings.plan()["recordings"] == 4 and settings.plan()["until_all_dead"] is True
    assert pipeline.live_plan(settings.as_dict()) == settings.plan()
