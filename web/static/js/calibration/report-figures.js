// The calibration report's figures: the confusion matrix, the windows and offsets
// of the mite's own threshold, the survival rate over time (and per group), the
// scores against the thresholds, the ROC curve, and where on the plate the errors
// are. Every observation, from whichever dataset, opens its mite in its recording.

class ReportFigures {
  // The error map of a recording no labelled mite of the dataset has.
  static NO_MITES = { mites: [], counts: { correct: 0, "missed-positive": 0, "missed-negative": 0 } };

  // The Discobox's original software, which the test report compares with (classes/benchmark.py).
  static BENCHMARK = "benchmark (Abilium)";

  // Where a row comes from: the recording folder and, when known, the recording in it.
  static sourceText(row) {
    return `${esc(row.dataset_name)}${row.recording_name ? ` / ${esc(row.recording_name)}` : ""}`;
  }

  // Two thresholds (ReportPage.thresholdMarks) compare the scores with the same
  // thing: one threshold for every mite, or the mite's median over the same window.
  static sameWindow(a, b) {
    return a.call.window === b.call.window && (!a.call.window || a.call.centred === b.call.centred);
  }

  static percentFormat(v) {
    return `${Math.round(v * 100)}%`;
  }

  observationTip(row, r) {
    const { thr } = ReportPage;
    return `<div class="tip-title">Mite ${esc(row.mite_id)} · zone ${row.zone_id} · ${minutes(row.time)}</div>
    <div class="tip-note">${ReportFigures.sourceText(row)}</div>
    <div>labelled ${row.movement}, called ${row.outcome.split("_called_")[1]}</div>
    <div class="tip-note">score ${thr(row.score)}${r.threshold_fits ? ` · its threshold in use ${thr(row.threshold)}` : ""}</div>
    <div class="tip-hint">Click to see it in its recording</div>`;
  }

  openObservation(row) {
    return () => cal.goToMite(row.dataset, row.zone_id, row.recording);
  }

  // The confusion counts `c` with their `rates` (the server's), each a fraction of its row.
  confusionTable(c, rates) {
    const cell = (truth, call) => {
      const count = ReportPage.called(c, truth, call);
      const rate = ReportPage.called(rates, truth, call);
      return `<td class="cm" style="--f:${rate ?? 0}">
      <b>${count}</b><small>${pct(rate)}</small>
      <span class="cm-name">${truth} called ${call}</span></td>`;
    };
    const { movingBadge } = Markup;
    return `<table class="confusion">
    <thead>
      <tr><th rowspan="2">Ground truth</th><th colspan="2" class="cm-group">Called by the detector</th><th rowspan="2" class="num">Total</th></tr>
      <tr><th class="cm-col">moving</th><th class="cm-col">still</th></tr>
    </thead>
    <tbody>
      <tr><td>${movingBadge(true)}</td>${cell("moving", "moving")}${cell("moving", "still")}<td class="num">${c.n_moving}</td></tr>
      <tr><td>${movingBadge(false)}</td>${cell("still", "moving")}${cell("still", "still")}<td class="num">${c.n_still}</td></tr>
    </tbody>
  </table>`;
  }

  // Whose calls a survival figure draws beside the ground truth: the detector's at
  // each threshold of `marks` and, when the report has it, the benchmark's.
  static callers(curves, marks) {
    return [
      ...marks.map((mark) => ({ key: mark.key, name: `detector, ${mark.name}`, value: mark.text, color: mark.color })),
      ...(curves.benchmark ? [{ key: "benchmark", name: ReportFigures.BENCHMARK, value: "", color: token("--series-7") }] : []),
    ];
  }

  // The Kaplan-Meier curve of the ground truth (black, with its confidence band)
  // against those of the detector's calls, one per threshold, and of the
  // benchmark's (the server's, calibration.survival_curves). The labels' curve
  // comes last so it is drawn on top where the curves coincide.
  survivalSeries(curves, marks, { legend = true } = {}) {
    return [
      ...ReportFigures.callers(curves, marks).map((caller) => ({
        name: `${caller.name} ${caller.value}`.trim(),
        values: curves[caller.key].alive,
        color: caller.color, dashed: true, step: true, markers: false, legend,
      })),
      {
        name: "ground truth", values: curves.truth.alive, band: { low: curves.truth.low, high: curves.truth.high },
        color: token("--ink"), width: 2.25, step: true, markers: false, legend,
      },
    ];
  }

  // How many mites each curve rests on, for the tooltip.
  survivalNote(curves, marks) {
    const count = (name, curve) => `<div class="tip-note">${name}: ${curve.n_mites} mites, ${curve.n_dead} dead, ${curve.n_left_out} left out</div>`;
    return [count("ground truth", curves.truth),
      ...ReportFigures.callers(curves, marks).map((caller) => count(caller.name, curves[caller.key]))].join("");
  }

  drawSurvival(container, curves, times, marks) {
    Charts.line(container, {
      x: times,
      yLabel: "Survival rate (%)",
      yMin: 0, yMax: 100,
      yFormat: (v) => `${Math.round(v)}`,
      noDirectLabels: true,
      series: this.survivalSeries(curves, marks),
      tooltipExtra: () => this.survivalNote(curves, marks),
    });
  }

  // Small multiples: one chart per group, sharing one legend.
  drawGroupSurvival(r, marks) {
    $("group-legend").innerHTML = Charts.legendHtml(this.survivalSeries(r.survival, marks).map((s) => ({
      name: s.name, color: s.color, ...(s.dashed ? { dashed: true } : { shape: "line" }),
    })));
    const container = $("group-moving");
    r.groups.forEach((group, index) => {
      const curves = group.survival;
      const n = curves.truth.n_mites;
      const leftOut = curves.truth.n_left_out;
      const card = document.createElement("div");
      card.className = "group-card fig";
      const id = `group-moving-${index}`;
      card.innerHTML = `<div class="group-card-head">${Markup.groupTag(group.group, token(group.group === "unlabeled" ? "--series-other" : "--muted"))}
      <span class="hint">${n} mite${n === 1 ? "" : "s"}${leftOut ? `, ${leftOut} never moving left out` : ""}</span>
      ${ChartDownloads.buttons(id, `Survival rate · ${group.group} (${n} mites)`, "group-legend")}</div>`;
      const plot = document.createElement("div");
      plot.id = id;
      card.appendChild(plot);
      container.appendChild(card);
      if (!curves.truth.n_mites && ReportFigures.callers(curves, marks).every((caller) => !curves[caller.key].n_mites)) {
        plot.innerHTML = `<p class="muted">No mite of this group was seen moving, by the labels, the detector or the benchmark, so none is in the study.</p>`;
        return;
      }
      Charts.line(plot, {
        x: r.times,
        height: 190,
        yLabel: "Survival rate (%)",
        yMin: 0, yMax: 100,
        yFormat: (v) => `${Math.round(v)}`,
        series: this.survivalSeries(curves, marks, { legend: false }),
        tooltipExtra: () => this.survivalNote(curves, marks),
      });
    });
  }

  // Moving labels in one row, still in the other, jittered so equal scores stay
  // visible. By the scores themselves while every threshold shown is the same for
  // all mites; else by each score's margin above its mite's own threshold (the
  // last mark's), so one line at 0 separates the calls.
  drawStrip(container, r, marks) {
    const { thr } = ReportPage;
    const shown = marks[marks.length - 1];
    const own = marks.some((mark) => mark.call.window);
    Charts.scatter(container, {
      height: 220,
      points: r.observations.map((row) => ({
        x: own ? row[shown.margin] : row.score,
        y: (row.movement === "moving" ? 1 : 0) + ChartKit.jitter(`${row.dataset}/${row.mite_id}/${row.recording}`),
        color: token(row.movement === "moving" ? "--moving" : "--still"),
        shape: row.movement === "moving" ? "circle" : "cross",
        r: 3.5,
        tip: this.observationTip(row, r),
        onClick: this.openObservation(row),
      })),
      refX: own ? [{ value: 0, label: `${shown.name}: ${shown.text}` }]
        : marks.map((mark) => ({ value: mark.call.offset, label: `${mark.name} ${thr(mark.call.offset)}` })),
      yCategories: [{ value: 0, label: "○ still" }, { value: 1, label: "● moving" }],
      yMin: -0.5, yMax: 1.5,
      ...(own ? {} : { xMin: 0 }),
      xLabel: own ? "Motion score above the mite's own threshold in that recording" : "Motion score in that recording",
    });
  }

  // Every window the server tried, with its best offset (ThresholdSearch.table):
  // a line for the centred windows, one for the trailing ones, against one
  // threshold for every mite. Selecting a point hands it to `onPick`.
  drawWindows(container, r, marks, onPick) {
    const { thr } = ReportPage;
    const { percentFormat } = ReportFigures;
    const rows = r.windows.filter((w) => w.window);
    const single = r.windows.find((w) => !w.window);
    const kinds = [{ centred: true, name: "centred", color: token("--ink") }, { centred: false, name: "trailing", color: token("--series-4") }];
    Charts.scatter(container, {
      height: 300,
      yMax: 1,
      xFormat: (v) => (Number.isInteger(v) ? `${v}` : ""),
      yFormat: percentFormat,
      xLabel: "Window (recordings)",
      yLabel: "Moving and still called right (mean)",
      lines: kinds.map((kind) => ({
        points: rows.filter((w) => w.centred === kind.centred).map((w) => [w.window, w.balance]), color: kind.color, width: 2,
      })),
      points: rows.map((w) => {
        const mark = marks.find((m) => m.call.window === w.window && m.call.centred === w.centred);
        return {
          x: w.window, y: w.balance, r: mark ? 6 : 3.5, label: mark?.name,
          color: mark ? mark.color : kinds.find((kind) => kind.centred === w.centred).color,
          tip: `<div class="tip-title">${w.window} recordings, ${w.centred ? "centred" : "trailing"}</div>
          <div>best offset ${thr(w.offset)}</div>
          <div>${percentFormat(w.sensitivity)} of moving labels called moving</div>
          <div>${percentFormat(w.specificity)} of still labels called still</div>
          <div class="tip-note">${percentFormat(w.accuracy)} called right · ${w.moving_called_still} moving called still, ${w.still_called_moving} still called moving</div>
          <div class="tip-hint">Click to fill it in</div>`,
          onClick: () => onPick(w),
        };
      }),
      refY: single ? [{ value: single.balance, label: `one threshold for every mite, ${thr(single.offset)}` }] : [],
      legend: [
        ...kinds.map((kind) => ({ name: `${kind.name} window`, color: kind.color, shape: "line" })),
        ...marks.filter((mark) => mark.call.window).map((mark) => ({ name: mark.name, color: mark.color, shape: "circle" })),
      ],
    });
  }

  // What each offset of the last mark's window does to the two kinds of label
  // (its ROC curve, read against the offset). Offsets at which nearly every
  // mite is called the same are left off, so the part that matters has the room.
  drawOffsets(container, marks) {
    const { thr } = ReportPage;
    const { percentFormat, sameWindow } = ReportFigures;
    const main = marks[marks.length - 1];
    const { tpr, specificity, thresholds } = main.roc;
    const steps = thresholds.map((offset, i) => ({ offset, moving: tpr[i], still: specificity[i] })).filter((step) => step.offset != null);
    const telling = steps.filter((step) => step.moving > 0.25 && step.still > 0.02);
    const shown = telling.length > 1 ? telling : steps;
    const what = main.call.window ? "offset" : "threshold";
    Charts.scatter(container, {
      height: 300,
      yMin: 0, yMax: 1,
      yFormat: percentFormat,
      xLabel: main.call.window ? "Offset above the mite's own median" : "Threshold",
      yLabel: "Called right",
      lines: [
        { points: shown.map((step) => [step.offset, step.moving]), color: token("--moving"), width: 2 },
        { points: shown.map((step) => [step.offset, step.still]), color: token("--still"), width: 2 },
      ],
      points: shown.flatMap((step) => ["moving", "still"].map((kind) => ({
        x: step.offset, y: step[kind], r: 3, hidden: true,
        tip: `<div class="tip-title">${what} ${thr(step.offset)}</div>
        <div>${percentFormat(step.moving)} of moving labels called moving</div>
        <div>${percentFormat(step.still)} of still labels called still</div>`,
      }))),
      refX: marks.filter((mark) => sameWindow(mark, main)).map((mark) => ({ value: mark.call.offset, label: `${mark.name} ${thr(mark.call.offset)}` })),
      legend: [
        { name: "moving called moving", color: token("--moving"), shape: "line" },
        { name: "still called still", color: token("--still"), shape: "line" },
      ],
    });
  }

  // The ROC curve of the last mark's window, over every offset; the curve of a
  // mark with another window is drawn thin beside it, each mark on its own curve.
  drawRoc(container, marks) {
    const { thr } = ReportPage;
    const { percentFormat, sameWindow } = ReportFigures;
    const main = marks[marks.length - 1];
    const others = marks.filter((mark) => !sameWindow(mark, main));
    const { fpr, tpr, thresholds } = main.roc;
    const what = main.call.window ? "offset" : "threshold";
    Charts.scatter(container, {
      square: true,
      height: 400,
      xMin: 0, xMax: 1, yMin: 0, yMax: 1,
      xFormat: percentFormat,
      yFormat: percentFormat,
      xLabel: "Still called moving (false positive rate)",
      yLabel: "Moving called moving",
      lines: [
        { points: [[0, 0], [1, 1]], color: token("--muted"), width: 1, dashed: true },
        ...others.map((mark) => ({ points: mark.roc.fpr.map((f, i) => [f, mark.roc.tpr[i]]), color: mark.color, width: 1.25 })),
        { points: fpr.map((f, i) => [f, tpr[i]]), color: token("--ink"), width: 2 },
      ],
      points: [
        // Every step of the curve can be hovered for its offset.
        ...fpr.slice(1).map((f, i) => ({
          x: f, y: tpr[i + 1], r: 3, hidden: true,
          tip: `<div class="tip-title">${what} ${thr(thresholds[i + 1])}</div>
          <div>${percentFormat(tpr[i + 1])} of moving labels called moving</div>
          <div>${percentFormat(f)} of still labels called moving</div>`,
        })),
        ...marks.map((mark, i) => {
          const c = mark.confusion;
          const f = mark.rates.still_called_moving;
          return {
            // the second label goes under its point, so close thresholds stay readable
            x: f, y: c.sensitivity, r: 6, color: mark.color, label: mark.name, labelDy: i ? 16 : 0,
            tip: `<div class="tip-title">${mark.name}: ${mark.text}</div>
            <div>${percentFormat(c.sensitivity)} of moving labels called moving</div>
            <div>${percentFormat(f)} of still labels called moving</div>`,
          };
        }),
      ],
      legend: [
        { name: others.length ? `ROC, ${main.name}` : "ROC", color: token("--ink"), shape: "line" },
        ...others.map((mark) => ({ name: `ROC, ${mark.name}`, color: mark.color, shape: "line" })),
        { name: "chance", color: token("--muted"), dashed: true },
        ...marks.map((mark) => ({ name: `${mark.name} threshold`, color: mark.color, shape: "circle" })),
      ],
    });
  }

  // --- where the errors are (test report)

  // The dataset the error map shows: the last one chosen, else the one on the
  // ground-truth page, else the first in the report.
  mapDataset(r) {
    const ids = r.datasets.map((d) => d.id);
    return [cal.mapDataset, cal.datasetId].find((id) => ids.includes(id)) || ids[0];
  }

  // One dot per mite, of the kind the server gave it (classes/error_map.py): right
  // in every recording shown, or its more frequent error.
  drawOutcomeMap(r, datasetId, recordingValue) {
    const container = $("outcome-map");
    const dataset = r.datasets.find((d) => d.id === datasetId);
    const map = r.error_map[datasetId];
    const shown = (recordingValue === "" ? map?.all : map?.recordings[recordingValue]) || ReportFigures.NO_MITES;
    const preview = `/api/calibration/datasets/${encodeURIComponent(datasetId)}/preview?t=${cal.stamp}`;
    const place = PlateView.overlay(container, preview, dataset.image);
    dataset.zones.forEach((zone) => {
      const box = document.createElement("div");
      box.className = "zone passive";
      Object.assign(box.style, place(zone.x1, zone.y1, zone.x2, zone.y2));
      container.appendChild(box);
    });

    shown.mites.forEach((mite) => {
      const { moving_missed: movingMissed, still_missed: stillMissed } = mite;
      const dot = document.createElement("span");
      dot.className = `outcome-dot ${mite.kind}`;
      dot.style.left = percent(mite.x, dataset.image.width);
      dot.style.top = percent(mite.y, dataset.image.height);
      const list = (errors) => errors.map((when) => `${minutes(when.time)}${when.recording_name ? ` (${esc(when.recording_name)})` : ""}`).join(", ");
      dot.addEventListener("mousemove", (event) => Charts.showTooltip(event,
        `<div class="tip-title">Mite ${esc(mite.mite_id)} · zone ${mite.zone_id}</div>
       <div class="tip-note">${esc(mite.dataset_name)}</div>
       <div>${movingMissed.length + stillMissed.length} of ${mite.n} recordings called wrong</div>
       ${movingMissed.length ? `<div class="tip-note">moving called still: ${list(movingMissed)}</div>` : ""}
       ${stillMissed.length ? `<div class="tip-note">still called moving: ${list(stillMissed)}</div>` : ""}
       <div class="tip-hint">Click to see it in its recording</div>`));
      dot.addEventListener("mouseleave", Charts.hideTooltip);
      dot.addEventListener("click", () => cal.goToMite(mite.open.dataset, mite.open.zone_id, mite.open.recording));
      container.appendChild(dot);
    });
    const { counts } = shown;

    $("outcome-legend").innerHTML = Charts.legendHtml([
      { name: `always right (${counts.correct})`, color: token("--muted"), shape: "ring" },
      { name: `moving called still (${counts["missed-positive"]})`, color: token("--series-2"), shape: "circle" },
      { name: `still called moving (${counts["missed-negative"]})`, color: token("--series-7"), shape: "square" },
    ]);
  }

  // Every zone of every pooled dataset, each opening its own recording folder.
  drawZoneErrors(r) {
    const table = $("zone-errors");
    const wrong = (n) => `<td class="num${n ? " error" : ""}">${n}</td>`;
    const folders = new Map(r.datasets.map((d) => [d.id, d.data_dir]));
    table.innerHTML = `
    <thead><tr><th>Recording folder</th><th>Zone</th><th>Label</th><th class="num">Mites</th>
      <th class="num">Moving</th><th class="num">Still</th>
      <th class="num">Moving called still</th><th class="num">Still called moving</th></tr></thead>
    <tbody>${r.zones.map((zone, index) => `
      <tr data-index="${index}" tabindex="0">
        <td title="${esc(folders.get(zone.dataset))}">${esc(zone.dataset_name)}</td>
        <td><a href="#" data-index="${index}">Zone ${zone.id}</a></td>
        <td>${zone.group === "unlabeled" ? "" : esc(zone.group)}</td>
        <td class="num">${zone.n_mites}</td>
        <td class="num">${zone.n_moving}</td><td class="num">${zone.n_still}</td>
        ${wrong(zone.moving_called_still)}${wrong(zone.still_called_moving)}
      </tr>`).join("")}</tbody>`;
    const open = (event, index) => {
      event.preventDefault();
      const zone = r.zones[index];
      cal.goToMite(zone.dataset, zone.id, 0);
    };
    table.querySelectorAll("tr[data-index]").forEach((row) => {
      row.addEventListener("click", (event) => open(event, Number(row.dataset.index)));
      row.addEventListener("keydown", (event) => { if (event.key === "Enter") open(event, Number(row.dataset.index)); });
    });
  }
}
