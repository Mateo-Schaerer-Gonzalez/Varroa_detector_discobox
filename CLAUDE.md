# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Varroa mite motion detector for Agroscope's Discobox: finds mites on the plates in the first
frame, scores how much each one moves in every recording (a burst of frames), and reports
moving/still calls, survival and statistics per plate group. It runs from a folder of
recordings or live from the Discobox camera. `README.md` documents every user-visible
behaviour in detail; read the relevant section before changing a feature, and keep it in
step with the change.

## Commands

The app and tests run in the conda env `discobox_env` (`discobox_env.yaml`; Python 3.11+).

```
python -m uvicorn web.server:app --port 8000   # the web app (start.bat does the same on Windows; start.sh uses port 8010)
python main.py                                 # folder mode on sample_data -> results/sample_data/
python main.py <recordings dir> <out dir>
python main.py --live [--camera-id ID --run-name NAME --no-save-frames]

python -m pytest                               # whole suite (unit_tests/, pytest.ini sets pythonpath)
python -m pytest -m "not slow"                 # skip the runs over all of sample_data
python -m pytest unit_tests/zones_test.py::test_name
```

Test files are named `*_test.py` (plus `test_layering.py`). `unit_tests/conftest.py` points
`DISCOBOX_CONFIG` at a temporary copy of `config.default.yaml`, so tests never read or write
the machine's `config.yaml`.

**Reference snapshots.** `folder_regression_test.py`, `live_acceptance_test.py` and
`roi_conversion_test.py` compare against `unit_tests/reference/` to the last digit (results, every workbook sheet, figure
contents, pixels, CLI output). There is one reference per OpenCV major version
(`<name>.json` for OpenCV 4, `<name>.opencv5.json` for 5; see `reference._path()`). Regenerate
only for a deliberate change in output, with `DISCOBOX_CONFIG` set to a copy of
`config.default.yaml`: `python unit_tests/make_reference.py`, in an OpenCV 4 and an OpenCV 5
Python both, and record why in `make_reference.py`'s docstring. Don't open `sample_data` in the
app by typed path: saving labels writes `sample_data/labels.json`, which makes the slow
reference test skip.

## Architecture

**One-way layering, enforced by `unit_tests/test_layering.py`:** `web/` → `pipeline.py` →
`classes/`. `web/server.py` (FastAPI) may import only `pipeline` from the project, never
cv2/numpy/pandas/matplotlib/`classes`; `pipeline`/`classes` never import web libraries; the
static page may not reference any remote URL (the app works offline). Everything crossing
`pipeline`'s boundary is plain dicts/lists/strings/numbers, never a `Zone`, `Mite`,
`DataFrame` or image array. `pipeline.py`'s module docstring lists its public functions.

**Logic in Python, drawing in JS.** Any number a page shows (survival, tests, summaries)
is computed in a class under `classes/` and served through a `pipeline` function; the JS
only draws. The front end in `web/static/` has no framework and no build step: small files
under `web/static/js/<area>/`, one class each, loaded in order by `index.html`, wired up in
`js/main.js`.

**One analysis core for folder and live runs.** `classes/motion_analysis.py`
(`MotionAnalysis`) detects mites on the first frame, then scores each recording from all its
frames as it arrives, from a frame source it doesn't distinguish
(`classes/frame_source.py`, `classes/live/sources.py`): `FolderSource` (BMP folders),
`RoiSource` (a live run's saved per-mite FFV1 ROI videos, `classes/roi_recordings.py`) or
`CameraSource`. Analysing a saved live run must give exactly the scores the live run gave.
`classes/live/` holds the camera (vmbpy, Vimba X), fan/LEDs over serial (pyserial), the
schedule and the live session; those libraries are imported only for a live run.
`classes/discobox/camera_utils.py` is copied unchanged from the Discobox app.

**Scoring.** `classes/analyzer.py` holds the metrics; the only one in use is fixed in
`classes/app_config.py` (`METRIC = "outline_variability"`), which ignores a config file's own
`mite.metric` and forces `stabilize_plate` on. The stabilizer (`classes/plate_stabilizer.py`)
moves each mite's patch back by its own centre's shift within the recording; a mite whose
centre is lost takes the median of the others'. Since 2026-10-16; before, every mite took the
plate's median ECC shift, which `scripts/centre_stabilization.py` keeps for comparison
(`notebooks/centre_stabilization.ipynb`). Frames are greyscale everywhere: `Frame.image` is
(H, W) uint8 and metrics compute on grey; don't reintroduce 3-channel frames.

**Reads stay inside the saved ROI.** A saved live run keeps only `roi_recordings.ROI_MARGIN`
(32) px round each mite's box: the metric's pad (16) plus `plate_stabilizer.MARGIN` (16, the
source of `pipeline.STABILIZE_MARGIN`). A shift is followed at most `MARGIN` minus the
Lanczos reach (12 px) so a cut never reads further, and `RoiRecordings.check_margin` refuses a
pad that would. Anything new that reads round a mite must stay within that, or a saved run
stops scoring like the live one.

**Caches keyed on source code.** Calibration score caches (`pipeline._metric_version`) hash
the source of `Analyzer` and `plate_stabilizer`; kept analysis scores
(`results/<name>/kept/`, `classes/kept_scores.py` `_SCORING`) hash the scoring modules. Any
edit to those files, even a comment, makes every dataset score again from its frames. After
such an edit, verify scores are unchanged against the committed code (the slow regression
test covers sample_data only).

**Configuration.** `config.yaml` is per machine and not in git; it is created from
`config.default.yaml` (in git, the defaults for everyone), and the calibration and results
pages write thresholds and review bands into it. `DISCOBOX_CONFIG` overrides its path.
`DISCOBOX_AUTO_STOP=1` (set by the start scripts) stops the server once the last tab closes.

**Storage.** `recordings/<name>/` holds each session: frames (or `first_frame.png` +
`rois/`), `labels.json`/`controls.json` (`labels_2.json`/`controls_2.json` for two zones per
plate), `ground_truth.json`, `poke_test.json`, `corrections.json`, `.settings.txt`,
`run.json`, and a `scores/` cache. `results/<name>/` holds the latest analysis (workbook,
figures, `clips/`, `kept/`, `calibration/`). Labels, ground truth and corrections are keyed
by mite position, so they survive detector changes. On startup the server migrates older
layouts (`output/`, `outputs/`, `uploads/`, `calibration_data/`).

**Zones and IDs.** `coords_pixel.txt` (one zone per plate) and `coords_pixel_2.txt` (two)
list `type x1 y1 x2 y2` (type 1 plate, 0 masked label area); the choice is saved per
recording as `zones_per_plate` in `.settings.txt` (`classes/zone_layout.py`). Plates are
numbered 0-14 in reading order; mite `13.4` is the fourth mite of plate 13.

**Scripts and notebooks.** `scripts/` holds benchmarks and searches; they write to
`results/scripts/`. A notebook in `notebooks/` reads what its script wrote (the slow part), so
it reruns in seconds. They import `pipeline`/`classes` and may use their private helpers.

`pipeline.py` has a block marked `TEMPORARY` (the label-overlap check page,
`web/static/overlap.html`) that lists what to delete together with it.
