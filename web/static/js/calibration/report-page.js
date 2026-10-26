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
    this.lastRecording = new LastRecording();
    this.wrongCalls = new WrongCalls();
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

  // How far a threshold ("current" or "suggested") puts the deaths from the labels', e.g. "3.49 rec."
  static deathText(r, key) {
    const error = r.death_error?.[key]?.mae;
    return error == null ? "–" : `${(+error).toFixed(2)} rec.`;
  }

  static rocCaption(r) {
    return `Every possible threshold, from the highest (bottom left) to the lowest (top right). AUC ${ReportPage.aucText(r)}. Hover the curve for the threshold at each step.`;
  }

  // Who is left out of a survival curve, by the labels and by the detector's calls.
  static leftOutText(curves, marks) {
    const parts = [`${curves.truth.n_left_out} never labelled moving`,
      ...marks.map((mark) => `${curves[mark.key].n_left_out} never called moving at the threshold ${mark.name}`),
      ...(curves.benchmark ? [`${curves.benchmark.n_left_out} never called moving by the benchmark`] : []),
      ...(curves.outline ? [`${curves.outline.n_left_out} never called moving by the outline change`] : [])];
    return `Left out: ${parts.join(", ")}.`;
  }

  static survivalCaption(r, marks) {
    return `The Kaplan–Meier survival rate of the labelled mites: by the ground truth (black, with its 95% confidence band) and as the detector's calls
    ${r.survival.benchmark ? "and the benchmark's " : ""}${r.survival.outline ? `and the outline change between recordings (Fig. ${ReportPage.betweenNumber(r)}) ` : ""}would have it. A mite counts as alive up to the last recording in which it moved and as dead from the next labelled one on; a mite moving in its last
    labelled recording is right-censored there. Only mites seen moving at least once are in the study, each curve by its own calls, as a mite never
    seen moving may have been dead from the start. ${ReportPage.leftOutText(r.survival, marks)} The closer the dashed curves follow the black one,
    the better the threshold gives the true survival. Hover for the numbers.${ReportPage.poolNote(r)}`;
  }

  // The number of the figure of the outline change between recordings, after the poke test's.
  static betweenNumber(r) {
    return r.roc ? 9 : 7;
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
    this.wrongCalls.checking = false;  // back on the report: the ground-truth page asks about no wrong call
    const left = [
      r.n_not_a_mite ? `${r.n_not_a_mite} detection${r.n_not_a_mite > 1 ? "s" : ""} not a mite, left out` : "",
      r.n_unlabelled ? `${r.n_unlabelled} mite-recordings unlabelled, left out` : "",
    ].filter(Boolean).join(" · ");

    body.innerHTML = `
    ${cal.reportStale ? `<div class="banner">The ground truth or the poke test changed since this report.
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
        ${cal.data ? '<a class="button secondary small" href="#/cal/truth">Edit ground truth</a>' : ""}
        ${cal.data && testing ? '<a class="button secondary small" href="#/cal/poke">Poke test</a>' : ""}
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

  // The datasets that can be pooled: every recording with ground truth saved.
  poolable() {
    return cal.datasets;
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
        <span class="hint">Old recordings are scored again with the movement score below, from their recordings, never from old scores.</span></span>
    </label>` : "";
    const shown = !cal.datasetId || this.pooling();
    const rows = cal.datasets.map((d) => {
      const inReport = used.get(d.id);
      const open = d.id === cal.datasetId;
      return `<li><label class="dataset-option">
      <input type="checkbox" class="dataset-check" value="${esc(d.id)}" ${cal.selected.includes(d.id) ? "checked" : ""}>
      <span class="group-name" title="${esc(d.data_dir)}">${esc(d.name)}${open ? ' <span class="muted">(on the ground-truth page)</span>' : ""}</span>
      <span class="hint">${savedDate(d.saved_at)} ·
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
        Hint.error($("dataset-status"), "Keep at least one dataset.");
        return;
      }
      change(chosen);
    }));
  }

  // --- the movement score the report is scored with

  // The movement score is outline_variability, always, on frames that follow a
  // shaking plate: nothing to choose, the report only says what it scored with.
  scorePicker(r) {
    const { thr, scoreText } = ReportPage;
    if (!cal.scores) return `<p class="hint">The movement score could not be read.</p>`;
    return `<p id="score-status" class="hint">Scored with <code>${esc(scoreText(r.metric, r.metric_params, r))}</code>.
      Threshold in use for analyses: ${thr(cal.scores.in_use.threshold)}.</p>`;
  }

  // The test report only says which score it tests: scoring again with another one
  // there would judge it by a threshold set for a different score.
  scoreTested(r) {
    const { thr, scoreText } = ReportPage;
    return `<p class="hint">Tested: <code>${esc(scoreText(r.metric, r.metric_params, r))}</code> with the threshold in use, ${thr(r.threshold)}.
      </p>`;
  }

  wireScorePicker() {}

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

  // A stat tile for one kind of wrong call, e.g. still called moving: the count at
  // the suggested threshold, its share of its row and the count in use.
  wrongStat(title, r, truth, other) {
    const { called } = ReportPage;
    return Markup.stat(title, `${called(r.best, truth, other)}`,
      `${pct(called(r.rates.best, truth, other))} of ${r.best[`n_${truth}`]} ${truth} · in use: ${called(r.current, truth, other)}`);
  }

  calibrateReport(r) {
    const { thr, oneClassNote, survivalCaption, rocCaption, scoreText, deathText, CONFUSION_CAPTION, STRIP_CAPTION } = ReportPage;
    const { stat, figure, section } = Markup;
    if (r.suggested_threshold == null) {
      return `<div class="banner">${oneClassNote(r)}</div>
      <div class="stats">
        ${stat("Called right", pct(r.current.accuracy), `threshold in use ${thr(r.threshold)}`)}
        ${this.outcomeStat("Moving called moving", r.current, r.rates.current, "moving", "still")}
        ${this.outcomeStat("Still called still", r.current, r.rates.current, "still", "moving")}
        ${stat("Death time off by", deathText(r, "current"), "mean, in recordings")}
      </div>
      <div class="grid-2">
        ${figure("confusion", 1, "Confusion matrix at the threshold in use", CONFUSION_CAPTION)}
        ${figure("chart-survival", 2, "Survival rate: ground truth and the detector", survivalCaption(r, ReportPage.thresholdMarks(r)))}
      </div>
      ${this.wrongCalls.html()}`;
    }
    const same = Math.abs(r.suggested_threshold - r.threshold) < 0.005;
    const shown = cal.shownThreshold === "current" ? "current" : "best";
    return `
    <div class="stats stats-5">
      ${stat("Suggested threshold", thr(r.suggested_threshold), `F1 ${r.best.f1.toFixed(3)} · ${same ? "the one in use" : `in use: ${thr(r.threshold)}`}`)}
      ${stat("Called right", pct(r.best.accuracy), `${r.best.n_wrong} wrong · in use: ${pct(r.current.accuracy)}`)}
      ${this.wrongStat("Moving called still", r, "moving", "still")}
      ${this.wrongStat("Still called moving", r, "still", "moving")}
      ${stat("Death time off by", deathText(r, "suggested"), `mean, in recordings · in use: ${deathText(r, "current")}`)}
    </div>
    <p class="caption">Key figures at the suggested threshold; "in use" is the threshold in config.yaml. The suggestion is the threshold with the
      largest F1 of the calls moving, mite-recording by mite-recording: 2 × moving called moving over 2 × moving called moving + moving called still
      + still called moving. The death time is reported, not chosen on.</p>

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
        <p class="hint">The suggestion has the largest F1: it weighs a moving recording called still the same as a still one called moving, however many
          more still labels there are; among thresholds that make the same calls, it lies halfway into the gap between the scores on either side.
          A mite dies at the recording after its last movement, so a still recording called moving long after a death moves the death there
          (<i>death error</i>, the mean distance in recordings between the death by the detector and by the labels): the close calls that can do that are
          asked to be checked by eye on the result pages. Saving moves the band to check by eye in config.yaml with the threshold, keeping how far it
          reaches below it against above. Every analysis started after saving uses the new value.
          Check it with <b>Test the threshold</b> on a <em>different</em> recording: on this one it looks better than it will be.</p>
        ${this.comparisonTable(r)}`)}
    </div>

    ${this.wrongCalls.html()}

    <div class="grid-2">
      ${figure("chart-survival", 2, "Survival rate: ground truth and the detector", survivalCaption(r, ReportPage.thresholdMarks(r)))}
      ${figure("chart-strip", 3, "Motion score distribution", STRIP_CAPTION)}
    </div>

    <div class="grid-2">
      ${figure("chart-roc", 4, "ROC curve", rocCaption(r))}
    </div>`;
  }

  comparisonTable(r) {
    const { thr } = ReportPage;
    // The values as shown everywhere else, so the same threshold never rounds two ways.
    const rows = [["in use", r.threshold, r.current, "current"], ...(r.best ? [["suggested", r.suggested_threshold, r.best, "suggested"]] : [])];
    const deathError = (key) => ReportPage.deathText(r, key);
    return `<div class="table-wrap"><table>
    <thead><tr><th>Threshold</th><th class="num">Value</th><th class="num">F1</th><th class="num">Called right</th>
      <th class="num">Moving called still</th><th class="num">Still called moving</th>
      <th class="num" title="Mean distance, in recordings, between each mite's death by the detector and by the labels">Death error</th></tr></thead>
    <tbody>${rows.map(([name, value, c, key]) => `<tr>
      <td>${name}</td><td class="num">${thr(value)}</td><td class="num">${c.f1 == null ? "–" : c.f1.toFixed(3)}</td><td class="num">${pct(c.accuracy)}</td>
      <td class="num">${c.moving_called_still}</td><td class="num">${c.still_called_moving}</td><td class="num">${deathError(key)}</td></tr>`).join("")}</tbody>
  </table></div>`;
  }

  drawCalibrateFigures(r) {
    const marks = ReportPage.thresholdMarks(r);
    const { figures } = this;
    figures.drawSurvival($("chart-survival"), r.survival, r.times, marks);
    const matrix = (shown) => (shown === "current" ? figures.confusionTable(r.current, r.rates.current) : figures.confusionTable(r.best, r.rates.best));
    // The wrong calls listed are those of the confusion matrix shown.
    const wrong = (shown) => (shown === "current" ? this.wrongCalls.draw(r, r.current, false) : this.wrongCalls.draw(r, r.best, true));
    if (r.suggested_threshold == null) {
      $("confusion").innerHTML = matrix("current");
      wrong("current");
      return;
    }
    $("confusion").innerHTML = matrix(cal.shownThreshold);
    wrong(cal.shownThreshold);
    document.querySelectorAll("[data-shown]").forEach((button) => button.addEventListener("click", () => {
      cal.shownThreshold = button.dataset.shown;
      document.querySelectorAll("[data-shown]").forEach((b) => b.classList.toggle("secondary", b !== button));
      $("confusion").innerHTML = matrix(button.dataset.shown);
      wrong(button.dataset.shown);
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
      Hint.error(status, "Enter a positive number.");
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
      Hint.note($("save-status"), `Saved ${scoreText(saved.metric, saved.params, saved)} with threshold ${thr(saved.threshold)}${
        saved.review_band ? ` and its band to check by eye, ${thr(saved.review_band[0])} to ${thr(saved.review_band[1])},` : ""} to config.yaml. Analyses started from now on use them.`);
    } catch (error) {
      Hint.error(status, error.message);
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

    ${section("The last recording", `<div id="last-recording" data-number="${r.roc ? 6 : 4}">${this.lastRecording.html(r, r.roc ? 6 : 4)}</div>`)}

    ${section("Per zone", `<div class="table-wrap"><table class="clickable" id="zone-errors"></table></div>
      <p class="caption">Counts are mite-recordings, at the threshold in use. Select a zone to review its labels.</p>`)}

    ${section("Poke test", this.pokeReport(r, r.roc ? 8 : 6))}

    ${r.between_recordings ? section("Between recordings", this.betweenReport(r)) : ""}`;
  }

  // The survival of the mites poked by hand, by the pokes and by the detector at
  // the threshold in use (the server's r.poke, classes/ground_truth/poke_test.py): a mite that
  // moved when poked was alive up to then, one that did not is dead from then on.
  pokeReport(r, number) {
    const { pooled } = ReportPage;
    const poke = r.poke;
    if (!poke) {
      return `<p class="hint">No poke test was entered for ${pooled(r) ? "these recordings" : "this recording"}.
        ${cal.data ? '<a href="#/cal/poke">Enter one</a>: which mites moved when you poked them, to compare their survival with that by the detector.' : ""}</p>`;
    }
    const outline = poke.others?.outline;
    return Markup.figure("chart-poke-survival", number, `Survival rate of the poked mites: the pokes and the detector${outline ? " and the outline change" : ""}`,
      `The Kaplan–Meier survival rate of the ${poke.poke.n_mites} poked mites by the pokes (black, with its 95% confidence band) and as the detector's calls
      at the threshold in use would have it (dashed)${outline ? `, and the outline change between recordings (Fig. ${ReportPage.betweenNumber(r)})` : ""}, on the same mites. By the pokes a mite dies at the first poke it did not answer, so in the recording after it;
      one that answered every poke is right-censored at its last one, where it still counts among the living. By the detector a mite dies at the recording after its last movement,
      one never called moving at the first recording, and one moving in its last recording is right-censored there${outline ? "; likewise by the outline change" : ""}. A poke only says dead by then, so the black curve
      falls at the pokes, not at the deaths: the dashed one may fall earlier and still agree, and should not be above it at a poke.
      ${poke.final_poke ? "The last point is the poke after the last recording, where the detector saw nothing, so its curve ends before it." : ""}
      ${poke.n_left_out ? `Left out: ${plural(poke.n_left_out, "mite")} that answered a poke after not answering an earlier one.` : ""} Hover for the numbers.`);
  }

  // Every mite's outline change from one recording to the next, a change opening the
  // box does not fake (the server's r.between_recordings, classes/scoring/outline_change.py).
  betweenReport(r) {
    const between = r.between_recordings;
    const { thr } = ReportPage;
    return Markup.figure("chart-between", ReportPage.betweenNumber(r), "Outline change between recordings, mite by mite",
      `One row per mite seen moving by the ground truth (${between.mites.length}), in the order the ground truth has them die, the first at the top.
      Each cell is how far the mite's outline changed from the recording before, in pixels (log scale): its shape alone, at the turn that fits best,
      so a mite pushed or turned when the box is opened does not change; one that moves a leg does. A change above ${thr(between.limit)} px counts,
      and a mite moved in a recording when the change into it and into the one before both count; it dies at the recording after its last movement, as by the detector.
      Over them, on the right-hand axis, the Kaplan–Meier survival rate by the ground truth (black, with its 95% confidence band), which runs along the left edge of the quiet part,
      and by the outline change (dashed)${r.poke ? `, and by the pokes (purple, on the poked mites only, Fig. ${r.roc ? 8 : 6})` : ""}.
      What is coloured right of the black curve changed after the mite's last labelled movement. Hover a cell for its numbers, click it to see the mite in that recording.`);
  }

  // The detector at the threshold in use beside the Discobox's original software and
  // the outline change between recordings: how far each puts the mites' deaths from
  // where the ground truth puts them, in recordings (the server's figures, calibration.death_errors).
  benchmarkTable(r) {
    const { thr, scoreText } = ReportPage;
    if (!r.benchmark && !r.death_error.outline) return `<p id="benchmark-status" class="hint">The benchmark has not been run on these datasets.</p>`;
    const share = (n, of) => (of ? `${n} <span class="muted">(${(100 * n / of).toFixed(0)}%)</span>` : "–");
    const recordings = (value, signed = false) => (value == null ? "–" : `${signed && value > 0 ? "+" : ""}${value.toFixed(2)}`);
    const rows = [
      [`Detector <span class="muted">${esc(scoreText(r.metric, r.metric_params, r))}</span>`, thr(r.threshold), r.death_error.current],
      ...(r.benchmark ? [[`Benchmark <span class="muted">${esc(r.benchmark.name)}, the Discobox's original software</span>`, r.benchmark.threshold, r.death_error.benchmark]] : []),
      ...(r.death_error.outline ? [[`Outline change <span class="muted">between recordings, Fig. ${ReportPage.betweenNumber(r)}</span>`,
        `${thr(r.between_recordings.limit)} px`, r.death_error.outline]] : []),
    ];
    return `<div class="table-wrap"><table>
    <thead><tr><th>Called by</th><th class="num">Threshold</th>
      <th class="num" title="Mean absolute error of the death time, in recordings">Death time off by (MAE)</th>
      <th class="num" title="Mean error: positive when the mites die later than by the ground truth">Mean error</th>
      <th class="num">Same recording</th><th class="num">One recording off</th><th class="num">Further off</th>
      <th class="num">Too early</th><th class="num">Too late</th></tr></thead>
    <tbody>${rows.map(([name, threshold, d]) => `<tr>
      <td>${name}</td><td class="num">${threshold}</td>
      <td class="num"><b>${recordings(d.mae)}</b></td><td class="num">${recordings(d.bias, true)}</td>
      <td class="num">${share(d.n_exact, d.n_mites)}</td><td class="num">${share(d.n_one_off, d.n_mites)}</td><td class="num">${share(d.n_further, d.n_mites)}</td>
      <td class="num">${d.n_early}</td><td class="num">${d.n_late}</td></tr>`).join("")}</tbody>
  </table></div>
  <p class="caption">How closely each follows the ground truth's survival curve (Fig. 2), mite by mite, on the same ${r.death_error.current.n_mites} labelled mites.
    A mite dies at the recording after its last movement; <b>death time off by</b> is the mean absolute error of that recording against the ground truth's,
    counted in recordings: 1 is one recording off on average. A mite never called moving is dead from its first recording, one still moving in its last
    dies after it. <b>Mean error</b> is positive when the mites die later than by the ground truth, which a still mite called moving does, and negative when
    earlier, which a missed last movement does.${r.benchmark ? ` The benchmark denoises each recording's frames, takes the difference of every frame to the first and
    calls a mite moving when a difference above ${r.benchmark.threshold} lies on it; that threshold is fixed in its code, where the detector's is
    config.yaml's.` : ""}${r.death_error.outline ? ` The outline change calls a mite moving from one recording to the next, not within one (Fig. ${ReportPage.betweenNumber(r)}),
    so it sees a mite that goes on changing after its last movement within a recording, and puts that death later.` : ""} Their survival curves are in Fig. 2 and in the groups' below.</p>`;
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
    this.lastRecording.draw(r);
    if (r.poke) figures.drawPokeSurvival($("chart-poke-survival"), r);
    if (r.between_recordings) figures.drawBetween($("chart-between"), r);
  }
}
