"""A run's results as the result pages browse them, with the calls corrected
by hand, the calls to check by eye, and the settings saved with the recordings
that change the numbers shown (death time, mites to check).
"""

import reporting
from classes.app_config import get_default_config
from classes import settings_file
from classes.live.settings import RANGES as SETTING_RANGES
from classes.movement_stats import MovementReport
from classes.review_band import ReviewBand
from classes.survival import SurvivalReport
from pipeline import output_files, paths, plate_zones, preview_images, refusals, scoring


def review_calls(run, mite_data, changes, data_dir):
    """The calls to check by eye (ReviewBand.describe()): those of the narrowest
    band around the threshold, shaped as config.yaml's, that asks about the
    mites to check for the recordings in `data_dir` (review_mites()); None when
    it asks about none."""
    mite = get_default_config().mite
    band = ReviewBand.fitted(mite_data, run.analyzer.config.mite.motion_threshold, review_mites(data_dir),
                             mite.review_band_for(mite.metric))
    return band.describe(mite_data, changes) if band is not None else None


def change_call(zone_manager, corrections, mite_id, recording, state, detected=None, checked=False):
    """Make the mite `mite_id` `state` in `recording`, or step it to its next
    state without one (CallCorrections.change()). `detected` maps mite id to
    the detector's call per recording, where normalised scores make them other
    than the mite's own. With `checked` the call is kept as checked by eye."""
    mite = next((m for m in zone_manager.mites if m.text == str(mite_id)), None)
    if mite is None:
        raise ValueError(f"No mite {mite_id} in these results.")
    calls = mite.moving if detected is None else detected[mite.text]
    refusals.check_recording(recording, len(calls), "these results")
    corrections.change(*mite.home, recording, bool(calls[recording]), state,
                       checked=checked)


REVIEW_MITES = "review_mites"  # the line of a run's .settings.txt with its own number of mites to check


def review_mites(data_dir=None):
    """How many mites the result pages ask to check by eye for the recordings in
    `data_dir`: their own number, saved with them, or config.yaml's
    (mite.review_mites) without one or without `data_dir`."""
    default = max(0, int(get_default_config().mite.review_mites))
    return default if data_dir is None else settings_file.whole_number(data_dir, REVIEW_MITES, default)


def save_review_mites(data_dir, mites):
    """Make `mites` the number of mites to check by eye for the recordings in
    `data_dir`: the review_mites line of their .settings.txt. With None the
    line goes, and config.yaml's number holds again. Returns the number now."""
    if mites is None:
        settings_file.remove(data_dir, REVIEW_MITES)
        return review_mites(data_dir)
    value = refusals.whole_number(mites, "The mites to check must be a whole number", 0)
    settings_file.save(data_dir, REVIEW_MITES, value)
    return value


def death_minutes(data_dir):
    """How long a mite must be still to count as dead, from the test-run settings
    saved with the recordings; 0 (dead from its last movement on) without them.
    The pages take it with the results, for the mites alive over time."""
    return settings_file.whole_number(data_dir, "death_minutes", 0)


def death_minutes_range():
    """The least and the most a mite can be still to count as dead, in minutes."""
    _label, _unit, lowest, highest = SETTING_RANGES["death_minutes"]
    return [lowest, highest]


def save_death_minutes(data_dir, minutes):
    """Make `minutes` the time a mite must be still to count as dead for the
    recordings in `data_dir`: the death_minutes line of their .settings.txt,
    added or replaced, every other line kept as it is."""
    label, unit, lowest, highest = SETTING_RANGES["death_minutes"]
    value = refusals.whole_number(minutes, f"{label} must be a whole number of {unit}", lowest, highest)
    settings_file.save(data_dir, "death_minutes", value)
    return value


def describe_results(run, out_dir, labels, write_files=True, corrections=None, normalizer=None):
    """The results of a run as the UI browses them. With `write_files`, the
    workbook, the figures, the annotated first frame and the preview are written
    to `out_dir` too. A live run describes its results this same way after every
    recording, so its pages are drawn from exactly what a folder run returns. The calls
    corrected by hand (`corrections`, a CallCorrections) replace the detector's,
    and the mites marked gone are censored; with any, the results say which
    ("corrections", "censored", "gone_from", see CallCorrections.apply()). With
    a `normalizer` (a ScoreNormalizer) the results say which normalisations the
    scores went through ("normalization"): config.yaml's for a folder, none for
    a live run. With mites to check by eye, they hold the calls to check
    ("review", see review_calls()): by the number saved with the recordings, which
    are where the corrections are kept."""
    burst_minutes = run.burst_minutes
    mite_data, changes = scoring.mite_table(run, corrections, normalizer)

    if write_files:
        preview_images.write_preview(run.first_frame, out_dir)
        results = output_files.write_files(output_files.annotated(run), out_dir, mite_data)
    else:
        results = reporting.describe_outputs(mite_data)

    results.update(
        {
            "n_recordings": run.n_recordings,
            "times": [round(float(minute), 2) for minute in burst_minutes],
            "threshold": float(run.analyzer.config.mite.motion_threshold),
            "preview": paths.PREVIEW_NAME,
            "image": preview_images.image_size(run.first_frame),
            # "rois": only the mites' surroundings were saved, so the only clips are the mites'
            "frames": run.frames,
            "zones": reporting.describe_zones(mite_data, plate_zones.describe_zones(run.zone_manager, labels),
                                              burst_minutes),
            "mites": reporting.describe_mites(mite_data),
            "groups": reporting.describe_groups(mite_data, burst_minutes),
        }
    )
    results.update(changes)
    if run.frames == "rois" and getattr(run, "data_dir", None) is not None:
        # The plate as it was in each recording, so a mite added during the run is
        # drawn where it can be seen: only a live run that added mites has them.
        previews = preview_images.added_previews(run.data_dir, out_dir, run.n_recordings, again=False)
        if any(name != paths.PREVIEW_NAME for name in previews):
            results["previews"] = previews
    if getattr(run, "activity", None) is not None:
        results["activity"] = run.activity.describe()
    if normalizer is not None:
        results["normalization"] = normalizer.describe()
    review = review_calls(run, mite_data, changes, corrections.path.parent if corrections is not None else None)
    if review is not None:
        results["review"] = review
    return results


def describe_movement(results):
    """`results` (as run_analysis() returns them) with the numbers the result
    pages show about how the mites move: per mite, per zone (their rests between
    movements too), and the groups in the order the pages list them, each with
    the box of its moving mites' scores (see classes/movement_stats.py)."""
    return {**results, **MovementReport(results).describe()}


def describe_survival(results, death_minutes=0, controls=()):
    """The survival numbers of `results` (as run_analysis() returns them) for the
    result pages, with `death_minutes` the time a mite must be still to count as
    dead and `controls` the zones ticked as negative controls: the mites alive
    over time per group and per zone, and every group, its zones pooled, against
    the controls by the log-rank test (see classes/survival.py). They change with
    those two, with no need to run the analysis again."""
    return SurvivalReport(results, death_minutes, controls).describe()
