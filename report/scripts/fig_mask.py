"""How the stabiliser's body mask is made (report/images/body_mask.png), with the constants in use."""
import pickle, sys
import numpy as np, cv2
import figure_kit
sys.path.insert(0, str(figure_kit.REPO))
from classes.scoring.plate_stabilizer import _RIM, PAD, BODY_SHARE, DARKEST_N, BODY_GROW
figure_kit.interactive()
import matplotlib; import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb
from matplotlib.patches import Patch
OUT = figure_kit.out_dir()
RIM, CUT, GROW1, GROW2, CENTRE, INK, MUTED, PLATE = "#2A9BB8", "#D9730D", "#F2A65A", "#F7D3A8", "#1F8A5B", "#222222", "#777777", "#5B6CC2"
plt.rcParams.update({"font.size": 9.5, "figure.dpi": 130})
d = pickle.load(open(figure_kit.needs(figure_kit.HERE / "stab_9.1_123.pkl", "stab_data.py", "9.1", "123"), "rb"))
crop, rim, plate = d["crop"], d["rim"], d["plate"]
dark = np.clip(1 - crop / plate[:, None, None], 0, None); still = dark.mean(axis=0)
h, w = still.shape; yy, xx = np.ogrid[:h, :w]; fm = np.hypot(yy - (h - 1) / 2, xx - (w - 1) / 2)
top = np.sort(still[~rim])[-DARKEST_N:].mean(); cut = BODY_SHARE * top
# the rings grown round the core, +1 px to +BODY_GROW px, light to lighter
RINGS = [tuple(a + (b - a) * k / max(BODY_GROW - 1, 1) for a, b in zip(to_rgb(GROW1), to_rgb(GROW2))) for k in range(BODY_GROW)]

def mask(frac):
    de = (still > frac * top) & ~rim
    n, pieces = cv2.connectedComponents(de.astype(np.uint8))
    chosen = pieces == pieces.ravel()[np.where(de, fm, np.inf).argmin()]
    grown = [cv2.dilate(chosen.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=k).astype(bool) for k in range(1, BODY_GROW + 1)]
    return de, pieces, chosen, grown

def centre(body):
    wgt = dark * body; t = wgt.sum(axis=(1, 2))
    c = np.stack([(wgt * np.arange(w)).sum(axis=(1, 2)) / t, (wgt * np.arange(h)[:, None]).sum(axis=(1, 2)) / t], 1)
    return c

de, pieces, chosen, grown = mask(BODY_SHARE); body = grown[-1]
c = centre(body); cm = c.mean(axis=0); row = int(round(cm[1]))

def clean(a, t):
    a.set_xticks([]); a.set_yticks([]); a.set_title(t, loc="left", fontsize=9.5)
def over(a, m, col, al):
    rgba = np.zeros((h, w, 4)); rgba[m] = (*matplotlib.colors.to_rgb(col), al); a.imshow(rgba, interpolation="nearest")

fig = plt.figure(figsize=(14, 7.6))
gs = fig.add_gridspec(2, 4, hspace=0.45, wspace=0.42)
# a. mean frame
a = fig.add_subplot(gs[0, 0]); a.imshow(crop.mean(axis=0), cmap="gray", vmin=0, vmax=255); over(a, rim, RIM, 0.2)
a.contour(~rim, levels=[0.5], colors=[RIM], linewidths=1.8)
a.axhline(row, color="white", lw=0.8, ls="--")
clean(a, f"1. mean of the frames (box + {PAD} px)\nblue rim, {_RIM} px: bare plate, its light $P_t$")
# b. darkness
a = fig.add_subplot(gs[0, 1]); im = a.imshow(still, cmap="magma_r", vmin=0, vmax=still.max())
a.contour((still > cut) & ~rim, levels=[0.5], colors=[CUT], linewidths=1.8); a.axhline(row, color=INK, lw=0.8, ls="--")
cb = fig.colorbar(im, ax=a, fraction=0.046, pad=0.03); cb.ax.axhline(cut, color=CUT, lw=2)
clean(a, f"2. darkness: 0 = plate; darkest {top:.2f}\n(mean of the {DARKEST_N} darkest within the rim)\n"
         f"orange line: {BODY_SHARE} × {top:.2f} = {cut:.2f}")
# c. profile
a = fig.add_subplot(gs[0, 2:])
x = np.arange(w); prof = still[row]
a.fill_between(x, 0, prof, where=body[row], step="mid", color=GROW2, alpha=0.9, label=f"grown by {BODY_GROW} px (in the mask)")
a.fill_between(x, 0, prof, where=chosen[row], step="mid", color=CUT, alpha=0.8, label="above the cut-off (core)")
a.step(x, prof, where="mid", color=INK, lw=1.5, label="darkness along the dashed line")
a.axhline(top, color=MUTED, lw=1, ls=":"); a.text(w - 0.5, top + 0.015, f"darkest {top:.2f}", ha="right", fontsize=8.5, color=MUTED)
a.axhline(cut, color=CUT, lw=1.5, ls="--"); a.text(0.5, cut + 0.015, f"cut-off {BODY_SHARE} × darkest = {cut:.2f}", ha="left", fontsize=8.5, color=CUT)
plate_px = still[~rim & ~body]
if plate_px.size:
    a.axhspan(0, np.percentile(plate_px, 99), color=PLATE, alpha=0.12, lw=0)
    a.text(w - 0.5, np.percentile(plate_px, 99) + 0.012, ha="right", s=f"bare plate: 99 % below {np.percentile(plate_px, 99):.2f}", fontsize=8.5, color=PLATE)
a.axvspan(-0.5, _RIM - 0.5, color=RIM, alpha=0.15, lw=0); a.axvspan(w - _RIM - 0.5, w - 0.5, color=RIM, alpha=0.15, lw=0)
a.set_xlim(-0.5, w - 0.5); a.set_ylim(0, max(top, prof.max()) * 1.45); a.set_xlabel("pixel along the line"); a.set_ylabel("darkness")
a.spines["top"].set_visible(False); a.spines["right"].set_visible(False)
a.legend(frameon=False, fontsize=8, loc="upper left")
a.set_title("3. one row through the mite (blue: the rim): the steep edge crosses the cut-off within a pixel or two;\n"
            f"growing by {BODY_GROW} px adds back the half-covered edge pixels the cut-off left out", loc="left", fontsize=9.5)
# d. pieces
a = fig.add_subplot(gs[1, 0]); a.imshow(crop.mean(axis=0), cmap="gray", vmin=0, vmax=255)
n = pieces.max()
over(a, de & ~chosen, "#B8467A", 0.5); over(a, chosen, CUT, 0.5)
a.plot((w - 1) / 2, (h - 1) / 2, "x", color="white", ms=8, mew=2)
clean(a, f"4. pixels above {cut:.2f} form\nconnected pieces ({n} here); keep\nthe one nearest the middle (×)")
# e. grown
a = fig.add_subplot(gs[1, 1]); a.imshow(crop.mean(axis=0), cmap="gray", vmin=0, vmax=255)
inner = chosen
for ring, colour in zip(grown, RINGS):
    over(a, ring & ~inner, colour, 0.6); inner = ring
over(a, chosen, CUT, 0.45)
clean(a, f"5. grow it {BODY_GROW} times by 1 px:\nthe mask B\n({int(chosen.sum())} → {int(body.sum())} pixels)")
a.legend(handles=[Patch(color=CUT, label="core")] + [Patch(color=col, label=f"+{k} px") for k, col in enumerate(RINGS, 1)],
         frameon=False, fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=3)
# f. weights
a = fig.add_subplot(gs[1, 2]); wimg = still * body
im = a.imshow(wimg, cmap="magma_r", vmin=0, vmax=still.max()); a.plot(*cm, "+", color=CENTRE, ms=14, mew=2.5)
clean(a, "6. weights = darkness inside\nthe mask; + their centre\n(one per frame)")
# g. sensitivity
a = fig.add_subplot(gs[1, 3]); a.imshow(crop.mean(axis=0), cmap="gray", vmin=0, vmax=255)
lines = []
for frac, col in ((0.1, "#2A9BB8"), (BODY_SHARE, CUT), (0.7, "#B8467A")):
    m2 = mask(frac)[3][-1]; s = centre(m2); s = s - s[0]
    a.contour(m2, levels=[0.5], colors=[col], linewidths=1.6)
    lines.append(Patch(color=col, label=f"{frac}: {int(m2.sum())} px, shake {np.abs(s).max():.3f} px"))
clean(a, f"7. the mask at cut-offs 0.1,\n{BODY_SHARE} and 0.7: the measured\nshake barely changes")
a.legend(handles=lines, frameon=False, fontsize=7.5, loc="lower center", bbox_to_anchor=(0.5, -0.32))
fig.suptitle(f"How the body mask is made (long run, mite {d['mite']}, recording {d['recording']})", x=0.01, ha="left", fontsize=11)
fig.savefig(OUT / "body_mask.png", bbox_inches="tight")
print("ok", n, int(chosen.sum()), int(body.sum()), row)
figure_kit.show()
