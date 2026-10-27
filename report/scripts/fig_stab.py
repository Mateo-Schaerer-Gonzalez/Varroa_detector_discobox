import pickle, sys
from pathlib import Path
import numpy as np, cv2
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Patch
from matplotlib.lines import Line2D
H = Path(__file__).parent; OUT = Path(sys.argv[1])
RIM, BODY, PIECE, CENTRE, BAND, IGN = "#2A9BB8", "#D9730D", "#B8467A", "#1F8A5B", "#F2C230", "#999999"
INK, MUTED = "#222222", "#777777"
plt.rcParams.update({"font.size": 10, "figure.dpi": 130})
d = pickle.load(open(H / "stab_9.1_123.pkl", "rb"))

def overlay(ax, mask, color, alpha=0.45):
    rgba = np.zeros((*mask.shape, 4)); rgba[mask.astype(bool)] = (*matplotlib.colors.to_rgb(color), alpha); ax.imshow(rgba, interpolation="nearest")

def clean(ax, title):
    ax.set_xticks([]); ax.set_yticks([]); ax.set_title(title, loc="left", fontsize=9.5)

# ---------- Figure 1: the stabiliser ----------
crop, rim = d["crop"], d["rim"]; box = d["box"]; pad = 8
fig, ax = plt.subplots(2, 3, figsize=(12, 8.2))
a = ax[0, 0]; a.imshow(crop[0], cmap="gray", vmin=0, vmax=255); overlay(a, rim, RIM)
a.add_patch(Rectangle((pad - 0.5, pad - 0.5), box[2] - box[0], box[3] - box[1], fill=False, ec="white", lw=1.2, ls="--"))
clean(a, "a. crop: the box (dashed) + 8 px\nrim of 6 px (blue): the plate's light $P_t$")
a = ax[0, 1]; im = a.imshow(d["still"], cmap="magma_r", vmin=0, vmax=d["still"].max())
cs = d["dark_enough"]; other = cs & ~d["chosen"]
a.contour(d["chosen"], levels=[0.5], colors=[BODY], linewidths=2)
if other.any(): a.contour(other, levels=[0.5], colors=[PIECE], linewidths=1.5)
fig.colorbar(im, ax=a, fraction=0.046, pad=0.03).set_label(r"mean darkness $\bar D$")
clean(a, "b. mean darkness; pieces darker than 30 %\nof the darkest (orange: nearest the middle)")
a = ax[0, 2]; a.imshow(crop.mean(axis=0), cmap="gray", vmin=0, vmax=255); overlay(a, d["body"], BODY, 0.35)
a.contour(d["chosen"], levels=[0.5], colors=[BODY], linewidths=1)
cx = [(d["body"] * np.clip(1 - f / p, 0, None) * np.arange(f.shape[1])[None]).sum() / (d["body"] * np.clip(1 - f / p, 0, None)).sum() for f, p in zip(crop, d["plate"])]
cy = [(d["body"] * np.clip(1 - f / p, 0, None) * np.arange(f.shape[0])[:, None]).sum() / (d["body"] * np.clip(1 - f / p, 0, None)).sum() for f, p in zip(crop, d["plate"])]
a.plot(np.mean(cx), np.mean(cy), "+", color=CENTRE, ms=14, mew=2.5)
clean(a, "c. body mask $B$: that piece grown by 2 px;\n+ the darkness-weighted centre $c_t$")
a = ax[1, 0]; s = d["shifts"]
a.plot(s[:, 0], s[:, 1], "-", color=MUTED, lw=1); sc = a.scatter(s[:, 0], s[:, 1], c=np.arange(len(s)), cmap="viridis", s=45, zorder=3)
for i, (x, y) in enumerate(s): a.annotate(str(i + 1), (x, y), xytext=(4, 4), textcoords="offset points", fontsize=7)
lim = max(0.25, np.abs(s).max() * 1.3); a.set_xlim(-lim, lim); a.set_ylim(lim, -lim); a.set_aspect("equal")
a.axhline(0, color="#DDDDDD", lw=0.8); a.axvline(0, color="#DDDDDD", lw=0.8)
a.set_xlabel("x shift (px)"); a.set_ylabel("y shift (px)")
a.set_title(f"d. shift $s_t = c_t - c_1$, frame by frame\n(largest {np.hypot(*s.T).max():.2f} px)", loc="left", fontsize=9.5)
vmax = max(d["raw"]["std"].max(), d["cut"]["std"].max()) * 0.8
for a, key, title in ((ax[1, 1], "raw", "e. not stabilised"), (ax[1, 2], "cut", "f. stabilised (in use)")):
    im = a.imshow(d[key]["std"], cmap="Blues", vmin=0, vmax=vmax)
    clean(a, f"{title}: SD of each pixel over the\n10 frames; score {d[key]['score']:.3f} (threshold 0.135)")
fig.colorbar(im, ax=ax[1, 2], fraction=0.046, pad=0.03).set_label("SD over frames (grey levels)")
fig.suptitle(f"Long run, mite {d['mite']}, recording {d['recording']}: labelled still, plate shaking ~0.2 px", x=0.01, ha="left", fontsize=11)
fig.tight_layout(); fig.savefig(OUT / "stabilizer_steps.png", bbox_inches="tight"); plt.close(fig)

# ---------- Figure 2: regions of the score patch ----------
c = d["cut"]; roi = c["roi"]; mean = roi.mean(axis=0); hh, ww = mean.shape
variance, edge, step, centre = c["rays"]
edge_mask = c["edge_mask"]
ign = np.zeros((hh, ww), bool); m8 = 8; ign[:m8] = ign[-m8:] = True; ign[:, :m8] = True; ign[:, -m8:] = True; ign &= ~edge_mask
# body for the score: as _outline_rays
plate = np.median(roi[:, edge_mask], axis=1); light = plate.mean(); lit = roi * (light / plate)[:, None, None]
dark = np.clip(1 - lit / light, 0, None); still = dark.mean(axis=0)
near = ~(ign | edge_mask); de = (still > 0.3 * still[near].max()) & near
pieces = cv2.connectedComponents(de.astype(np.uint8))[1]
yy, xx = np.mgrid[:hh, :ww]; fm = np.hypot(yy - (hh - 1) / 2, xx - (ww - 1) / 2)
bodym = cv2.dilate((pieces == pieces.ravel()[np.where(de, fm, np.inf).argmin()]).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=2)
ang = np.arange(64) * 2 * np.pi / 64
fig, ax = plt.subplots(1, 3, figsize=(13, 4.6), gridspec_kw={"width_ratios": [1, 1, 1.1]})
a = ax[0]; a.imshow(mean, cmap="gray", vmin=0, vmax=255)
overlay(a, edge_mask, RIM, 0.5); overlay(a, ign, IGN, 0.35); overlay(a, bodym, BODY, 0.3)
a.add_patch(Rectangle((16 - 0.5, 16 - 0.5), box[2] - box[0], box[3] - box[1], fill=False, ec="white", lw=1.2, ls="--"))
clean(a, "a. the score's patch: box (dashed) + 16 px")
a.legend(handles=[Patch(color=RIM, alpha=0.6, label=r"rim, 6 px: lamp light $P_t$ and noise floor $\sigma^2$"),
                  Patch(color=IGN, alpha=0.5, label="up to 8 px from the edge (rim included): not searched for the body"),
                  Patch(color=BODY, alpha=0.5, label="body mask")], loc="upper center", bbox_to_anchor=(0.5, -0.02), frameon=False, fontsize=8)
a = ax[1]; a.imshow(mean, cmap="gray", vmin=0, vmax=255)
for k in range(64):
    a.plot([centre[0], centre[0] + 13 * np.cos(ang[k])], [centre[1], centre[1] + 13 * np.sin(ang[k])], color=BAND, lw=0.4, alpha=0.7)
r_e = edge * step
for off, ls in ((-1.5, ":"), (0, "-"), (1.5, ":")):
    r = np.clip(r_e + off, 0, None); a.plot(np.r_[centre[0] + r * np.cos(ang), centre[0] + r[0]], np.r_[centre[1] + r * np.sin(ang), centre[1]], color=BODY, lw=1.6 if off == 0 else 1.1, ls=ls)
a.plot(*centre, "+", color=CENTRE, ms=12, mew=2)
clean(a, "b. 64 rays from the centre (yellow); body edge (line)\nand the outline band ±1.5 px (dotted)")
a = ax[2]
var_rim = lit[:, edge_mask].var(axis=0)
a.hist(var_rim, bins=40, color=RIM, alpha=0.8)
a.axvline(np.median(var_rim), color=INK, lw=1.5, ls="--")
a.text(np.median(var_rim) * 1.05, a.get_ylim()[1] * 0.92, rf"median = $\sigma^2$ = {np.median(var_rim):.2f}", fontsize=9)
a.set_xlabel("variance over the frames (grey levels²)"); a.set_ylabel("rim pixels")
a.spines["top"].set_visible(False); a.spines["right"].set_visible(False)
a.set_title(f"c. the noise floor: variance of each rim pixel\n({edge_mask.sum()} pixels); the score's profile is divided by it", loc="left", fontsize=9.5)
fig.tight_layout(); fig.savefig(OUT / "score_regions.png", bbox_inches="tight"); plt.close(fig)
print("ok", c["noise"], np.median(var_rim))
