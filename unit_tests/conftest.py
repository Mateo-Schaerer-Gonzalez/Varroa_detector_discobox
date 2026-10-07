import pytest

import pipeline


@pytest.fixture(autouse=True)
def no_review_band(monkeypatch):
    """Every run in a test is without a band to check by eye, whatever this
    machine's config.yaml holds: the band adds the calls to check to the
    results, which the references were made without. A test of the band gives
    its own (see review_band_test.py)."""
    monkeypatch.setattr(pipeline, "_review_band", lambda metric: None)
