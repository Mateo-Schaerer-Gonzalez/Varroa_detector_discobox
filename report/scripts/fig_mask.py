import pickle, sys
from pathlib import Path
import numpy as np, cv2
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
OUT = Path(sys.argv[1])
RIM, CUT, GROW1, GROW2, CENTRE, INK, MUTED, PLATE = "#2A9BB8", "#D9730D", "#F2A65A", "#F7D3A8", "#1F8A5B", "#222222", "#777777", "#5B6CC2"
plt.rcParams.update({"font.size": 9.5, "figure.dpi": 130})
d = pickle.load(open(Path(__file__).parent / "stab_9.1_123.pkl", "rb"))
crop, rim, plate = d["crop"], d["rim"], d["plate"]
dark = np.clip(1 - crop / plate[:, None, None], 0, None); still = dark.mean(axis=0)
h, w = still.shape; yy, xx = np.ogrid[:h, :w]; fm = np.hypot(yy - (h - 1) / 2, xx - (w - 1) / 2)
top = still[~rim].max(); cut = 0.3 * top

def mask(frac):
    de = (still > frac * top) & ~rim
    n, pieces = cv2.connectedComponents(de.astype(np.uint8))
    chosen = pieces == pieces.ravel()[np.where(de, fm, np.inf).argmin()]
    one = cv2.dilate(chosen.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1).astype(bool)
    two = cv2.dilate(chosen.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=2).astype(bool)
    return de, pieces, chosen, one, two

def centre(body):
    wgt = dark * body; t = wgt.sum(axis=(1, 2))
    c = np.stack([(wgt * np.arange(w)).sum(axis=(1, 2)) / t, (wgt * np.arange(h)[:, None]).sum(axis=(1, 2)) / t], 1)
    return c

de, pieces, chosen, one, two = mask(0.3)
c = centre(two); cm = c.mean(axis=0); row = int(round(cm[1]))

def clean(a, t):
    a.set_xticks([]); a.set_yticks([]); a.set_title(t, loc="left", fontsize=9.5)
def over(a, m, col, al):
    rgba = np.zeros((h, w, 4)); rgba[m] = (*matplotlib.colors.to_rgb(col), al); a.imshow(rgba, interpolation="nearest")

fig = plt.figure(figsize=(14, 7.6))
gs = fig.add_gridspec(2, 4, hspace=0.45, wspace=0.42)
# a. mean frame
a = fig.add_subplot(gs[0, 0]); a.imshow(crop.mean(axis=0), cmap="gray", vmin=0, vmax=255); over(a, rim, RIM, 0.45)
a.axhline(row, color="white", lw=0.8, ls="--")
clean(a, "1. mean of the frames (box + 8 px)\nblue rim: bare plate, its light $P_t$")
# b. darkness
a = fig.add_subplot(gs[0, 1]); im = a.imshow(still, cmap="magma_r", vmin=0, vmax=top)
a.contour(still > cut, levels=[0.5], colors=[CUT], linewidths=1.8); a.axhline(row, color=INK, lw=0.8, ls="--")
cb = fig.colorbar(im, ax=a, fraction=0.046, pad=0.03); cb.ax.axhline(cut, color=CUT, lw=2)
a.annotate("shadow ≈ 0.1–0.2", xy=(22, 19), xytext=(9, h - 3), fontsize=8, color=INK, arrowprops=dict(arrowstyle="->", color=INK, lw=0.8))
clean(a, f"2. darkness: 0 = plate, darkest {top:.2f}\norange line: 0.3 × {top:.2f} = {cut:.2f}")
# c. profile
a = fig.add_subplot(gs[0, 2:])
x = np.arange(w); prof = still[row]
a.fill_between(x, 0, prof, where=two[row], step="mid", color=GROW2, alpha=0.9, label="grown by 2 px (in the mask)")
a.fill_between(x, 0, prof, where=chosen[row], step="mid", color=CUT, alpha=0.8, label=f"above the cut-off (core)")
a.step(x, prof, where="mid", color=INK, lw=1.5, label="darkness along the dashed line")
a.axhline(top, color=MUTED, lw=1, ls=":"); a.text(w - 0.5, top + 0.015, f"darkest {top:.2f}", ha="right", fontsize=8.5, color=MUTED)
a.axhline(cut, color=CUT, lw=1.5, ls="--"); a.text(0.5, cut + 0.015, f"cut-off 0.3 × darkest = {cut:.2f}", ha="left", fontsize=8.5, color=CUT)
plate_px = still[~rim & ~two]
a.axhspan(0, np.percentile(plate_px, 99), color=PLATE, alpha=0.12, lw=0)
a.text(0.5, np.percentile(plate_px, 99) + 0.012, f"bare plate: 99 % below {np.percentile(plate_px, 99):.2f}", fontsize=8.5, color=PLATE)
a.annotate("shadow: below the cut-off,\npartly inside the +2 px", xy=(21, 0.17), xytext=(22.3, 0.42), fontsize=8, color=INK,
           arrowprops=dict(arrowstyle="->", color=INK, lw=0.8))
for xr in np.flatnonzero(rim[row]): pass
a.axvspan(-0.5, 5.5, color=RIM, alpha=0.15, lw=0); a.axvspan(w - 6.5, w - 0.5, color=RIM, alpha=0.15, lw=0)
a.set_xlim(-0.5, w - 0.5); a.set_ylim(0, top * 1.12); a.set_xlabel("pixel along the line"); a.set_ylabel("darkness")
a.spines["top"].set_visible(False); a.spines["right"].set_visible(False)
a.legend(frameon=False, fontsize=8, loc="upper left")
a.set_title("3. one row through the mite: the steep edge crosses the cut-off within a pixel or two;\n"
            "growing by 2 px adds back the half-covered edge pixels the cut-off left out", loc="left", fontsize=9.5)
# d. pieces
a = fig.add_subplot(gs[1, 0]); a.imshow(crop.mean(axis=0), cmap="gray", vmin=0, vmax=255)
n = pieces.max()
over(a, de & ~chosen, "#B8467A", 0.5); over(a, chosen, CUT, 0.5)
a.plot((w - 1) / 2, (h - 1) / 2, "x", color="white", ms=8, mew=2)
clean(a, f"4. pixels above {cut:.2f} form\nconnected pieces ({n} here); keep\nthe one nearest the middle (×)")
# e. grown
a = fig.add_subplot(gs[1, 1]); a.imshow(crop.mean(axis=0), cmap="gray", vmin=0, vmax=255)
over(a, two & ~one, GROW2, 0.6); over(a, one & ~chosen, GROW1, 0.6); over(a, chosen, CUT, 0.45)
clean(a, f"5. grow it by 1 px, then 1 px\nmore: the mask B\n({int(chosen.sum())} → {int(two.sum())} pixels)")
a.legend(handles=[Patch(color=CUT, label="core"), Patch(color=GROW1, label="+1 px"), Patch(color=GROW2, label="+2 px")],
         frameon=False, fontsize=7.5, loc="lower right", labelcolor="white")
# f. weights
a = fig.add_subplot(gs[1, 2]); wimg = still * two
im = a.imshow(wimg, cmap="magma_r", vmin=0, vmax=top); a.plot(*cm, "+", color=CENTRE, ms=14, mew=2.5)
clean(a, "6. weights = darkness inside\nthe mask; + their centre\n(one per frame)")
# g. sensitivity
a = fig.add_subplot(gs[1, 3]); a.imshow(crop.mean(axis=0), cmap="gray", vmin=0, vmax=255)
ref = c - c[0]; lines = []
for frac, col in ((0.1, "#2A9BB8"), (0.3, CUT), (0.7, "#B8467A")):
    m2 = mask(frac)[4]; s = centre(m2); s = s - s[0]
    a.contour(m2, levels=[0.5], colors=[col], linewidths=1.6)
    lines.append(Patch(color=col, label=f"{frac}: {int(m2.sum())} px, shake {np.abs(s).max():.3f} px"))
clean(a, "7. the mask at cut-offs 0.1,\n0.3 and 0.7: the measured\nshake barely changes")
a.legend(handles=lines, frameon=False, fontsize=7.5, loc="lower center", bbox_to_anchor=(0.5, -0.32))
fig.suptitle("How the body mask is made (long run, mite 9.1, recording 123)", x=0.01, ha="left", fontsize=11)
fig.savefig(OUT / "body_mask.png", bbox_inches="tight")
print("ok", n, int(chosen.sum()), int(two.sum()), row)
