# Varroa_detector_discobox

Detects varroa mites on discobox plates, scores how much each one moves over a
session of recordings, and reports the results grouped by plate.

## Running the app

Double-click `start.bat`, or:

```
python -m uvicorn web.server:app --port 8000
```

On Linux, run `bash install_linux.sh` once. It installs Miniforge if conda is
missing, creates `discobox_env`, and adds a *Varroa discobox* icon to the
desktop and the app menu. The icon runs `start.sh`, the Linux version of
`start.bat`: the server runs in the background (output in `server.log`) and
only the browser opens. Right-click the icon and pick *Stop the app* to stop
it, or run `./start.sh stop`.

Started from `start.bat` or `start.sh`, the server stops by itself about 10
seconds after the last browser tab is closed, so the next start always runs
the current code (e.g. after a `git pull`). A tab left in the background keeps
it running. Started by hand with the command above, it keeps running.

Then in the browser:

1. **Recordings**: drag the session folder (the one holding the `..._fps-30`
   folders) onto the page, or click *Choose folder*. The images are copied to
   `uploads/<folder name>/`. Dropping the same folder again only sends files that
   changed, and keeps the labels you already typed. You can also type a path
   instead, and then labels are saved next to the recordings.
2. **Plate labels**: click a plate and type its group (e.g. the venom extract).
   <kbd>Tab</kbd> saves and moves to the next plate. Labels are saved to
   `labels.json` automatically.
3. **Results**: an overview with the fraction of mites moving per group, a plate
   map, one card per zone, every motion score by group, the scores of the moving
   mites alone by group (a box plot the many still recordings do not pull down),
   and per zone a ridgeline of the time between two movements of a mite. Click a
   zone to see its mites, how many moved and their motion scores. Click a mite
   to see its close-up and score in each recording. Every chart has a tooltip,
   opens what it shows when clicked, and downloads as SVG or PNG. The browser's
   back button works throughout.

### Moving or still

The camera only sees movement, so that is all the app reports. A mite is
*moving* in a recording when its motion score in that recording reaches
`mite.motion_threshold` in `config.yaml`, and *still* otherwise. Each recording
is judged on its own; the app makes no call about a mite being alive or dead.

### Calibration

*Calibration ↗* in the header switches to calibration in the same window, where
you mark by eye which mites move in each recording and compare that with the
detector. *← Exit calibration* goes back to the analysis where you left it; both
keep their state while you switch:

1. **Calibration data**: pick *Calibrate the threshold* or *Test the threshold*,
   then drop the folder. Every frame is decoded and each mite is scored.
2. **Ground truth**: zone by zone and recording by recording, the zone's frames
   of that recording play in a loop; click each mite to cycle it through
   *moving*, *still*, *not a mite* (a false detection) and back to unlabelled;
   clicking on past a *not a mite* you just set brings back the mite's labels.
   <kbd>↑</kbd> <kbd>↓</kbd> change recording, <kbd>←</kbd> <kbd>→</kbd> change
   zone. The detector's own call is hidden so it cannot bias you. *Save changes*,
   or showing the report, saves the labels by position in `ground_truth.json`
   next to the recordings, so they survive a change in detector settings.
3. **Report**: every labelled (mite, recording) is compared with the
   detector's call there, moving when that recording's score reaches the
   threshold. *Calibration* suggests the threshold that maximises sensitivity +
   specificity and can save it to `config.yaml`; its confusion matrix switches
   between the suggested threshold and the one in use. *Test* shows the
   confusion matrix at the threshold in use, the ROC curve with AUC, and where on
   the plate the errors are. Both show the fraction of mites moving per recording
   by the ground truth against the detector's; *Test* also shows it per group. Everything is
   also written to `calibration.xlsx`. Under *Data used*, switch on *Pool with
   saved ground truth* to add other labelled recordings, and untick any you
   want left out. Every point, map dot and zone row names the folder and
   recording it comes from, and clicking it opens that mite in its own recording,
   whichever dataset it belongs to.
   Under *Movement score*, choose a metric and its parameters (e.g. `n` for
   `topN_variability`) and *Score again*: nothing in `config.yaml` changes
   until you save a threshold, which saves the metric and parameters with it.

Test a threshold on a different recording from the one it was calibrated on.

**Saved ground truth.** Every labelled recording is also kept in
`calibration_data/<folder>-<hash>/`: its mites, ground truth, first frame and a
copy of its recordings, never its scores. The *Saved ground truth* list on the
first calibration page lets you reopen a dataset to go on labelling it (nothing
is decoded), delete it, or tick several and report on them pooled. Every report
scores the pooled datasets again from their recordings with the movement score
chosen, so old ground truth can judge a new metric. `scores/` in each dataset
only caches the scores of one exact metric, parameters and scoring code, to
skip decoding again; it can be deleted at any time.

`config.yaml` holds the metric in use and, under `metric_params`, the
parameters of each metric (`{topN_variability: {n: 10}}`); one left out uses the
default in `classes/analyzer.py`.

A detection marked *not a mite* is removed from every later analysis of that
folder: `run_analysis` drops it before scoring, so it appears in no count,
curve or figure.

Everything runs on `127.0.0.1` and no asset is fetched from the internet, so the
app works with no network connection.

### Live from the Discobox

*Live ↗* in the header runs a Discobox test run from this app, as the Discobox app
(github.com/Abilium-GmbH/varroa-discobox) does: every *time between recordings*
the fan and LEDs come on and the camera records a burst of frames. Each recording
is analysed as soon as it is in, and the usual result pages fill in as the run goes.

1. **Camera**: name the run and *Connect*: the camera and the Discobox's
   Arduino are found by themselves, and the LEDs come on so the plates can be
   seen. The camera's image shows at once. The test run's settings are the
   Discobox app's (number of recordings, time between them, fan and LED
   durations and intensities, frames per recording, frames per second); they
   are saved to `settings.txt` as you change them. *On/Off* switches the fan or
   an LED to check it. *More options* holds the frames per pool and whether the
   recordings are saved.
2. **Plate labels**: the same page as for a folder, on the camera's newest frame,
   with the LEDs on (any switched off comes back on first). *Start test run*
   switches them off and starts recording; from then on the run switches them.
3. **Live results**: the result pages of a folder, with a panel above them: a
   bar for the whole run (how far it is, a tick per recording, the time left),
   the frame rate, dropped frames, the fan and LEDs, and *Pause* / *Stop*. The
   charts' time axis covers the whole run from the start, and each recording
   fills in its part; once the run is over, the axis is what was recorded.
   *Follow the latest recording* shows each new recording as it comes; choose
   an older one and the page stays on it. Labels and *not a mite* marks can
   still change; the results follow them.

Each recording is saved, as the Discobox app saves it, to
`output/<run name>/<YYYY-MM-DD-HH-MM-SS>_fps-<fps>/<recording>_<frame id>.bmp`
(8-bit grey), with the settings, labels and marks next to them. Only the bursts are
saved, never the camera image in between. That folder is a session like any
other: opened as a folder, it gives exactly the results the live run gave.
Untick *Save the recordings* for long runs; the results are the same, but there
is then no clip to play and nothing to open again.

*Stop* ends the recording being captured with the frames already in, analyses it
and writes the results; so does Ctrl+C on the server. Closing the page does not
stop a run: open the page again to get back to it. Started from `start.bat` or
`start.sh`, the server waits for a run to end before stopping by itself.

With no camera, *No camera? Replay a recorded folder* plays a folder's recordings
as if they came from the camera, to try all this; its results are the folder's.

**Frames per pool** sets how many consecutive frames are scored together. Left
empty, a pool is a whole recording, as it has always been. With a number N, each
recording is split into pools of N frames; the frames left at the end of a
recording are not scored. The same option is under *Plate labels* for a folder,
and live and folder runs pool the same way.

**One difference from the Discobox app.** The app switches on only one of the
devices due at the same moment: with equal fan and LED durations (20 s each for
`sample_data`) only LED 2 ever came on, never the fan or LED 1. Here every device
comes on as set. Mites stirred by the fan may move more than in recordings made
with the app, so check the movement threshold on a live recording (Calibration)
before comparing the two.

**Setting up the camera.** Install Vimba X as the Discobox readme describes, then
`bash install_linux.sh <VimbaX SDK path>` (the path given to the app's
`setup-python-env.sh`), and add yourself to the `dialout` group for the fan and
LEDs (`sudo adduser $USER dialout`, then log in again). Folder mode needs none of
this.

## Running from the command line

```
python main.py                       # sample_data, labels from its labels.json
python main.py my_recordings out/run1
python main.py my_recordings out/run1 --pool-size 10
```

A live test run, with the settings in `settings.txt`; Ctrl+C stops it cleanly:

```
python main.py --list-cameras
python main.py --live                       # the only camera connected
python main.py --live --camera-id DEV_000F31 --fps 30 --run-name hive3 --labels labels.json
python main.py --live --no-save-frames      # long runs: analyse, save nothing
python main.py --replay sample_data         # a recorded folder, as if from the camera
```

It prints a line per recording analysed, and the results go to
`outputs/<run name>/` (`--out-dir` to change that).

## Results

Each run writes to `outputs/<session>/`:

| File | Contents |
| --- | --- |
| `results.xlsx` | `measurements` (one row per mite per recording, with `moving` and position), `group_summary`, and `moving` (fraction of mites moving per group and per zone at each recording) |
| `moving_by_group.png` | Fraction of each group's mites moving in each recording |
| `distribution_by_group.png` | Score distribution per group, box plot with raw points |
| `score_over_time.png` | Each mite's score across the session |
| `score_distribution.png` | Overall histogram |
| `detections.jpg` | First frame with zones, labels and detected mites drawn on |

## Layout

Dependencies point one way: `web/` → `pipeline.py` → `classes/`.

```
classes/      detection, zones, motion scoring, plotting; the analysis core
              (motion_analysis.py) and where its frames come from
              (frame_source.py, pooling.py)
classes/live/ the camera, fan and LEDs, test run, replay and live session
classes/discobox/  camera_utils.py from the Discobox app, unchanged
pipeline.py   the only module the interface may call
reporting.py  score table -> Excel + figures
main.py       command-line entry point
web/          FastAPI server + static page (no framework, no build step)
unit_tests/   includes test_layering.py, which enforces the boundary above
```

Folder and live runs go through one analysis core, `MotionAnalysis`: it finds the
mites on the first frame, then scores each pool of frames as it comes, from a
folder (`FolderSource`), the camera (`CameraSource`) or a replay (`ReplaySource`),
without knowing which. vmbpy and pyserial are only imported for a live run.

`pipeline.open_session()` and `pipeline.run_analysis()` exchange only plain dicts,
lists, strings and numbers with the web layer -- never a `Zone`, `Mite`,
`DataFrame` or image array. `unit_tests/test_layering.py` fails if the web layer
imports cv2/pandas/matplotlib/numpy/classes, if the analysis imports anything
web-related, or if the page references a remote URL.

## Zone coordinates

`coords_pixel.txt` holds one line per zone: `type x1 y1 x2 y2`, where type `1` is a
plate and type `0` is a printed-label area that is masked out before detection.
Plates are numbered 0-14 in reading order (left to right, top to bottom), and that
id is what a typed label attaches to.

## Tests

```
python -m pytest
python -m pytest -m "not slow"     # without the runs on the whole of sample_data
```

`folder_regression_test.py` compares folder mode with a reference made before live
input was added (`unit_tests/reference/`): the results, every sheet of the
workbook, what each figure draws, the images' pixels and what the command line
prints. `live_acceptance_test.py` replays folders through the live pipeline and
checks that folder mode on the frames it saved gives exactly the same. Rewrite the
reference (`python unit_tests/make_reference.py`) only for a deliberate change to
what folder mode produces. The camera and the fan and LEDs are tested with
stand-ins; the first run on the real Discobox is the test of the hardware itself.
