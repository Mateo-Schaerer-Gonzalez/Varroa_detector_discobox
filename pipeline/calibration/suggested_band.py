"""The band around a suggested threshold whose calls are checked by eye: the
one a calibration report suggests (death_calibration.best_band(), the labels
standing in for the eye), and its shape kept in config.yaml for the result pages
(classes/results/review_band.py), which widen or narrow it to the mites to check.
"""

from classes import app_config
from classes.ground_truth import death_calibration


# Checks by eye per mite the band suggested with a threshold may ask for, unless the report is asked for another number.
REVIEW_CHECKS = 0.5
# Edges tried on each side of the threshold for that band.
REVIEW_BAND_STEPS = 24


def checks_allowed(checks_per_mite):
    """The checks by eye per mite the suggested band may ask for: REVIEW_CHECKS
    unless given, from 0 to 100."""
    checks_per_mite = REVIEW_CHECKS if checks_per_mite is None else float(checks_per_mite)
    if not 0 <= checks_per_mite <= 100:
        raise ValueError("The checks allowed per mite must be between 0 and 100.")
    return checks_per_mite


def for_threshold(runs, threshold, checks_per_mite):
    """The band to check by eye that goes with a suggested threshold, for a
    calibration report: the one with the smallest death error among those asking
    for at most `checks_per_mite` checks per mite, the labels standing in for
    the eye (death_calibration.best_band()), with what it leaves:

        {checks_allowed, low, high, mae, checks_per_mite, exact,
         frontier: what the checks buy (death_calibration.checks_frontier()), up
                   to four times the checks allowed}

    low == high when no band does better than the threshold alone."""
    threshold = round(threshold, 3)
    grid = death_calibration.band_grid(runs, threshold, REVIEW_BAND_STEPS)
    low, high = death_calibration.best_band(runs, threshold, checks_per_mite, grid=grid)
    low, high = min(round(low, 3), threshold), max(round(high, 3), threshold)
    shown = max(4 * checks_per_mite, 2.0)

    def rounded(band):
        return {"low": round(band["low"], 3), "high": round(band["high"], 3), "mae": round(band["mae"], 3),
                "checks_per_mite": round(band["checks_per_mite"], 3), "exact": round(band["exact"], 4)}

    return {"checks_allowed": checks_per_mite,
            **rounded({"low": low, "high": high, **death_calibration.band_outcome(runs, low, high)}),
            "frontier": [rounded(band) for band in death_calibration.checks_frontier(grid)
                         if band["checks_per_mite"] <= shown]}


def keep_shape(band, suggested, threshold):
    """Keep the shape of the band a calibration report suggests (around the
    `suggested` threshold) in config.yaml, moved to hold the `threshold` in use:
    the result pages widen or narrow it to the mites to check
    (classes/results/review_band.py), so only how far it reaches below the threshold
    against above counts. Nothing when the report suggests no band. Returns
    [low, high] as saved, or None."""
    if not band["high"] > band["low"]:
        return None
    try:
        return app_config.save_review_band(threshold - (suggested - band["low"]), threshold + (band["high"] - suggested))
    except ValueError:  # too narrow to tell apart from the threshold, once rounded
        return None
