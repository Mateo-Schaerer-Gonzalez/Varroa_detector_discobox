"""The movement score in use (config.yaml's metric, parameters and threshold),
the ones a calibration can choose from, and saving a new one.
"""

from classes.scoring.analyzer import Analyzer
from classes import app_config
from classes.app_config import get_default_config, save_motion_threshold


def movement_scores():
    """The metrics a calibration can score with -- for each its name, a one-line
    description, its default parameters, which of them are whole numbers and
    its parameters after config.yaml's -- and the metric, parameters and
    threshold in use."""
    mite = get_default_config().mite
    return {
        "metrics": [
            {
                "name": name,
                "description": Analyzer.metric_description(name),
                "defaults": Analyzer.metric_defaults(name),
                # JSON does not tell 0.0 from 0, and the page has to know which of the two to ask for
                "whole": [param for param, value in Analyzer.metric_defaults(name).items() if isinstance(value, int)],
                "params": Analyzer.check_metric_params(name, mite.params_for(name)),
            }
            for name in Analyzer.metric_names()
        ],
        "in_use": in_use(mite),
    }


def in_use(mite):
    return {
        "metric": mite.metric,
        "params": Analyzer.check_metric_params(mite.metric, mite.params_for(mite.metric)),
        "threshold": float(mite.motion_threshold),
        "stabilize_plate": bool(mite.stabilize_plate),
        "normalize_brightness": bool(mite.normalize_brightness),
        "normalize_floor": bool(mite.normalize_floor),
        # the band around the threshold whose calls are checked by eye: [low, high], or None
        "review_band": list(mite.review_band_for(mite.metric) or []) or None,
    }


def resolve_metric(metric, params):
    """The metric to score with and all its parameters: the one in config.yaml
    unless `metric` is given; its defaults, then config.yaml's values for it,
    then `params`."""
    mite = get_default_config().mite
    metric = metric or mite.metric
    if metric not in Analyzer.metric_names():
        raise ValueError(f"Unknown movement score {metric!r}; choose one of {', '.join(Analyzer.metric_names())}.")
    return metric, Analyzer.check_metric_params(metric, {**mite.params_for(metric), **(params or {})})


def save_threshold(value):
    """Make `value` the movement threshold for every analysis from now on."""
    return save_motion_threshold(value)


def save_movement_score(metric, params, threshold, stabilize=None, normalize_brightness=None, normalize_floor=None,
                        review_band=None):
    """Make `metric` with `params`, and `threshold` on its scale, the movement
    score of every analysis from now on; with `stabilize`, plate stabilization
    on or off too, and with `normalize_brightness` and `normalize_floor` the
    normalisations of a folder's scores (each left as it is when None). With
    `review_band` ([low, high], holding the threshold), the band whose calls are
    checked by eye is saved with them (classes/results/review_band.py); without it, the
    metric's band stays as it is, and is not used while the threshold is
    outside it."""
    metric, params = resolve_metric(metric, params)
    if not float(threshold) > 0:
        raise ValueError("The threshold must be positive.")
    return app_config.save_movement_score(metric, params, threshold, stabilize_plate=stabilize,
                                          normalize_brightness=normalize_brightness, normalize_floor=normalize_floor,
                                          review_band=review_band)
