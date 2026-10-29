"""Figure for report/2_how_it_works.md: still recordings' score before and after
dividing by the noise floor, per dataset (from results/scripts/noise_floor.csv.gz)."""
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
import pandas as pd

import figure_kit

ROOT, OUT = figure_kit.REPO, figure_kit.out_dir()
d = pd.read_csv(figure_kit.needs(ROOT / "results/scripts/noise_floor.csv.gz", "../../scripts/noise_floor.py"), dtype={"mite": str})
d = d[(d.noise > 0) | (d.raw > 0)]
labelled = d.labelled.isna() | (d.labelled == True)  # noqa: E712
still = d[labelled & (d.moving == False)]  # noqa: E712

ORDER = [("sample_data", "sample_data\n30 frames"),
         ("ground_truth_60min", "GT 60 min\n30 frames"),
         ("ground_truth_90min", "GT 90 min\n30 frames"),
         ("poke_test_oct", "poke run\n90 frames"),
         ("test_run_2026-09-08_Mathis_last_dsRNA", "long run\n10 frames")]
per_mite = still.groupby(["dataset", "mite"])[["noise", "raw", "score"]].median()

plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": "#bbbbbb", "xtick.color": "#666666", "ytick.color": "#666666"})
fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
PANELS = [("noise", "a. noise floor $\\sigma^2$", "grey levels²", False),
          ("raw", "b. still score before dividing", "grey levels²", True),
          ("score", "c. still score after dividing (in use)", "multiples of the noise floor", True)]
rng = np.random.default_rng(0)
for ax, (col, title, unit, log) in zip(axes, PANELS):
    for i, (name, _) in enumerate(ORDER):
        v = per_mite.loc[name, col].to_numpy()
        colour = "#d95f02" if name != ORDER[-1][0] else "#9a9a9a"
        ax.scatter(i + rng.uniform(-0.18, 0.18, len(v)), v, s=14, color=colour, alpha=0.75, lw=0)
        med = still.loc[still.dataset == name, col].median()
        ax.plot([i - 0.3, i + 0.3], [med, med], color="#222222", lw=2)
        ax.annotate(f"{med:.3g}", (i + 0.32, med), va="center", fontsize=8.5, color="#222222")
    ax.set_xticks(range(len(ORDER)), [label for _, label in ORDER], fontsize=8.5)
    ax.set_xlim(-0.5, len(ORDER) - 0.3)
    if log:
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"{y:g}"))
        ax.yaxis.set_minor_locator(matplotlib.ticker.LogLocator(subs=(2, 5)))
        ax.yaxis.set_minor_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"{y:g}"))
    ax.set_ylabel(unit)
    ax.set_title(title, loc="left")
fig.text(0.01, 0.005, "Each dot: one mite's median over its still recordings. Black bar: median of all the "
         "dataset's still recordings. Grey: the long run, 10 frames per recording.", fontsize=8.5, color="#666666")
plt.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(OUT / "still_noise_floor.png", dpi=120)
figure_kit.show()
