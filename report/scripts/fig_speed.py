import json, sys
from pathlib import Path
import numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
H = Path(__file__).parent; OUT = Path(sys.argv[1])
APP, ABIL, INK, MUTED = "#1F8A5B", "#5B6CC2", "#222222", "#777777"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": "#BBBBBB", "xtick.color": MUTED, "ytick.color": MUTED,
                     "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 130})
r = [json.loads(l) for l in open(H / "speed.jsonl")]
get = lambda w, t: next(x for x in r if x["which"] == w and x["threads"] == t)
fig, ax = plt.subplots(1, 3, figsize=(13, 4))
def bars(a, labels, app, orig, unit, title, log=False, fmt="{:.2f}"):
    x = np.arange(len(labels)); w = 0.36
    for j, (vals, col, name) in enumerate(((app, APP, "app"), (orig, ABIL, "Discobox original"))):
        b = a.bar(x + (j - 0.5) * w, vals, w - 0.04, color=col, label=name)
        for bb, v in zip(b, vals): a.text(bb.get_x() + bb.get_width() / 2, v * (1.15 if log else 1.02), (f"{v:.0f}" if v >= 10 else fmt.format(v)), ha="center", fontsize=8)
    if log: a.set_yscale("log")
    a.set_xticks(x); a.set_xticklabels(labels, fontsize=8.5); a.set_ylabel(unit); a.set_title(title, loc="left", fontsize=10)
bars(ax[0], ["all cores\n(as shipped)", "one core"], [get("app", "shipped")["90_wall"], get("app", "1")["90_wall"]],
     [get("original", "shipped")["90_wall"], get("original", "1")["90_wall"]], "seconds (log scale)",
     "a. time to analyse one 90-frame recording", log=True, fmt="{:.2g}")
ax[0].legend(frameon=False, fontsize=8, loc="center left")
bars(ax[1], ["frames of the recording\n(both hold them)", "extra while analysing"], [287, 103], [287, 380], "MB",
     "b. memory for one 90-frame recording", fmt="{:.0f}")
runs = ["sample_data\n6 rec.\n× 30 frames", "long run\n295 rec.\n× 10 frames", "poke run\n95 rec.\n× 90 frames", "48 h live*\n288 rec.\n× 90 frames"]
app_mb = [16.4 + 1.6, 501.7 + 1.6, 284.9 + 1.6, 60 * 288 * 0.272 + 1.6]
bmp_mb = [574, 9404, 27256, 288 * 90 * 3.188]
bars(ax[2], runs, [v / 1000 for v in app_mb], [v / 1000 for v in bmp_mb], "GB (log scale)", "c. storage of a whole run", log=True, fmt="{:.2g}")
ax[2].tick_params(axis="x", labelsize=7.5)
fig.text(0.01, -0.03, "* 60 mites, every 10 min, if none died (dead mites stop being saved). Laptop: Intel Core Ultra 7 155H, 22 logical processors; sample_data, 30 mites.", fontsize=8, color=MUTED)
fig.tight_layout(); fig.savefig(OUT / "speed_memory_storage.png", bbox_inches="tight")
print("ok")
