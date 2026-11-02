"""Finds the glass slides on a frame, and the zone on each where the writing
is, for the automatic zone mask (zone_masks.AUTO, pipeline/auto_zones.py).

Each slide is found from its frosted end, where the name is written:
1. Ink and mites: pixels darker than DARK times their surroundings, as
   components, each mite-shaped or a stroke; straight lines (edges of the
   holder or a slide) are dropped. Writing is a group of dark thin strokes
   with the mite-shaped blobs inside its box (o's, dots).
2. The frosted end hides the holder's 3D-print lines, which show through
   clear glass, and has straight edges: round each piece of writing, the
   rectangle of a frosted end's size with the smoothest inside against a
   rougher ring, and the strongest edges, is its frosted end (at half size).
3. The glass is on the side with at least MIN_MITES mites (the right, unless
   only the left has any), SLIDE_W long; on the right of a slide with none
   yet, so mites put on it later are in a zone.
4. A row of MIN_MITES mites on no slide yet (writing too faint, or none) gets
   its frosted end looked for just left of it.

The written zone is the frosted end and any writing past it; the plate the
rest of the slide. On 128 labelled 2025 frames it found all 951 slides in use,
and no other but slides written on with no mites yet (scripts/auto_zones.py, notebooks/auto_zones.ipynb, 2026-11-02).
"""

import cv2
import numpy as np

SLIDE_W = 620                   # px, a 75 mm slide at the Discobox camera's scale
FROST_W = range(140, 201, 6)    # the frosted end, about 20 mm
FROST_H = range(192, 241, 6)    # the slide's width, 26 mm
DARK = 0.72                     # a pixel this dark against its surroundings is ink or a mite
INK = 0.45                      # a component whose darkest tenth is this dark is ink or a mite, not a shadow
PEN = 0.5                       # strokes this dark make writing; fainter ones (pencil, the holder's shadows) do not
STROKE = 7.5                    # px, half a stroke's width at most: thicker is a blob (mites touching)
BAND = (4, 16)                  # the ring outside a frosted end that must be rougher, px
MIN_MITES = 3                   # mites on the glass that make a slide in use
PAD = 12                        # px kept between writing and the plate
REACH = 30                      # px the plate reaches past the slide's length, under the clamp


def find_slides(image):
    """[{frost, slide, text, plate, side, found_by}] of the slides with mites on
    them in `image` (greyscale): text is the written zone, plate the rest of
    the slide, each [x1, y1, x2, y2] in pixels."""
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ratio = _ratio(image)
    comps = _components(ratio)
    mites = comps[(comps[:, 5] == 1) & (comps[:, 8] < INK)]
    half = cv2.resize(image, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    ink = cv2.resize((ratio < DARK).astype(np.uint8), (half.shape[1], half.shape[0]), interpolation=cv2.INTER_NEAREST)
    rough, sums = _roughness(half, ink), _edge_sums(half)

    frosts = []
    for x1, y1, x2, y2 in _writing(comps, image.shape):
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        known = [f for f in frosts if f["frost"][0] <= cx <= f["frost"][2] and f["frost"][1] <= cy <= f["frost"][3]]
        if not known:
            frost = _fit_frost(rough, sums, (x1 / 2, y1 / 2, x2 / 2, y2 / 2), half.shape)
            if frost is None:
                continue
            known = [f for f in frosts if _overlap(frost, f["frost"]) > 0.3]
            if not known:
                frosts.append({"frost": frost, "ink": (x1, y1, x2, y2), "found_by": "writing"})
                continue
        b = known[0]["ink"]  # more writing on a frosted end found already
        known[0]["ink"] = (min(b[0], x1), min(b[1], y1), max(b[2], x2), max(b[3], y2))

    slides = [_slide(f, side, image.shape[1], frosts) for f in frosts if (side := _glass_side(f, frosts, mites))]
    for group in _clusters(mites, 110, 45):
        if len(group) < MIN_MITES:
            continue
        x1, y1, _x2, y2 = _box(mites[group])
        cy = (y1 + y2) / 2
        if any(s["slide"][0] <= x1 <= s["slide"][2] and s["slide"][1] <= cy <= s["slide"][3] for s in slides):
            continue
        frost = _fit_frost(rough, sums, ((x1 - 100) / 2, cy / 2 - 2, (x1 - 92) / 2, cy / 2 + 2), half.shape)
        if frost is None or frost[2] > x1 or any(_overlap(frost, s["frost"]) > 0.3 for s in slides):
            continue
        slides.append(_slide({"frost": frost, "ink": frost, "found_by": "mites"}, "right", image.shape[1], frosts + slides))
    return slides


def coords_lines(slides):
    """The slides' zones as a coordinates file's lines (zone_masks.py): `1 x1 y1
    x2 y2` for each plate, then `0 ...` for its written zone."""
    return [f"{number} {x1:.2f} {y1:.2f} {x2:.2f} {y2:.2f}\n" for slide in slides
            for number, (x1, y1, x2, y2) in (("1", slide["plate"]), ("0", slide["text"]))]


def _ratio(image):
    """Each pixel over its surroundings' brightness (a 31 px closing)."""
    f = image.astype(np.float32)
    background = cv2.morphologyEx(f, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
    return f / np.maximum(cv2.GaussianBlur(background, (0, 0), 5), 1)


def _components(ratio):
    """Dark components as rows (x, y, w, h, area, mite_shaped, cx, cy, darkness,
    thickness): darkness the 10th percentile of their ratio, thickness the
    largest distance from their edge (half the widest stroke)."""
    count, labels, stats, centres = cv2.connectedComponentsWithStats((ratio < DARK).astype(np.uint8), connectivity=8)
    rows = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if area < 8 or (max(w, h) > 120 and min(w, h) < 20):
            continue  # noise, or a straight line (an edge of the holder or a slide)
        own = labels[y:y + h, x:x + w] == i
        contours, _ = cv2.findContours(own.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        hull = cv2.contourArea(cv2.convexHull(max(contours, key=cv2.contourArea))) or 1
        mite = 60 <= area <= 900 and area / hull > 0.85 and max(w, h) / max(1, min(w, h)) < 2.6
        thickness = cv2.distanceTransform(np.pad(own, 1).astype(np.uint8), cv2.DIST_L2, 5).max()
        rows.append((x, y, w, h, area, mite, *centres[i], np.percentile(ratio[y:y + h, x:x + w][own], 10), thickness))
    return np.array(rows, dtype=float).reshape(-1, 10)


def _clusters(comps, join_x, join_y):
    """Index groups of components whose boxes are less than join_x, join_y apart."""
    parent = list(range(len(comps)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    x1, y1 = comps[:, 0], comps[:, 1]
    x2, y2 = x1 + comps[:, 2], y1 + comps[:, 3]
    for i in range(len(comps)):
        gap_x = np.maximum(0, np.maximum(x1 - x2[i], x1[i] - x2))
        gap_y = np.maximum(0, np.maximum(y1 - y2[i], y1[i] - y2))
        for j in np.nonzero((gap_x < join_x) & (gap_y < join_y))[0]:
            parent[find(i)] = find(j)
    groups = {}
    for i in range(len(comps)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _box(comps):
    return (comps[:, 0].min(), comps[:, 1].min(), (comps[:, 0] + comps[:, 2]).max(), (comps[:, 1] + comps[:, 3]).max())


def _writing(comps, shape):
    """Boxes (x1, y1, x2, y2) of handwriting, most ink first: groups of dark
    thin strokes with the mite-shaped blobs inside their box, clear of the
    frame's edge (the holder's corners). A mite next to the writing stays out
    of it."""
    strokes = comps[(comps[:, 5] == 0) & (comps[:, 8] < PEN) & (comps[:, 9] <= STROKE)]
    blobs = comps[comps[:, 5] == 1]
    found = []
    for group in _clusters(strokes, 40, 30):
        c = strokes[group]
        x1, y1, x2, y2 = _box(c)
        inner = blobs[(blobs[:, 0] >= x1 - 4) & (blobs[:, 0] + blobs[:, 2] <= x2 + 4)
                      & (blobs[:, 1] >= y1 - 4) & (blobs[:, 1] + blobs[:, 3] <= y2 + 4)]
        ink = c[:, 4].sum() + inner[:, 4].sum()
        if len(c) + len(inner) < 3 or ink < 250:
            continue
        if not (25 <= x2 - x1 <= max(FROST_W) and 12 <= y2 - y1 <= max(FROST_H)):
            continue
        if x1 < 3 or y1 < 3 or x2 > shape[1] - 3 or y2 > shape[0] - 3:
            continue
        found.append((ink, (x1, y1, x2, y2)))
    return [box for _ink, box in sorted(found, key=lambda item: -item[0])]


def _roughness(image, ink):
    """Running sums (cv2.integral) of the log of the finest texture over
    brightness: the holder's print lines show through clear glass, not through
    a frosted end. Ink and mites count as smooth."""
    f = image.astype(np.float32)
    fine = f - cv2.GaussianBlur(f, (0, 0), 1.5)
    energy = np.sqrt(cv2.GaussianBlur(fine * fine, (0, 0), 2)) / np.maximum(cv2.GaussianBlur(f, (0, 0), 2), 1) * 100
    texture = np.log(energy + 0.05)
    texture[cv2.dilate(ink.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0] = np.percentile(texture, 5)
    return cv2.integral(texture.astype(np.float64))


def _edge_sums(image):
    """Running sums of |d/dy| along rows and |d/dx| down columns, each capped at
    the frame's 90th percentile so a short strong edge (the holder's) cannot
    outweigh a long faint one (a slide's)."""
    f = cv2.GaussianBlur(image.astype(np.float32), (0, 0), 1)
    gy = np.abs(cv2.Sobel(f, cv2.CV_32F, 0, 1, ksize=3))
    gx = np.abs(cv2.Sobel(f, cv2.CV_32F, 1, 0, ksize=3))
    gy, gx = np.minimum(gy, np.percentile(gy, 90)), np.minimum(gx, np.percentile(gx, 90))
    return np.pad(np.cumsum(gy, axis=1), ((0, 0), (1, 0))), np.pad(np.cumsum(gx, axis=0), ((1, 0), (0, 0)))


def _mean(sums, x1, y1, x2, y2):
    return (sums[y2, x2] - sums[y1, x2] - sums[y2, x1] + sums[y1, x1]) / np.maximum((x2 - x1) * (y2 - y1), 1)


def _fit_frost(rough, edges, box, shape):
    """The frosted end holding `box`, at half size, as [x1, y1, x2, y2] in full
    pixels (None if none fits): smooth inside against a rougher ring (its three
    most contrasting sides: the next slide's frosted end makes the fourth
    smooth too) plus the edges along its three strongest sides, each part
    scaled by its spread over the rectangles tried."""
    H, W = shape
    bx1, by1, bx2, by2 = (int(v) for v in box)
    a, b = BAND[0] // 2, BAND[1] // 2
    rows, cols = edges
    tried = []
    for w in sorted({v // 2 for v in FROST_W}):
        xs = np.arange(max(b, bx2 - w + 3), min(W - w - b, bx1 - 3) + 1)
        for h in sorted({v // 2 for v in FROST_H}):
            ys = np.arange(max(b, by2 - h + 3), min(H - h - b, by1 - 3) + 1)
            if not len(xs) or not len(ys):
                continue
            X, Y = np.meshgrid(xs, ys)
            inside = _mean(rough, X + 4, Y + 4, X + w - 4, Y + h - 4)
            ring = np.stack([_mean(rough, X, Y - b, X + w, Y - a), _mean(rough, X, Y + h + a, X + w, Y + h + b),
                             _mean(rough, X - b, Y, X - a, Y + h), _mean(rough, X + w + a, Y, X + w + b, Y + h)])
            sides = np.stack([(rows[Y, X + w] - rows[Y, X]) / w, (rows[Y + h - 1, X + w] - rows[Y + h - 1, X]) / w,
                              (cols[Y + h, X] - cols[Y, X]) / h, (cols[Y + h, X + w - 1] - cols[Y, X + w - 1]) / h])
            smooth = np.sort(ring - inside, axis=0)[1:].mean(axis=0)
            straight = np.sort(sides, axis=0)[1:].mean(axis=0)
            tried.append(np.stack([smooth.ravel(), straight.ravel(), X.ravel(), Y.ravel(),
                                   np.full(X.size, w), np.full(X.size, h)], axis=1))
    if not tried:
        return None
    t = np.concatenate(tried)
    score = t[:, 0] / (t[:, 0].std() + 1e-9) + t[:, 1] / (t[:, 1].std() + 1e-9)
    x, y, w, h = (int(v) for v in t[int(np.argmax(score)), 2:])
    return [2 * x, 2 * y, 2 * (x + w), 2 * (y + h)]


def _overlap(a, b):
    """The share of a's area that b covers."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(w, 0) * max(h, 0) / ((a[2] - a[0]) * (a[3] - a[1]))


def _glass_side(frost, frosts, mites):
    """"right" or "left": the side of a frosted end its glass is on: the one with
    MIN_MITES mites, the right if both have; the right if neither has (a slide
    with no mites yet). A side with another frosted end well on it (by 80 px:
    the next column's may start where this slide ends) is not glass; None if
    both are not."""
    fx1, fy1, fx2, fy2 = frost["frost"]
    others = [o["frost"] for o in frosts if o is not frost]
    row = mites[(mites[:, 7] > fy1) & (mites[:, 7] < fy2)]
    open_sides = []
    for side, (gx1, gx2) in (("right", (fx2, fx1 + SLIDE_W)), ("left", (fx2 - SLIDE_W, fx1))):
        if any(o[0] < gx2 - 80 and o[2] > gx1 + 80 and o[1] < fy2 - 40 and o[3] > fy1 + 40 for o in others):
            continue
        if ((row[:, 6] > gx1) & (row[:, 6] < gx2)).sum() >= MIN_MITES:
            return side
        open_sides.append(side)
    return "right" if "right" in open_sides else None


def _slide(frost, side, width, others):
    """The slide of a frosted end, its written zone (the frosted end and any
    writing past it) and its plate (the rest). The plate reaches REACH past the
    slide's length (the glass runs on under the clamp), short of the next
    frosted end in its row (`others`)."""
    fx1, fy1, fx2, fy2 = frost["frost"]
    ink = frost["ink"]
    row = [o["frost"] for o in others if o is not frost and o["frost"][1] < fy2 - 40 and o["frost"][3] > fy1 + 40]
    if side == "right":
        end = min([fx1 + SLIDE_W + REACH, width] + [o[0] - PAD for o in row if o[0] > fx2])
        edge = max(fx2, int(ink[2]) + PAD)
        slide, text, plate = (fx1, fy1, end, fy2), (fx1, fy1, edge, fy2), (edge, fy1, end, fy2)
    else:
        end = max([fx2 - SLIDE_W - REACH, 0] + [o[2] + PAD for o in row if o[2] < fx1])
        edge = min(fx1, int(ink[0]) - PAD)
        slide, text, plate = (end, fy1, fx2, fy2), (edge, fy1, fx2, fy2), (end, fy1, edge, fy2)
    whole = lambda rect: [int(v) for v in rect]  # noqa: E731
    return {"frost": whole(frost["frost"]), "slide": whole(slide), "text": whole(text), "plate": whole(plate),
            "side": side, "found_by": frost["found_by"]}
