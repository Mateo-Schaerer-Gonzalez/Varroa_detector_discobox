// The hyperparameter search of the calibration report: the user ticks which
// hyperparameters of the movement score and of the threshold to search, the
// server searches them for the lowest death-time error on mites the threshold
// never saw (classes/hyper_search.py), and this shows how far it is and what it
// found: the best against the values in use, how sure that is, how much each
// hyperparameter matters, and what a shaking plate does to it. Every number is
// the server's.

class SearchPanel {
  static POLL_MS = 1000;

  constructor() {
    this.spaces = {};     // metric -> what can be searched for it (the server's)
    this.status = null;   // the session's search, as the server describes it
    this.chosen = null;   // names ticked, kept while the report is redrawn
    this.trials = null;
    this.shake = true;    // try what is found on a shaking plate afterwards
    this.note = "";       // what the last save did, shown once the report is drawn again
    this.timer = null;
  }

  static html() {
    return `<div id="search-panel"><p class="hint"><span class="spinner"></span> Loading…</p></div>`;
  }

  // A hyperparameter's value as the page words it.
  static valueText(name, value) {
    if (value == null) return "–";
    if (name === "stabilize") return value ? "on" : "off";
    if (name === "threshold_centred") return value ? "centred" : "trailing";
    if (name === "threshold_window") return value ? `${value} recordings` : "none";
    return Number.isInteger(value) ? `${value}` : `${+Number(value).toFixed(2)}`;
  }

  // The range a hyperparameter is searched over.
  static rangeText(spec) {
    const { valueText } = SearchPanel;
    if (spec.kind === "choice") return spec.choices.map((choice) => valueText(spec.name, choice)).join(" or ");
    if (spec.name === "threshold_window") return `none, or 2 up to ${spec.high ?? "all the"} recordings`;
    return `${spec.low} to ${spec.high ?? "the frames of a recording"}${spec.step && spec.step !== 1 ? `, in steps of ${spec.step}` : ""}`;
  }

  static mins(value) {
    return value == null ? "–" : `${value.toFixed(2)} min`;
  }

  running() {
    return ["loading", "searching", "shaking"].includes(this.status?.state);
  }

  // Called each time the report is drawn: ask what can be searched and whether
  // the session has a search, then draw and follow it while it runs.
  async mount(r) {
    clearTimeout(this.timer);
    this.report = r;
    try {
      this.spaces[r.metric] ??= await getJson(`/api/calibration/search-space?metric=${encodeURIComponent(r.metric)}`, "Could not list the hyperparameters");
      this.status = await getJson(`/api/calibration/${cal.id}/search`);
    } catch (error) {
      if ($("search-panel")) $("search-panel").innerHTML = `<p class="hint error">${esc(error.message)}</p>`;
      return;
    }
    this.draw();
    if (this.running()) this.follow();
  }

  follow() {
    clearTimeout(this.timer);
    this.timer = setTimeout(async () => {
      if (!$("search-panel")) return;  // the report is gone
      try {
        this.status = await getJson(`/api/calibration/${cal.id}/search`);
      } catch (error) {
        return;
      }
      this.draw();
      if (this.running()) this.follow();
    }, SearchPanel.POLL_MS);
  }

  draw() {
    const panel = $("search-panel");
    if (!panel) return;
    const r = this.report;
    const space = this.spaces[r.metric];
    const s = this.status;
    const busy = this.running();
    // By default everything but the plate stabilization, which reads every recording twice.
    this.chosen ??= new Set(space.hyperparameters.filter((spec) => spec.name !== "stabilize").map((spec) => spec.name));
    this.trials ??= space.default_trials;
    const boxes = (group) => space.hyperparameters.filter((spec) => spec.group === group).map((spec) => `
      <label class="param" title="Searched over: ${esc(SearchPanel.rangeText(spec))}">
        <input type="checkbox" class="search-check" value="${esc(spec.name)}" ${this.chosen.has(spec.name) ? "checked" : ""} ${busy ? "disabled" : ""}>
        ${esc(spec.label)}</label>`).join("");

    panel.innerHTML = `
    <p class="hint">Tick what to search. Each trial scores the labelled mites with one set of values, fits the threshold's offset on part of the mites
      and judges it by the <b>death-time error on the mites left out</b>, so a set of values cannot win by fitting these mites' noise.
      Whatever is not ticked keeps its value: the movement score shown above, and the threshold in config.yaml for that metric.</p>
    <div class="row score-picker"><b>Movement score</b> ${boxes("score")}</div>
    <div class="row score-picker"><b>Threshold</b> ${boxes("threshold")}
      <span class="hint">the offset is always fitted</span></div>
    <div class="row score-picker">
      <label class="param">Trials <input type="number" id="search-trials" min="1" max="${space.max_trials}" step="1" value="${this.trials}" ${busy ? "disabled" : ""}></label>
      <label class="param" title="Afterwards, shake the plate in the recordings by a fraction of a pixel and see how much worse the best values and those in use get, with and without plate stabilization. Reads every recording again, four times.">
        <input type="checkbox" id="search-shake" ${this.shake ? "checked" : ""} ${busy ? "disabled" : ""}> then shake the plate</label>
      ${busy ? `<button type="button" id="search-stop" class="small secondary">Stop</button>`
        : `<button type="button" id="search-start" class="small">Search</button>`}
    </div>
    <p id="search-status" class="hint">${this.progressText()}</p>
    ${s?.best ? this.result(s) : ""}`;

    panel.querySelectorAll(".search-check").forEach((check) => check.addEventListener("change", () => {
      if (check.checked) this.chosen.add(check.value); else this.chosen.delete(check.value);
    }));
    $("search-trials").addEventListener("change", (event) => { this.trials = Number(event.target.value); });
    $("search-shake").addEventListener("change", (event) => { this.shake = event.target.checked; });
    $("search-start")?.addEventListener("click", () => this.start());
    $("search-stop")?.addEventListener("click", () => this.stop());
    if (s?.best) this.wireResult(s);
  }

  progressText() {
    const s = this.status;
    const { mins } = SearchPanel;
    if (!s || s.state === "none") return "No search yet in this session.";
    if (s.state === "error") return `<span class="error">The search failed: ${esc(s.error)}</span>`;
    if (s.state === "loading") return `<span class="spinner"></span> Reading the mites' frames into memory… ${s.loaded} of ${s.to_load || "?"} recordings.`;
    const best = s.best ? ` · best so far ${mins(s.best.mean)}` : "";
    if (s.state === "searching") return `<span class="spinner"></span> Trial ${Math.min(s.n_done + 1, s.n_trials)} of ${s.n_trials}${best}.`;
    if (s.state === "shaking") return `<span class="spinner"></span> Shaking the plate and scoring again… ${s.shaken} of ${s.to_shake || "?"} recordings.`;
    return `${s.state === "stopped" ? "Stopped" : "Done"} after ${s.n_done ?? 0} trials on <code>${esc(s.metric)}</code>.`;
  }

  async start() {
    const r = this.report;
    const status = $("search-status");
    if (!this.chosen.size) {
      status.className = "hint error";
      status.textContent = "Tick at least one hyperparameter.";
      return;
    }
    this.note = "";
    try {
      this.status = await post(`/api/calibration/${cal.id}/search`, {
        datasets: cal.selected, metric: r.metric, params: r.metric_params, stabilize: r.stabilize_plate,
        searched: [...this.chosen], trials: this.trials, shake_test: this.shake,
      });
      this.draw();
      this.follow();
    } catch (error) {
      status.className = "hint error";
      status.textContent = error.message;
    }
  }

  async stop() {
    try {
      this.status = await post(`/api/calibration/${cal.id}/search/stop`);
      this.draw();
      if (this.running()) this.follow();
    } catch (error) {
      $("search-status").className = "hint error";
      $("search-status").textContent = error.message;
    }
  }

  // --- what the search found

  result(s) {
    const { mins, valueText } = SearchPanel;
    const { stat, figure } = Markup;
    const { best, baseline, difference, plateau } = s;
    const interval = (d) => `95% interval ${mins(d.low)} to ${mins(d.high)}`;
    const sure = difference.high < 0 ? "lower than in use beyond the chance of which mites were labelled"
      : difference.mean < 0 ? "lower than in use, but within what the choice of mites alone could give" : "no better than in use";
    const rows = s.searched.map((spec) => {
      const about = plateau.values[spec.name];
      const aboutText = about.choices ? about.choices.map((choice) => valueText(spec.name, choice)).join(", ")
        : about.low === about.high ? valueText(spec.name, about.low) : `${valueText(spec.name, about.low)} to ${valueText(spec.name, about.high)}`;
      const importance = s.importances?.[spec.name];
      return `<tr><td>${esc(spec.label)}</td>
        <td class="num">${valueText(spec.name, baseline.values[spec.name])}</td>
        <td class="num"><b>${valueText(spec.name, best.values[spec.name])}</b></td>
        <td class="num">${aboutText}</td>
        <td class="num">${importance == null ? "–" : pct(importance)}</td></tr>`;
    }).join("");
    const folds = (d) => d.folds.map((fold) => fold.toFixed(1)).join(", ");

    return `
    <div class="stats">
      ${stat("Best held-out death-time error", mins(best.mean), `${interval(best)} · trial ${best.number + 1} of ${s.n_done}`)}
      ${stat("With the values in use", mins(baseline.mean), interval(baseline))}
      ${stat("Best minus in use", mins(difference.mean), `${interval(difference)} · ${sure}`)}
      ${stat("Trials about as good", `${plateau.n_trials} of ${s.n_done}`, `within ${pct(plateau.within)} of the best error`)}
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Hyperparameter</th><th class="num">In use</th><th class="num">Best</th>
        <th class="num">About as good</th><th class="num">Importance</th></tr></thead>
      <tbody>${rows}
        <tr><td>offset <span class="muted">fitted on all the mites</span></td><td class="num">${baseline.offset.toFixed(2)}</td>
          <td class="num"><b>${best.offset.toFixed(2)}</b></td><td class="num"></td><td class="num"></td></tr>
      </tbody>
    </table></div>
    <p class="caption">Errors are the mean distance, over the ${s.n_mites} labelled mites, between the death time by the detector's calls and by the ground truth,
      each mite judged by a threshold fitted on the other ${s.folds - 1} of ${s.folds} parts of the mites. The intervals come from drawing the mites again at random:
      when the interval of <b>best minus in use</b> reaches 0, other mites could as well have favoured the values in use.
      <b>About as good</b>: the values of the trials within ${pct(plateau.within)} of the best error; a wide range says the value hardly matters, a single value among many trials that the optimum is sharp.
      <b>Importance</b>: the share of the differences between the trials that each hyperparameter explains.
      Error of each part of the mites, best: ${folds(best)} min; in use: ${folds(baseline)} min. Fitted and judged on all the mites, the best gives ${mins(best.mae_all)}, in use ${mins(baseline.mae_all)}.</p>
    <div class="row">
      <button type="button" id="search-use" class="small" ${this.running() ? "disabled" : ""}>Score the report with the best</button>
      <button type="button" id="search-save" class="small secondary" ${this.running() ? "disabled" : ""}>Save the best to config.yaml</button>
      <span id="search-action" class="hint">${esc(this.note)}</span>
    </div>
    <div class="grid-2">
      ${figure("search-history", "S1", "The search, trial by trial",
        "Each trial's held-out death-time error, and the best so far. A line that went flat long before the end says more trials would find little.")}
      ${s.searched.map((spec, index) => figure(`search-slice-${index}`, `S${index + 2}`, `Error by ${esc(spec.label)}`,
        `Every trial at its value of this hyperparameter; the other hyperparameters differ between the trials too. The dashed line is the value in use, the large point the best trial.`)).join("")}
    </div>
    ${s.shake_test ? this.shakeResult(s) : ""}`;
  }

  // The lines of the shake test: the best trial and, when they differ, the values
  // in use, each cut following the plate and not.
  static shakeLines(s) {
    const colors = { best: token("--series-2"), baseline: token("--ink") };
    const names = { best: "best", baseline: "in use" };
    return s.shake_test.rows.map((row) => ({
      ...row,
      name: `${names[row.config]}, ${row.stabilize ? "plate stabilized" : "not stabilized"}${row.chosen ? "" : " (not as chosen)"}`,
      color: colors[row.config], dashed: !row.stabilize,
    }));
  }

  // What a shaking plate does to what the search found (the server's, _shake_test).
  shakeResult(s) {
    const { mins } = SearchPanel;
    const { shakes } = s.shake_test;
    const lines = SearchPanel.shakeLines(s);
    const worse = (row, i) => (i ? ` <span class="muted">+${(row.mae[i] - row.mae[0]).toFixed(2)}</span>` : "");
    const chosen = lines.find((row) => row.config === "best" && row.chosen);
    const other = lines.find((row) => row.config === "best" && !row.chosen);
    const last = shakes.length - 1;
    return `
    <h3>On a shaking plate</h3>
    <div class="table-wrap"><table>
      <thead><tr><th>Death-time error</th>${shakes.map((shake) => `<th class="num">${shake ? `shaken by ${shake} px` : "as recorded"}</th>`).join("")}</tr></thead>
      <tbody>${lines.map((row) => `<tr><td>${row.chosen ? `<b>${esc(row.name)}</b>` : esc(row.name)}</td>
        ${row.mae.map((mae, i) => `<td class="num">${mins(mae)}${worse(row, i)}</td>`).join("")}</tr>`).join("")}</tbody>
    </table></div>
    <p class="caption">The plate is shaken in the recordings themselves: every frame is moved by a random offset, the same for the whole plate,
      with the given standard deviation along x and y. The mites are scored again and called at the threshold as it was fitted on the plate as recorded,
      as a threshold saved from a steady plate would be; the error is over all ${s.n_mites} labelled mites, and the grey number is how much it grew.
      With the best values, a shake of ${shakes[last]} px takes the error from ${mins(chosen.mae[0])} to ${mins(chosen.mae[last])}
      ${chosen.stabilize ? "with the plate stabilized" : "without stabilization"}, and to ${mins(other.mae[last])} ${other.stabilize ? "with it stabilized" : "without stabilization"}.</p>
    ${Markup.figure("search-shake-chart", `S${s.searched.length + 2}`, "Death-time error on a shaking plate",
      "The same numbers: solid lines with the plate stabilized, dashed without. A flat line is a detector the shake does not reach.")}`;
  }

  wireResult(s) {
    const { mins, valueText } = SearchPanel;
    const tip = (trial) => `<div class="tip-title">Trial ${trial.number + 1}: ${mins(trial.value)}</div>
      ${s.searched.map((spec) => `<div class="tip-note">${esc(spec.label)}: ${valueText(spec.name, trial.values[spec.name])}</div>`).join("")}
      <div class="tip-note">fitted and judged on all the mites: ${mins(trial.mae_all)}</div>`;
    const isBest = (trial) => trial.number === s.best.number;
    const point = (trial, x) => ({
      x, y: trial.value, r: isBest(trial) ? 6 : 3, color: token(isBest(trial) ? "--series-2" : "--ink"),
      label: isBest(trial) ? "best" : undefined, tip: tip(trial),
    });

    Charts.scatter($("search-history"), {
      height: 280, yMin: 0,
      xLabel: "Trial", yLabel: "Held-out death-time error (min)",
      xFormat: (v) => (Number.isInteger(v) ? `${v}` : ""),
      lines: [{ points: s.trials.map((trial) => [trial.number + 1, trial.best_so_far]), color: token("--series-2"), width: 2 }],
      points: s.trials.map((trial) => point(trial, trial.number + 1)),
      legend: [{ name: "trial", color: token("--ink"), shape: "circle" }, { name: "best so far", color: token("--series-2"), shape: "line" }],
    });

    s.searched.forEach((spec, index) => {
      // a choice is drawn at its place in the list of choices
      const place = (value) => (spec.kind === "choice" ? spec.choices.indexOf(value) : value);
      Charts.scatter($(`search-slice-${index}`), {
        height: 240, yMin: 0,
        xLabel: spec.label, yLabel: "Held-out error (min)",
        ...(spec.kind === "choice" ? {
          xMin: -0.5, xMax: spec.choices.length - 0.5,
          xFormat: (v) => (Number.isInteger(v) && spec.choices[v] !== undefined ? valueText(spec.name, spec.choices[v]) : ""),
        } : { xFormat: (v) => (spec.kind === "int" && !Number.isInteger(v) ? "" : `${v}`) }),
        points: s.trials.map((trial) => point(trial, place(trial.values[spec.name]))),
        refX: [{ value: place(s.baseline.values[spec.name]), label: "in use" }],
      });
    });

    if (s.shake_test) {
      const lines = SearchPanel.shakeLines(s);
      Charts.scatter($("search-shake-chart"), {
        height: 280, yMin: 0,
        xLabel: "Plate shake (px, standard deviation per frame)", yLabel: "Death-time error (min)",
        lines: lines.map((row) => ({ points: s.shake_test.shakes.map((shake, i) => [shake, row.mae[i]]), color: row.color, width: 2, dashed: row.dashed })),
        points: lines.flatMap((row) => s.shake_test.shakes.map((shake, i) => ({
          x: shake, y: row.mae[i], r: 3.5, color: row.color,
          tip: `<div class="tip-title">${esc(row.name)}</div><div>shaken by ${shake} px: ${mins(row.mae[i])}</div>`,
        }))),
        legend: lines.map((row) => ({ name: row.name, color: row.color, ...(row.dashed ? { dashed: true } : { shape: "line" }) })),
      });
    }

    $("search-use").addEventListener("click", () => this.useBest(s));
    $("search-save").addEventListener("click", () => this.saveBest(s));
  }

  // Score the report with the best trial's movement score; its threshold is the
  // report's to suggest and save.
  useBest(s) {
    const before = cal.metric;
    cal.metric = { name: s.metric, params: s.best.metric_params, stabilize: s.best.stabilize };
    cal.reportAgain("search-action", () => { cal.metric = before; });
  }

  // Save the best trial's movement score and threshold for every analysis from now on.
  async saveBest(s) {
    const status = $("search-action");
    const { best } = s;
    try {
      const saved = await post("/api/movement-score", {
        metric: s.metric, params: best.metric_params, threshold: best.offset, stabilize: best.stabilize,
        window: best.window, centred: best.centred, scale: best.scale,
      });
      this.note = `Saved ${ReportPage.scoreText(saved.metric, saved.params, saved.stabilize_plate)} with threshold ${ReportPage.thresholdText(saved)} to config.yaml. Analyses started from now on use them.`;
      // The report again, with what was just saved as the values in use.
      const before = cal.metric;
      cal.metric = null;
      await cal.reportAgain("search-action", () => { cal.metric = before; });
    } catch (error) {
      status.className = "hint error";
      status.textContent = error.message;
    }
  }
}
