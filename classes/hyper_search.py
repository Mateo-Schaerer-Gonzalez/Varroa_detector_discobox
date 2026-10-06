"""A search of the hyperparameters of the movement score and of the threshold
(Optuna, TPE) for the lowest error in the time each mite died.

The hyperparameters are the metric's own parameters, whether the plate is
stabilized, and the mite's threshold: its window, where the window lies and how
many MADs it rises by (classes/mite_threshold.py). The user chooses which are
searched; the others keep the values in use. The threshold's offset is never
searched: for any choice of the others, the best one is found exactly
(ThresholdSearch.fit()).

What a trial is judged by is the death-time error on mites its threshold never
saw: the mites are split into folds, the offset is fitted on all folds but one
and the death times of the mites of that one are compared with the labels', in
turn for every fold. The mean distance over all the mites, in minutes, is the
trial's value. Judged on the mites it was fitted on, the best of many trials
would partly be the best at fitting their noise.

SearchSpace says what can be searched and over which range; HyperSearch runs the
search and describes it for the calibration report. It can also say what a
shaking plate does to what it found (HyperSearch.shaken_error()).
"""

import threading

import numpy as np

from classes.mite_threshold import MiteThreshold, ThresholdSearch

# Names of the hyperparameters that are not the metric's own.
STABILIZE = "stabilize"
WINDOW = "threshold_window"
CENTRED = "threshold_centred"
SCALE = "threshold_scale"


class SearchSpace:
    """The hyperparameters that can be searched for one metric, each as
    {name, group ("score" or "threshold"), label, kind ("int", "float" or
    "choice"), low, high, log, step, choices}."""

    PADS = [0, 4, 8, 12]             # pixels around the mite's box that optical_flow can read
    POLY_SIGMA = {5: 1.1, 7: 1.5}    # follows poly_n, as the OpenCV docs advise

    # A mite's box holds a few hundred pixels; more than that is the whole box.
    _TOP_N = {"n": {"kind": "int", "low": 1, "high": 1000, "log": True}}
    METRICS = {
        "topN_variability": _TOP_N,
        "topN_temporal_range": _TOP_N,
        "topN_vector_temporal_range": _TOP_N,
        "topN_binary_flux": {"threshold": {"kind": "int", "low": 10, "high": 245}, **_TOP_N},
        # Farneback wants odd window sizes; `step` must stay below the frames of a recording.
        "optical_flow": {
            "pad": {"kind": "choice", "choices": PADS},
            "window": {"kind": "int", "low": 3, "high": 25, "step": 2},
            "n": {"kind": "int", "low": 5, "high": 300, "log": True},
            "step": {"kind": "int", "low": 1, "high": None},
            "winsize": {"kind": "int", "low": 5, "high": 51, "step": 2},
            "levels": {"kind": "int", "low": 1, "high": 4},
            "poly_n": {"kind": "choice", "choices": [5, 7]},
            "iterations": {"kind": "int", "low": 1, "high": 6},
        },
    }
    LABELS = {
        STABILIZE: "plate stabilization",
        WINDOW: "window of the mite's own threshold",
        CENTRED: "window centred or trailing",
        SCALE: "MADs above the median",
    }

    def __init__(self, metric, n_recordings=None, n_frames=None):
        """`n_recordings`: the longest series, the widest window; `n_frames`: the
        frames of the shortest recording. Without them those ranges are open."""
        self.metric = metric
        self.n_recordings = n_recordings
        self.n_frames = n_frames

    def specs(self):
        specs = []
        for name, spec in self.METRICS.get(self.metric, {}).items():
            spec = {"name": name, "group": "score", "label": name, **spec}
            if name == "step":
                spec["high"] = None if self.n_frames is None else max(1, self.n_frames - 1)
            specs.append(spec)
        specs += [
            {"name": STABILIZE, "group": "score", "kind": "choice", "choices": [True, False]},
            # 0: one threshold for every mite
            {"name": WINDOW, "group": "threshold", "kind": "int", "low": 0, "high": self.n_recordings, "skip": [1]},
            {"name": CENTRED, "group": "threshold", "kind": "choice", "choices": [True, False]},
            {"name": SCALE, "group": "threshold", "kind": "float", "low": 0.0, "high": 8.0, "step": 0.5},
        ]
        return [{"label": self.LABELS.get(spec["name"], spec["name"]), **spec} for spec in specs]

    def spec(self, name):
        found = [spec for spec in self.specs() if spec["name"] == name]
        if not found:
            raise ValueError(f"{name!r} cannot be searched for {self.metric}; choose among "
                             f"{', '.join(spec['name'] for spec in self.specs())}.")
        return found[0]

    @staticmethod
    def holds(spec, value):
        """Whether `value` is one the search could try."""
        if spec["kind"] == "choice":
            return value in spec["choices"]
        if not spec["low"] <= value <= spec["high"] or value in spec.get("skip", []):
            return False
        step = spec.get("step")
        return not step or abs((value - spec["low"]) / step - round((value - spec["low"]) / step)) < 1e-9

    @staticmethod
    def suggest(trial, spec):
        """Have an Optuna trial choose the hyperparameter's value."""
        name = spec["name"]
        if spec["kind"] == "choice":
            return trial.suggest_categorical(name, spec["choices"])
        if spec["kind"] == "float":
            return trial.suggest_float(name, spec["low"], spec["high"], step=spec.get("step"))
        if spec.get("skip"):
            # the window: 1 recording is no window, so the value below the range stands for the skipped one
            value = trial.suggest_int(name, spec["low"] + 1, spec["high"])
            return spec["low"] if value == spec["low"] + 1 else value
        return trial.suggest_int(name, spec["low"], spec["high"], step=spec.get("step") or 1, log=bool(spec.get("log")))

    @staticmethod
    def as_suggested(spec, value):
        """A value as suggest() has Optuna hold it."""
        return spec["low"] + 1 if spec.get("skip") and value == spec["low"] else value


class HyperSearch:
    """One search. `score(metric_params, stabilize)` gives every mite's scores
    ({mite: [score per recording]}); `observations` and `times` are
    ThresholdSearch's. `values` holds every hyperparameter's value in use (the
    metric's parameters by their names, and STABILIZE, WINDOW, CENTRED, SCALE);
    those named in `searched` are searched over `space`."""

    FOLDS = 5
    RESAMPLES = 2000     # of the mites, for the confidence intervals
    PLATEAU = 0.10       # trials within this share of the best error count as as good

    def __init__(self, space, values, searched, score, observations, times, n_trials=60, seed=0):
        self.space = space
        self.values = dict(values)
        self.specs = [space.spec(name) for name in searched]
        if not self.specs:
            raise ValueError("Choose at least one hyperparameter to search.")
        self.score = score
        self.observations = observations
        self.times = times
        self.n_trials = int(n_trials)
        if self.n_trials < 1:
            raise ValueError("The number of trials must be at least 1.")
        self.seed = seed
        self.trials = []          # every finished trial, see _trial()
        self.baseline = None      # the values in use, judged like a trial
        self.importances = None
        self._scores = {}
        self._stop = threading.Event()
        self._folds = None

    def stop(self):
        """End the search after the trial running now; what is found is kept."""
        self._stop.set()

    # --- judging one set of values

    def _series(self, values):
        """Every mite's scores with the values' metric parameters, kept so a
        trial that only changes the threshold scores nothing again."""
        metric_params = {name: value for name, value in values.items() if name not in SearchSpace.LABELS}
        if "poly_n" in metric_params and "poly_sigma" in metric_params:
            metric_params["poly_sigma"] = SearchSpace.POLY_SIGMA.get(metric_params["poly_n"], metric_params["poly_sigma"])
        key = (tuple(sorted(metric_params.items())), bool(values[STABILIZE]))
        if key not in self._scores:
            self._scores[key] = self.score(metric_params, bool(values[STABILIZE]))
        return self._scores[key], metric_params

    def _fold_of(self, search):
        """Per labelled mite, the fold it is held out in. The same for every
        trial: the mites are the same and in the same order."""
        if self._folds is None:
            n_mites = len(search.by_mite)
            if n_mites < 2:
                raise ValueError("A search needs at least two labelled mites: one to fit the threshold on and one to judge it on.")
            order = np.random.default_rng(self.seed).permutation(n_mites)
            folds = np.empty(n_mites, dtype=int)
            folds[order] = np.arange(n_mites) % min(self.FOLDS, n_mites)
            self._folds = folds
        return self._folds

    def judge(self, values):
        """How one set of values does: {value (the death-time error on held-out
        mites, minutes), errors (each mite's, signed, when it was held out),
        folds (the error of each fold), mae_all and offset (fitted on all the
        mites, what would be saved), metric_params}."""
        series, metric_params = self._series(values)
        if not all(np.isfinite(scores).all() for scores in series.values()):
            return None
        search = ThresholdSearch(series, self.observations, self.times)
        fold_of = self._fold_of(search)
        window = int(values[WINDOW])
        choice = (window, bool(values[CENTRED]), float(values[SCALE]) if window else 0.0)
        mite_number = {mite: number for number, mite in enumerate(search.by_mite)}
        fold_of_observation = np.array([fold_of[mite_number[mite]] for mite in search.mites])

        errors = np.empty(len(fold_of))
        for fold in range(fold_of.max() + 1):
            fitted = search.fit(*choice, subset=fold_of_observation != fold)
            errors[fold_of == fold] = search.death_errors(search.calls(fitted))[fold_of == fold]
        mae_all, _balance, fitted = search._fitted(*choice)
        return {
            "value": float(np.abs(errors).mean()),
            "errors": errors,
            "folds": [float(np.abs(errors[fold_of == fold]).mean()) for fold in range(fold_of.max() + 1)],
            "mae_all": mae_all,
            "offset": round(fitted.offset, 3),
            "metric_params": metric_params,
        }

    # --- the search

    def run(self):
        """Search until `n_trials` are done or stop() is called."""
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        judged = self.judge(self.values)
        if judged is None:
            raise ValueError("The values in use give scores that are not numbers, so there is nothing to compare a search with.")
        self.baseline = {"values": dict(self.values), **judged}

        study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(
            seed=self.seed, multivariate=True, n_startup_trials=max(4, min(15, self.n_trials // 4))))
        # Start from the values in use, where the search could try them.
        if all(SearchSpace.holds(spec, self.values[spec["name"]]) for spec in self.specs):
            study.enqueue_trial({spec["name"]: SearchSpace.as_suggested(spec, self.values[spec["name"]]) for spec in self.specs})

        def objective(trial):
            values = dict(self.values)
            for spec in self.specs:
                values[spec["name"]] = SearchSpace.suggest(trial, spec)
            judged = self.judge(values)
            if judged is None:
                raise optuna.TrialPruned()
            self._trial(values, judged)
            return judged["value"]

        def stop_when_asked(study, _trial):
            if self._stop.is_set():
                study.stop()

        study.optimize(objective, n_trials=self.n_trials, callbacks=[stop_when_asked])
        self.importances = self._importances(study)

    def _trial(self, values, judged):
        best = min([trial["value"] for trial in self.trials] + [judged["value"]])
        self.trials.append({"number": len(self.trials), "values": values, "best_so_far": best, **judged})

    def _importances(self, study):
        """How much of the differences between the trials each searched
        hyperparameter explains (Optuna's PED-ANOVA), summing to 1; None when
        there is too little to tell."""
        import optuna

        if len(self.specs) < 2 or len(self.trials) < 4:
            return None
        try:
            return {name: float(value) for name, value in optuna.importance.get_param_importances(
                study, evaluator=optuna.importance.PedAnovaImportanceEvaluator()).items()}
        except Exception:
            return None

    # --- what it found

    def best(self):
        """The trial with the lowest error, the first of equally good ones."""
        return min(self.trials, key=lambda trial: trial["value"]) if self.trials else None

    def shaken_error(self, judged, series):
        """The death-time error, in minutes over all the mites, of a judged set
        of values (a trial or the baseline) on other scores of the same mites,
        `series`, e.g. those of a shaking plate: its threshold stays as it was
        fitted, as one saved from a steady plate would."""
        values = judged["values"]
        window = int(values[WINDOW])
        threshold = MiteThreshold(judged["offset"], window, bool(values[CENTRED]), float(values[SCALE]) if window else 0.0)
        return ThresholdSearch(series, self.observations, self.times).mae(threshold)

    def _interval(self, values):
        """The mean of `values` (one per mite) with the 95% confidence interval
        of resampling the mites."""
        rng = np.random.default_rng(self.seed)
        means = values[rng.integers(0, len(values), (self.RESAMPLES, len(values)))].mean(axis=1)
        low, high = np.percentile(means, [2.5, 97.5])
        return {"mean": float(values.mean()), "low": float(low), "high": float(high)}

    def _plateau(self, best):
        """Per searched hyperparameter, the values of the trials about as good as
        the best (within PLATEAU of its error): a wide range says the value
        hardly matters, a narrow one that the best is a lucky spot or a sharp optimum."""
        limit = best["value"] * (1 + self.PLATEAU) + 1e-9
        good = [trial for trial in self.trials if trial["value"] <= limit]
        plateau = {}
        for spec in self.specs:
            values = [trial["values"][spec["name"]] for trial in good]
            if spec["kind"] == "choice":
                plateau[spec["name"]] = {"choices": [choice for choice in spec["choices"] if choice in values]}
            else:
                plateau[spec["name"]] = {"low": min(values), "high": max(values)}
        return {"n_trials": len(good), "within": self.PLATEAU, "values": plateau}

    def _described(self, judged, values):
        return {
            "values": {name: values[name] for name in values},
            "metric_params": judged["metric_params"],
            "stabilize": bool(values[STABILIZE]),
            "window": int(values[WINDOW]),
            "centred": bool(values[CENTRED]),
            "scale": float(values[SCALE]) if values[WINDOW] else 0.0,
            "offset": judged["offset"],
            "mae_all": round(judged["mae_all"], 3),
            "folds": [round(fold, 3) for fold in judged["folds"]],
            **{key: round(value, 3) for key, value in self._interval(np.abs(judged["errors"])).items()},
        }

    def describe(self):
        """Plain data for the report: the hyperparameters searched, every trial
        so far ({number, value, best_so_far, mae_all, values of the searched})
        and, once there is a trial, the best one and the values in use, each
        with its held-out error ("mean") and confidence interval, the error of
        each fold, and what would be saved (see _described()); "difference", the
        best's error minus that of the values in use, mite by mite; "plateau"
        and "importances"."""
        searched = [spec["name"] for spec in self.specs]
        trials = list(self.trials)
        described = {
            "metric": self.space.metric,
            "searched": self.specs,
            "n_trials": self.n_trials,
            "n_done": len(trials),
            "folds": None if self._folds is None else int(self._folds.max() + 1),
            "n_mites": None if self._folds is None else int(len(self._folds)),
            "trials": [{"number": trial["number"], "value": round(trial["value"], 4),
                        "best_so_far": round(trial["best_so_far"], 4), "mae_all": round(trial["mae_all"], 4),
                        "values": {name: trial["values"][name] for name in searched}} for trial in trials],
            "best": None, "baseline": None, "difference": None, "plateau": None, "importances": self.importances,
        }
        if self.baseline is not None:
            described["baseline"] = self._described(self.baseline, self.baseline["values"])
        if trials:
            best = min(trials, key=lambda trial: trial["value"])
            described["best"] = {"number": best["number"], **self._described(best, best["values"])}
            described["plateau"] = self._plateau(best)
            if self.baseline is not None:
                difference = np.abs(best["errors"]) - np.abs(self.baseline["errors"])
                described["difference"] = {key: round(value, 3) for key, value in self._interval(difference).items()}
        return described
