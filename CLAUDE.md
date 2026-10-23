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

Run tests in `discobox_env` only (the user's rule; no second run in another Python). Test
files are named `*_test.py` (plus `test_layering.py`). `unit_tests/conftest.py` points
`DISCOBOX_CONFIG` at a temporary copy of `config.default.yaml`, so tests never read or write
the machine's `config.yaml`. The outdated tests were removed at the user's request; the
reference tests below are the regression guard and stay.

**Reference snapshots.** `folder_regression_test.py`, `live_acceptance_test.py` and
`roi_conversion_test.py` compare against `unit_tests/reference/` to the last digit (results, every workbook sheet, figure
contents, pixels, CLI output). There is one reference per OpenCV major version
(`<name>.json` for OpenCV 4, `<name>.opencv5.json` for 5; see `reference._path()`). Regenerate
only for a deliberate change in output, with `DISCOBOX_CONFIG` set to a copy of
`config.default.yaml` (run plainly it reads the machine's `config.yaml`, another threshold):
`python unit_tests/make_reference.py`, in an OpenCV 4 and an OpenCV 5 Python both, and
record why in `make_reference.py`'s docstring. Don't open `sample_data` in the app by typed
path: saving labels writes `sample_data/labels.json`, which makes the slow reference test
skip.

## Architecture

**One-way layering, enforced by `unit_tests/test_layering.py`:** `web/` → `pipeline/` →
`classes/`. `web/` (FastAPI) may import only `pipeline` from the project, never
cv2/numpy/pandas/matplotlib/`classes`; `pipeline`/`classes` never import web libraries; the
static page may not reference any remote URL (the app works offline). Everything crossing
`pipeline`'s boundary is plain dicts/lists/strings/numbers, never a `Zone`, `Mite`,
`DataFrame` or image array.

**The `pipeline/` package** (split from one 3,900-line `pipeline.py` on 2026-10-22, the
user's choice: "easily understandable, quickly find what is implemented where, avoid super
massive files"). `pipeline/__init__.py` re-exports the API the server, `main.py` and the
tests call, and its docstring lists every module with one line on what it holds; each
module's docstring says more. Inside the package a module uses another as `module.name`
(`from pipeline import paths` then `paths.PREVIEW_NAME`), never `from pipeline.x import f`:
every call shows where it is defined, and a test patches the defining module
(`monkeypatch.setattr(score_cache, "score_mites", ...)`) for every caller at once. A
helper used by another module has no leading underscore; one used only in its own module
keeps it. Imports inside the package point one way with no circle (enforced by
`test_layering.py`); `paths.py` is at the bottom. Keep modules small (about 300 lines at
most) and add a module rather than grow one. Module state (the last runs, the truth drafts,
the open live runs) sits at the top of its module, each in one module only.

**`classes/`** is grouped by what it works on (2026-10-22, the user's choice, accepting one
re-score of every kept score and dataset cache): `scoring/` (detection, metrics, stabilizer,
`motion_analysis.py`), `plate/` (zones, mites, ids, label reader), `storage/` (frame sources,
ROI recordings, the app's files), `results/` (`reporting.py`, moved from the root; survival,
corrections, review band), `ground_truth/` (`calibration.py`, death calibration, truth draft,
poke test), `live/`, `discobox/`; `app_config.py` stays at the top. Each package's
`__init__.py` lists its modules with a line each; put a new module in the package it works on.
Moving them changed only import lines: every raw score and brightness came out identical as
`float.hex()` on sample_data and the long run (35,400 values).

**The server** (`web/`, split 2026-10-22): `server.py` puts the app together (still
`uvicorn web.server:app`) and lists the modules; `routes/` holds one FastAPI router per part
of the page (recordings, analysis, playback, calibration, live), each with its request
models; `page_sessions.py` the pages' sessions and what several routes ask of them;
`page_watch.py` the auto-stop; `http_helpers.py` the shared replies. FastAPI 0.143 matches
an included router as a unit: a new route whose path another router's could also match must
go in the same router, in order.

**Logic in Python, drawing in JS.** Any number a page shows (survival, tests, summaries)
is computed in a class under `classes/` and served through a `pipeline` function; the JS
only draws (the user's choice: "make all classes python", logic in Python rather than a
Python UI framework). Math only for drawing (chart scales, jitter, kernel density) may stay
in JS. The front end in `web/static/` has no framework and no build step: small files under
`web/static/js/<area>/`, one class each, loaded in order by `index.html`,
wired up in `js/main.js`. The styles are in `web/static/css/`, one file per part of the page (cut from
one `style.css` on 2026-10-22), linked by `index.html` in an order the cascade depends on
(`narrow-screens.css` overrides those before it).

**One analysis core for folder and live runs.** `classes/scoring/motion_analysis.py`
(`MotionAnalysis`) detects mites on the first frame, then scores each recording from all its
frames as it arrives, from a frame source it doesn't distinguish
(`classes/storage/frame_source.py`, `classes/live/sources.py`): `FolderSource` (BMP folders),
`RoiSource` (a live run's saved per-mite FFV1 ROI videos, `classes/storage/roi_recordings.py`) or
`CameraSource`. Analysing a saved live run must give exactly the scores the live run gave.
A live run also follows its mites (each recording's first frame moves each box to its blob,
`Settings.follow_px`), takes mites added mid-run (`add_mites`) and stops following mites
counted dead (`stop`); the ROI index records each recording's boxes so a replay follows them
the same way. A `Mite`'s own box stays where it was found (its key); recordings it was not
followed in hold None (`classes/scoring/follow_up.py` turns them into censored/still rows).

The user's choices for live runs (2026-10-20), not to be undone:
- **Following** is live only (folder mode keeps fixed boxes, so references don't change):
  each mite moves to the nearest blob in its zone within `follow_px` (default 50), stays put
  with none or under 2 px. **Clips follow the mite** (the user's choice of 2026-10-22,
  replacing "clips stay at the first position", which showed the ring off the mite and black
  where its moved ROI no longer reached): a mite's clip, variation picture, outline and
  playback square are cut round where it was in that recording (`pipeline.clips.where_in()`,
  `RoiRecordings.centre_in()`/`roi_in()`), and the clip says where (`"mite": {x, y}`) so the
  pages put the ring there. Everything else (ids, labels, plate map) stays at the first position.
- **Added mites** (live panel button: LEDs on between recordings, run held, detect, untick,
  confirm) are followed from the next recording, numbered after the zone's mites in reading
  order. Each mite and zone runs on its own clock from when it was added (not
  left-truncation); a zone all of whose mites were added later is on its own clock too.
- **Dead mites** (by the death rule, never-moved ones too) are no longer scored or saved;
  a correction can't revive them. Live runs require `death_minutes` > 0.
- **Zone circles** replace the run bar. A zone is done when all mites seen moving are dead
  or gone (zones with no mite seen moving don't count); the run stops when every counting
  zone is done, so the duration is a maximum. There is no `death_reset` and no progress bar.
- **Recordings are fixed at 3 s / 30 fps** (90 frames; `classes/live/settings.py` `FPS`,
  `FRAME_COUNT`, `FIXED`), not settings: `scripts/recording_length.py` showed length matters
  far more than frame rate, and a threshold only fits the length it was calibrated on.
  Don't reintroduce fps or frame_count as settings.
`classes/live/` holds the camera (vmbpy, Vimba X), fan/LEDs over serial (pyserial), the
schedule and the live session; those libraries are imported only for a live run.
`classes/discobox/camera_utils.py` is copied unchanged from the Discobox app.

**Scoring.** `classes/scoring/analyzer.py` holds the metrics; the only one in use is fixed in
`classes/app_config.py` (`METRIC = "outline_variability"`, the user's choice: no metric
picker), which ignores a config file's own `mite.metric`, takes the threshold and parameters
from `config.default.yaml` where `config.yaml` has none, and forces `stabilize_plate` on.
`outline_variability` scores the vector sum round the mite of the variance on its outline
(the one-sided part, grey levels squared); its `relative` (default 0, the user's choice)
divides by the mean variance to that power. The thresholds in config (1.638 default) were
calibrated on 10-frame, 10-fps recordings and don't fit 3 s / 30 fps ones: the next
ground-truth run at 3 s / 30 fps sets the threshold.

The stabilizer (`classes/scoring/plate_stabilizer.py`) moves each mite's patch back by its own
centre's shift within the recording, capped at `MARGIN` minus the Lanczos reach (12 px); a
mite whose centre is lost takes the median of the others'. That is the user's choice of
2026-10-16. Before, every mite took the plate's median ECC shift, which
`scripts/centre_stabilization.py` keeps as `ecc_shifts()` (`notebooks/centre_stabilization.ipynb`):
the centre made the same calls on rigid shake, far fewer still-called-moving when plates
shake apart, and is 19x cheaper. An earlier per-mite version was reverted on 2026-10-14
when the user saw results "regressed a lot"; that code is on branch
`backup/before-revert-2026-10-14`. If results look worse again, compare against
`ecc_shifts()` before blaming the centre. `PlateStabilizer._shift` (phase correlation +
ECC) stays for `mite_look` and `recording_change`.

Frames are greyscale everywhere: `Frame.image` is (H, W) uint8 and metrics compute on grey
(`Analyzer.grey()`); the user rejected keeping 3-channel scoring for bit-identical scores
("change computation to work with greyscale"). It changed 0 of 17,700 calls on the long run
and scores 30% faster. Don't reintroduce 3-channel frames; new code taking frames must
accept (H, W). `cv2.setNumThreads(1)` (`classes/scoring/workers.py`) is set because the work is
parallel already. The frame-rate and memory limits are measured by
`scripts/frame_rate_limits.py` (`notebooks/frame_rate_limits.ipynb`).

**Reads stay inside the saved ROI.** A saved live run keeps only `roi_recordings.ROI_MARGIN`
(32) px round each mite's box: the metric's pad (16) plus `plate_stabilizer.MARGIN` (16, the
source of `pipeline.scoring.STABILIZE_MARGIN`). A shift is followed at most `MARGIN` minus the
Lanczos reach (12 px) so a cut never reads further, and `RoiRecordings.check_margin` refuses a
pad that would. Anything new that reads round a mite must stay within that, or a saved run
stops scoring like the live one.

**Caches keyed on source code.** Calibration score caches (`pipeline/calibration/score_cache.py`, `_metric_version`) hash
the source of `Analyzer` and `plate_stabilizer`; kept analysis scores
(`results/<name>/kept/`, `classes/storage/kept_scores.py` `_SCORING`) hash the scoring modules. Any
edit to those files, even a comment, makes every dataset score again from its frames. Tell
the user before editing them (the next calibration report re-scores every dataset, slower on
the Discobox). After such an edit, prove scores are unchanged against the committed code:
analyse with both and compare every mite's raw `motion_scores` and `brightness` as
`float.hex()`, on sample_data and on the long run (the slow regression test covers
sample_data only). The cache file names in a dataset's `scores/` are made by the `_*_name`
functions and `_metric_version`; old caches are found again only while they stay the same. Scores
of one dataset differ slightly between this Windows laptop and the Discobox's Linux PC with
the same code (2026-10-08: 56% of values, 0.009 median, 0.23 at most; likely the OpenCV
build).

**Configuration.** `config.yaml` is per machine and not in git; it is created from
`config.default.yaml` (in git, the defaults for everyone), and the calibration and results
pages write thresholds and review bands into it. `DISCOBOX_CONFIG` overrides its path.
`DISCOBOX_AUTO_STOP=1` (set by the start scripts) stops the server once the last tab closes.

**Storage.** `recordings/<name>/` holds each session: frames (or `first_frame.png` +
`rois/`), `labels.json`/`controls.json` (`labels_2.json`/`controls_2.json` for two zones per
plate), `ground_truth.json`, `poke_test.json`, `corrections.json`, `.settings.txt`,
`run.json`, and a `scores/` cache. `results/<name>/` holds the latest analysis (workbook,
figures, `clips/`, `kept/`, `calibration/`). Labels, ground truth and corrections are keyed
by mite position, so they survive detector changes. On startup the server removes pooled
report folders that made no report. The one-off migrations of older layouts (`output/`,
`outputs/`, `uploads/`, `calibration_data/`, BMP folders shrunk to ROIs in bulk) were
deleted on 2026-10-22 at the user's request; uploads and typed-path calibrations are still
shrunk to ROIs.

There is one store, the user's choice of 2026-10-16 ("everything stored in recordings, get
rid of the calibration folder"); never reintroduce a second one. A dataset is a folder in
`recordings/` with moving or still labels in its `ground_truth.json`; its id is the folder
name, and everything a report needs is worked out from the folder (`pipeline.calibration.dataset_library.read_dataset`).
Calibration sessions and reports go to `results/<run>/calibration/`, pooled reports to
`results/pooled/<date time>/`, script outputs to `results/scripts/`, old reports to
`results/earlier calibration reports/`. A folder opened by typed path is copied into
`recordings/` (with `copied_from.txt`) and shrunk to ROIs; Delete removes a run's ground
truth, poke test and scores. Tests make datasets in `tmp_path/recordings` (see
`calibration_library_test.py`).

Saved runs keep only the mites' surroundings (the user's choices of 2026-10-15, for storage:
sample_data takes 17.5 MB as ROIs against 574 MB as BMP): `first_frame.png`,
`rois/index.json` (with the plate-wide blobs as JSON) and one lossless FFV1
`rois/mite_NNN.mkv` per mite (lossless so scores stay identical); bursts go to
`rois/parts/<recording>/` and are stitched on at the end. The ROI is the box ± 32 px, at
least ± 40 round the centre, with even sizes (the FFV1 writer crops odd ones). Old BMP
folders stay readable; dropped/uploaded BMP folders are converted on upload
(`classes/storage/roi_conversion.py`); folders opened by typed path are only converted when
calibrated. Zone, plate and fly-off clips don't exist for ROI sessions; mite clips and the
still frame do. Results say `frames: "rois" | "whole" | "none"`. The sibling worktree
`Varroa_detector_discobox_video` (branch `video-storage`) is an older, different attempt.

**Zones and IDs.** `coords_pixel.txt` (one zone per plate) and `coords_pixel_2.txt` (two)
list `type x1 y1 x2 y2` (type 1 plate, 0 masked label area); the choice is saved per
recording as `zones_per_plate` in `.settings.txt` (`classes/plate/zone_layout.py`). Plates are
numbered 0-14 in reading order; mite `13.4` is the fourth mite of plate 13. Ids come only
from `zones.mite_ids()` (first-frame mites and mites added mid-run alike), the zone of a box
only from `ZoneManager.zone_of()`.

**One place for each job.** Use these instead of writing another copy:
`classes/storage/files.py` (JSON read/write, write-then-rename, images, `remove_tree`),
`classes/storage/settings_file.py` (`.settings.txt`), `classes/plate/positions.py` (matching saved
entries to mites within 10 px), `survival.own_time`/`since_start`/`death_after` (a mite's
own clock and the death rule), `Mite.home` (a mite's centre), `ZoneManager.mites`. In
`pipeline/`: `clips.kept_clip` (anything cut from frames into `clips/`),
`score_cache._cached_by_mite` and the `_*_name` functions (a dataset's `scores/`),
`ground_truth.mite_states` (a dataset's mites not marked "not a mite"),
`plate_zones.mite_view`, `plate_zones.zones_of` (a folder's ZoneManager), `paths` (every
folder and file name), `refusals` (`find`/`check_recording`/`recordings_dir`/
`whole_number`). In `web/`: `http_helpers.refused()`/`answer()` turn refusals into HTTP
errors. In the page: `Hint` (status lines), `ChartKit.show`, `Charts.PERCENT_AXIS`,
`ResultsPage.clockOf()`, `PlateView.clipPicture()`. Scripts: `scripts/script_data.py`.

**Scripts and notebooks.** `scripts/` holds benchmarks and searches; they write to
`results/scripts/`. A notebook in `notebooks/` reads what its script wrote (the slow part), so
it reruns in seconds. They import `pipeline`/`classes` and may use a module's helpers (`from pipeline.calibration
import dataset_library`).

The temporary label-overlap check page was deleted on 2026-10-22 at the user's request.

## The data

- **The long run** is `recordings/test_run_2026-09-08_Mathis_last_dsRNA` (295 recordings of
  10 frames, 59 mites, 49 h). Its saved labels (re-saved 2026-10-09) agree with
  `outline_variability >= 0.31` in all but 2 of 17,314 recordings, so any moving-against-still
  AUC or death error there is perfect for the score in use by construction. Judge a new
  measure on what it sees in recordings the score calls still, or against the label-free
  `adf.last_change`, not by agreement with these labels. It is unknown whether the user
  meant the labels to be the detector's calls. `adf.features()`'s cached `movement_score` is
  of the metric in use when that cache was made.
- **There is no real poke test data.** `recordings/ground_truth_60min/poke_test.json` is a
  made-up test entry (the user called it "bs"). Check poke-report changes with unit tests,
  and ask the user for a real poke dataset before drawing conclusions from poke curves.
- The scripts' cut patches of the long run are cached in `%TEMP%\varroa_death_time_patches`
  (4.4 GB), so the `alive_dead_*` notebooks run in seconds.

## The Discobox PC

The camera is on the Discobox PC (Linux), not on the Windows dev laptop. There, Vimba X and
the original Discobox app are installed as the Discobox readme describes and find the
camera: the user's installation is known to be good. Look for differences in how this code
runs, not for install problems, and don't install anything on the Windows laptop. When live
input fails, ask for the red/grey status text under Connect. `discobox_env` runs Python 3.14;
the Discobox app's venv uses the older system Python. Known fixes in `classes/live/camera.py`:
vmbpy 1.1.x on Python 3.14 needs `resolve_type_hint_names()` (vmbpy 1.2.2 doesn't), and GigE
discovery waits up to 3 s because the first listing in a process is empty.

Updates: `start.sh` runs `git pull --ff-only` before starting (local changes, e.g. a
`config.yaml` saved by the calibration page, are stashed first), runs `conda env update`
when `discobox_env.yaml` changed, logs to `update.log` (its tail shows in the popup), and
always restarts the server (except during a live run) on port **8010**, so the Discobox URL
is http://127.0.0.1:8010. Changes reach it only once pushed to origin/main. If it looks
stale, open `/api/version` (folder, commit, live run) and ask for `update.log`. The clone in
use is `~/Varroa_detector_discobox`; a recloned folder needs `install_linux.sh` rerun so the
desktop icon points at it.

## Working on the Windows dev laptop

- **Pythons.** `discobox_env` (Python 3.14, OpenCV 5) runs the app, start.bat and the tests.
  The base miniforge Python (3.12, OpenCV 4.12) has nbclient and Optuna for notebooks; it
  is not used for tests.
- **The user's own server** runs here as `discobox_env\python.exe -m uvicorn web.server:app
  --port 8000`. Check process command lines (`Get-CimInstance Win32_Process`) before
  stopping any python process, stop only your own jobs, and use spare ports (e.g. 8765) for
  test servers. Its load can skew timings.
- **Copies of real recordings** for experiments go in a short path (`%TEMP%\zzrc\<name>`):
  hard-link the frames and videos (`os.link`, never written) and really copy the small
  files. Never open a real run in the app itself (labels and corrections would be written
  into it). Keep scripts in the session scratchpad; `zzrc` was wiped once, so treat it as
  recreatable (it holds `cal_backup`, the small files of the old calibration library from
  before its migration on 2026-10-16). A long path plus recording names passes Windows'
  260-character limit and
  OpenCV then reads empty frames. Remove junctions with `cmd //c rmdir`, never `rm -rf` on
  the parent.
- **OneDrive** sets a read-only flag on folders, which stops even an empty one from being
  removed until cleared (`os.chmod(path, stat.S_IWRITE)`; `files.remove_tree` does it).
- **Timings** vary about 20% between runs and throughput is power-limited (more than 4 to 8
  threads gains nothing); compare the best of several. Background work in the server makes
  a concurrent request up to ten times slower on Windows.
- **Checking the page**: start the server on a spare port without `DISCOBOX_AUTO_STOP`, run
  Chrome headless with `--remote-debugging-port` and a scratchpad profile, and drive it with
  a small Node 22 CDP script (global fetch and WebSocket). The page lands on Live: switch
  with `location.hash = "#/open"`, then `await analysis.openFolder(path); await
  analysis.run()` (it writes `results/<folder>/`: remove it after). For a refactor of the
  page, snapshot every view's HTML before and after through the DOM and diff; only the
  looping clip's frame, ports and timestamps differ between runs.
- **Live mode without a camera**: start the server from a scratchpad launcher that patches
  `pipeline.live.live_setup`'s `CameraSource`, `open_lights`, `live_camera.choose_camera` and
  `live_camera.list_cameras` with `unit_tests/folder_camera.py` (`FolderCamera`, fed from a small copy of
  sample_data). Back up `settings.txt` first: the live page saves every setting into it.
  Close a finished run through `/api/live/<id>/close` before screenshots of the landing page.
- **CPU** (measured 2026-10-14 with a streaming stand-in camera): server idle 0.3%, camera
  connected 2-4%, page on the feed ~10-13% of Chrome. The live workbook and figures are
  written at most every 10 min (`LIVE_FILES_EVERY`). Not done (needs the real camera):
  lowering the camera's frame rate between bursts, possibly the largest constant cost.
- **Notebooks headless**: the default `python3` kernelspec points at the `myenv` env, which
  lacks cv2 and Optuna. Make a kernelspec whose argv runs the base Python
  (`-m ipykernel_launcher -f {connection_file}`) under `<dir>/kernels/<name>/`, set
  `JUPYTER_PATH=<dir>`, run `nbclient.NotebookClient(nb, kernel_name=<name>,
  resources={"metadata": {"path": notebooks_dir}})`, and save with the kernelspec set back
  to `python3`. A notebook importing `pipeline` needs `%matplotlib inline` after its imports
  (`classes/results/reporting.py` selects Agg). A script started from stdin can't start a ProcessPool on
  Windows: run a file.
