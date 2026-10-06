// The calibration or test report. Each (mite, recording) labelled moving or still
// is compared with the detector's call: moving when that recording's score reaches
// the mite's threshold, its own (an offset above the moving median of its scores
// over a window of recordings, plus a number of their median absolute deviations)
// or the one of every mite. A threshold is judged by the time each mite died by
// its calls against the time by the labels. The numbers are the server's
// (evaluate_calibration); this draws them, with pickers for the datasets pooled
// and the movement score.

class ReportPage {
  static CONFUSION_CAPTION =
    "The ground truth against the detector's call, which is moving when that recording's score reaches the mite's threshold. One count per mite-recording; percentages are of each row.";

  // The strip is drawn by the scores themselves while every threshold shown is the
  // same for all mites, else by how far each score is above its mite's own.
  static stripCaption(marks) {
    return marks.some((mark) => mark.call.window)
      ? `Each labelled mite-recording by how far its motion score is above its mite's own threshold (${esc(marks[marks.length - 1].name)}). Everything right of the line is called moving. Select a point to see that mite.`
      : "Each labelled mite-recording at its motion score. Everything right of a line is called moving at that threshold. Select a point to see that mite.";
  }

  constructor() {
    this.figures = new ReportFigures();
    this.search = new SearchPanel();
  }

  static thr(value) {
    return Number(value).toFixed(2);
  }

  // How a mite is called moving: at one threshold for every mite or, with a window,
  // at its own, an offset above the moving median of its scores over that many
  // recordings plus `scale` MADs of them (classes/mite_threshold.py). `t` has
  // window, centred, scale and offset (or threshold).
  static thresholdText(t) {
    const offset = ReportPage.thr(t.offset ?? t.threshold);
    if (!t.window) return offset;
    return `own ${t.centred ? "" : "trailing "}median of ${t.window}${t.scale ? ` + ${t.scale} MAD` : ""} + ${offset}`;
  }

  // A death-time error, in minutes.
  static mins(value) {
    return value == null ? "–" : `${value.toFixed(1)} min`;
  }

  // The distance between two survival curves, in percentage points.
  static points(value) {
    return value == null ? "–" : `${value.toFixed(1)} points`;
  }

  static DEATH_NOTE = `A mite's death time is the first labelled recording after the last one it moved in; one never moving died at its first recording,
    and one moving in its last died one recording later, the earliest it can have. The <b>death-time error</b> is the mean distance, over the labelled mites,
    between the time by the detector's calls and the time by the ground truth.`;

  static called(c, truth, call) {
    return c[`${truth}_called_${call}`];
  }

  static oneClassNote(r) {
    return `All ${r.n_moving + r.n_still} labels are ${r.n_moving ? "moving" : "still"}, so there is no ROC curve and no threshold to suggest: that needs both moving and still labels.`;
  }

  static pooled(r) {
    return r.datasets.length > 1;
  }

  // e.g. "topN_variability (n=10), plate stabilized"
  static scoreText(metric, params, stabilized) {
    const list = Object.entries(params || {}).map(([k, v]) => `${k}=${v}`).join(", ");
    return (list ? `${metric} (${list})` : metric) + (stabilized ? ", plate stabilized" : "");
  }

  // The curve of the last mark; the one of the threshold in use is drawn beside it
  // when its window is another one.
  static rocCaption(marks) {
    const main = marks[marks.length - 1];
    const { window, centred, scale } = main.call;
    const what = window ? "offset" : "threshold";
    const other = marks.find((mark) => !ReportFigures.sameWindow(mark, main));
    return `Every possible ${what}${window ? ` above the mite's own ${centred ? "" : "trailing "}median of ${window} recordings${scale ? ` plus ${scale} MADs` : ""}` : ""}, from the highest (bottom left) to the lowest (top right).
      AUC ${main.roc.auc.toFixed(3)}. Hover the curve for the ${what} at each step.${other ? ` The thin curve is the one of the threshold ${other.name} (AUC ${other.roc.auc.toFixed(3)}).` : ""}`;
  }

  // Who is left out of a survival curve, by the labels and by the detector's calls.
  static leftOutText(curves, marks) {
    const parts = [`${curves.truth.n_left_out} never labelled moving`,
      ...marks.map((mark) => `${curves[mark.key].n_left_out} never called moving at the threshold ${mark.name}`),
      ...(curves.benchmark ? [`${curves.benchmark.n_left_out} never called moving by the benchmark`] : [])];
    return `Left out: ${parts.join(", ")}.`;
  }

  static survivalCaption(r, marks) {
    return `The Kaplan–Meier survival rate of the labelled mites: by the ground truth (black, with its 95% confidence band) and as the detector's calls
    ${r.survival.benchmark ? "and the benchmark's " : ""}would have it. A mite counts as alive up to the last recording in which it moved and as dead from the next labelled one on; a mite moving in its last
    labelled recording is right-censored there. Only mites seen moving at least once are in the study, each curve by its own calls, as a mite never
    seen moving may have been dead from the start. ${ReportPage.leftOutText(r.survival, marks)} The closer the dashed curves follow the black one,
    the better the threshold gives the true survival: ${ReportPage.gapText(r, marks)}. Hover for the numbers.${ReportPage.poolNote(r)}`;
  }

  // How far each caller's survival curve is from the ground truth's (the
  // server's, calibration.curve_gap), and its death-time error.
  static gapText(r, marks) {
    const { points, mins } = ReportPage;
    const callers = [...marks.map((mark) => [`the threshold ${mark.name}`, r.death_time[mark.key]]),
      ...(r.death_time.benchmark ? [["the benchmark", r.death_time.benchmark]] : [])];
    return callers.map(([name, d]) => `at ${name} the curve is on average ${points(d.km_gap)} from it, the mites' death times ${mins(d.mae)}`).join("; ");
  }

  // Pooled datasets need not cover every recording, e.g. recordings of different
  // lengths, so the fractions over time can rest on different numbers of mites.
  static poolNote(r, counts = null) {
    if (!ReportPage.pooled(r)) return "";
    const known = (counts || []).filter((n) => n != null);
    const range = known.length && Math.min(...known) !== Math.max(...known)
      ? ` (here from ${Math.min(...known)} to ${Math.max(...known)})` : "";
    return ` <b>Pooled:</b> not every recording has the same number of mites${range}, e.g. when the datasets have recordings of different lengths,
    so later recordings may rest on fewer mites${counts ? ". Hover a point for its count." : ": a mite of a shorter dataset is censored at its last recording."}`;
  }

  // The thresholds to show: the one in use and, when there is one, the suggestion,
  // each with its window and offset (`call`), its confusion counts and their rates,
  // its ROC curve and the key of each observation's margin above it (from the server).
  static thresholdMarks(r) {
    const marks = [{
      key: "current", name: "in use", call: r.calls.current, text: ReportPage.thresholdText(r.calls.current),
      margin: "margin", roc: r.roc, confusion: r.current, rates: r.rates.current, color: token("--series-1"),
    }];
    if (r.calls.suggested) {
      marks.push({
        key: "suggested", name: "suggested", call: r.calls.suggested, text: ReportPage.thresholdText(r.calls.suggested),
        margin: "margin_suggested", roc: r.roc_suggested, confusion: r.best, rates: r.rates.best, color: token("--series-2"),
      });
    }
    return marks;
  }

  draw() {
    const r = cal.report;
    const { thresholdText, scoreText, pooled, poolNote } = ReportPage;
    const { section } = Markup;
    const testing = cal.mode === "test";
    const body = $("report-body");
    const left = [
      r.n_not_a_mite ? `${r.n_not_a_mite} detection${r.n_not_a_mite > 1 ? "s" : ""} not a mite, left out` : "",
      r.n_unlabelled ? `${r.n_unlabelled} mite-recordings unlabelled, left out` : "",
    ].filter(Boolean).join(" · ");

    body.innerHTML = `
    ${cal.reportStale ? `<div class="banner">The ground truth changed since this report.
      <button type="button" id="report-refresh" class="small">Update</button></div>` : ""}
    <header class="page-head">
      <div>
        <h1>${testing ? "Threshold test" : "Calibration"}</h1>
        <p class="meta">${pooled(r) ? `${r.datasets.length} datasets pooled` : `<span title="${esc(r.datasets[0].data_dir)}">${esc(r.datasets[0].name)}</span>`} ·
          movement score <code>${esc(scoreText(r.metric, r.metric_params, r.stabilize_plate))}</code> ·
          ${r.n_mites} mite${r.n_mites === 1 ? "" : "s"} over ${r.times.length} recordings ·
          ${r.n_moving} moving and ${r.n_still} still labels</p>
        ${left ? `<p class="meta">${left}</p>` : ""}
      </div>
      <div class="row">
        <div class="segmented" role="group" aria-label="Report">
          <button type="button" data-mode="calibrate" class="small ${testing ? "secondary" : ""}">Calibration</button>
          <button type="button" data-mode="test" class="small ${testing ? "" : "secondary"}">Test</button>
        </div>
        ${cal.data ? '<a class="button secondary small" href="#/cal/truth">Edit ground truth</a>' : ""}
      </div>
    </header>
    ${section("Data used", this.datasetPicker(r))}
    ${section("Movement score", testing ? this.scoreTested(r) : this.scorePicker(r))}
    ${testing ? "" : section("Search the hyperparameters", SearchPanel.html())}
    ${r.threshold_fits ? "" : `<div class="banner">The threshold in use, ${thresholdText(r.calls.current)}, was set for
      <code>${esc(scoreText(r.in_use.metric, r.in_use.params, r.in_use.stabilize_plate))}</code>. These scores are
      <code>${esc(scoreText(r.metric, r.metric_params, r.stabilize_plate))}</code>, on another scale, so figures "in use" say little:
      look at the suggested threshold, and save it with this movement score to use it.</div>`}
    ${testing ? this.testReport(r) : this.calibrateReport(r)}
    ${testing ? section("Survival rate per group", `<div id="group-legend" class="legend"></div><div id="group-moving" class="group-cards"></div>
      <p class="caption">Each group's Kaplan–Meier survival rate, by the ground truth and as the detector's calls at the threshold in use${r.benchmark ? " and the benchmark's" : ""} would have it, as in Fig. 2;
        the number is the group's mites in the study by the ground truth. Groups are the plate labels.${poolNote(r)}</p>`) : ""}
    ${section("Files", `<ul class="files">
      <li><a href="${cal.fileUrl(r.excel)}" download>${esc(r.excel)}</a>
        <span class="muted">every labelled mite-recording with its score, threshold and outcome, every mite's death time by the labels and by the detector, the survival curves, the fraction moving per recording, every window tried, the ROC curve and the summary</span></li></ul>`)}`;

    body.querySelectorAll(".segmented [data-mode]").forEach((button) => button.addEventListener("click", () => {
      cal.setMode(button.dataset.mode);
      this.draw();
      // A report asked for on the calibration tab came without the benchmark.
      if (cal.mode === "test" && !cal.report.benchmark) {
        cal.reportAgain("benchmark-status", () => {}, "Running the benchmark… the first time a dataset meets it this takes about a minute.");
      }
    }));
    $("report-refresh")?.addEventListener("click", () => cal.evaluate());
    this.wireDatasetPicker();
    if (!testing) this.wireScorePicker(r);
    if (!testing) this.search.mount(r);

    // Groups matter to a test of the threshold, not to finding one.
    if (testing) {
      this.drawTestFigures(r);
      this.figures.drawGroupSurvival(r, ReportPage.thresholdMarks(r).slice(0, 1));
    } else {
      this.drawCalibrateFigures(r);
    }
  }

  // --- the datasets pooled

  // The datasets that can be pooled: those whose recordings can still be scored.
  poolable() {
    return cal.datasets.filter((d) => d.recordings_available);
  }

  // The report pools more than the dataset on the ground-truth page.
  pooling() {
    return cal.selected.some((id) => id !== cal.datasetId);
  }

  // Which saved datasets the report pools. With a dataset open for labelling, a
  // toggle pools the other saved ground truth with it or not; ticking a dataset
  // compares again at once.
  datasetPicker(r) {
    const { savedDate, labelsText } = DatasetLibrary;
    const used = new Map(r.datasets.map((d) => [d.id, d]));
    const toggle = cal.datasetId ? `
    <label class="pool-toggle">
      <input type="checkbox" id="pool-toggle" ${this.pooling() ? "checked" : ""} ${this.poolable().some((d) => d.id !== cal.datasetId) ? "" : "disabled"}>
      <span><b>Pool with saved ground truth from other recordings</b>
        <span class="hint">Old recordings are scored again with the movement score below, from their saved copy, never from old scores.</span></span>
    </label>` : "";
    const shown = !cal.datasetId || this.pooling();
    const rows = cal.datasets.map((d) => {
      const inReport = used.get(d.id);
      const open = d.id === cal.datasetId;
      return `<li><label class="dataset-option">
      <input type="checkbox" class="dataset-check" value="${esc(d.id)}" ${cal.selected.includes(d.id) ? "checked" : ""}
        ${d.recordings_available ? "" : "disabled"}>
      <span class="group-name" title="${esc(d.data_dir)}">${esc(d.name)}${open ? ' <span class="muted">(on the ground-truth page)</span>' : ""}</span>
      <span class="hint">${d.recordings_available ? "" : "recordings moved and not copied, cannot be scored · "}${savedDate(d.saved_at)} ·
        ${d.n_recordings} recordings · ${d.n_mites} mites · ${labelsText(d)}${inReport ? ` · <b>${inReport.n_observations}</b> in this report` : ""}</span>
    </label></li>`;
    }).join("");
    return `${toggle}
    ${shown ? `<ul class="group-list dataset-list">${rows}</ul>` : ""}
    <p id="dataset-status" class="hint">${ReportPage.pooled(r)
      ? "The mite-recordings of all ticked datasets are pooled. For the charts over time, recordings are lined up by their order (first, second, …) at their mean time. Click any mite in the charts, the map or the table to open it in its own recording."
      : cal.datasetId ? "Only the recording on the ground-truth page is used." : "Tick more datasets to pool their labels, for a threshold based on more data."}</p>`;
  }

  wireDatasetPicker() {
    const change = (chosen) => {
      const before = cal.selected;
      cal.selected = chosen;
      cal.reportAgain("dataset-status", () => { cal.selected = before; });
    };
    $("pool-toggle")?.addEventListener("change", (event) => {
      change(event.target.checked ? [cal.datasetId, ...this.poolable().map((d) => d.id).filter((id) => id !== cal.datasetId)] : [cal.datasetId]);
    });
    document.querySelectorAll(".dataset-check").forEach((check) => check.addEventListener("change", () => {
      const chosen = [...document.querySelectorAll(".dataset-check:checked")].map((c) => c.value);
      if (!chosen.length) {
        check.checked = true;
        $("dataset-status").className = "hint error";
        $("dataset-status").textContent = "Keep at least one dataset.";
        return;
      }
      change(chosen);
    }));
  }

  // --- the movement score the report is scored with

  // Choose a metric and its parameters, and score again with them. Nothing is
  // written to config.yaml until a threshold is saved with them.
  scorePicker(r) {
    const { thresholdText, scoreText } = ReportPage;
    if (!cal.scores) return `<p class="hint">Movement scores could not be listed.</p>`;
    const options = cal.scores.metrics.map((m) =>
      `<option value="${esc(m.name)}" ${m.name === r.metric ? "selected" : ""}>${esc(m.name)}${m.name === cal.scores.in_use.metric ? " (config.yaml)" : ""}</option>`).join("");
    return `<div class="row score-picker">
      <label for="score-metric">Metric</label>
      <select id="score-metric">${options}</select>
      <span id="score-params" class="row"></span>
      <label class="param" title="Measure how the whole plate moved in each frame, from all the mites at once, and shift it back before scoring. Changes nothing on a still plate.">
        <input type="checkbox" id="score-stabilize" ${r.stabilize_plate ? "checked" : ""}> Stabilize plate</label>
      <button type="button" id="score-apply" class="small">Score again</button>
      <button type="button" id="score-reset" class="small secondary" ${r.threshold_fits ? "hidden" : ""}>Back to config.yaml's</button>
    </div>
    <p id="score-description" class="hint"></p>
    <p id="score-status" class="hint">In use for analyses: <code>${esc(scoreText(cal.scores.in_use.metric, cal.scores.in_use.params, cal.scores.in_use.stabilize_plate))}</code>
      with threshold ${thresholdText(cal.scores.in_use)}. Try another here; saving a threshold below saves the movement score with it.</p>`;
  }

  // The test report only says which score it tests: scoring again with another one
  // there would judge it by a threshold set for a different score.
  scoreTested(r) {
    const { thresholdText, scoreText } = ReportPage;
    return `<p class="hint">Tested: <code>${esc(scoreText(r.metric, r.metric_params, r.stabilize_plate))}</code> with the threshold in use, ${thresholdText(r.calls.current)}.
      Try another movement score on the <b>Calibration</b> tab.</p>`;
  }

  wireScorePicker(r) {
    if (!cal.scores) return;
    const select = $("score-metric");
    const showParams = () => {
      const metric = cal.scores.metrics.find((m) => m.name === select.value);
      // the report's own values for its metric, else config.yaml's or the defaults
      const values = metric.name === r.metric ? r.metric_params : metric.params;
      $("score-params").innerHTML = Object.entries(metric.defaults).map(([name, fallback]) => `
      <label class="param">${esc(name)}
        <input type="number" data-param="${esc(name)}" min="${Number.isInteger(fallback) ? 1 : 0}" step="${Number.isInteger(fallback) ? 1 : "any"}"
          value="${values[name] ?? fallback}" title="default ${fallback}"></label>`).join("")
        || '<span class="hint">no parameters</span>';
      $("score-description").textContent = metric.description;
    };
    select.addEventListener("change", showParams);
    showParams();

    const status = $("score-status");
    $("score-apply").addEventListener("click", () => {
      const params = {};
      for (const input of document.querySelectorAll("#score-params [data-param]")) {
        const value = Number(input.value);
        if (!(value > 0)) {
          status.className = "hint error";
          status.textContent = `${input.dataset.param} must be a positive number.`;
          return;
        }
        params[input.dataset.param] = value;
      }
      const before = cal.metric;
      cal.metric = { name: select.value, params, stabilize: $("score-stabilize").checked };
      cal.reportAgain("score-status", () => { cal.metric = before; });
    });
    $("score-reset").addEventListener("click", () => {
      const before = cal.metric;
      cal.metric = null;
      cal.reportAgain("score-status", () => { cal.metric = before; });
    });
  }

  // --- key figures and the confusion matrix, shared by both tabs

  // A stat tile for one kind of label, e.g. still called still, with the other
  // call beside it; `rates` are the server's for the confusion counts `c`.
  outcomeStat(title, c, rates, truth, other, compare = null) {
    const { called } = ReportPage;
    const total = c[`n_${truth}`];
    const right = called(c, truth, truth);
    const note = [`${right} of ${total} · ${called(c, truth, other)} called ${other}`];
    if (compare) note.push(`in use: ${called(compare, truth, truth)} of ${total}`);
    return Markup.stat(title, pct(called(rates, truth, truth)), note.join(" · "));
  }

  // --- calibrate: pick a window and an offset and save them

  calibrateReport(r) {
    const { thr, mins, thresholdText, oneClassNote, survivalCaption, rocCaption, stripCaption, scoreText, CONFUSION_CAPTION, DEATH_NOTE } = ReportPage;
    const { stat, figure, section } = Markup;
    const marks = ReportPage.thresholdMarks(r);
    const inUse = thresholdText(r.calls.current);
    if (!r.calls.suggested) {
      return `<div class="banner">${oneClassNote(r)}</div>
      <div class="stats">
        ${stat("Death-time error", mins(r.death_time.current.mae), `mean per mite · threshold in use ${inUse}`)}
        ${this.outcomeStat("Moving called moving", r.current, r.rates.current, "moving", "still")}
        ${this.outcomeStat("Still called still", r.current, r.rates.current, "still", "moving")}
        ${stat("AUC", "–", "needs moving and still labels")}
      </div>
      <div class="grid-2">
        ${figure("confusion", 1, "Confusion matrix at the threshold in use", CONFUSION_CAPTION)}
        ${figure("chart-survival", 2, "Survival rate: ground truth and the detector", survivalCaption(r, marks))}
      </div>`;
    }
    const { suggested } = r.calls;
    const suggestedText = thresholdText(suggested);
    const single = r.windows[0];
    const shown = cal.shownThreshold === "current" ? "current" : "best";
    return `
    <div class="stats">
      ${stat("Suggested threshold", `median + ${suggested.scale ? `${suggested.scale} MAD + ` : ""}${thr(suggested.offset)}`,
        `the mite's own median${suggested.scale ? " and MAD" : ""} over ${suggested.window} recordings, ${suggested.centred ? "centred" : "trailing"} · ${suggestedText === inUse ? "the one in use" : `in use: ${inUse}`}`)}
      ${stat("Death-time error", mins(r.death_time.suggested.mae),
        `mean per mite · ${r.death_time.suggested.n_exact} of ${r.death_time.suggested.n_mites} mites exact · in use: ${mins(r.death_time.current.mae)}`)}
      ${this.outcomeStat("Moving called moving", r.best, r.rates.best, "moving", "still", r.current)}
      ${this.outcomeStat("Still called still", r.best, r.rates.best, "still", "moving", r.current)}
    </div>
    <p class="caption">Key figures at the suggested threshold: the death-time error per mite, the others per mite-recording; "in use" is the threshold in config.yaml. ${DEATH_NOTE}</p>
    ${r.death_time.single.mae < r.death_time.suggested.mae ? `<div class="banner"><span>On these labels one threshold for every mite (${thr(single.offset)}) gives the death times within ${mins(r.death_time.single.mae)},
      the best own threshold within ${mins(r.death_time.suggested.mae)}. A mite's median is only what it scores when still while it is still in most of the window:
      see the wrong calls by how often the mite moves, below. To keep one threshold, choose the window <b>none</b> when saving.</span></div>` : ""}

    <div class="grid-2">
      <figure class="fig">
        <div class="fig-title fig-title-row">Confusion matrix
          <div class="segmented" role="group" aria-label="Threshold shown">
            <button type="button" data-shown="best" class="small ${shown === "best" ? "" : "secondary"}">suggested</button>
            <button type="button" data-shown="current" class="small ${shown === "current" ? "" : "secondary"}">in use</button>
          </div>
        </div>
        <div id="confusion"></div>
        <figcaption><b>Fig. 1.</b> ${CONFUSION_CAPTION} Suggested: ${suggestedText}; in use: ${inUse}.</figcaption>
      </figure>
      ${section("Save the threshold", `
        <div class="row save-threshold">
          <label for="window-input">Window</label>
          <select id="window-input">${[...new Set(r.windows.map((w) => w.window))].map((size) =>
            `<option value="${size}" ${size === suggested.window ? "selected" : ""}>${size ? `${size} recordings` : "none: one threshold for every mite"}</option>`).join("")}</select>
          <select id="align-input" aria-label="Where the window lies">
            <option value="centred" ${suggested.centred ? "selected" : ""}>centred</option>
            <option value="trailing" ${suggested.centred ? "" : "selected"}>trailing</option>
          </select>
          <label for="scale-input" title="How many median absolute deviations of the mite's scores over the window its threshold rises by: more for a noisier mite.">MADs</label>
          <select id="scale-input">${r.scales.map((scale) =>
            `<option value="${scale}" ${scale === suggested.scale ? "selected" : ""}>${scale || "0: none"}</option>`).join("")}</select>
          <label for="threshold-input" id="threshold-label">Offset</label>
          <input id="threshold-input" type="number" step="0.01" value="${thr(suggested.offset)}">
          <button type="button" id="save-threshold">Save to config.yaml</button>
        </div>
        <p id="window-note" class="hint"></p>
        <p id="save-status" class="hint">Saves the movement score <code>${esc(scoreText(r.metric, r.metric_params, r.stabilize_plate))}</code> along with the threshold.</p>
        <p class="hint">A mite counts as moving in a recording when its score reaches its own threshold: the median of its scores over the window, plus so many
          of their median absolute deviations (<b>MADs</b>: the noisier the mite, the higher its threshold), plus the offset.
          A <b>centred</b> window lies around the recording, a <b>trailing</b> one ends at it, so it needs no later recordings.
          The suggestion is the window, number of MADs and offset whose calls give the mites' death times with the smallest mean error, since the death times
          are what a survival curve is made of; of equally good ones, the one calling most labels right. The offset sits halfway between the two nearest scores.
          Choosing a window fills in its best MADs and offset. Every analysis started after saving uses the new values.
          Check them with the <b>Test</b> report on a <em>different</em> recording: on this one they look better than they will be.</p>
        ${this.comparisonTable(r)}`)}
    </div>

    <div class="grid-2">
      ${figure("chart-windows", 2, "Window of the mite's own threshold",
        `Each window, with its best number of MADs and offset, by its death-time error: what the suggestion minimises, so lower is better.
        The dashed line is one threshold for every mite, at its best. Hover a point for its MADs, offset and counts; select it to fill it in above.`)}
      ${figure("chart-offsets", 3, "Death-time error by the offset",
        `For the suggested window and number of MADs: the death-time error at every offset that gives different calls.
        A higher offset calls fewer mites moving, so they die earlier; a lower one keeps them alive longer. Hover for the numbers.`)}
    </div>

    <div class="grid-2">
      ${figure("chart-survival", 4, "Survival rate: ground truth and the detector", survivalCaption(r, marks))}
      ${figure("chart-roc", 5, "ROC curve", rocCaption(marks))}
    </div>

    ${figure("chart-strip", 6, "Motion score against the threshold", stripCaption(marks))}

    ${section("Wrong calls by how often the mite moves", this.shareTable(r))}`;
  }

  // The thresholds side by side, and how the choice holds on mites it never saw.
  comparisonTable(r) {
    const { thr, mins, points, thresholdText } = ReportPage;
    const single = r.windows[0];
    const rows = [["in use", thresholdText(r.calls.current), r.current, r.death_time.current],
      ...(r.best ? [["suggested", thresholdText(r.calls.suggested), r.best, r.death_time.suggested]] : []),
      ...(single ? [["one for every mite", `${thr(single.offset)}, its best`, single, r.death_time.single]] : [])];
    const held = r.held_out;
    return `<div class="table-wrap"><table>
    <thead><tr><th>Threshold</th><th class="num">Death-time error</th><th class="num">Survival curve off by</th><th class="num">Called right</th></tr></thead>
    <tbody>${rows.map(([name, value, c, d]) => `<tr>
      <td>${name} <span class="muted">${value}</span></td><td class="num">${mins(d.mae)}</td><td class="num">${points(d.km_gap)}</td>
      <td class="num">${pct(c.accuracy)}</td></tr>`).join("")}</tbody>
  </table></div>
  <p class="caption"><b>Survival curve off by</b>: the mean distance between the Kaplan–Meier curve by the detector's calls and the one by the ground truth, over the recordings.</p>
  ${held ? `<p class="hint"><b>On mites the choice never saw:</b> chosen on half of the mites, the thresholds give the other half's death times within
    ${mins(held.single)} with one threshold for every mite, ${mins(held.own)} with the mite's median plus an offset, and ${mins(held.scaled)} with
    the median plus MADs plus an offset (means of ${held.repeats} random halves). Chosen and judged on the same mites, as above, every one looks better than it will be.</p>` : ""}`;
  }

  // Where a mite's own threshold goes wrong: its median is only its noise while it
  // is still in most of the window (the server's, ThresholdSearch.by_share_moving).
  shareTable(r) {
    const rows = r.by_share_moving.filter((row) => row.n);
    return `<div class="table-wrap"><table>
    <thead><tr><th>Mite labelled moving in</th><th class="num">Mites</th><th class="num">Mite-recordings</th>
      <th class="num">Called wrong</th><th class="num">Share wrong</th></tr></thead>
    <tbody>${rows.map((row) => `<tr>
      <td>${row.share === "never" ? "none of its recordings" : `${row.share} of its recordings`}</td>
      <td class="num">${row.n_mites}</td><td class="num">${row.n}</td>
      <td class="num${row.n_wrong ? " error" : ""}">${row.n_wrong}</td><td class="num">${pct(row.n_wrong / row.n)}</td></tr>`).join("")}</tbody>
  </table></div>
  <p class="caption">At the suggested threshold, ${ReportPage.thresholdText(r.calls.suggested)}. The median of a mite's scores is what it scores when still
    only as long as it is still in most of the window: a mite moving in most recordings has a high median, and its movement no longer stands out above it.
    Wrong calls gathering in the lower rows say the window is too short for how long these mites keep moving.</p>`;
  }

  drawCalibrateFigures(r) {
    const marks = ReportPage.thresholdMarks(r);
    const { figures } = this;
    figures.drawSurvival($("chart-survival"), r.survival, r.times, marks);
    const matrix = (shown) => (shown === "current" ? figures.confusionTable(r.current, r.rates.current) : figures.confusionTable(r.best, r.rates.best));
    if (!r.calls.suggested) {
      $("confusion").innerHTML = matrix("current");
      return;
    }
    $("confusion").innerHTML = matrix(cal.shownThreshold);
    document.querySelectorAll("[data-shown]").forEach((button) => button.addEventListener("click", () => {
      cal.shownThreshold = button.dataset.shown;
      document.querySelectorAll("[data-shown]").forEach((b) => b.classList.toggle("secondary", b !== button));
      $("confusion").innerHTML = matrix(button.dataset.shown);
    }));
    figures.drawWindows($("chart-windows"), r, marks, (choice) => this.chooseWindow(r, choice.window, choice.centred, choice.scale));
    figures.drawOffsets($("chart-offsets"), r, marks);
    figures.drawRoc($("chart-roc"), marks);
    figures.drawStrip($("chart-strip"), r, marks);
    const chosen = () => this.chooseWindow(r, Number($("window-input").value), $("align-input").value === "centred");
    $("window-input").addEventListener("change", chosen);
    $("align-input").addEventListener("change", chosen);
    $("scale-input").addEventListener("change", () => this.chooseWindow(
      r, Number($("window-input").value), $("align-input").value === "centred", Number($("scale-input").value)));
    this.describeWindow(r);
    $("save-threshold").addEventListener("click", () => this.saveThreshold());
  }

  // The window and scale tried by the server that the save form shows.
  shownWindow(r) {
    const size = Number($("window-input").value);
    const centred = $("align-input").value === "centred";
    const scale = Number($("scale-input").value);
    return r.windows.find((w) => w.window === size && (!size || (w.centred === centred && w.scale === scale)));
  }

  // Put a window in the save form, with its best offset; without a `scale`,
  // with the window's best number of MADs too (the server's, best_of_window).
  chooseWindow(r, size, centred, scale = null) {
    $("window-input").value = String(size);
    if (size) $("align-input").value = centred ? "centred" : "trailing";
    const best = r.windows.find((w) => w.window === size && (!size || w.centred === centred) && w.best_of_window);
    $("scale-input").value = String(size ? scale ?? best?.scale ?? 0 : 0);
    const choice = this.shownWindow(r);
    if (choice) $("threshold-input").value = ReportPage.thr(choice.offset);
    this.describeWindow(r);
  }

  describeWindow(r) {
    const choice = this.shownWindow(r);
    const single = !Number($("window-input").value);
    $("align-input").disabled = single;
    $("scale-input").disabled = single;
    $("threshold-label").textContent = single ? "Threshold" : "Offset";
    $("window-note").textContent = choice
      ? `With its best ${single ? "threshold" : "offset"}, ${ReportPage.thr(choice.offset)}: death times within ${ReportPage.mins(choice.mae)}, ${pct(choice.accuracy)} called right, ${choice.moving_called_still} moving called still, ${choice.still_called_moving} still called moving.`
      : "";
  }

  async saveThreshold() {
    const { thresholdText, scoreText } = ReportPage;
    const value = Number($("threshold-input").value);
    const size = Number($("window-input").value);
    const status = $("save-status");
    if ($("threshold-input").value === "" || !Number.isFinite(value) || (!size && !(value > 0))) {
      status.className = "hint error";
      status.textContent = size ? "Enter a number." : "Enter a positive number.";
      return;
    }
    try {
      // The threshold only fits the scores it was chosen on, so the movement score
      // of this report is saved with it.
      const r = cal.report;
      const saved = await post("/api/movement-score", {
        metric: r.metric, params: r.metric_params, threshold: value, stabilize: r.stabilize_plate,
        window: size, centred: $("align-input").value === "centred", scale: size ? Number($("scale-input").value) : 0,
      });
      if (cal.data) cal.data.threshold = saved.threshold;
      // Evaluate again, so "in use" is what was just saved.
      cal.takeReport(await cal.requestReport());
      this.draw();
      $("save-status").className = "hint";
      $("save-status").textContent = `Saved ${scoreText(saved.metric, saved.params, saved.stabilize_plate)} with threshold ${thresholdText(saved)} to config.yaml. Analyses started from now on use them.`;
    } catch (error) {
      status.className = "hint error";
      status.textContent = error.message;
    }
  }

  // --- test: how good is the threshold in use, and where does it go wrong

  testReport(r) {
    const { mins, points, thresholdText, oneClassNote, survivalCaption, rocCaption, stripCaption, pooled, CONFUSION_CAPTION, DEATH_NOTE } = ReportPage;
    const { stat, figure, section } = Markup;
    const c = r.current;
    const d = r.death_time.current;
    const marks = ReportPage.thresholdMarks(r).slice(0, 1);
    return `
    <div class="stats">
      ${stat("Death-time error", mins(d.mae), `mean per mite · ${d.n_exact} of ${d.n_mites} mites exact · survival curve off by ${points(d.km_gap)}`)}
      ${stat("Called right", pct(c.accuracy), `${c.n_wrong} wrong · threshold ${thresholdText(r.calls.current)}`)}
      ${this.outcomeStat("Moving called moving", c, r.rates.current, "moving", "still")}
      ${this.outcomeStat("Still called still", c, r.rates.current, "still", "moving")}
    </div>
    <p class="caption">${DEATH_NOTE} The survival curve is off by the mean distance between the detector's Kaplan–Meier curve and the ground truth's (Fig. 2).
      By the detector's calls the mites die ${d.bias > 0 ? "later" : "earlier"} than by the ground truth, by ${mins(Math.abs(d.bias))} on average.</p>

    <div class="grid-2">
      ${figure("confusion", 1, "Confusion matrix at the threshold in use", CONFUSION_CAPTION)}
      ${figure("chart-survival", 2, "Survival rate: ground truth and the detector", survivalCaption(r, marks))}
    </div>

    ${section("Against the benchmark", this.benchmarkTable(r))}

    <div class="grid-2">
      <figure class="fig">
        <div class="fig-title fig-title-row">Where the errors are
          <span class="row">
          ${pooled(r) ? `<select id="map-dataset" aria-label="Recording folder">
            ${r.datasets.map((d) => `<option value="${esc(d.id)}" ${d.id === this.figures.mapDataset(r) ? "selected" : ""}>${esc(d.name)}</option>`).join("")}
          </select>` : ""}
          <select id="map-recording" aria-label="Recording">
            <option value="">all recordings</option>
            ${r.times.map((time, i) => `<option value="${i}">${minutes(time)}</option>`).join("")}
          </select>
          </span>
        </div>
        <div id="outcome-map" class="plate outcome-map"></div>
        <div id="outcome-legend" class="legend map-legend"></div>
        <figcaption><b>Fig. 3.</b> Every labelled mite on the first frame. Mites called right in every selected recording are faint rings;
          a mite called wrong at least once is coloured by its more frequent error. Hover a mite for its recordings, select it to see it.
          ${pooled(r) ? "One recording folder at a time: choose it above." : ""}</figcaption>
      </figure>
      ${r.roc ? figure("chart-roc", 4, "ROC curve", rocCaption(marks)) : section("ROC curve", `<p class="hint">${oneClassNote(r)}</p>`)}
    </div>

    ${r.roc ? figure("chart-strip", 5, "Motion score against the threshold", stripCaption(marks)) : ""}

    ${section("Per zone", `<div class="table-wrap"><table class="clickable" id="zone-errors"></table></div>
      <p class="caption">Counts are mite-recordings, at the threshold in use. Select a zone to review its labels.</p>`)}`;
  }

  // The detector at the threshold in use beside the Discobox's original software,
  // on the same mite-recordings (the server's figures, calibration.calls_confusion).
  benchmarkTable(r) {
    const { mins, points, thresholdText, scoreText } = ReportPage;
    if (!r.benchmark) return `<p id="benchmark-status" class="hint">The benchmark has not been run on these datasets.</p>`;
    const share = (value) => (value == null ? "–" : `${(value * 100).toFixed(1)}%`);
    const rows = [
      [`Detector <span class="muted">${esc(scoreText(r.metric, r.metric_params, r.stabilize_plate))}</span>`, thresholdText(r.calls.current), r.current, r.death_time.current],
      [`Benchmark <span class="muted">${esc(r.benchmark.name)}, the Discobox's original software</span>`, r.benchmark.threshold, r.benchmark, r.death_time.benchmark],
    ];
    return `<div class="table-wrap"><table>
    <thead><tr><th>Called by</th><th class="num">Threshold</th><th class="num">Death-time error</th><th class="num">Survival curve off by</th>
      <th class="num">Precision</th><th class="num">Recall</th><th class="num">F1 score</th>
      <th class="num">Called right</th><th class="num">Moving called still</th><th class="num">Still called moving</th></tr></thead>
    <tbody>${rows.map(([name, threshold, c, d]) => `<tr>
      <td>${name}</td><td class="num">${threshold}</td>
      <td class="num">${mins(d.mae)}</td><td class="num">${points(d.km_gap)}</td>
      <td class="num">${share(c.precision)}</td><td class="num">${share(c.sensitivity)}</td><td class="num">${share(c.f1)}</td>
      <td class="num">${share(c.accuracy)}</td><td class="num">${c.moving_called_still}</td><td class="num">${c.still_called_moving}</td></tr>`).join("")}</tbody>
  </table></div>
  <p class="caption">Both on the same ${r.n_moving + r.n_still} labelled mite-recordings, moving being the positive call.
    <b>Death-time error</b> and <b>survival curve off by</b>: as above, per mite and per recording.
    <b>Precision</b>: of the calls "moving", the share labelled moving. <b>Recall</b>: of the labels "moving", the share called moving.
    <b>F1 score</b>: their harmonic mean. The benchmark denoises each recording's frames, takes the difference of every frame to the first and
    calls a mite moving when a difference above ${r.benchmark.threshold} lies on it; that threshold is fixed in its code, where the detector's is
    config.yaml's. Its survival curve is in Fig. 2 and in the groups' below.</p>`;
  }

  drawTestFigures(r) {
    const marks = ReportPage.thresholdMarks(r).slice(0, 1);
    const { figures } = this;
    $("confusion").innerHTML = figures.confusionTable(r.current, r.rates.current);
    figures.drawSurvival($("chart-survival"), r.survival, r.times, marks);
    const drawMap = () => {
      if ($("map-dataset")) cal.mapDataset = $("map-dataset").value;
      figures.drawOutcomeMap(r, figures.mapDataset(r), $("map-recording").value);
    };
    $("map-recording").addEventListener("change", drawMap);
    $("map-dataset")?.addEventListener("change", drawMap);
    drawMap();
    if (r.roc) {
      figures.drawRoc($("chart-roc"), marks);
      figures.drawStrip($("chart-strip"), r, marks);
    }
    figures.drawZoneErrors(r);
  }
}
