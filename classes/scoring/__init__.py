"""Scoring the mites: finding them on the first frame, the motion metrics, following
a shaking plate, and what else is measured while scoring.

    motion_analysis.py   the analysis core: detect, then score each recording as it comes
    analyzer.py          the detector and the motion metrics (outline_variability in use)
    plate_stabilizer.py  takes a shaking plate out of each mite's patch before scoring
    workers.py           work shared out over threads
    mite_look.py         how a mite looks in one recording, measured while it is scored
    unusual_activity.py  fly-offs, turns and other activity besides moving the legs
    follow_up.py         recordings a live run did not follow a mite in, for the results
    score_normalizer.py  the scores of a finished run put on one scale for every mite
    outline_view.py      what the score sees of a mite, for the result pages to draw
    benchmark.py         the Discobox's original software, to compare the scores with
    outline_change.py    how much a mite's outline changes between recordings
    recording_change.py  how much a mite's image changes between recordings
    leg_tracker.py       finds a mite's legs in each frame and follows them
"""
