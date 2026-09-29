// The overview's figures of motion scores and rests: every mite-recording at its
// score per group (Fig. 3), the moving ones with their box (Fig. 4, the box from
// the server), and the rests between movements per zone (Fig. 5, the rests from
// the server).

class ScoreFigures {
  constructor(page, groups) {
    this.page = page;
    this.groups = groups;
    this.rows = ctx.groupRows();
  }

  draw() {
    // Figs. 3 and 4 share their scale, so a group's scores compare between them.
    const { results } = this.page;
    const topScore = results.mites.reduce((top, mite) => mite.scores.reduce((a, b) => Math.max(a, b), top), results.threshold);
    this.drawGroupScores(topScore * 1.05);
    this.drawMovingScores(topScore * 1.05);
    this.drawRestPeriods();
  }

  // The row of the index-th group, the first group on top.
  rowY(index) {
    return this.rows.length - 1 - index;
  }

  // A mite in one recording at its motion score, on the row `y` of its group;
  // selecting it opens the mite in that recording.
  scorePoint(mite, recording, y, group, zones) {
    const { enterFrom } = resultsView;
    const moving = mite.moving[recording];
    const value = mite.scores[recording];
    return {
      x: value,
      y: y + ChartKit.jitter(`${mite.id}/${recording}`),
      color: token(moving ? "--moving" : "--still"),
      shape: moving ? "circle" : "cross",
      r: recording === ctx.shown ? 4.5 : 2.75,
      enter: enterFrom != null && recording >= enterFrom,
      // Built on hover only: a mite's glyphs span every recording, too much to build for every point.
      tip: () => `<div class="tip-title">Mite ${esc(mite.id)} · zone ${mite.zone_id} · ${minutes(this.page.results.times[recording])}</div>
      <div class="tip-note">${esc(group)} · zones ${zones.map((z) => z.id).join(", ")}</div>
      <div>${Markup.movingBadge(moving)} · score ${score(value)}</div>${this.page.movementGlyphs(mite)}
      <div class="tip-hint">Click to open this mite in this recording</div>`,
      onClick: () => resultsView.openMite(mite, recording),
    };
  }

  // On paper there is no recording on screen: every point the same size.
  static samePointSize(options) {
    return { ...options, points: options.points.map((point) => ({ ...point, r: 3 })) };
  }

  thresholdLine() {
    const { threshold } = this.page.results;
    return [{ value: threshold, label: `threshold ${score(threshold)}` }];
  }

  // Like the calibration's "Scores by your label": each mite-recording at its
  // score, one row per group (every zone with the same label), against the threshold.
  drawGroupScores(xMax) {
    const { rows } = this;
    const points = [];
    const categories = [];
    rows.forEach(({ group, zones, mites }, index) => {
      categories.push({ value: this.rowY(index), label: `${group} (${mites.length})` });
      mites.forEach((mite) => mite.scores.forEach((_value, recording) => {
        points.push(this.scorePoint(mite, recording, this.rowY(index), group, zones));
      }));
    });
    const container = $("chart-group-scores");
    container.exportAdjust = ScoreFigures.samePointSize;
    Charts.scatter(container, {
      height: Math.max(180, rows.length * 44 + 60),
      padLeft: 150,
      points,
      refX: this.thresholdLine(),
      yCategories: categories,
      yMin: -0.6, yMax: rows.length - 0.4,
      xMin: 0, xMax,
      xLabel: "Motion score",
      legend: [
        { name: "moving", color: token("--moving"), shape: "circle" },
        { name: "still", color: token("--still"), shape: "cross" },
      ],
    });
  }

  // Only the mite-recordings in which the mite moved, one row per group, with the
  // box plot of their scores: how strongly the mites move when they do, untouched
  // by how often they sit still.
  drawMovingScores(xMax) {
    const { rows } = this;
    const points = [];
    const boxes = [];
    const notes = [];
    const categories = [];
    rows.forEach(({ group, zones, mites, moving_scores: box }, index) => {
      const y = this.rowY(index);
      categories.push({ value: y, label: `${group} (${box ? box.n : 0})` });
      if (!box) {
        notes.push({ y, text: "no mite seen moving yet" });
        return;
      }
      boxes.push({
        y, color: groupColor(group, this.groups), lo: box.lo, q1: box.q1, median: box.median, q3: box.q3, hi: box.hi,
        tip: `<div class="tip-title">${esc(group)}</div>
        <div class="tip-note">${box.n} moving mite-recording${box.n === 1 ? "" : "s"} of ${box.n_mites} mite${box.n_mites === 1 ? "" : "s"}</div>
        <div>median ${score(box.median)}</div>
        <div>middle half ${score(box.q1)}–${score(box.q3)}</div>
        <div>whiskers ${score(box.lo)}–${score(box.hi)}</div>`,
      });
      mites.forEach((mite) => mite.moving.forEach((isMoving, recording) => {
        if (isMoving) points.push(this.scorePoint(mite, recording, y, group, zones));
      }));
    });
    const container = $("chart-moving-scores");
    container.exportAdjust = ScoreFigures.samePointSize;
    Charts.scatter(container, {
      height: Math.max(160, rows.length * 44 + 60),
      padLeft: 150,
      points,
      boxes,
      notes,
      refX: this.thresholdLine(),
      yCategories: categories,
      yMin: -0.6, yMax: rows.length - 0.4,
      xMin: 0, xMax,
      xLabel: "Motion score",
    });
  }

  // The rests pooled per zone, one ridge per zone, zones of a group together. The
  // axis reaches as far as two recordings can be apart.
  drawRestPeriods() {
    const { times } = this.page.results;
    const ridges = [];
    let without = 0;
    this.rows.forEach(({ group, zones }) => zones.forEach((zone) => {
      const rests = zone.rests;
      if (!rests) { without += 1; return; }
      const n = rests.values.length;
      ridges.push({
        group,
        label: `Zone ${zone.id} · ${shorten(group, 14)} (${n})`,
        color: groupColor(group, this.groups),
        values: rests.values,
        tip: `<div class="tip-title">Zone ${zone.id} · ${esc(group)}</div>
        <div class="tip-note">${n} rest${n === 1 ? "" : "s"}, of ${rests.n_mites} mite${rests.n_mites === 1 ? "" : "s"}</div>
        <div>median ${minutes(rests.median)}</div>
        <div>middle half ${minutes(rests.q1)}–${minutes(rests.q3)}</div>
        <div>shortest ${minutes(rests.shortest)}, longest ${minutes(rests.longest)}</div>
        <div class="tip-hint">Click to open zone ${zone.id}</div>`,
        onClick: () => router.go(ctx.href(`zone/${zone.id}`)),
      });
    }));

    $("intervals-left").textContent = without
      ? `${without} zone${without === 1 ? "" : "s"} where no mite was seen still between two movements ${without === 1 ? "is" : "are"} left out. ` : "";
    const domain = this.page.timeDomain();
    if (!ridges.length) {
      $("chart-intervals").innerHTML = `<p class="muted">No mite has been seen still between two movements${domain ? " yet" : ""}, so there is no rest to show.</p>`;
      return;
    }
    // Times that come in steps of the time between recordings are smoothed over at least half a step.
    const steps = times.slice(1).map((t, i) => t - times[i]).filter((step) => step > 0).sort((a, b) => a - b);
    const shownGroups = [...new Set(ridges.map((ridge) => ridge.group))];
    Charts.ridgeline($("chart-intervals"), {
      rows: ridges,
      xMin: 0,
      xMax: domain ? domain[1] - domain[0] : times[times.length - 1] - times[0],
      xLabel: "Rest of a mite between two movements (min)",
      xFormat: (v) => `${+v.toFixed(1)}`,
      minBandwidth: steps.length ? Charts.quantile(steps, 0.5) / 2 : 0,
      padLeft: 170,
      legend: shownGroups.length > 1 ? shownGroups.map((group) => ({ name: group, color: groupColor(group, this.groups), shape: "square" })) : [],
    });
  }
}
