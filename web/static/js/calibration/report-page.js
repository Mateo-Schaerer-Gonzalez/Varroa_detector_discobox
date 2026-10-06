// The calibration or test report. Each (mite, recording) labelled moving or still
// is compared with the detector's call: moving when that recording's score reaches
// the threshold. The numbers are the server's (evaluate_calibration); this draws
// them, with pickers for the datasets pooled and the movement score.

class ReportPage {
  static CONFUSION_CAPTION =
    "The ground truth against the detector's call, which is moving when that recording's score reaches the threshold. One count per mite-recording; percentages are of each row.";
  static STRIP_CAPTION =
    "Each labelled mite-recording at its motion score. Everything right of a line is called moving at that threshold. Select a point to see that mite.";

  constructor() {
    this.figures = new ReportFigures();
  }

  static thr(value) {
    return Number(value).toFixed(2);
  }

  static called(c, truth, call) {
    return c[`${truth}_called_${call}`];
  }

  static aucText(r) {
    return r.auc == null ? "–" : r.auc.toFixed(3);
  }

  static oneClassNote(r) {
    return `All ${r.n_moving + r.n_still} labels are ${r.n_moving ? "moving" : "still"}, so there is no ROC curve and no threshold to suggest: that needs both moving and still labels.`;
  }

  static pooled(r) {
    return r.datasets.length > 1;
  }

  // e.g. "topN_variability (n=10), plate stabilized, per-mite floor"; `how` holds
  // stabilize_plate, normalize_brightness and normalize_floor: a report, the
  // movement score in use, or what was just saved.
  static scoreText(metric, params, how = {}) {
    const list = Object.entries(params || {}).map(([k, v]) => `${k}=${v}`).join(", ");
    return (list ? `${metric} (${list})` : metric) + (how.stabilize_plate ? ", plate stabilized" : "")
      + (how.normalize_brightness ? ", brightness normalised" : "") + (how.normalize_floor ? ", per-mite floor" : "");
  }

  static rocCaption(r) {
    return `Every possible threshold, from the highest (bottom left) to the lowest (top right). AUC ${ReportPage.aucText(r)}. Hover the curve for the threshold at each step.`;
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
    the better the threshold gives the true survival. Hover for the numbers.${ReportPage.poolNote(r)}`;
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
  // each with its confusion counts and their rates (from the server).
  static thresholdMarks(r) {
    const marks = [{ key: "current", name: "in use", value: r.threshold, confusion: r.current, rates: r.rates.current, color: token("--series-1") }];
    if (r.suggested_threshold != null) {
      marks.push({ key: "suggested", name: "suggested", value: r.suggested_threshold, confusion: r.best, rates: r.rates.best, color: token("--series-2") });
    }
    return marks;
  }

  draw() {
    const r = cal.report;
    const { thr, scoreText, pooled, poolNote } = ReportPage;
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
          movement score <code>${esc(scoreText(r.metric, r.metric_params, r))}</code> ·
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
    ${r.threshold_fits ? "" : `<div class="banner">The threshold in use, ${thr(r.threshold)}, was set for
      <code>${esc(scoreText(r.in_use.metric, r.in_use.params, r.in_use))}</code>. These scores are
      <code>${esc(scoreText(r.metric, r.metric_params, r))}</code>, on another scale, so figures "in use" say little:
      look at the suggested threshold, and save it with this movement score to use it.</div>`}
    ${testing ? this.testReport(r) : this.calibrateReport(r)}
    ${testing ? section("Survival rate per group", `<div id="group-legend" class="legend"></div><div id="group-moving" class="group-cards"></div>
      <p class="caption">Each group's Kaplan–Meier survival rate, by the ground truth and as the detector's calls at the threshold in use${r.benchmark ? " and the benchmark's" : ""} would have it, as in Fig. 2;
        the number is the group's mites in the study by the ground truth. Groups are the plate labels.${poolNote(r)}</p>`) : ""}
    ${section("Files", `<ul class="files">
      <li><a href="${cal.fileUrl(r.excel)}" download>${esc(r.excel)}</a>
        <span class="muted">every labelled mite-recording with its score and outcome, the fraction moving per recording, the ROC curve and the summary</span></li></ul>`)}`;

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
    const { thr, scoreText } = ReportPage;
    if (!cal.scores) return `<p class="hint">Movement scores could not be listed.</p>`;
    const options = cal.scores.metrics.map((m) =>
      `<option value="${esc(m.name)}" ${m.name === r.metric ? "selected" : ""}>${esc(m.name)}${m.name === cal.scores.in_use.metric ? " (config.yaml)" : ""}</option>`).join("");
    return `<div class="row score-picker">
      <label for="score-metric">Metric</label>
      <select id="score-metric">${options}</select>
      <span id="score-params" class="row"></span>
      <label class="param" title="Measure how the whole plate moved in each frame, from all the mites at once, and shift it back before scoring. Changes nothing on a still plate.">
        <input type="checkbox" id="score-stabilize" ${r.stabilize_plate ? "checked" : ""}> Stabilize plate</label>
      <label class="param" title="Scale each score to the typical brightness of its dataset: camera noise, and with it the score of a still mite, grows with the light on its patch. The analysis of a folder then does the same over its run.">
        <input type="checkbox" id="score-brightness" ${r.normalize_brightness ? "checked" : ""}> Normalise brightness</label>
      <label class="param" title="Move each mite's own floor, the median of its scores over the recordings of its dataset, to the median floor of all mites. The analysis of a folder then does the same over its run. A mite moving in more than half of the recordings gets too high a floor.">
        <input type="checkbox" id="score-floor" ${r.normalize_floor ? "checked" : ""}> Per-mite floor</label>
      <button type="button" id="score-apply" class="small">Score again</button>
      <button type="button" id="score-reset" class="small secondary" ${r.threshold_fits ? "hidden" : ""}>Back to config.yaml's</button>
    </div>
    <p id="score-description" class="hint"></p>
    <p id="score-status" class="hint">In use for analyses: <code>${esc(scoreText(cal.scores.in_use.metric, cal.scores.in_use.params, cal.scores.in_use))}</code>
      with threshold ${thr(cal.scores.in_use.threshold)}. Try another here; saving a threshold below saves the movement score with it.</p>`;
  }

  // The test report only says which score it tests: scoring again with another one
  // there would judge it by a threshold set for a different score.
  scoreTested(r) {
    const { thr, scoreText } = ReportPage;
    return `<p class="hint">Tested: <code>${esc(scoreText(r.metric, r.metric_params, r))}</code> with the threshold in use, ${thr(r.threshold)}.
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
      cal.metric = {
        name: select.value, params, stabilize: $("score-stabilize").checked,
        normalizeBrightness: $("score-brightness").checked, normalizeFloor: $("score-floor").checked,
      };
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

  // --- calibrate: pick a threshold and save it

  calibrateReport(r) {
    const { thr, oneClassNote, survivalCaption, rocCaption, scoreText, CONFUSION_CAPTION, STRIP_CAPTION } = ReportPage;
    const { stat, figure, section } = Markup;
    if (r.suggested_threshold == null) {
      return `<div class="banner">${oneClassNote(r)}</div>
      <div class="stats">
        ${stat("Called right", pct(r.current.accuracy), `threshold in use ${thr(r.threshold)}`)}
        ${this.outcomeStat("Moving called moving", r.current, r.rates.current, "moving", "still")}
        ${this.outcomeStat("Still called still", r.current, r.rates.current, "still", "moving")}
        ${stat("AUC", "–", "needs moving and still labels")}
      </div>
      <div class="grid-2">
        ${figure("confusion", 1, "Confusion matrix at the threshold in use", CONFUSION_CAPTION)}
        ${figure("chart-survival", 2, "Survival rate: ground truth and the detector", survivalCaption(r, ReportPage.thresholdMarks(r)))}
      </div>`;
    }
    const same = Math.abs(r.suggested_threshold - r.threshold) < 0.005;
    const shown = cal.shownThreshold === "current" ? "current" : "best";
    return `
    <div class="stats">
      ${stat("Suggested threshold", thr(r.suggested_threshold), same ? "the one in use" : `in use: ${thr(r.threshold)}`)}
      ${stat("Called right", pct(r.best.accuracy), `in use: ${pct(r.current.accuracy)}`)}
      ${this.outcomeStat("Moving called moving", r.best, r.rates.best, "moving", "still", r.current)}
      ${this.outcomeStat("Still called still", r.best, r.rates.best, "still", "moving", r.current)}
    </div>
    <p class="caption">Key figures at the suggested threshold, per mite-recording; "in use" is the threshold in config.yaml.</p>

    <div class="grid-2">
      <figure class="fig">
        <div class="fig-title fig-title-row">Confusion matrix
          <div class="segmented" role="group" aria-label="Threshold shown">
            <button type="button" data-shown="best" class="small ${shown === "best" ? "" : "secondary"}">suggested ${thr(r.suggested_threshold)}</button>
            <button type="button" data-shown="current" class="small ${shown === "current" ? "" : "secondary"}">in use ${thr(r.threshold)}</button>
          </div>
        </div>
        <div id="confusion"></div>
        <figcaption><b>Fig. 1.</b> ${CONFUSION_CAPTION}</figcaption>
      </figure>
      ${section("Save the threshold", `
        <div class="row save-threshold">
          <label for="threshold-input">Movement threshold</label>
          <input id="threshold-input" type="number" step="0.01" min="0" value="${thr(r.suggested_threshold)}">
          <button type="button" id="save-threshold">Save to config.yaml</button>
        </div>
        <p id="save-status" class="hint">Saves the movement score <code>${esc(scoreText(r.metric, r.metric_params, r))}</code> along with the threshold.</p>
        <p class="hint">The suggestion maximises the fraction of moving labels called moving plus the fraction of still labels called still,
          and sits halfway between the two nearest scores. Every analysis started after saving uses the new value.
          Check it with the <b>Test</b> report on a <em>different</em> recording: on this one it looks better than it will be.</p>
        ${this.comparisonTable(r)}`)}
    </div>

    <div class="grid-2">
      ${figure("chart-survival", 2, "Survival rate: ground truth and the detector", survivalCaption(r, ReportPage.thresholdMarks(r)))}
      ${figure("chart-roc", 3, "ROC curve", rocCaption(r))}
    </div>

    ${figure("chart-strip", 4, "Motion score distribution", STRIP_CAPTION)}`;
  }

  comparisonTable(r) {
    const { thr } = ReportPage;
    // The values as shown everywhere else, so the same threshold never rounds two ways.
    const rows = [["in use", r.threshold, r.current], ...(r.best ? [["suggested", r.suggested_threshold, r.best]] : [])];
    return `<div class="table-wrap"><table>
    <thead><tr><th>Threshold</th><th class="num">Value</th><th class="num">Called right</th>
      <th class="num">Moving called still</th><th class="num">Still called moving</th></tr></thead>
    <tbody>${rows.map(([name, value, c]) => `<tr>
      <td>${name}</td><td class="num">${thr(value)}</td><td class="num">${pct(c.accuracy)}</td>
      <td class="num">${c.moving_called_still}</td><td class="num">${c.still_called_moving}</td></tr>`).join("")}</tbody>
  </table></div>`;
  }

  drawCalibrateFigures(r) {
    const marks = ReportPage.thresholdMarks(r);
    const { figures } = this;
    figures.drawSurvival($("chart-survival"), r.survival, r.times, marks);
    const matrix = (shown) => (shown === "current" ? figures.confusionTable(r.current, r.rates.current) : figures.confusionTable(r.best, r.rates.best));
    if (r.suggested_threshold == null) {
      $("confusion").innerHTML = matrix("current");
      return;
    }
    $("confusion").innerHTML = matrix(cal.shownThreshold);
    document.querySelectorAll("[data-shown]").forEach((button) => button.addEventListener("click", () => {
      cal.shownThreshold = button.dataset.shown;
      document.querySelectorAll("[data-shown]").forEach((b) => b.classList.toggle("secondary", b !== button));
      $("confusion").innerHTML = matrix(button.dataset.shown);
    }));
    figures.drawRoc($("chart-roc"), r, marks);
    figures.drawStrip($("chart-strip"), r, marks);
    $("save-threshold").addEventListener("click", () => this.saveThreshold());
  }

  async saveThreshold() {
    const { thr, scoreText } = ReportPage;
    const value = Number($("threshold-input").value);
    const status = $("save-status");
    if (!(value > 0)) {
      status.className = "hint error";
      status.textContent = "Enter a positive number.";
      return;
    }
    try {
      // The threshold only fits the scores it was chosen on, so the movement score
      // of this report is saved with it.
      const r = cal.report;
      const saved = await post("/api/movement-score", {
        metric: r.metric, params: r.metric_params, threshold: value, stabilize: r.stabilize_plate,
        normalize_brightness: r.normalize_brightness, normalize_floor: r.normalize_floor,
      });
      if (cal.data) cal.data.threshold = saved.threshold;
      // Evaluate again, so "in use" is what was just saved.
      cal.takeReport(await cal.requestReport());
      this.draw();
      $("save-status").className = "hint";
      $("save-status").textContent = `Saved ${scoreText(saved.metric, saved.params, saved)} with threshold ${thr(saved.threshold)} to config.yaml. Analyses started from now on use them.`;
    } catch (error) {
      status.className = "hint error";
      status.textContent = error.message;
    }
  }

  // --- test: how good is the threshold in use, and where does it go wrong

  testReport(r) {
    const { thr, aucText, oneClassNote, survivalCaption, rocCaption, pooled, CONFUSION_CAPTION, STRIP_CAPTION } = ReportPage;
    const { stat, figure, section } = Markup;
    const c = r.current;
    return `
    <div class="stats">
      ${stat("Called right", pct(c.accuracy), `${c.n_wrong} wrong · threshold ${thr(r.threshold)}`)}
      ${this.outcomeStat("Moving called moving", c, r.rates.current, "moving", "still")}
      ${this.outcomeStat("Still called still", c, r.rates.current, "still", "moving")}
      ${stat("AUC", aucText(r), r.auc == null ? "needs moving and still labels" : "1 = perfect separation, 0.5 = chance")}
    </div>

    <div class="grid-2">
      ${figure("confusion", 1, "Confusion matrix at the threshold in use", CONFUSION_CAPTION)}
      ${figure("chart-survival", 2, "Survival rate: ground truth and the detector", survivalCaption(r, ReportPage.thresholdMarks(r).slice(0, 1)))}
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
      ${r.roc ? figure("chart-roc", 4, "ROC curve", rocCaption(r)) : section("ROC curve", `<p class="hint">${oneClassNote(r)}</p>`)}
    </div>

    ${r.roc ? figure("chart-strip", 5, "Motion score distribution", STRIP_CAPTION) : ""}

    ${section("Per zone", `<div class="table-wrap"><table class="clickable" id="zone-errors"></table></div>
      <p class="caption">Counts are mite-recordings, at the threshold in use. Select a zone to review its labels.</p>`)}`;
  }

  // The detector at the threshold in use beside the Discobox's original software,
  // on the same mite-recordings (the server's figures, calibration.calls_confusion).
  benchmarkTable(r) {
    const { thr, scoreText } = ReportPage;
    if (!r.benchmark) return `<p id="benchmark-status" class="hint">The benchmark has not been run on these datasets.</p>`;
    const share = (value) => (value == null ? "–" : `${(value * 100).toFixed(1)}%`);
    const rows = [
      [`Detector <span class="muted">${esc(scoreText(r.metric, r.metric_params, r))}</span>`, thr(r.threshold), r.current],
      [`Benchmark <span class="muted">${esc(r.benchmark.name)}, the Discobox's original software</span>`, r.benchmark.threshold, r.benchmark],
    ];
    return `<div class="table-wrap"><table>
    <thead><tr><th>Called by</th><th class="num">Threshold</th><th class="num">Precision</th><th class="num">Recall</th><th class="num">F1 score</th>
      <th class="num">Called right</th><th class="num">Moving called still</th><th class="num">Still called moving</th></tr></thead>
    <tbody>${rows.map(([name, threshold, c]) => `<tr>
      <td>${name}</td><td class="num">${threshold}</td>
      <td class="num">${share(c.precision)}</td><td class="num">${share(c.sensitivity)}</td><td class="num">${share(c.f1)}</td>
      <td class="num">${share(c.accuracy)}</td><td class="num">${c.moving_called_still}</td><td class="num">${c.still_called_moving}</td></tr>`).join("")}</tbody>
  </table></div>
  <p class="caption">Both on the same ${r.n_moving + r.n_still} labelled mite-recordings, moving being the positive call.
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
      figures.drawRoc($("chart-roc"), r, marks);
      figures.drawStrip($("chart-strip"), r, marks);
    }
    figures.drawZoneErrors(r);
  }
}
