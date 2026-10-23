"""The outline change between recordings: what a mite pushed or turned leaves
alone, what a moved leg changes, and the calls and the figure made of it."""

import numpy as np
import pytest

from classes.scoring.leg_tracker import synthetic_mite
from classes.scoring.outline_change import LIMIT, OutlineChange, outline, outline_change

LEGS = [(-150, 3), (-120, 3.5), (-60, 3.5), (-30, 3), (150, 2), (30, 2)]
MOVED_LEG = [(-150, 3), (-100, 3.5), (-60, 3.5), (-30, 3), (150, 2), (30, 2)]


def recording(legs, seed, neighbour=False, frames=10):
    """One recording of a mite drawn with `legs`, (frames, 46, 46); with
    `neighbour`, another mite at the patch's right edge, darker wins."""
    rng = np.random.default_rng(seed)
    out = []
    for _frame in range(frames):
        frame, _tips = synthetic_mite(legs, rng=rng)
        if neighbour:
            other, _tips = synthetic_mite([(0, 3)], shift=(19.0, 2.0), turn=70.0, noise=0, rng=rng)
            frame = np.minimum(frame, other)
        out.append(frame)
    return np.array(out)


def change(earlier, later):
    return outline_change(OutlineChange.outline_of(earlier), OutlineChange.outline_of(later))


def shifted(frames, dx, dy):
    """Moved by whole pixels, the plate that comes in at an edge its mirror."""
    return np.pad(frames, ((0, 0), (abs(dy),) * 2, (abs(dx),) * 2), mode="reflect")[
        :, abs(dy) - dy:abs(dy) - dy + frames.shape[1], abs(dx) - dx:abs(dx) - dx + frames.shape[2]]


def test_a_mite_that_did_nothing_does_not_change():
    assert change(recording(LEGS, 1), recording(LEGS, 2)) < LIMIT


@pytest.mark.parametrize("dx, dy, quarters", [(4, 0, 0), (-3, 5, 0), (0, 0, 1), (0, 0, 2), (5, -2, 3)])
def test_pushing_or_turning_a_mite_changes_nothing(dx, dy, quarters):
    earlier, later = recording(LEGS, 1), recording(LEGS, 2)
    moved = shifted(np.rot90(later, quarters, axes=(1, 2)), dx, dy)
    assert change(earlier, moved) == pytest.approx(change(earlier, later), abs=0.01)
    assert change(earlier, moved) < LIMIT


def test_a_moved_leg_changes_the_outline():
    earlier = recording(LEGS, 1)
    assert change(earlier, recording(MOVED_LEG, 2)) > 5 * LIMIT
    # and a turn on top changes nothing to that
    assert change(earlier, np.rot90(recording(MOVED_LEG, 2), 1, axes=(1, 2))) > 5 * LIMIT


def test_a_neighbour_at_the_edge_of_the_patch_is_not_the_mite():
    alone, beside = recording(LEGS, 1), recording(LEGS, 2, neighbour=True)
    assert change(alone, beside) < LIMIT


def test_an_empty_patch_has_a_flat_outline():
    assert not outline(np.full((46, 46), 110.0)).any()


def test_a_mite_moved_where_two_changes_in_a_row_count():
    judge = OutlineChange(limit=1.0)
    changes = [None, 2.0, 0.5, 2.0, 2.0, 2.0, 0.5]
    assert judge.calls(changes) == [False, False, False, False, True, True, False]
    assert judge.calls([]) == []


def test_the_changes_of_a_mite_start_with_none():
    outlines = [OutlineChange.outline_of(recording(legs, seed)) for seed, legs in enumerate([LEGS, LEGS, MOVED_LEG])]
    changes = OutlineChange.changes(outlines)
    assert changes[0] is None and changes[1] < LIMIT < changes[2]


def test_the_figure_has_the_mites_seen_moving_in_the_order_they_die():
    def mite(mite_id, moving, calls):
        return {"dataset": "a", "dataset_name": "a", "mite_id": mite_id, "zone_id": 0, "moving": moving,
                "changes": [None, 0.1, 0.1], "calls": calls}

    figure = OutlineChange().raster([
        mite("late", [True, True, None], [False, True, True]),
        mite("early", [True, False, False], [False, False, False]),
        mite("never", [False, False, False], [False, True, False]),
    ])
    assert figure["limit"] == LIMIT and figure["scale"] == [LIMIT / 2, LIMIT * 8]
    assert [(row["mite_id"], row["death"], row["outline_death"]) for row in figure["mites"]] == [
        ("early", 1, None), ("late", 2, 3)]
    assert set(figure["mites"][0]) == {"dataset", "dataset_name", "mite_id", "zone_id", "changes", "death", "outline_death"}
