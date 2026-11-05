# Varroa detector for the Discobox: user manual

*Agroscope · status of 5 November 2026 · part 1 of 3*

*This part explains how to use the app. Part 2 (`2_how_it_works.md`) explains what it
computes, with each step run on one real mite, and part 3 (`3_performance.md`) shows how
well it works.*

The app watches varroa mites glued on plates inside the Discobox. It detects the mites on
the first frame, decides in every short recording whether each mite moved, and generates
survival curves per treatment group. It can run a test from start to finish on the
Discobox camera (**Live**), analyse recordings made earlier (**Analysis**), and check its
own calls against what you see by eye (**Calibration**).

**The motion detection threshold matters most.** Every call depends on it. Section 4 explains when and how
to set it, and how to check it.

---

## 1. Installing, starting and stopping

### 1.1 First installation

**On the Discobox PC (Linux)**, for live runs:

1. Install Vimba X (the camera's driver) as the Discobox readme describes. The original (Abilium)
   Discobox app's setup uses the same installation.
2. Get the Varroapp and install it, giving the path of the Vimba X SDK (the same path as for
   the Discobox app's `setup-python-env.sh`):

   ```bash
   git clone https://github.com/Mateo-Schaerer-Gonzalez/Varroa_detector_discobox ~/Varroa_detector_discobox
   cd ~/Varroa_detector_discobox
   bash install_linux.sh ../VimbaX_Setup-2025-1-Linux64     # your Vimba X SDK folder
   ```

   This installs conda (Miniforge) if it is missing, creates the Python environment
   `discobox_env` and adds a *Varroa discobox* icon to the desktop and the app menu.
3. Allow your user to set up the fan and LED parameters, then log out and in again (note on the discobox if reusing the VimbaX setup from original software this isn't needed):

   ```bash
   sudo adduser $USER dialout
   ```

Without the Vimba X path (`bash install_linux.sh`) the app installs for analysis only.

**On Windows** (analysis and calibration only, no camera): install
[Miniforge](https://github.com/conda-forge/miniforge), then in its prompt

```bash
git clone https://github.com/Mateo-Schaerer-Gonzalez/Varroa_detector_discobox
cd Varroa_detector_discobox
conda env create -f discobox_env.yaml
```

### 1.2 Starting

| Where | How to start | Address |
|---|---|---|
| Discobox PC (Linux) | Desktop icon *Varroa discobox* | http://127.0.0.1:8010 |
| Windows | Double-click `start.bat` | http://127.0.0.1:8000 |

The browser opens by itself. On the PC connected to the Discobox, the icon first fetches the newest version of
the app (if the PC is online) and restarts the server, except while a live test is
running. Everything runs on the PC itself: no internet is needed, except for the optional text recognition tool that reads the labels on the glass microscope slides automatically (section 2.2).

### 1.3 Stopping

Close every tab of the app; the server stops about 10 s later. A running live test keeps
it going until the test ends. On Linux you can also right-click the icon and choose *Stop
the app*.

---

## 2. Starting a run on the Discobox (Live)

![Live setup page](images/app_live_setup.png)

Ignore the camera message above: the screenshot was taken on the development laptop, which
has no camera.

### 2.1 Connect

1. Name your run and click **Connect**. The camera and the Discobox's Arduino (fan and
   LEDs) are found automatically, both LED strips are turned on, and the camera image appears.
2. Check the **settings**. They can be changed until the run starts:

   | Setting | Meaning |
   |---|---|
   | Time between recordings | Minutes from the start of one recording to the start of the next, as in the Discobox Abilium app. The fan, the LEDs and the recording itself (about 11 s together) fall within it |
   | Fan / LED durations and intensities | As in the Discobox Abilium app. *On/Off* tests the fan; the sliders set intensities |
   | Experiment duration, at most | The longest duration of a run. It stops earlier once every mite is dead (section 2.3) |
   | Dead when still for | How long, in minutes, a mite must stay still to count as dead (the death time). Required. This time is added to the end of the run so a dead mite can be told apart from a mite that is only still for a while |
   | Most a mite moves between recordings | How far a mite is followed from one recording to the next (50 px by default, 0 = not at all). A mite is about 20 px wide |
   | Save the recordings | Keep each mite's video. Needed to replay, label ground truth or re-analyse. Untick if you are only testing the run and don't need to keep the data |

   Every recording is **3 s at 30 fps** (90 frames). These are fixed, not settings, so that
   the threshold fits all future recordings.

3. If the status text under *Connect* turns red or grey, read it: it says what failed
   (camera not found, serial port refused, …).

### 2.2 Label the slides and start

Click **Next: label the slides**.

1. Check the **Zone mask**, which says where the slides and their label areas are:
   - **Found on the first frame (automatic)**, the default: the app finds each slide in use
     from its frosted end, and the label area on it.
   - **One zone per slide** or **Two zones per slide** (upper and lower half): fixed zones
     for the usual positions of the slides. Choose *One zone per slide* if the automatic
     mask misses a slide.
   - A mask you drew yourself on the **Zones** page (section 3.10), e.g. for slides placed
     differently.
2. If the PC is online you can tick **Read labels from glass slides** to fill in every
   slide's label automatically (see the note below). Otherwise click a slide and type its
   label. <kbd>Tab</kbd> saves and goes to the next slide. If you use negative controls, tick
   **negative control** under the control slides: every other group is compared with them using a log-rank test.
3. Each detected mite is encircled by a green ring. Click a ring that is not a mite (dust, a shadow) to cross
   it (this removes it from the analysis). To add a mite the detector missed, click **Place a mite by hand**, then click the mite
   (section 3.3).
4. Click **Start test run**. The LEDs turn off, and from then on the Varroapp switches on the fan and
   LEDs before each recording.

![The label page: detections ringed, slides coloured by group](images/app_labels.png)

**Note on *Read labels from glass slides*.** This option (off by default) sends a picture
of each hand-written label to Google Gemini and fills in the names for you to check. It
needs an internet connection and a free API key (aistudio.google.com/apikey) saved as
`GEMINI_API_KEY=...` in a file `.env` in the app's folder. The developer's key is preset,
so it works out of the box; to use your own, paste your key there instead.

### 2.3 During the run

The results pages fill in after every recording so that the output is updated in real time. A panel at the top of the page shows:

- **A circle per zone**, filling as its mites die. A zone with no mite seen moving yet is
  hollow and doesn't count. When every counting zone is done, the run stops by itself and
  the panel says why.
- The camera's frame rate and any dropped frames (shown in red if there are any); whether
  the fan, LED 1 and LED 2 are on or off at that moment (they come on before each recording
  for their durations, and are off in between; *No fan/LED controller* means the Arduino was
  not found and the run goes on without them); and the countdown to the next recording.

The panel also has buttons to **pause** and **stop** the run, **add mites** (put on slides after the start of the run; they are detected by the app between two recordings, and can be placed by hand
too), enter **ground truth** (label the mites observed moving or still by eye, section 4.3) and
enter a **poke test** between recordings (section 4.4). Closing the browser does **not**
stop a run: open the page again to get back to it.

### 2.4 After the run

The run is saved in `recordings/<run name>/` and listed with the previous recordings. Open
it in *Analysis* to see the results again, or in *Calibration* to label it. Re-analysing it
gives exactly the same scores as the live run because the algorithm is deterministic.

---

## 3. Analysing recordings made earlier (Analysis)

### 3.1 Open the recordings

In *Analysis*, either pick one of the previous recordings, or drag the session folder (e.g. the
one that holds the old Discobox recording folders) onto the page, or click *Choose folder*.
The images are copied into the app. Your own folder is not changed, and dropping the same
folder again only sends what changed.

The first time the folder is analysed or calibrated, the frames are shrunk to just the mites' surroundings, with the same results (part 3 shows how much space this saves). Until then
it keeps its whole frames, so before the first analysis is the moment to place any mite the detector missed
(section 3.3): afterwards there is nothing left to place it on.

> Don't open a folder by typing its path if you want to keep it untouched: labels and
> corrections are then saved next to its recordings.

### 3.2 Label glass slides

As in 2.2: check the zone mask, click a slide, type its label, <kbd>Tab</kbd> to the next,
tick the negative controls.

### 3.3 Place a mite the detector missed

Click **Place a mite by hand**, then click on the mites the automatic detection has missed. The ring goes on the dark spot
nearest the click (within 8 px), so the click need not be exact. A click off the slide, on
a slide's label, or within 10 px of another mite is refused. <kbd>Esc</kbd> or *Done
placing mites* ends it.

A mite placed by hand has a **dashed ring**; click it to take it away. It is saved with the
recordings (`mites_by_hand.json`) and found with the detector's mites everywhere: in the
analysis, in calibration and in a live run. The button is not shown for a session already
shrunk to the mites' surroundings (a saved live run, or a dropped folder after its first
analysis).

### 3.4 Mites put on the slides after the start of a run

Mites put on after the first recording of a run are found too: the app looks at the first frame of
every subsequent recording, and detects mites again in a zone only when at least **Least new
mites per zone** (on the label page, 3 by default, 0 to switch it off) turn up there in the
same recording. Mites are put on several at once, while debris or a mite that walked away
turns up alone. Lower the setting for a zone that got only one or two mites later.

Each mite found this way is numbered after its zone's mites (in a zone with mites 13.1 to
13.4, the next is 13.5) and runs on its own clock from
the recording it appeared in. The label page shows them in yellow under *Added at recording
N*, and the results list them under *Mites put on later*. Check each one, and mark any that
isn't a mite *not a mite* on the label page.

### 3.5 Read the results

![Results overview](images/app_results_top.png)

The overview shows, per group:

- the number and percentage of mites **moving** in each recording;
- the percent **alive** over time (Kaplan–Meier) with its 95 % confidence interval. The
  death time can be changed above the chart for a folder;
- a table with each group's (i.e. the pool of individuals under the same label) **LT50** (time by which half the mites are dead, with its 95 %
  interval) and a **log-rank test** against the negative controls (p value). Without a
  negative control the table is empty;
- the **plate shake** per recording, and the mites that drifted furthest;
- **unusual activity**: mites that came unglued and walked off (*fly-offs* are left out of the analysis),
  recordings another mite walked through (*set aside*, counted neither moving nor still),
  and mites that turned on the spot (*rotators*, kept in the analysis).

![Plate shake per recording](images/app_results_shake.png)

*The shake chart of a relatively still recording: the shake is under a tenth of a pixel
throughout. A recording or stretch that shakes much more than the rest is worth checking
in the playback.*

Below that: a **glass slide map**, one card per zone, all motion scores by group, and the scores
of the moving mites alone.

![Glass slide map](images/app_results_platemap.png)

![Survival by group, movement per zone, group summary](images/app_results_survival.png)

**Click** a zone to see its mites, click a mite to see its close-up video and score in every recording.
Every chart has a tooltip, opens what it shows when clicked, and downloads as SVG or PNG.
The browser's back button works throughout.

Every recording shown (slide, zone, mite, ground truth) **plays once** and stops on its
last frame; **Play** plays it again. Tick **Loop** to play it over and over (the browser
remembers the choice). Loop is off by default because it can bias the reading.

![Zone 7 with its six mites](images/app_zone_top.png)

A mite's close-up is **framed in the colour of its call**: green moving, orange still, grey
gone. The dots round the mite are darker where its outline changes more over the frames.

![A moving and a still mite's close-up, framed by their calls](images/mite_outline_app.png)

### 3.6 Correct a call

On a mite's page, click the mite in the recording shown (or the recording's button in the
table) to switch its call between *moving* and *still*. Every number follows at once and
the frame round the close-up turns **dashed** to indicate the manual change. Clicking again restores the detector's call.
A mite that is no longer there (fell off the slide) can be marked **gone** the same way, in
one recording or from a recording on: it then counts as alive up to its last recording, and
nothing is assumed after.

Corrections are saved by mite position in `corrections.json` next to the recordings, so a
later analysis keeps them. They don't change the calibration's ground truth in case the run was used for ground truthing.

### 3.7 Check the close calls by eye

A mite dies at the recording after its last movement, so a single wrong call can move its
death by hours. Under **To check by eye** you choose how many mites to check (20 by
default, 0 for none). The app picks the scores closest to the threshold that a mite's time
of death depends on and asks about them one by one. It also asks about the peaks of a
mite's score below the threshold after its last movement: a weak last twitch often scores
below the motion detection threshold but stands out on the mite's score graph, where every recording to check
is ringed. Click the recordings it suggests and label each as *Moving* or *Still*
(<kbd>M</kbd>, <kbd>S</kbd>).

### 3.8 Playback

![Playback page](images/app_playback.png)

Every mite's video is displayed side by side, laid out by zone, on one timer: play/pause, a slider over
the whole run, 1× to 16× speed. Each square is framed green if the app identified movement, orange if still, grey if gone or set aside, dashed when corrected by hand.
Click a square to open the mite-specific display.

### 3.9 Files written

| File in `results/<name>/` | Contents |
|---|---|
| `results.xlsx` | `mites` (one row per mite, when it last moved), `scores` (mite × recording), `mite_map` (the slide with every id), `measurements` (one row per mite and recording: moving, position, brightness, corrected), `group_summary` (with the percent of live mites in each group in every recording below it), `moving` (percentage of mites moving per group and zone), one `group <name>` sheet per group, and `settings` |
| `run_settings.json` | The settings the recordings were made and analysed with (code version, recording, detector, analysis, threshold), the same as the workbook's `settings` sheet. Keep it with results you pass on |
| `moving_by_group.png`, `distribution_by_group.png`, `score_over_time.png`, `score_distribution.png` | Figures |
| `detections.jpg` | The first frame with zones, labels and mites |

The workbook and figures are rewritten half a minute after the last correction, and at
once when you download the workbook or close the app.

### 3.10 Draw your own zones (Zones)

When the slides lie where neither the automatic mask nor the fixed ones put them, draw a
zone mask yourself on the **Zones** tab:

![The Zones page](images/app_zones.png)

1. Under **Picture**, choose the first frame of a recording, or click *Use an image file…*
   for a picture taken with the camera. Under **Start from**, choose an existing mask to
   change a copy of it, or start empty.
2. Choose **Mite zone** and drag on the picture round each slide's area where the mites
   are; choose **Text zone** and drag round each slide's label. Click a zone to pick it,
   drag it to move it or drag a corner to resize it; <kbd>Delete</kbd> removes it, the
   arrow keys move it by a pixel (<kbd>Shift</kbd>: ten). *Duplicate below* copies the
   zone picked under it.
3. Each slide shows the number the analysis will give it (in reading order), and each text
   zone the slide whose label is read from it.
4. Type a **Name** (letters, digits, `-` and `_`) and click **Save mask**.

The mask is then listed under *Zone mask* on every label page (section 2.2). Recordings
refer to a mask by its name, so changing a mask changes the next analysis of every recording
that uses it. Deleting one puts those recordings back on *One zone per slide*.

---

## 4. Calibrating the threshold

The motion detection threshold decides *moving* or *still* for every mite in every recording, so it decides
every death time and every survival curve. It is saved per machine in `config.yaml`. Set
it from recordings you labelled by eye, ideally a full run with as many mites as possible,
spread evenly over the camera's field of view. **Calibrate with the same parameters you use for your runs, and
recalibrate when anything in it changes** (section 4.1). The *Calibration* tab sets the
threshold (**Calibrate the threshold**). The test tab (**Test the
threshold**) is used to assess current performance on data not used for calibrating the motion detection threshold.

![Calibration landing page](images/app_calibration_open.png)

### 4.1 When to calibrate, and when to test

Calibrate, then test, whenever the scores may have moved relative to the motion detection threshold:

- **On a new machine**, or a new installation of the app. It starts with the default
  threshold (0.091), set on one 3 s / 30 fps run (`poke_test_oct`, 22–23 October 2026) of
  14 mites that lasted 15.7 hours, with a total of 95 recordings, of which the first 3.5
  hours were labelled (304 mite-recordings).
- **When anything in the setup changes**: the test settings (recording length or frame
  rate, time between recordings, fan, LED intensity), the box's location, the slide type or
  their support plate, the camera, lens or focus, the lighting. A threshold only fits recordings
  made the way it was calibrated on: older 1 s or 10-frame recordings need their own, and a
  fan that stirs the mites more makes them move more.
- **When results look wrong**: dead mites coming back to life, deaths much later than you
  see by eye, or many still mites called moving (section 6).

Otherwise there is no need to recalibrate for every experiment. **Test the performance
from time to time**, for example at the start of each season, to make sure the app still
works to standard (section 4.6), and recalibrate if need be.

### 4.2 What makes good calibration data

- **Recorded the way you run tests**: same Discobox, same settings, 3 s / 30 fps.
- **A whole run labelled** The hard part is not the lively first hours but
  keeping a dead mite still for hours: one still recording called moving brings it back to
  life. Label the still recordings of dead mites too; labels without them can't show
  whether the threshold keeps dead mites still.To avoid too much labelling you can increase the time between recordings for calibration runs.
- **Many mites, spread evenly over the slides and support plate**, so that every part of the image (light,
  focus, shake) is represented.

- **Label every mite in every recording you choose**, not only the obvious ones. The close calls
  are the ones that matter.

- **Two runs**: one to calibrate on, a different one to test on. On the run it was set on,
  a threshold always looks better than it will be.

- **Analyse the mite score traces and plate shake for anomalies** Since all future recordings depend on the quality of calibration data it is important to ensure that there are no anomalies (such as construction work nearby that might cause excessive plate shake)

### 4.3 Step 1: label the ground truth

Calibration needs ground truthing, whereby the user identifies moving and still mites by eye, in the recordings (step 1) or on the slides themselves (step 2).

1. On the *Calibration* tab choose **Calibrate the threshold**, then drop the folder (the
   one holding the `..._fps-30` folders), pick it under the previous recordings, or reopen
   it under *Saved ground truth*.
2. The ground-truth page shows **one mite in one recording** at a time: its clip on the
   left, and on the right where its pixels change over the frames (bright where a leg
   moved). The detector's call is hidden so it can't sway you.

   ![The ground-truth page](images/app_calibration_truth.png)

3. Watch the clip and label it: **moving** <kbd>M</kbd>, **still** <kbd>S</kbd>, **not a
   mite** <kbd>N</kbd>, **unlabelled** <kbd>U</kbd>. A label moves on to the mite's next
   recording, and after its last one to the next mite still to label.
4. **Dead from here on** <kbd>D</kbd> labels the mite still in this recording and in every
   later one not labelled yet. Use it once a mite has clearly died, then check a few of
   its later recordings by eye.
5. <kbd>←</kbd> <kbd>→</kbd> change recording, <kbd>↑</kbd> <kbd>↓</kbd> change mite,
   <kbd>P</kbd> plays or pauses. The slide and plate map on the right shows where the mite is; click
   a dot to go to that mite.
6. *Not a mite* applies to every recording for this entity and removes the detection from later analyses
   of that folder.

Labels are saved as you set them (`ground_truth.json`, by mite position, so they survive a
change of detector settings). The bar on the right counts the mite-recordings labelled.

During a live run, **Ground truth** on the live panel opens the same page on the
recordings so far, so you can label as the run goes.

### 4.4 Step 2 (optional): enter a poke test


**Note: the poke test is not used to calibrate the threshold; run one only if it is of interest to you. If you do decide to run a poke test ensure that the slides are moved as little as possible and align the support plate to the top right corner of the discobox each time it is placed in the box**

Poking a mite, e.g. approaching with the tip of a pencil (the static electricity should stimulate a live mite to move ahead of physical contact, pursue contact to confirm death) says whether it is alive: one that moves when poked was alive up to then, one
that doesn't is dead from then on. During a live run, open *Poke test* on the live panel
between two recordings, right after you poke; for recordings made earlier, click **Enter a
poke test** on the ground-truth page. Then:

1. **Add round** for each time you poked, saying after which recording.
2. Choose what a click marks (*moved*, *did not move*, *not poked*) and click each mite you
   poked, or a zone's number for all its mites not marked yet.

**Poke between two recordings, never during one**: a poked mite moves, and the detector
would count it. The *Test* report (section 4.6) then draws survival by the pokes with the
detector's survival over it, as well as the outline change between recordings.




### 4.5 Step 3: read the calibration report and decide

Click **Show calibration**. The report compares every labelled mite-recording with the
detector's call.

![The calibration report](images/app_calibration_report.png)

Read it top to bottom:

1. **The header** says what went in: the recordings, how many mites, how many moving and
   still labels, and how many were left out (unlabelled, not a mite).
2. **The suggested threshold** optimises the $F_{0.25}$ score, which weighs a false
   *moving* sixteen times as heavily as a false *still*, because a single false *moving*
   can bring a mite back to life hours after its death, while a missed movement is usually
   caught by the mite's next one. Among thresholds that make the same calls, it sits
   halfway between the scores on either side.
3. **Key figures**, for the suggested threshold and the one in use: overall accuracy (share
   of correct calls), moving mites called still, still mites called moving, the $F_{0.25}$
   score, and the **death-time error**: how many recordings each mite's death by the
   detector is off from its death by your labels (labeled recordings by eye).
4. **The table under *Save the threshold*** puts the two thresholds side by side. This is
   where you decide.
5. **The confusion matrix** (Fig. 1), switchable between the two thresholds (suggested and
   in use).
6. **Wrong calls**: *Show the wrong calls* lists every labelled mite-recording the detector
   called the other way; *Check them one by one* opens each so you can confirm or change
   your label (section 4.7). Do this before you save anything: a wrong call is often a
   wrong label.
7. **Fig. 2** (survival by your labels i.e. "ground truth" and by the detector), **Fig. 3** (every labelled
   score; everything right of a line is called moving at that threshold) and **Fig. 4**
   (precision-recall curve with both thresholds marked, average precision 1 = perfect).

**Should you save the suggestion?** Save it when:

- the data meets section 4.2 (above all: the dead mites' still recordings are labelled), and
- the table shows a real gain at the suggested threshold, chiefly fewer *still called
  moving* and a smaller death error, and
- the wrong calls have been checked.

Don't save it when the labelled recordings by eye are few or come only from the first hours. With few labels
the moving and still scores leave a wide gap, and the suggestion lands halfway into it,
which can be far from where a whole run would put it.

*Example.* The screenshot is `ground_truth_60min`, a 2025 test session of 6 recordings of
1 s. It suggests 0.39 against 0.09 in use: at 0.39 no still recording is called moving
but 5 moving ones are called still; at 0.09 it is 1 and 0. Both separate this session
almost perfectly (average precision 0.999). The data is too small, and the recordings
1 s long instead of 3 s, so this suggestion should **not** be saved for live runs.

To save: type the threshold (the suggestion is filled in) and click **Save to
config.yaml**. It is saved with the movement score, and the band of close calls to check
by eye moves with it. Every analysis started afterwards uses it.

Everything is also written to `results/<recording>/calibration/calibration.xlsx`.

### 4.6 Step 4: test the threshold on another run

Go **Back**, choose **Test the threshold**, and open a **different** labelled run (labelled recordings by eye, no poke test needed), then
click **Show test report**. The test report judges the threshold in use; it doesn't
suggest one. Testing works like calibrating: label the run first (section 4.3).

![The test report: key figures, confusion matrix, survival](images/app_calibration_test_top.png)

Read it in this order:

1. **Called right, moving called moving, still called still, average precision.** On a
   good threshold *still called still* stays very close to 100 %.
2. **Fig. 1, the confusion matrix**, at the threshold in use. The bottom-left cell, *still
   called moving*, is the one to keep at or near zero.
3. **Fig. 2, survival**: the black curve is your labels, the dashed ones the detector, the
   original Discobox software (*benchmark (Abilium)*) and the outline change between recordings.
   The closer the detector's curve follows the black one, the better.
4. **Against the benchmark**: how many recordings each method puts the deaths off. *Mean
   error* is positive when the deaths come too late, which is what still mites called
   moving results in, and negative when too early, which a missed last movement results in.

   ![Against the benchmark, where the errors are, precision-recall](images/app_calibration_test_errors.png)

5. **Fig. 3, where the errors are**: every labelled mite on the plate, coloured by its more
   frequent error. Errors that gather on one slide or at the edge point to that slide's specific surroundings
   (light, focus) rather than to the threshold.
6. **The last recording** as the detector and the benchmark call it, **per zone** counts,
   the **poke test** (the detector's survival should not lie above the pokes' at a poke),
   the **outline change between recordings**, and **survival per group**.

*Example.* The screenshots test 0.09 on `ground_truth_90min`: all 168 labelled
mite-recordings called right, every death in the right recording (the benchmark puts
two late).

**What to do with the result**

| The test shows | Then |
|---|---|
| Still called moving near 0, deaths within a recording or so | Keep the threshold |
| Many still called moving, deaths too late (positive mean error) | The threshold is too low for these recordings. Check the wrong calls, then calibrate on more data with mites labelled past their death time, pooled runs (section 4.8) |
| Many moving called still, deaths too early (negative mean error) | The threshold may be too high. Check the wrong calls; if they are real, calibrate again |
| Errors concentrated in one stretch of time | Look at the shake chart and the playback first; it may be the recording, not the threshold |

### 4.7 Check the wrong calls

In either report, **Show the wrong calls**, then **Check them one by one**. Each opens the
mite in its recording on the ground-truth page, indicates how you labelled it and how the
detector called it, and asks *Moving* or *Still* (<kbd>M</kbd>, <kbd>S</kbd>). Your answer
becomes its label, and the next wrong call comes up, across all pooled datasets. After the
last, the report comes back: click **Update** to see it with the corrected labels. 


**Note: this is a guard against mislabelled ground truth data, but if it is a close call it is recommended to keep your original label as otherwise this will introduce a bias.**

### 4.8 Pool several runs

Under **Data used**, tick **Pool with saved ground truth from other recordings**, then
untick any you want left out. Pooling gives more labels, and more varied ones, for a
steadier threshold. Pool only recordings made the same way (same setup, recording length
and frame rate). The *Saved ground truth* list on the first page can also report on ticked
datasets alone, and reopen or delete a dataset's ground truth (its recordings stay).

### 4.9 Checklist

1. Record a whole run with your usual setup, with many mites spread over the support plate and slides, some
   of which die.
2. Label it (section 4.3), including hours of dead mites; add a poke test if you have one.
3. *Calibrate*, check the wrong calls, read the table, save if section 4.5 says so.
4. *Test* on a different labelled run. Keep the threshold if *still called moving* stays
   near zero and the deaths land within a recording or so.
5. Repeat after any change in section 4.1, and test again from time to time (e.g. each
   season/ year).

---

## 5. Where things are kept

| Folder | Contents |
|---|---|
| `recordings/<name>/` | Each session: `first_frame.png`, one video per mite in `rois/`, labels, *not a mite* marks, mites placed by hand, ground truth, poke test, corrections, settings, `run.json` (live runs) |
| `results/<name>/` | The latest analysis: workbook, figures, `run_settings.json`, clips for the pages, `calibration/` |
| `results/pooled/<date time>/` | Calibration reports pooled over several recordings |
| `masks/` | The zone masks drawn on the *Zones* page (section 3.10) |
| `config.yaml` | This machine's threshold and settings (created from `config.default.yaml`) |

`scores/` in a recording and `kept/` and `clips/` in a result are caches: they can be
deleted at any time and are rebuilt.

---

## 6. When something goes wrong

| Problem | What to do |
|---|---|
| Live: camera or fan/LEDs not found | Read the red/grey status text under *Connect*. Check that the original Discobox app is closed (only one program can use the camera) and that you are in the `dialout` group |
| The page looks like an old version | Open http://127.0.0.1:8010/api/version: it shows the folder, the commit and any live run. The update log is `update.log` in the app's folder |
| Dead mites keep coming back to life | The threshold is probably too low for your recordings, or still recordings of dead mites were never labelled. Recalibrate (section 4), and check the close calls (section 3.7) |
| The calibration report says the threshold in use is on another scale | The score changed with an update. Calibrate and save a threshold again (section 4.5) |
| Many still mites called moving on some plates from one moment on | A plate may have moved by many pixels. In a live run the mites are followed; in a folder analysis the boxes stay where they were found. Check the playback and the shake chart, and correct or mark the affected recordings |
| A mite was not detected | Place it by hand before the first analysis (section 3.3), or during a live run with *Add mites* |
| A mite fell off | Mark it *gone* from that recording on (section 3.6) |

## 7. Contact

For any problem or request, open an issue on the GitHub repository:

https://github.com/Mateo-Schaerer-Gonzalez/Varroa_detector_discobox
