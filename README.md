# Varroa_detector_discobox

Detects varroa mites on discobox plates, scores how much each one moves over a
session of recordings, and reports the results grouped by plate.

## Running the app

Double-click `start.bat`, or:

```
python -m uvicorn web.server:app --port 8000
```

Then in the browser:

1. **Recordings**: drag the session folder (the one holding the `..._fps-30`
   folders) onto the page, or click *Choose folder*. The images are copied to
   `uploads/<folder name>/`. Dropping the same folder again only sends files that
   changed, and keeps the labels you already typed. You can also type a path
   instead, and then labels are saved next to the recordings.
2. **Plate labels**: click a plate and type its group (e.g. the venom extract).
   <kbd>Tab</kbd> saves and moves to the next plate. Labels are saved to
   `labels.json` automatically.
3. **Results**: an overview with survival by group, a plate map and one card per
   zone. Click a zone to see its mites, survival and motion scores. Click a mite
   to see its close-up and score in each recording. The browser's back button
   works throughout.

### Alive or dead

A mite is *moving* in a recording when its motion score reaches
`mite.motion_threshold` in `config.yaml`. It counts as *alive* up to and including
its last moving recording and as dead from then on, so a mite that rests for one
recording is not marked dead. As a result, survival curves never go back up. The
limit of this rule is the last recording: a mite that is still at the end cannot
be told apart from a dead one.

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
| `results.xlsx` | `measurements` (one row per mite per recording, with `moving`, `alive` and position), `group_summary`, and `survival` (fraction alive per group and per zone at each recording) |
| `survival_by_group.png` | Fraction of each group's mites alive over time |
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
