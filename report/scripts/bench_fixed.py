"""The app at its default threshold against the original software, per dataset group and pooled, scored by
the F-score calibration chooses on (calibration.F_BETA: F0.25 since 2026-10-29; the key is still "f05").
Writes bench_fixed.json."""
import json, sys
from pathlib import Path
import numpy as np
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from classes.ground_truth import calibration as cal
E = Path(__file__).parent / "eval"
GROUPS = {"2025 sessions": ["sample_data", "ground_truth_60min", "ground_truth_90min"], "GT_oct_2": ["GT_oct_2"],
          "poke run": ["poke_test_oct"], "long run": ["long_run"]}
rng = np.random.default_rng(0)
KEYS = ("accuracy", "precision", "sensitivity", "f05", "still_called_moving", "moving_called_still")

def counts(called, m):
    c = cal.calls_confusion(list(called), m)
    return {k: c[k] for k in KEYS}

def held_out(rows, s, m, splits=200):
    """Threshold fitted on a random half of the mites, calls made on the other half; both halves, summed."""
    mites = np.array([f'{r["dataset"]}|{r["mite_id"]}' for r in rows]); ids = np.unique(mites)
    totals = []
    for _ in range(splits):
        half = set(rng.choice(ids, len(ids) // 2, replace=False)); a = np.array([x in half for x in mites])
        called = np.zeros(len(rows), bool)
        for fit, test in ((a, ~a), (~a, a)):
            if not cal.has_both_classes(m[fit]): continue
            called[test] = s[test] >= cal.best_f05_threshold(s[fit], m[fit])
        c = cal.calls_confusion(list(called), m)
        totals.append([c["still_called_moving"], c["moving_called_still"], c["accuracy"], c["f05"]])
    t = np.array(totals, float)
    return {"still_called_moving": t[:, 0].mean(), "moving_called_still": t[:, 1].mean(), "accuracy": t[:, 2].mean(),
            "f05": t[:, 3].mean(), "f05_range": np.percentile(t[:, 3], [5, 95]).tolist()}

def boot_diff(rows, app_called, abil_called, m, n=2000):
    """95% interval of (app F-score - original F-score), resampling mites."""
    mites = np.array([f'{r["dataset"]}|{r["mite_id"]}' for r in rows]); ids = np.unique(mites)
    where = {i: np.flatnonzero(mites == i) for i in ids}; out = []
    for _ in range(n):
        idx = np.concatenate([where[i] for i in rng.choice(ids, len(ids))])
        mm = m[idx]
        if not cal.has_both_classes(mm): continue
        out.append(cal.calls_confusion(list(app_called[idx]), mm)["f05"] - cal.calls_confusion(list(abil_called[idx]), mm)["f05"])
    return np.percentile(out, [2.5, 50, 97.5]).tolist()

poke = json.load(open(E / 'poke_test_oct.json'))['rows']
T_poke = cal.best_f05_threshold(np.array([r['score'] for r in poke]), np.array([r['movement'] == 'moving' for r in poke]))
# the app's default threshold (config.default.yaml), the poke run's best by F0.5 and F0.25 alike
T = float(yaml.safe_load(open(Path(__file__).resolve().parents[2] / "config.default.yaml"))["mite"]["metric_thresholds"]["outline_variability"])
F = f"F{cal.F_BETA:g}"
print("threshold:", T, "· the poke run's own best", F, round(T_poke, 4))
res = {}
allrows = []
for g, names in list(GROUPS.items()) + [("all four, pooled", None)]:
    rows = allrows if names is None else [r for n in names for r in json.load(open(E / f"{n}.json"))["rows"]]
    if names is not None: allrows += rows
    s = np.array([r["score"] for r in rows]); m = np.array([r["movement"] == "moving" for r in rows])
    if "benchmark_call" not in rows[0]: print("no benchmark for", g); continue
    t = T
    app = s >= t; abil = np.array([r["benchmark_call"] == "moving" for r in rows])
    deaths = cal.death_errors(rows, {"app": t}, {"original": "benchmark_call"})
    res[g] = {"n": len(rows), "moving": int(m.sum()), "still": int((~m).sum()),
              "mites": len({(r["dataset"], r["mite_id"]) for r in rows}), "threshold": t,
              "ap": cal.average_precision(s, m), "app": counts(app, m), "original": counts(abil, m),
              "f05_diff_ci": boot_diff(rows, app, abil, m),
              "deaths": {k: {kk: v[kk] for kk in ("mae", "n_exact", "n_mites", "n_early", "n_late")} for k, v in deaths.items()}}
    r_ = res[g]
    print(f"== {g}: {r_['n']} obs ({r_['moving']}/{r_['still']}), {r_['mites']} mites, threshold {t:.3f}, AP {r_['ap']:.4f}")
    for k in ("app", "original"): print("  ", k, {a: round(b, 3) for a, b in r_[k].items()})
    print(f"   {F} app - original, 95%:", [round(x, 3) for x in r_["f05_diff_ci"]])
    print("   deaths", r_["deaths"])
json.dump(res, open(Path(__file__).parent / "bench_fixed.json", "w"), default=float)
