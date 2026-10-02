// One zone: its key figures, its crop playing the recording shown, its mites
// moving and their survival rate over time (beside its whole group's), each
// mite's lifeline, the score of each mite and a table of them.

class ZonePage extends ResultsPage {
  show(zoneId) {
    const { results } = this;
    const zone = ctx.zone(zoneId);
    if (!zone) { location.replace(ctx.href("results")); return; }
    const groups = ctx.resultGroups();
    const group = zone.label || "unlabeled";
    const color = groupColor(group, groups);
    const mites = ctx.mitesIn(zone.id);
    const { times } = results;
    const { stat, figure, section, movingBadge, groupTag } = Markup;
    this.breadcrumb([["Results", ctx.href("results")], [this.zoneName(zone), ctx.href(`zone/${zone.id}`)]]);

    const neverMoved = zone.n_never_moved;
    const survival = results.survival.zones[zone.id] || { n_mites: 0, n_left_out: 0 };
    // Step through the zones with mites; an empty zone, opened from the plate map, among all.
    const siblings = zone.n_mites ? ctx.zonesWithMites() : results.zones;
    const body = this.body;

    body.innerHTML = `
    ${this.staleBanner()}
    <header class="page-head">
      <div>
        <h1>Zone ${zone.id}</h1>
        <p class="meta">${groupTag(group, color)}</p>
      </div>
      ${Markup.pager(siblings, siblings.indexOf(zone), (z) => ctx.href(`zone/${z.id}`), (z) => `Zone ${z.id}`)}
    </header>

    <div class="stats">
      ${stat("Mites", mites.length, survival.n_left_out ? `${survival.n_mites} in the survival numbers, ${survival.n_left_out} never seen moving left out` : "")}
      ${stat("Moving in the last recording", mites.length ? `${zone.n_moving_last} <small>(${pct(zone.n_moving_last / mites.length)})</small>` : "–")}
      ${stat("Moving mite-recordings", mites.length ? `${zone.n_moving_observations} <small>of ${mites.length * times.length}</small>` : "–",
        neverMoved ? `${neverMoved} mite${neverMoved === 1 ? "" : "s"} never seen moving` : "")}
      ${stat("Mean motion score", score(zone.overall_mean_score), `threshold ${score(results.threshold)}`)}
    </div>

    <div class="clip-block">
      ${this.clipFigure("zone-crop", 1, `Zone ${zone.id} · recording at ${this.shownTime()}`,
        `The recording, looped, with each detected mite ${movingBadge(true)} or ${movingBadge(false)} in it. Hover a mite for every recording, select it to open it.`, "crop-wrap truth-crop")}
    </div>

    ${mites.length ? `<div class="block">${figure("chart-zone-moving", 2, "Mites moving", `Fraction of this zone's mites moving in each recording, with the whole group for comparison where the group spans several zones. Click a time to show that recording.${this.stillToCome()}`)}</div>` : ""}

    ${mites.length ? `<div class="block">${figure("chart-zone-alive", 3, "Survival rate", `Survival rate of this zone's mites in each recording, with the whole group for comparison where the group spans several zones.
      ${this.aliveBandNote()} ${this.deathRule()} ${this.leftOutNote(survival.n_left_out)}${this.aliveLiveNote()} Click a time to show that recording.${this.stillToCome()}`, "", this.deathControl())}</div>` : ""}

    ${mites.length ? `<div class="block">${figure("chart-zone-lifelines", 4, "Lifelines", `One line per mite, from the first recording to its death (×) or,
      for a mite still alive in the last recording, to there (○, right-censored: it lived at least that long). The dots on a line are the recordings in which the mite moved.
      The death times follow the rule of Fig. 3. ${this.leftOutNote(survival.n_left_out)}Hover a line's end for its numbers; select it to open the mite.${this.stillToCome()}`)}</div>` : ""}

    ${mites.length ? `
    <div class="grid-2">
      ${figure("chart-zone-scores", 5, "Motion score per mite",
        "Thin lines are single mites; the black line is the mean. The dashed line is the threshold. Hover to identify a mite, select to open it; click elsewhere to show that recording.")}
      ${section("Mites", `<div class="table-wrap"><table class="clickable" id="mite-table"></table></div>`)}
    </div>` : `<p class="muted">No mites were detected in this zone.</p>`}`;
    this.wire(body);

    this.drawCrop(zone, color, mites);
    if (!mites.length) return;
    // The whole group beside the zone, where the group spans several zones.
    const groupRow = ctx.groupRow(group);
    const spansZones = Boolean(groupRow && groupRow.zones.length > 1);
    this.drawMoving(zone, group, color, mites, spansZones);
    this.drawAlive(zone, group, color, mites, spansZones);
    this.drawLifelines(color, mites);
    this.drawScores(zone, mites);
    this.drawMiteTable(mites);
  }

  // The zone's crop with some margin, each mite marked, playing the recording shown.
  drawCrop(zone, color, mites) {
    const margin = 20;
    const crop = this.crop(zone.x1 - margin, zone.y1 - margin, zone.x2 - zone.x1 + 2 * margin, zone.y2 - zone.y1 + 2 * margin);
    crop.appendChild(this.zoneOutline(zone, color));
    const radius = PlateView.ringRadius(zone);
    mites.forEach((mite) => this.miteMarker(crop, mite, radius, { onClick: () => resultsView.openMite(mite) }));
    $("zone-crop").appendChild(crop);
    this.playClip(`/api/session/${ctx.sessionId}/clip/${ctx.shown}/${zone.id}`, $("zone-crop"), $("zone-crop").nextElementSibling,
      (clip) => ClipPlayer.onSvg(crop, clip));
  }

  drawMoving(zone, group, color, mites, spansZones) {
    const groupCurve = this.results.groups.find((g) => g.group === group);
    this.timeChart($("chart-zone-moving"), {
      yLabel: "Mites moving (%)",
      yMin: 0, yMax: 100,
      yFormat: (v) => `${Math.round(v)}`,
      series: [
        { name: `Zone ${zone.id}`, values: zone.moving.map((v) => v * 100), color },
        ...(groupCurve && spansZones
          ? [{ name: `all “${group}”`, values: groupCurve.moving.map((v) => (v == null ? null : v * 100)), color: token("--muted"), dashed: true, markers: false }]
          : []),
      ],
      tooltipExtra: (i) => `<div class="tip-note">${zone.n_moving[i]} of ${mites.length} mites moving</div>`,
    });
  }

  // The survival numbers are the server's (results.survival).
  drawAlive(zone, group, color, mites, spansZones) {
    const { survival } = this.results;
    const alive = survival.zones[zone.id];
    const groupAlive = survival.groups.find((g) => g.group === group);
    this.timeChart($("chart-zone-alive"), {
      yLabel: "Survival rate (%)",
      yMin: 0, yMax: 100,
      yFormat: (v) => `${Math.round(v)}`,
      series: [
        { name: `Zone ${zone.id}`, values: alive.alive, band: alive.alive_ci, color, step: true, markers: false },
        ...(groupAlive && spansZones
          ? [{ name: `all “${group}”`, values: groupAlive.alive, color: token("--muted"), dashed: true, markers: false, step: true }]
          : []),
      ],
      tooltipExtra: (i) => `<div class="tip-note">${alive.n_alive[i]} of ${alive.n_mites} mites alive</div>`,
    });
  }

  // One row per mite, first on top: a line from the first recording to its death
  // (×) or its censoring in the last recording (○), with a dot where it moved. A
  // mite left out has no line, only its id greyed out. The lifelines are the
  // server's (results.survival.mites).
  drawLifelines(color, mites) {
    const { times } = this.results;
    const rowY = (index) => mites.length - 1 - index;
    const domain = this.timeDomain();
    const lines = [];
    const points = [];
    const notes = [];
    mites.forEach((mite, index) => {
      const y = rowY(index);
      const { in_study: inStudy, time, dead } = this.lifeline(mite);
      if (!inStudy) {
        notes.push({ y, text: "never seen moving: left out" });
        return;
      }
      lines.push({ points: [[times[0], y], [time, y]], color, width: 2 });
      mite.moving.forEach((moving, recording) => {
        if (moving) points.push({ x: times[recording], y, color: token("--moving"), shape: "circle", r: 3.25 });
      });
      points.push({
        x: time, y, color: dead ? token("--ink") : color, shape: dead ? "cross" : "ring", r: 5,
        tip: `<div class="tip-title">Mite ${esc(mite.id)}</div>
        <div>${this.survivalText(mite)}</div>${this.movementGlyphs(mite)}
        <div class="tip-hint">Click to open this mite</div>`,
        onClick: () => resultsView.openMite(mite),
      });
    });
    Charts.scatter($("chart-zone-lifelines"), {
      height: Math.max(140, mites.length * 22 + 60),
      padLeft: 80,
      lines,
      points,
      notes,
      yCategories: mites.map((mite, index) => ({ value: rowY(index), label: `Mite ${mite.id}`, muted: !this.inStudy(mite) })),
      yMin: -0.6, yMax: mites.length - 0.4,
      xMin: domain ? domain[0] : times[0],
      xMax: domain ? domain[1] : times[times.length - 1],
      xLabel: "Time (min)",
      xFormat: (v) => `${+v.toFixed(1)}`,
      legend: [
        { name: "died", color: token("--ink"), shape: "cross" },
        { name: "alive at the end (censored)", color, shape: "ring" },
        { name: "moved", color: token("--moving"), shape: "circle" },
      ],
    });
  }

  drawScores(zone, mites) {
    this.timeChart($("chart-zone-scores"), {
      yLabel: "Motion score",
      noDirectLabels: true,
      threshold: { value: this.results.threshold, label: "threshold" },
      series: [
        ...mites.map((mite) => ({
          name: `Mite ${mite.id}`,
          values: mite.scores,
          color: token("--series-1"),
          width: 1,
          faint: true,
          legend: false,
          tooltip: false,
          onClick: () => resultsView.openMite(mite),
        })),
        { name: "mean", values: zone.mean_score, color: token("--ink"), width: 2 },
      ],
    });
  }

  drawMiteTable(mites) {
    const { times } = this.results;
    const table = $("mite-table");
    table.innerHTML = `
    <thead><tr><th>Mite</th><th>At ${this.shownTime()}</th><th class="num">Last movement</th><th>Survival</th><th class="num">Moving</th><th class="num">Mean</th><th class="num">Max</th></tr></thead>
    <tbody>${mites.map((mite) => `
      <tr data-href="${this.miteHref(mite)}" tabindex="0">
        <td>${this.miteId(mite, this.miteHref(mite))}</td>
        <td>${Markup.movingBadge(this.movingShown(mite))}</td>
        <td class="num">${this.lastMovementText(mite)}</td>
        <td class="${this.inStudy(mite) ? "" : "muted"}">${this.survivalText(mite)}</td>
        <td class="num">${mite.n_moving}/${times.length}</td>
        <td class="num">${score(mite.mean_score)}</td>
        <td class="num">${score(mite.max_score)}</td>
      </tr>`).join("")}</tbody>`;
    Markup.wireRowLinks(table);
  }
}
