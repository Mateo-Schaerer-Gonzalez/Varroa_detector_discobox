"""The peaks of a mite's score below the threshold after its last movement are
asked to be checked by eye, beside the band's close calls."""

from classes.results.review_band import ReviewBand
from classes.results.score_peaks import ScorePeaks

from review_band_test import THRESHOLD, calls, mite_data

PEAKS = ScorePeaks(THRESHOLD)
# a mite still from recording 2 on, its score round 1.0
STILL = [9.0, 9.0, 1.0, 1.1, 0.9, 1.0, 1.05, 0.95, 1.0, 1.1, 0.9, 1.0]


def with_peak(at, value, scores=STILL):
    scores = list(scores)
    scores[at] = value
    return scores


def test_a_peak_standing_out_of_the_still_level_is_to_check():
    scores = with_peak(8, 2.5)
    assert PEAKS.to_check(scores, calls(scores)) == [8]
    scores = with_peak(4, 2.0, scores)
    assert PEAKS.to_check(scores, calls(scores)) == [8, 4]  # the latest first


def test_noise_of_the_still_level_is_no_peak():
    assert PEAKS.to_check(STILL, calls(STILL)) == []
    # a peak higher than the rest but below half the threshold is not asked for
    scores = with_peak(8, 1.7)
    assert PEAKS.to_check(scores, calls(scores)) == []


def test_only_peaks_after_the_last_movement_are_to_check():
    scores = with_peak(6, 9.0, with_peak(4, 2.5))
    assert PEAKS.to_check(scores, calls(scores)) == []
    scores = with_peak(9, 2.5, scores)
    assert PEAKS.to_check(scores, calls(scores)) == [9]


def test_a_peak_answered_is_asked_for_no_more():
    scores = with_peak(9, 2.5, with_peak(5, 2.5))
    moving = calls(scores)
    assert PEAKS.to_check(scores, moving) == [9, 5]
    checked = [False] * len(scores)
    checked[9] = True
    assert PEAKS.to_check(scores, moving, checked=checked) == [5]  # answered still
    moving[9] = True
    assert PEAKS.to_check(scores, moving, checked=checked) == []  # answered moving: the earlier one matters no more


def test_a_gone_recording_is_not_asked_for():
    scores = with_peak(8, 2.5)
    censored = [False] * len(scores)
    censored[8] = True
    assert PEAKS.to_check(scores, calls(scores), censored=censored) == []


def test_a_mite_still_from_the_start_has_its_peaks_asked_for_too():
    scores = with_peak(6, 2.5, [1.0, 1.1, 0.9, 1.0, 1.05, 0.95, 1.0, 1.1, 0.9])
    assert PEAKS.to_check(scores, calls(scores)) == [6]


def test_the_pages_are_told_the_peaks_beside_the_band():
    data = mite_data({"0": with_peak(8, 2.0), "1": with_peak(8, 3.0)})
    # mite 1's peak is in the band and a peak; mite 0's below the band, a peak only
    review = ReviewBand(2.5, 4.5).describe(data, peaks=PEAKS)
    assert review["to_check"] == {"0": [8], "1": [8]} and review["peaks"] == {"0": [8], "1": [8]}
    assert ReviewBand(2.5, 4.5).describe(data)["to_check"] == {"1": [8]}
    # a band from the threshold to itself asks for the peaks only
    review = ReviewBand(THRESHOLD, THRESHOLD).describe(data, peaks=PEAKS)
    assert review["to_check"] == {"0": [8], "1": [8]} and (review["n_asked"], review["n_done"]) == (2, 0)
    answered = ReviewBand(THRESHOLD, THRESHOLD).describe(data, {"checked": {"0": [8]}}, peaks=PEAKS)
    assert answered["to_check"] == {"1": [8]} and (answered["n_asked"], answered["n_done"]) == (2, 1)
