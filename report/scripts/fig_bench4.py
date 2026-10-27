import json, sys
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
H = Path(__file__).parent; OUT = Path(sys.argv[1])
APP, ABIL, INK, MUTED = "#1F8A5B", "#5B6CC2", "#222222", "#777777"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": "#BBBBBB", "xtick.color": MUTED, "ytick.color": MUTED,
                     "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 130})
B = json.load(open(H / "bench_fixed.json")); TH = B["long run"]["threshold"]
groups = ["2025 sessions", "GT_oct_2", "long run"]
fmt = {"2025 sessions": "1 s, 30 fps", "GT_oct_2": "1 s, 10 fps", "poke run": "3 s, 30 fps", "long run": "10 frames"}
lab = [f"{g}\n{fmt[g]}\n{B[g]['n']:,} obs." for g in groups]
fig, ax = plt.subplots(1, 2, figsize=(12, 4))
x = np.arange(3); w = 0.36
for a, key, den, title in ((ax[0], "still_called_moving", "still", "a. still recordings called moving (% of still)"),
                           (ax[1], "moving_called_still", "moving", "b. moving recordings called still (% of moving)")):
    for j, (name, k, col) in enumerate(((f"app at {TH:.3f} (tuned on the poke run)", "app", APP), ("Discobox original (25)", "original", ABIL))):
        n = [B[g][k][key] for g in groups]; pct = [100 * v / B[g][den] for v, g in zip(n, groups)]
        bars = a.bar(x + (j - 0.5) * w, pct, w - 0.04, color=col, label=name)
        for b_, p, v in zip(bars, pct, n):
            a.text(b_.get_x() + b_.get_width() / 2, p + 0.25, f"{int(v)}", ha="center", fontsize=8, color=INK)
    a.set_xticks(x); a.set_xticklabels(lab, fontsize=8); a.set_title(title, loc="left", fontsize=10); a.set_ylabel("%")
ax[0].legend(frameon=False, fontsize=8, loc="upper left")
fig.text(0.01, -0.03, "Bar labels: number of recordings.", fontsize=8, color=MUTED)
fig.tight_layout(); fig.savefig(OUT / "benchmark_bars.png", bbox_inches="tight"); plt.close(fig)

# PR curves
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
names = {"2025 sessions": ["sample_data", "ground_truth_60min", "ground_truth_90min"], "GT_oct_2": ["GT_oct_2"],
         "poke run": ["poke_test_oct"], "long run": ["long_run"]}
fig, ax = plt.subplots(1, 3, figsize=(10.5, 3.6), sharey=True)
for a, g in zip(ax, groups):
    rows = [r for n in names[g] for r in json.load(open(H / "eval" / f"{n}.json"))["rows"]]
    s = np.array([r["score"] for r in rows]); m = np.array([r["movement"] == "moving" for r in rows])
    th = np.unique(s)[::-1]; srt = np.sort(s[m]); allsrt = np.sort(s)
    tp = len(srt) - np.searchsorted(srt, th); called = len(allsrt) - np.searchsorted(allsrt, th)
    a.step(tp / m.sum(), tp / called, where="post", color=APP, lw=2, label=f"app (AP {B[g]['ap']:.3f})")
    a.plot(B[g]["app"]["sensitivity"], B[g]["app"]["precision"], "s", color=APP, ms=7, mfc="white", label=f"app at {TH:.3f}")
    a.plot(B[g]["original"]["sensitivity"], B[g]["original"]["precision"], "D", color=ABIL, ms=8, label="original (25)")
    a.set_title(f"{g}, {fmt[g]}", loc="left", fontsize=9); a.set_xlabel("recall"); a.set_xlim(0, 1.03); a.set_ylim(0, 1.03)
    a.legend(frameon=False, fontsize=7.5, loc="lower left")
ax[0].set_ylabel("precision")
fig.tight_layout(); fig.savefig(OUT / "benchmark_pr.png", bbox_inches="tight"); plt.close(fig)

# long run: still called moving by shake
d = pd.DataFrame(json.load(open(H / "eval" / "long_run.json"))["rows"]); st = d[d.movement == "still"].copy()
sh = pd.read_csv(Path(__file__).resolve().parents[2] / "results" / "scripts" / "shaky_recordings.csv.gz")
shake = sh[sh.dataset.str.startswith("test_run")].groupby("recording")["shake"].median()
st["shake"] = st.recording.map(shake)
bins = [0, .05, .1, .15, .2, .25]
st["bin"] = pd.cut(st.shake, bins)
t = st.groupby("bin", observed=False).agg(n=("score", "size"), orig=("benchmark_call", lambda c: (c == "moving").mean() * 100),
                                          app=("score", lambda c: (c >= B["long run"]["threshold"]).mean() * 100))
fig, a = plt.subplots(figsize=(8, 3.6)); x = np.arange(len(t))
a.bar(x - 0.19, t.app, 0.34, color=APP, label=f"app at {TH:.3f} (tuned on the poke run)"); a.bar(x + 0.19, t.orig, 0.34, color=ABIL, label="Discobox original (25)")
for i, (p1, p2) in enumerate(zip(t.app, t.orig)):
    a.text(i - 0.19, p1 + 0.6, f"{p1:.1f}", ha="center", fontsize=8); a.text(i + 0.19, p2 + 0.6, f"{p2:.1f}", ha="center", fontsize=8)
a.set_xticks(x); a.set_xticklabels([f"{b.left:.2f}–{b.right:.2f} px\n{n:,} rec." for b, n in zip(t.index, t.n)], fontsize=8)
a.set_ylabel("% of still recordings called moving"); a.set_xlabel("plate shake within the recording (median over the mites)")
a.legend(frameon=False, fontsize=8, loc="upper left"); a.set_title("Long run: still recordings called moving, by shake", loc="left", fontsize=10)
fig.tight_layout(); fig.savefig(OUT / "benchmark_shake.png", bbox_inches="tight"); plt.close(fig)
print(t)
