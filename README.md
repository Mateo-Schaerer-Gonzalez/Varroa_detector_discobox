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
   map and one card per zone. Click a zone to see its mites, how many moved and
   their motion scores. Click a mite
   to see its close-up and score in each recording. The browser's back button
   works throughout.

### Moving or still

The camera only sees movement, so that is all the app reports. A mite is
*moving* in a recording when its motion score in that recording reaches
`mite.motion_threshold` in `config.yaml`, and *still* otherwise. Each recording
is judged on its own; the app makes no call about a mite being alive or dead.

### Calibration

*Calibration ↗* in the header opens a second window, where you mark by eye which
mites move in each recording and compare that with the detector:

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
   by the ground truth against the detector's (overall and per group). Everything is
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

## Running from the command line

```
python main.py                       # sample_data, labels from its labels.json
python main.py my_recordings out/run1
```

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
classes/      detection, zones, motion scoring, plotting
pipeline.py   the only two functions the interface may call
reporting.py  score table -> Excel + figures
main.py       command-line entry point
web/          FastAPI server + static page (no framework, no build step)
unit_tests/   includes test_layering.py, which enforces the boundary above
```

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
```
