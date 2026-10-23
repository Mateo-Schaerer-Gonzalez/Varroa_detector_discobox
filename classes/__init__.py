"""The analysis itself, one class or a few functions per module, grouped by what
they work on. pipeline/ turns them into what the pages need; nothing here knows
about the web.

    scoring/        finding the mites and scoring their motion (motion_analysis.py is the core)
    plate/          the plate, its zones, the mites in them and their ids
    storage/        recordings (whole frames or the mites' ROIs) and the app's own files
    results/        a run's results: workbook and figures, survival, corrections, calls to check
    ground_truth/   what the user saw: calibration against it, the poke test
    live/           the Discobox camera, fan and LEDs, and a live test run
    discobox/       code copied unchanged from the Discobox app
    app_config.py   config.yaml and config.default.yaml
"""
