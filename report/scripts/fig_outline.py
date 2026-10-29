"""The outline score step by step on the poke run (3 s / 30 fps), current units and constants
(outline_unrolled.png, outline_vector_sum.png)."""
import pickle, sys
import numpy as np
import figure_kit
sys.path.insert(0, str(figure_kit.REPO))
from classes.scoring import analyzer
figure_kit.interactive()
import matplotlib.pyplot as plt
OUT = figure_kit.out_dir()
GREEN, ORANGE, BLUE, INK, MUTED = "#1F8A5B", "#D9730D", "#5B6CC2", "#222222", "#777777"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": "#BBBBBB", "axes.labelcolor": INK, "xtick.color": MUTED,
                     "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 130})
d = pickle.load(open(figure_kit.needs(figure_kit.HERE / "outline_poke_test_oct.pkl", "outline_data.py", "poke_test_oct"), "rb"))
N, REACH, WIDTH = analyzer.ANGLES, analyzer.REACH, figure_kit.width()
rows = []
for r, rec in enumerate(d["data"]):
    for i, m in enumerate(d["ids"]):
        v = rec.get(m)
        if v is None or not v["noise"] or not d["labelled"][i, r] or v["rays"] is None:
            continue
        rows.append((bool(d["moving"][i, r]), v["score"], m, r, v))
mv = sorted([x for x in rows if x[0]], key=lambda x: x[1]); st = sorted([x for x in rows if not x[0]], key=lambda x: x[1])
moving, still = mv[int(len(mv) * 0.6)], st[len(st) // 2]
print("moving", moving[2], moving[3], moving[1], "still", still[2], still[3], still[1])

def unit(v):
    return v["profile"] / v["noise"]

# Figure 1: the outline unrolled (moving example)
v = moving[4]
variance, edge, step, centre = v["rays"]
fig, ax = plt.subplots(1, 3, figsize=(12, 3.9), gridspec_kw={"width_ratios": [1, 1, 1.5]})
ax[0].imshow(v["mean"], cmap="gray"); ax[0].set_title("a. mean of the frames", loc="left", fontsize=10)
ang = np.arange(N) * 2 * np.pi / N
for k in range(0, N, N // 16):
    ax[0].plot([centre[0], centre[0] + REACH * np.cos(ang[k])], [centre[1], centre[1] + REACH * np.sin(ang[k])], color="#F2C230", lw=0.6)
ax[0].plot(centre[0] + edge * step * np.cos(ang), centre[1] + edge * step * np.sin(ang), color=ORANGE, lw=1.6)
im = ax[1].imshow(v["var"] / v["noise"], cmap="Blues", vmin=0, vmax=np.percentile(v["var"] / v["noise"], 99.5))
ax[1].plot(centre[0] + edge * step * np.cos(ang), centre[1] + edge * step * np.sin(ang), color=ORANGE, lw=1.2)
ax[1].set_title("b. variance over the frames ÷ noise floor", loc="left", fontsize=10)
for a in ax[:2]:
    a.set_xticks([]); a.set_yticks([])
unrolled = (variance / v["noise"]).T
ax[2].imshow(unrolled, aspect="auto", cmap="Blues", origin="lower", extent=[0, 360, 0, unrolled.shape[0] * step],
             vmin=0, vmax=np.percentile(unrolled, 99.5))
deg = np.arange(N) * 360 / N + 360 / (2 * N)
ax[2].plot(deg, edge * step, color=ORANGE, lw=1.6, label="body edge")
ax[2].fill_between(deg, edge * step - WIDTH, edge * step + WIDTH, color=ORANGE, alpha=0.18, label=f"outline band (±{WIDTH} px)")
ax[2].set_xlabel("direction (degrees, clockwise from right)"); ax[2].set_ylabel("distance from centre (px)")
ax[2].set_title(f"c. unrolled: {N} rays × {step} px steps", loc="left", fontsize=10); ax[2].legend(loc="upper right", fontsize=8, frameon=False)
fig.colorbar(im, ax=ax[1], fraction=0.046, pad=0.03).set_label("× noise floor")
fig.tight_layout(); fig.savefig(OUT / "outline_unrolled.png", bbox_inches="tight")

# Figure 2: profile and vector sum, moving vs still
fig = plt.figure(figsize=(12, 4))
a1 = fig.add_subplot(1, 3, 1)
for (lab, ex, col, mk) in (("moving", moving, GREEN, "-"), ("still", still, ORANGE, "--")):
    a1.plot(deg, unit(ex[4]), mk, color=col, lw=2, label=f"{lab} (mite {ex[2]}, rec. {ex[3]})")
a1.set_xlabel("direction (degrees)"); a1.set_ylabel("outline variance ÷ noise floor")
a1.set_title(f"a. outline profile, {N} values", loc="left", fontsize=10); a1.legend(frameon=False, fontsize=8)
for idx, (lab, ex, col) in enumerate((("moving", moving, GREEN), ("still", still, ORANGE))):
    a = fig.add_subplot(1, 3, 2 + idx)
    p = unit(ex[4]) / N
    vec = p * np.exp(1j * ang)
    pts = np.concatenate([[0], np.cumsum(vec)])
    a.plot(pts.real, -pts.imag, color=col, lw=1.4, marker="o", ms=2)
    a.annotate("", xy=(pts[-1].real, -pts[-1].imag), xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color=INK, lw=2))
    a.set_aspect("equal"); a.plot(0, 0, "o", color=INK, ms=5)
    span = max(np.abs(pts).max(), 1e-9) * 1.15
    a.set_xlim(-span, span); a.set_ylim(-span, span)
    a.set_title(f"{'b' if idx == 0 else 'c'}. {lab}: {N} arrows tip to tail (own scale)\nscore = length of the black arrow = {abs(pts[-1]):.3f}", loc="left", fontsize=10)
    a.set_xticks([]); a.set_yticks([])
fig.tight_layout(); fig.savefig(OUT / "outline_vector_sum.png", bbox_inches="tight")
print("moving mean", unit(moving[4]).mean(), "still mean", unit(still[4]).mean())
figure_kit.show()
