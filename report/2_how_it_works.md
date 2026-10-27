# Varroa detector for the Discobox: how it works

*Agroscope · status of 26 October 2026 · part 2 of 3*

*Part 1 (`1_user_manual.md`) explains how to use the app. Part 3 (`3_performance.md`) says how
well it works. This part explains what the app computes, one step at a time, with the
formulas and constants the code uses. Every step names the file it lives in, so a reader
can check it.*

```mermaid
flowchart LR
    A["First frame"] --> B["§1 Find the mites"]
    B --> C["§2 Every recording:<br/>cut each mite's patch,<br/>hold it still"]
    C --> D["§3 Outline score<br/>(in multiples of<br/>the noise floor)"]
    D --> E{"§4 score ≥ T ?"}
    E -- yes --> F["moving"]
    E -- no --> G["still"]
    F & G --> H["§5 Alive / dead,<br/>Kaplan–Meier, LT50,<br/>log-rank"]
    I["§6 Labels by eye"] -. "choose T (F0.5)" .-> E
```

**Notation.** A *recording* is a short burst of $N$ grey frames $I_1,\dots,I_N$ (live runs
are fixed at 3 s × 30 fps, so $N = 90$; older recordings have 10 or 30 frames). Grey levels
run from 0 (black) to 255. $\operatorname{var}_t$ is the variance over the frames of a recording
(population variance, divided by $N$), $\operatorname{med}$ a median. All pixel distances are in
pixels (px) of the 2064 × 1544 camera image.

**Positions are vectors.** Bold letters are positions or displacements in the image, with two
components: $\mathbf x = (x, y)$, where $x$ is the column and $y$ the row, in pixels. The
origin is the top-left pixel of whatever is being worked on (the crop in §2, the patch in
§3), $x$ grows to the right and $y$ **downwards**, as in any image. A pixel's whole-number
coordinates are its centre, so the top-left pixel is $(0, 0)$ and its neighbour to the right
$(1, 0)$. A position worked out from pixels (a centre $\mathbf c_t$, a shift $\mathbf s_t$)
has real-valued components and can fall between pixel centres; the image's value there,
$I_t(\mathbf x)$, is interpolated. $\sum_{\mathbf x}$ runs over every pixel of the crop or
patch. A shift is a difference of two positions, so it doesn't depend on where the origin is.

---

## 1. Finding the mites

*Code: `classes/scoring/analyzer.py` (`detect`), `classes/plate/zones.py`.*

The mites are found once, on the first frame of the first recording.

1. **Mask.** `coords_pixel.txt` lists each plate as a rectangle (type 1) and the area of
   its hand-written label (type 0). Everything outside the plates and inside the label
   areas is blanked, so writing and the box around the plates can't be taken for mites.
2. **Blob detection.** OpenCV's `SimpleBlobDetector` thresholds the masked image at every
   grey level $g = 30, 40, \dots, 200$, finds the connected dark regions at each level,
   and keeps the regions whose centres agree across several levels. A region then has to
   pass every filter (from `config.yaml`, section `detector`):

   | Filter | Definition | Kept when |
   |---|---|---|
   | colour | grey level at the blob's centre | dark (`blob_color: 0`) |
   | area | pixels in the region | 40 ≤ A ≤ 1,200 px² |
   | circularity | $4\pi A / P^2$ (P = perimeter) | ≥ 0.55 |
   | convexity | $A / A_\text{convex hull}$ | ≥ 0.80 |
   | inertia ratio | minor / major axis of the second moments | ≥ 0.45 |

3. **Box.** Each blob gives a centre $(x, y)$ and a diameter $s$. The mite's **box** is the
   square $[x - s/2,\, x + s/2] \times [y - s/2,\, y + s/2]$.
4. **Zone and id.** A mite belongs to the zone (plate, or half-plate with two zones per
   plate) that holds its whole box. Inside a zone the mites are sorted in reading order:
   into lines two mite heights tall (the median box height), top to bottom, then left to right within a
   line. Mite `13.4` is the fourth mite of zone 13.

![Detection in three steps on plates 6 and 7](images/detector_steps.png)

Labels, ground truth and corrections are saved **by position** (matched to a mite within
10 px, `classes/plate/positions.py`), not by id, so they survive a change to the detector.

**In a live run** each mite is also *followed* (`classes/live/`, `motion_analysis.py`):
before each recording the detector runs on its first frame, and each mite moves to the
nearest blob of its own zone at most `follow_px` (50 px) away, nearest pairs first. A mite
with no blob in reach, or one less than 2 px away, stays where it is. Within a recording
the box doesn't move.

---

## 2. Cutting each mite's patch, and holding it still

*Code: `classes/scoring/plate_stabilizer.py`.*

For each recording, each mite gets a **patch**: its box plus $p = 16$ px on every side,
cut from every frame, giving a stack of $N$ small images. Everything after this point
looks only at the patch. Before the patch is cut, the **stabiliser** measures how far the
mite moved as a whole in each frame and cuts each frame shifted back by that much.

### 2.1 Why a fraction of a pixel matters

The score looks for pixels that change over the recording. A plate that shakes moves the
whole mite, and every pixel on its edge changes, although the mite does nothing.

How much? Across the edge of a mite the grey level drops from the plate's (about 130) to
the body's (about 30) within two or three pixels: up to **52 grey levels per pixel** for the
mite in the figure below. Slide that edge by $\delta$ pixels and each edge pixel changes by
about $52\,\delta$. A shake of $\delta = 0.2$ px, far too small to see, changes the edge
pixels by about **10 grey levels**, while the camera's noise is about 1.7 grey levels (its
standard deviation). To the score, that looks like legs moving all round the mite.

The long run's plates shake by up to 0.24 px within a recording. Without stabilisation,
the shaky recordings are where most still mites get called moving.

### 2.2 The idea: follow the centre of the mite's darkness

A mite glued to the plate moves with the plate. So the shake can be measured on the mite
itself: find where the mite is in each frame, and move each frame back so that the mite sits
where it was in the first.

"Where the mite is" is the **centre of its darkness**: the average position of its pixels,
each weighted by how dark it is. This can measure a shift far smaller than a pixel, for two
reasons:

- **It moves exactly with the mite.** Shift the whole mite by $\delta$, and every weighted
  position shifts by $\delta$, so their average does too, whether $\delta$ is 2 px or
  0.02 px. The pixel grid doesn't round it off, because a sub-pixel shift changes the
  *weights* of the edge pixels (a pixel half covered by the mite is half as dark), and the
  weighted average follows them.
- **It averages out the noise.** The centre is an average over the body's ~200 pixels, so
  the noise of single pixels mostly cancels. For this mite, noise moves the centre by
  roughly a hundredth of a pixel, twenty times less than the shake being measured.

The **legs** pull the centre a little: on the ground truth, a moving mite's centre wanders
0.07 to 0.13 px (median) from where the plate's shake alone would put it, a still mite's
0.03 px. That small pull is taken out along with the shake, but a moving leg changes
pixels by far more than it moves the centre, so the movement the score looks for stays.

**Why each mite on its own, not the whole plate.** Plates don't always shake as one piece:
in the long run the zones once moved apart by up to 0.85 px. Following each mite's own
centre copes with that; one shift for the whole plate doesn't. It is also cheap: about
0.5 ms per mite and recording, against 9.7 ms for image registration (phase correlation and
ECC), which it replaced on 16 October 2026 (`notebooks/centre_stabilization.ipynb`).

### 2.3 Step by step

**Step 1: light of the plate.** Take a slightly larger crop, the box plus 4 px. Its outer
ring of 8 px (the *rim*) is bare plate. In each frame $t$ the plate's light is

$$P_t = \operatorname{med}_{\mathbf x \in \text{rim}} I_t(\mathbf x).$$

**Step 2: darkness.** Each pixel's darkness is the share of the plate's light it takes
away:

$$D_t(\mathbf x) = \max\!\left(0,\; 1 - \frac{I_t(\mathbf x)}{P_t}\right).$$

Dividing by $P_t$ makes this independent of the lamp's brightness in that frame: a lamp
that flickers doesn't move the centre.

**Step 3: the body.** On the mean darkness $\bar D = \frac{1}{N}\sum_t D_t$, let $\delta$
be the mean of its 8 largest values inside the rim (the mite's darkest part). The pixels
inside the rim with $\bar D(\mathbf x) > 0.241\,\delta$ form one piece. It is grown
by 4 px (four 3 × 3 dilations) to make the body mask $B$: $B(\mathbf x) = 1$ for a pixel
in the mask, 0 elsewhere.

![How the body mask is made](images/body_mask.png)

*(Drawn with the constants before 27 October 2026: crop box + 8 px, rim 6 px, body
$0.3 \max \bar D$ grown 2 px.)*

**Where the constants come from.** The crop (box + 4 px), the rim (8 px), the share
(0.241, `plate_stabilizer.BODY_SHARE`), the 8 darkest pixels (`DARKEST_N`) and the growth
(4 px) were chosen by an Optuna search on the labelled recordings on 27 October 2026, with
the score's constants (§3), see `notebooks/pipeline_optuna.ipynb`. What they have to do:
the share has to sit above the plate's darkness, and the grown mask has to hold all of the
mite's darkness, the faint edge too, as darkness the mask cuts off slides across its border
when the mite shifts and the centre then moves less than the mite (a mask at half the
darkest made exactly that error: a shaken synthetic mite scored 60 % higher). Before:
box + 8 px, rim 6 px, $0.3 \max \bar D$, grown 2 px.

**Step 4: centre per frame.** The mite's centre in frame $t$ is the centre of its
darkness inside the body: the average of the pixel positions, each weighted by how dark
the pixel is (0 outside the mask). With the weights $w_t(\mathbf x) = D_t(\mathbf x)\,B(\mathbf x)$,

$$\mathbf c_t = \frac{\sum_{\mathbf x} w_t(\mathbf x)\,\mathbf x}{\sum_{\mathbf x} w_t(\mathbf x)},
\qquad\text{that is}\qquad
c_{t,x} = \frac{\sum_{\mathbf x} w_t(\mathbf x)\,x}{\sum_{\mathbf x} w_t(\mathbf x)},\quad
c_{t,y} = \frac{\sum_{\mathbf x} w_t(\mathbf x)\,y}{\sum_{\mathbf x} w_t(\mathbf x)}.$$



If some frame's centre is a whole pixel or more from the mean centre, the mask $B$ is moved
by those whole pixels for that frame and the centre is computed again, so no part of the
mite falls outside its mask.

**Step 5: shift.** The mite's shift in frame $t$ is the vector

$$\mathbf s_t = \mathbf c_t - \mathbf c_1 $$

how far it moved since the first frame, to the right and downwards ($\mathbf s_1 = (0, 0)$).
Each component is clipped to ±12 px (the 16 px of margin a saved
run keeps, minus the 4 px a Lanczos interpolation would read, kept as the margin): a larger shift belongs to a mite
walking, not a plate shaking. A mite whose centre can't be found in some frame takes the
plate's shift: the median of the other mites' shifts.

**Step 6: cut.** Each frame's patch is cut shifted back by $-\mathbf s_t$: the value the
stabilised frame has at position $\mathbf x$ is the one the original frame has where the mite
had moved to,

$$I^{\text{stab}}_t(\mathbf x) = I_t(\mathbf x + \mathbf s_t),$$

so the mite sits in every frame where it sat in the first. A shift of a fraction of a pixel
puts $\mathbf x + \mathbf s_t$ between pixel centres, so it needs interpolation: each new
pixel is computed from the pixels around the point it comes from. The stabiliser uses
**bilinear** interpolation (the 2 × 2 neighbours, weighted by closeness). Bilinear blurs
the edge more for a shift of half a pixel than for none, so frames shifted by different
amounts differ a little in blur, a change the score could see; Lanczos (a windowed sinc
over 8 × 8 neighbours) keeps the edge sharp, and was used until 27 October 2026. The Optuna
search found no difference between the two (or bicubic) in how well the score separates
moving from still (importance ≤ 0.01), and its chosen trial used bilinear. Where the cut
reaches past the image's edge, the image is mirrored in.



### 2.4 What it records, and what it doesn't handle

The app records, per mite and recording, the largest shift (`shake`) and how far the
mite's shift strayed from the plate's median (`stray`). The results page plots the median
shake per recording, to spot a recording or a stretch of time in which the plate shook.

A mite that walks more than 12 px within a recording, or a plate displaced by many pixels
*between* recordings, is beyond what the stabiliser follows. The second is handled in live
runs by moving each mite's box to the mite before every recording (§1).

---

## 3. The motion score: outline variability

*Code: `classes/scoring/analyzer.py`, `_outline_variability`, `outline_variability_profile`,
`plate_noise`, `_lit`, `_outline_rays`.*

A living mite glued to a plate still moves its **legs**, and legs sit on the **outline** of
the body, usually on one side at a time. Camera noise changes every pixel a little, the same
on all sides. The score measures how much the outline changes over the recording **on one
side more than the others**, in units of the camera's noise in that recording.

The score works on the stabilised patch: the box plus 16 px on every side.

**The constants changed on 27 October 2026.** They were chosen by an Optuna search on the
labelled recordings (`scripts/pipeline_optuna.py`, `notebooks/pipeline_optuna.ipynb`): rim
3 px, body mask at 0.355 of the darkest (not grown), "the darkest" the mean of 8 pixels, the
edge at 0.226 of it, 128 rays of 11.4 px and an outline band of ±1.04 px. The search also
divided the score by the profile's mean to the power 0.491; that was taken out the same day
(§3.7). The text below gives these. **The figures and example numbers of this section were
made with the constants before** (rim 6 px, body $0.3\max\bar d$ grown 2 px, edge at
$0.5\,\delta$ of the 30 darkest, 64 rays of 13 px, band ±1.5 px);
`visual_how_it_works.md` has figures made with the current ones.

The score uses three regions of the patch:

![The regions of the score's patch](images/score_regions.png)

*The same mite as in §2, stabilised. a. Blue: the rim, the outermost 6 px, always bare plate.
It gives the lamp's light in each frame (§3.1) and the noise floor (§3.6). Grey and blue: the
outer 8 px, where the body isn't looked for, so a neighbour at the patch's edge isn't taken
for the mite. Orange: the body mask (§3.2). b. The 64 rays from the centre (§3.3), the body's
edge on each (solid, §3.4) and the outline band ±1.5 px round it (dotted, §3.5). c. The noise
floor: the variance over the frames of each of the rim's 936 pixels; their median is
$\sigma^2$ (§3.6). The median ignores the long right tail, where a neighbour or a speck
changes a few rim pixels.*

The example below is mite 7.1 in recording 8 of the poke run of 22 October 2026 (3 s,
30 fps, 90 frames), labelled moving by eye.

![The outline unrolled into 64 rays](images/outline_unrolled.png)

### 3.1 Even out the lamp

The patch's outermost 3 px are bare plate (the rim, $R$). Per frame, the plate's light is
$P_t = \operatorname{med}_{\mathbf x\in R} I_t(\mathbf x)$, and its mean over the recording is
$L = \frac{1}{N}\sum_t P_t$. Every frame is scaled to the same plate light:

$$\tilde I_t(\mathbf x) = I_t(\mathbf x)\,\frac{L}{P_t}.$$

A flickering lamp then changes nothing. (If the plate is black, $P_t \le 0$, the patch
gets no score.)

### 3.2 Find the body once, its centre in every frame

Darkness $D_t$, the body mask $B$ and the centre $\mathbf c_t$ are found as in the
stabiliser, with these differences: the body is the piece darker than $0.355\,\delta$
($\delta$ the mean of the 8 darkest pixels of the whole patch), not grown; the outer 8 px of
the patch are left out of the mask; and the mask is not moved along for frames where
the centre strays a pixel or more. The mask is found once, on $\bar D$, and is the same in
every frame; the centre is found in every frame.

If the mite or the plate moved a little within the recording, $\mathbf c_t$ moves with
it, and the rays below start from where the mite is **in that frame**. Shake the stabiliser
left over then does not count as a change of outline.

Why not simply threshold the darkness in each frame and take the centre of what is left?



### 3.3 Cast 128 rays

From $\mathbf c_t$, $K = 128$ rays go out at angles $\theta_k = 2\pi k/K$ ($k = 0,\dots,127$, one
every 2.8°). Ray $k$ points along the unit vector $\mathbf e_k = (\cos\theta_k, \sin\theta_k)$:
$\theta = 0$ points right, $\theta = 90°$ down (since $y$ grows downwards), so the angles go
round clockwise in the image. Each ray is sampled every 0.5 px from $r = 0$ out to the reach
$\rho = \min(11.4\text{ px},$ the distance from the centre to the patch's edge$)$, with
bilinear interpolation; the point at distance $r$ along ray $k$ is $\mathbf c_t + r\,\mathbf e_k$:

$$u_t(k, r) = \tilde I_t\big(\mathbf c_t + r\,\mathbf e_k\big).$$

11.4 px reaches past a mite's legs (the yellow lines in panel **a**, drawn 13 px long).
Unrolled, the patch becomes a grid of 128 directions × 23 distances (panel **c**: 64 × 26). If $\rho < 2$ px, the patch
gets no score.

### 3.4 Find the body's edge on each ray

Let $\delta$ be the mean of the 8 largest values of $\bar d$ (the mite's darkest part). On
ray $k$, with $\bar u(k, r) = \frac{1}{N}\sum_t u_t(k, r)$ the mean frame along it, the edge
$b_k$ is the first distance at which its darkness drops below 0.226 of that:

$$b_k = \min\big\{ r : d\big(\bar u(k, r)\big) < 0.226\,\delta \big\}$$

(the outermost point if it never does). This is the solid orange line in panels **a**–**c**.

### 3.5 Measure the change along the outline

The variance over the frames at every point of every ray is
$V(k, r) = \operatorname{var}_t\, u_t(k, r)$ (blue in panels **b** and **c**). The
**outline** is the band within $w = 1.04$ px of the edge (shaded in **c**). Each direction's
value is the mean variance in that band:

$$v_k = \operatorname{mean}\{\,V(k, r) : |r - b_k| \le 1.04\,\}, \qquad k = 0,\dots,127.$$

These 128 numbers, in grey levels², are the mite's **outline profile**. If they are all
below $10^{-6}$ (frames identical), the score is 0.

### 3.6 Divide by the recording's noise floor

The camera's noise in this recording, at this mite, is the median over the rim's pixels of
their variance over the frames (lamp-corrected as in 3.1):

$$\sigma^2 = \operatorname{med}_{\mathbf x\in R}\; \operatorname{var}_t\,\tilde I_t(\mathbf x).$$

The profile is then
expressed in multiples of this noise floor:

$$a_k = v_k / \sigma^2.$$

This has the added benefit of making the score robust to changes in plate color and lighting as camera noise is correlated to pixel brightness.

If $\sigma^2 = 0$ (frames with no noise at all, or a black plate), the profile is left
undivided and the app raises a `NoNoiseWarning`: that score isn't on the threshold's scale.

### 3.7 Add the 128 values up as vectors

Each direction's value becomes an arrow pointing in that direction, as long as the value:
the vector $a_k\,\mathbf e_k$, with $\mathbf e_k$ the unit
vector of ray $k$ (§3.3). The score is the length $\lVert\cdot\rVert$ of their sum, divided
by $K = 128$:

$$\boxed{\;\text{score} = \left\lVert\frac{1}{K}\sum_{k=0}^{K-1} a_k\,\mathbf e_k\right\rVert\;}$$

Reading each position $(x, y)$ of the image as the complex number $x + jy$, the unit vector
$\mathbf e_k$ becomes $e^{j\theta_k} = e^{j2\pi k/K}$, and the score can be written as

$$\boxed{\;\text{score} = \left|\frac{1}{K}\sum_{k=0}^{K-1} a_k\, e^{j2\pi k/K}\right|\;}$$

This is closely linked to the discrete Fourier transform (DFT) of the outline profile. The DFT of the $K$
values $a_0, \dots, a_{K-1}$ (here normalised by $1/K$) is

$$X[h] = \frac{1}{K}\sum_{k=0}^{K-1} a_k\, e^{-j2\pi hk/K}, \qquad h = 0, \dots, K-1.$$

The score is equal to the DFT coefficient $X[-1] = X[K-1]$. Since the $a_k$ are real, $X[-1]$ is the complex
conjugate of $X[1]$ and has the same magnitude, so the score is the magnitude of the first
Fourier coefficient:

$$\text{score} = \big|X[1]\big|.$$



![The 64 values and their vector sum](images/outline_vector_sum.png)


**Do still mites land on the same level?** 

![Still recordings' noise floor and score, per dataset](images/still_noise_floor.png)

*a. The noise floor at each mite. b. The still scores, in grey
levels². c. The same score divided by the floor, as the app computes it now (log scales in
b and c). Each dot is one mite's median over its still recordings; the black bar is the
median of the dataset's still recordings. Data: `results/scripts/noise_floor.csv.gz`
(`scripts/noise_floor.py`).*

### 3.8 How the app displays the score

The mite page draws the profile over the mite's clip: a dot per direction, darker where the
outline varies more, and an arrow for the vector sum, green when the mite is called moving
and orange when still.

![The app's outline view, moving and still](images/mite_outline_app.png)

*The dots are shaded relative to the mite's own largest value, so a still mite's noise
looks dark all round. That is exactly why its arrow stays short.*

---

## 4. One threshold: moving or still

*Code: `classes/plate/mite.py`, `classes/app_config.py`.*

$T$ is `mite.metric_thresholds.outline_variability` in the machine's `config.yaml`
(default for a new machine: 0.074, the poke run's best F0.5 threshold with the constants of
27 October 2026; a threshold saved before that is on another scale and has to be saved
again). It is chosen on the Calibration
page. **A threshold fits only recordings as long as the ones it was calibrated on, which
is why live recordings are fixed at 3 s / 30 fps.**

**Close calls.** On the results page the app also draws a band $[T - \beta_-, T + \beta_+]$
around $T$ (`classes/results/review_band.py`). A score inside it is a close call. The user
says how many mites to check by eye ($n$, 20 by default). The app takes the narrowest band
of the configured shape (how far below $T$ against above, or symmetric) that contains close
calls of $n$ mites whose time of death depends on them. Neither edge goes further than $T$
from $T$ (so the band stays within $[0, 2T]$). Only close calls after the mite's last
*settled* movement count: a score at or above the band, or a call set by hand. They are
asked latest first. The band changes no call by itself.

**Set aside.** A recording in which another mite walked into this mite's patch
(`classes/scoring/unusual_activity.py`) is censored: it counts neither as moving nor as
still. A mite whose place stays empty for 3 recordings in a row (no blob within 6 px and its
contrast below half its first) is a *fly-off* and is left out of the analysis.

---

## 5. From moving and still to alive and dead

*Code: `classes/results/survival.py`.*

### 5.1 The death rule

For one mite, let its calls be $m_0, m_1, \dots$ (moving, still, or none where it wasn't
followed), with recording times $t_0, t_1, \dots$ in minutes, and let $D$ be the death time
(*dead when still for*, e.g. 300 min).

- **In the study** only if it moved at least once. A mite never seen moving may have been
  dead from the start.
- $\ell$ = its last recording called moving; $E$ = its last recording with a call (the end
  of its follow-up); $s$ = the recording it was first followed in (0 unless added mid-run).
- If $E > \ell$ and $t_E - t_{\max(\ell, s)} < D$, it hasn't been still long enough: it is
  **alive and censored** at $t_E - t_s$ (all that is known is that it lived that long).
- Otherwise it **died** at recording $\ell + 1$, at time $t_{\ell+1} - t_s$.

Every mite runs on its own clock from $t_s$. A mite marked *gone* (e.g. fell off) has no
call from then on and is censored at its last recording.

### 5.2 Kaplan–Meier survival

With the deaths at distinct times $\tau_1 < \tau_2 < \dots$, $d_j$ deaths at $\tau_j$ and
$n_j$ mites at risk just before it (not yet dead or censored):

$$\hat S(t) = \prod_{\tau_j \le t}\left(1 - \frac{d_j}{n_j}\right).$$

The 95 % confidence interval uses Greenwood's variance on the log-log scale, which keeps it
inside 0–100 % (`scipy.stats.ecdf(...).sf.confidence_interval(method="log-log")`):

$$\hat V = \sum_{\tau_j\le t} \frac{d_j}{n_j(n_j - d_j)}, \qquad
\hat S(t)^{\exp\left(\pm 1.96\,\sqrt{\hat V}\,/\,\ln \hat S(t)\right)}.$$

Where it is undefined (everyone alive or everyone dead) the interval is the estimate itself.

### 5.3 LT50

LT50 is the first recording time at which $\hat S \le 50\,\%$. Its 95 % interval runs from
the first time the lower bound reaches 50 % to the first time the upper bound does. Each is
"not reached" if it doesn't happen by the end of the run.

### 5.4 Log-rank test against the negative control

Each group (all zones with the same label, pooled) is tested against the zones ticked as
negative control. At each death time $\tau_j$ (pooled over both), with $d_j$ deaths among
$n_j$ at risk, of which $n_{1j}$ in the tested group, the expected deaths in the tested
group are

$$E = \sum_j d_j\,\frac{n_{1j}}{n_j},$$

against the observed $O$. The statistic is scipy's log-rank $Z$, and
$\chi^2 = Z^2$ with one degree of freedom gives the p value. The table shows $O$, $E$,
$\chi^2$ and $p$.

### 5.5 A live run stops itself

After each recording, a mite that counts as dead by §5.1 (a never-moved one too, once
still for $D$ from its start) is no longer followed, scored or saved. A zone is done when
every mite in it that was seen moving is dead or gone. Zones with no mite seen moving
don't count. The run stops when every counting zone is done.

---

## 6. Calibration: choosing $T$

*Code: `classes/ground_truth/calibration.py`, `pipeline/calibration/calibration_report.py`.*

**Labels.** On the ground-truth page the user marks each mite in each recording as
*moving*, *still* or *not a mite*, watching the clip without seeing the detector's call.
Each labelled (mite, recording) is one observation; *moving* is the positive class.

**Counts at a threshold $T$.** TP = moving called moving, FN = moving called still,
FP = still called moving, TN = still called still.

$$\text{precision} = \frac{TP}{TP + FP},\qquad \text{recall} = \frac{TP}{TP + FN}.$$

**Suggested threshold: the best F0.5.**

$$F_\beta = \frac{(1+\beta^2)\,TP}{(1+\beta^2)\,TP + \beta^2\,FN + FP}, \qquad \beta = 0.5.$$

With $\beta = 0.5$ one still recording called moving (FP) costs as much as four moving
recordings called still (FN, weight $\beta^2 = 0.25$). The reason is asymmetric: in a long
run a dead mite is scored hundreds of times, and a single FP after its death brings it back
to life and moves its death by hours. A live mite called still once moves again in a later
recording and loses nothing. TN counts for nothing, so the number of still labels doesn't
dilute the result.

$F_{0.5}$ is evaluated at every distinct score, from the highest down. Of the thresholds
with the largest $F_{0.5}$, the highest is taken. 

**Precision-recall curve and average precision.** The report draws precision against
recall over all thresholds and gives the average precision

$$AP = \sum_n (R_n - R_{n-1})\,P_n,$$

the precision averaged over recall: 1 when every moving label scores above every still
label, and the share of moving labels when the score tells nothing.

**Death-time error** (reported, not chosen on). For each mite seen moving, its death by the
detector (the recording after its last call of moving) is compared with its death by the
labels. The report gives the mean absolute difference in recordings and how many mites are
exact.

**Poke test.** A poked mite that moves was alive; one that doesn't is dead from that poke.
The report draws the Kaplan–Meier curve of the poked mites by the pokes (dead at the first
poke not answered; censored at the last poke for one that answered every poke) with the
detector's curve over it.

**Saving.** Saving a threshold writes it to `config.yaml`, and scales the review band in
use by $T_\text{new}/T_\text{old}$, so the band keeps its shape.

---

## 7. What is saved

*Code: `classes/storage/roi_recordings.py`, `classes/storage/kept_scores.py`.*

A live run saves only each mite's surroundings: its box plus 32 px (the score's 16 px pad
plus the stabiliser's 16 px margin), at least 40 px round its centre, as one lossless FFV1
video per mite (`rois/mite_NNN.mkv`). Lossless compression and the 32-px margin mean that
analysing the saved run reads exactly the pixels the live run read, so it gives the same
scores to the last digit. For `sample_data` this takes 17.5 MB instead of 574 MB of BMPs.

Scores are cached per dataset (`scores/`) and per result (`kept/`) under a hash of the
scoring source code: any change to the scoring code re-scores from the frames.
