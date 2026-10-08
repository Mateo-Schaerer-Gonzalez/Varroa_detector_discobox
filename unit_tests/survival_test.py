"""Alive or dead, and the log-rank test against the negative controls
(classes/survival.py), as the result pages show them."""

import math
import random

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


def alive_by_the_rule(survival, moving, recording):
    """The rule as the module's docstring states it, recording by recording."""
    moved = [index for index, value in enumerate(moving) if value]
    there = [index for index, value in enumerate(moving) if value is not None]
    last, end = (moved[-1] if moved else -1), (there[-1] if there else -1)
    if recording <= last:
        return True
    if recording > end:
        return False
    return survival.times[end] - survival.times[max(last, 0)] < survival.death_minutes


def test_one_pass_over_a_mites_calls_tells_every_recording():
    rng = random.Random(3)
    for _trial in range(400):
        n = rng.randint(1, 12)
        times = sorted(rng.sample(range(300), n))
        survival = SurvivalAnalysis(times, rng.choice([0, 10, 40, 500]))
        movings = [[rng.choice([True, False, False, None]) for _ in range(n)] for _ in range(rng.randint(0, 5))]
        movings.append([None] * n)  # never there
        for moving in movings:
            alive = [alive_by_the_rule(survival, moving, recording) for recording in range(n)]
            assert [survival.is_alive(moving, recording) for recording in range(n)] == alive
            # alive up to a last recording, never again after it
            assert alive == [recording <= survival.alive_until(moving) for recording in range(n)]
        assert survival.alive_counts(movings) == [survival.alive_count(movings, recording) for recording in range(n)]
        assert survival.alive_counts(movings) == [sum(alive_by_the_rule(survival, moving, recording) for moving in movings)
                                                  for recording in range(n)]


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


def test_the_confidence_interval_by_hand():
    # Deaths at 0 (1 of 4 at risk) and 10 (1 of 3); two mites alive at the end.
    # Greenwood: var(log S) sums d / (n (n - d)); on the log-log scale the
    # interval is S ** exp(±z sigma), with sigma = sqrt(var(log S)) / |log S|.
    ci = SurvivalAnalysis(TIMES).alive_ci([NEVER, FIRST_ONLY, ALWAYS, ALWAYS])
    z = stats.norm.ppf(0.975)
    for recording, alive, greenwood in [(0, 0.75, 1 / 12), (1, 0.5, 1 / 12 + 1 / 6), (2, 0.5, 1 / 12 + 1 / 6)]:
        sigma = math.sqrt(greenwood) / abs(math.log(alive))
        assert ci["low"][recording] == pytest.approx(100 * alive ** math.exp(z * sigma))
        assert ci["high"][recording] == pytest.approx(100 * alive ** math.exp(-z * sigma))


def test_the_confidence_interval_is_the_estimate_where_all_or_none_are_alive():
    survival = SurvivalAnalysis(TIMES)
    assert survival.alive_ci([ALWAYS, ALWAYS]) == {"low": [100.0] * 3, "high": [100.0] * 3}
    assert survival.alive_ci([NEVER, NEVER]) == {"low": [0.0] * 3, "high": [0.0] * 3}
    assert survival.alive_ci([FIRST_ONLY]) == {"low": [100.0, 0.0, 0.0], "high": [100.0, 0.0, 0.0]}
    assert survival.alive_ci([]) == {"low": [None] * 3, "high": [None] * 3}


def test_the_share_alive_is_the_kaplan_meier_estimate_inside_its_interval():
    rng = random.Random(3)
    for _ in range(200):
        times = sorted(rng.sample(range(100), rng.randint(2, 6)))
        survival = SurvivalAnalysis(times, rng.choice([0, 15]))
        movings = [[rng.random() < 0.6 for _ in times] for _ in range(rng.randint(1, 12))]
        alive = survival.alive_percent(movings)
        ci = survival.alive_ci(movings)
        estimate = stats.ecdf(survival.censored([survival.survival(moving) for moving in movings])).sf.evaluate(times)
        assert alive == pytest.approx(list(100 * estimate))
        for low, value, high in zip(ci["low"], alive, ci["high"]):
            assert 0 <= low <= value + 1e-9 and value - 1e-9 <= high <= 100


def test_lt50_is_the_first_time_at_most_half_are_alive():
    survival = SurvivalAnalysis(TIMES)
    # Alive: 75%, 50%, 50%. The interval (see the Greenwood test above) is about
    # 13-96% at 0 and 6-84% after, so its high bound never reaches 50%.
    assert survival.lt50([NEVER, FIRST_ONLY, ALWAYS, ALWAYS]) == {"estimate": 10, "low": 0, "high": None}
    assert survival.lt50([NEVER, NEVER]) == {"estimate": 0, "low": 0, "high": 0}


def test_lt50_is_none_when_more_than_half_are_alive_at_the_end():
    survival = SurvivalAnalysis(TIMES)
    assert survival.lt50([ALWAYS, ALWAYS]) == {"estimate": None, "low": None, "high": None}
    # 2 of 3 alive at the end: not reached, though the interval's low bound is.
    assert survival.lt50([ALWAYS, ALWAYS, FIRST_TWO]) == {"estimate": None, "low": 20, "high": None}


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
    assert report["groups"][0]["alive"] == [100.0, 100.0, 50.0]
    assert report["zones"][4]["alive"] == [100.0, 100.0, 0.0]
    assert report["zones"][4]["n_alive"] == [1, 1, 0]
    # Each curve with its confidence interval, the group's of its zones pooled.
    assert report["zones"][1]["alive_ci"] == SurvivalAnalysis(TIMES).alive_ci([FIRST_ONLY])
    assert report["groups"][1]["alive_ci"] == SurvivalAnalysis(TIMES).alive_ci([FIRST_ONLY, FIRST_TWO])
    assert 5 not in report["zones"]  # nothing to show in a zone without mites


def test_every_group_against_the_controls():
    log_rank = SurvivalReport(RESULTS, controls=[3, 5]).describe()["log_rank"]
    assert log_rank["controls"] == [3, 5]
    assert log_rank["control_zones"] == [3]  # zone 5 holds no mites
    assert log_rank["control_groups"] == ["Buffer"]
    assert (log_rank["n_control_mites"], log_rank["n_control_dead"]) == (2, 1)
    assert log_rank["control_lt50"] == SurvivalAnalysis(TIMES).lt50([FIRST_TWO, ALWAYS])
    # One row per group, its zones pooled; "unlabeled" last.
    assert [(row["group"], row["zones"]) for row in log_rank["rows"]] == [("venom", [1, 4]), ("unlabeled", [2])]
    venom = log_rank["rows"][0]
    assert venom["n_mites"] == 2  # the mite never seen moving is left out
    assert venom["observed"] == 2
    assert venom["lt50"] == SurvivalAnalysis(TIMES).lt50([FIRST_ONLY, FIRST_TWO])
    assert set(venom) == {"group", "zones", "n_mites", "lt50", "observed", "expected", "chi2", "p"}


def test_a_groups_zones_ticked_as_control_are_left_out_of_its_row():
    results = results_with({(1, "venom"): [FIRST_TWO], (2, "venom"): [ALWAYS], (3, "venom"): [FIRST_ONLY]})
    [row] = SurvivalReport(results, controls=[2]).describe()["log_rank"]["rows"]
    assert (row["group"], row["zones"], row["n_mites"]) == ("venom", [1, 3], 2)


def test_no_rows_without_a_control_mite():
    assert SurvivalReport(RESULTS).describe()["log_rank"]["rows"] == []
    assert SurvivalReport(RESULTS, controls=[5]).describe()["log_rank"]["rows"] == []


def test_the_death_time_changes_the_numbers():
    assert SurvivalReport(RESULTS, death_minutes=25).describe()["groups"][1]["alive"] == [100.0, 100.0, 100.0]
    assert pipeline.describe_survival(RESULTS, 25, [3]) == SurvivalReport(RESULTS, 25, [3]).describe()


def test_the_live_page_counts_the_mites_alive_by_the_same_rule():
    # Of the 6 mites, the one never seen moving is left out.
    assert pipeline.mites_alive(RESULTS, 0) == {"alive": 2, "mites": 5}
    assert pipeline.mites_alive(RESULTS, 25) == {"alive": 5, "mites": 5}


def test_a_mite_never_seen_moving_is_left_out():
    report = SurvivalReport(RESULTS).describe()
    # Zone 1 holds NEVER and FIRST_ONLY: only FIRST_ONLY counts.
    assert report["zones"][1]["alive"] == [100.0, 0.0, 0.0]
    assert (report["zones"][1]["n_mites"], report["zones"][1]["n_left_out"]) == (1, 1)
    venom = report["groups"][1]
    assert venom["alive"] == [100.0, 50.0, 0.0]
    assert (venom["n_mites"], venom["n_left_out"]) == (2, 1)
    assert report["n_left_out"] == 1
    log_rank = SurvivalReport(RESULTS, controls=[3]).describe()["log_rank"]
    assert log_rank["rows"][0]["n_mites"] == 2  # venom


def test_each_mites_lifeline():
    mites = SurvivalReport(RESULTS).describe()["mites"]
    assert mites["0"] == {"in_study": False, "time": None, "dead": None, "lost": False}  # NEVER
    assert mites["1"] == {"in_study": True, "time": 10, "dead": True, "lost": False}  # FIRST_ONLY: dies at 10
    assert mites["2"] == {"in_study": True, "time": 20, "dead": False, "lost": False}  # ALWAYS: censored at the end
