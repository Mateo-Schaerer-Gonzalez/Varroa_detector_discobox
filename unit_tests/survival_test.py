"""Alive or dead, and the log-rank test against the negative controls
(classes/survival.py), as the result pages show them."""

import pytest
from scipy import stats

import pipeline
from classes.survival import SurvivalAnalysis, SurvivalReport

TIMES = [0, 10, 20]
NEVER = [False, False, False]
FIRST_ONLY = [True, False, False]
FIRST_TWO = [True, True, False]
ALWAYS = [True, True, True]


def test_a_mite_is_alive_up_to_its_last_movement():
    survival = SurvivalAnalysis(TIMES)
    assert [survival.is_alive(FIRST_ONLY, r) for r in range(3)] == [True, False, False]
    assert [survival.is_alive(ALWAYS, r) for r in range(3)] == [True, True, True]
    assert [survival.is_alive(NEVER, r) for r in range(3)] == [False, False, False]


def test_with_a_death_time_a_mite_still_for_less_counts_as_alive():
    # Still for 20 min since its movement at 0: dead after 15 min, not after 25.
    assert [SurvivalAnalysis(TIMES, 15).is_alive(FIRST_ONLY, r) for r in range(3)] == [True, False, False]
    assert [SurvivalAnalysis(TIMES, 25).is_alive(FIRST_ONLY, r) for r in range(3)] == [True, True, True]
    # Never seen moving: still since the first recording.
    assert [SurvivalAnalysis(TIMES, 25).is_alive(NEVER, r) for r in range(3)] == [True, True, True]


def test_the_last_movement():
    survival = SurvivalAnalysis(TIMES)
    assert survival.last_movement(FIRST_TWO) == 1
    assert survival.last_movement(NEVER) == -1
    assert survival.last_movement_time(FIRST_TWO) == 10
    assert survival.last_movement_time(NEVER) is None


def test_the_share_alive_in_each_recording():
    survival = SurvivalAnalysis(TIMES)
    assert survival.alive_percent([FIRST_ONLY, ALWAYS, FIRST_TWO]) == [100.0, 200 / 3, 100 / 3]
    assert survival.alive_count([FIRST_ONLY, ALWAYS, FIRST_TWO], 1) == 2
    assert survival.alive_percent([]) == [None, None, None]


def test_a_mite_alive_at_the_end_is_censored_there():
    survival = SurvivalAnalysis(TIMES)
    assert survival.survival(FIRST_ONLY) == (10, True)
    assert survival.survival(NEVER) == (0, True)
    assert survival.survival(ALWAYS) == (20, False)
    assert survival.dead_count([FIRST_ONLY, NEVER, ALWAYS]) == 2


def test_the_log_rank_test_by_hand():
    # Tested: deaths at 0 and 10. Controls: one censored at 20, one dead at 20.
    # At 0: 4 at risk, half tested, 1 death -> expected 1/2, variance 1/4.
    # At 10: 3 at risk, a third tested, 1 death -> expected 1/3, variance 2/9.
    # At 20: only controls at risk, which adds nothing.
    test = SurvivalAnalysis(TIMES).log_rank([NEVER, FIRST_ONLY], [ALWAYS, FIRST_TWO])
    assert test.observed == 2
    assert test.expected == pytest.approx(5 / 6)
    assert test.chi2 == pytest.approx(49 / 17)
    assert test.p == pytest.approx(0.08956, abs=1e-5)


def test_the_p_value_is_that_of_chi_squared_with_one_degree_of_freedom():
    test = SurvivalAnalysis(TIMES).log_rank([NEVER, FIRST_ONLY], [ALWAYS, FIRST_TWO])
    assert test.p == pytest.approx(stats.chi2.sf(test.chi2, df=1))


def test_no_p_value_when_no_death_could_have_gone_either_way():
    test = SurvivalAnalysis(TIMES).log_rank([ALWAYS], [ALWAYS])
    assert (test.observed, test.expected, test.chi2, test.p) == (0, 0.0, None, None)


def results_with(zones):
    """Results as pipeline describes them: `zones` maps (zone id, label) to the
    movement of each of its mites."""
    described, mites = [], []
    for (zone_id, label), movings in zones.items():
        described.append({"id": zone_id, "label": label, "n_mites": len(movings)})
        for moving in movings:
            mites.append({"id": str(len(mites)), "zone_id": zone_id, "moving": moving, "scores": [1.0] * len(moving)})
    return {"times": TIMES, "zones": described, "mites": mites}


RESULTS = results_with({
    (1, "venom"): [NEVER, FIRST_ONLY],
    (2, ""): [ALWAYS],
    (3, "Buffer"): [FIRST_TWO, ALWAYS],
    (4, "venom"): [FIRST_TWO],
    (5, "empty"): [],
})


def test_the_groups_alive_over_time_in_the_order_the_pages_list_them():
    report = SurvivalReport(RESULTS).describe()
    assert [row["group"] for row in report["groups"]] == ["Buffer", "venom", "unlabeled"]
    assert report["groups"][1]["alive"] == [200 / 3, 100 / 3, 0.0]
    assert report["zones"][1] == {"alive": [50.0, 0.0, 0.0], "n_alive": [1, 0, 0]}
    assert 5 not in report["zones"]  # nothing to show in a zone without mites


def test_every_group_against_the_controls():
    log_rank = SurvivalReport(RESULTS, controls=[3, 5]).describe()["log_rank"]
    assert log_rank["controls"] == [3, 5]
    assert log_rank["control_zones"] == [3]  # zone 5 holds no mites
    assert log_rank["control_groups"] == ["Buffer"]
    assert (log_rank["n_control_mites"], log_rank["n_control_dead"]) == (2, 1)
    # One row per group, its zones pooled; "unlabeled" last.
    assert [(row["group"], row["zones"]) for row in log_rank["rows"]] == [("venom", [1, 4]), ("unlabeled", [2])]
    venom = log_rank["rows"][0]
    assert venom["n_mites"] == 3
    assert venom["observed"] == 3
    assert set(venom) == {"group", "zones", "n_mites", "observed", "expected", "chi2", "p"}


def test_a_groups_zones_ticked_as_control_are_left_out_of_its_row():
    results = results_with({(1, "venom"): [NEVER], (2, "venom"): [ALWAYS], (3, "venom"): [FIRST_ONLY]})
    [row] = SurvivalReport(results, controls=[2]).describe()["log_rank"]["rows"]
    assert (row["group"], row["zones"], row["n_mites"]) == ("venom", [1, 3], 2)


def test_no_rows_without_a_control_mite():
    assert SurvivalReport(RESULTS).describe()["log_rank"]["rows"] == []
    assert SurvivalReport(RESULTS, controls=[5]).describe()["log_rank"]["rows"] == []


def test_the_death_time_changes_the_numbers():
    assert SurvivalReport(RESULTS, death_minutes=25).describe()["groups"][1]["alive"] == [100.0, 100.0, 100.0]
    assert pipeline.describe_survival(RESULTS, 25, [3]) == SurvivalReport(RESULTS, 25, [3]).describe()


def test_the_live_page_counts_the_mites_alive_by_the_same_rule():
    assert pipeline.mites_alive(RESULTS, 0) == 2
    assert pipeline.mites_alive(RESULTS, 25) == 6
