// One zone: its key figures, its crop playing the recording shown, its mites
// moving and alive over time (beside its whole group's), the score of each mite
// and a table of them.

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
      ${stat("Mites", mites.length)}
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

    ${mites.length ? `<div class="block">${figure("chart-zone-alive", 3, "Mites alive", `Fraction of this zone's mites alive in each recording, with the whole group for comparison where the group spans several zones.
      ${this.aliveBandNote()} ${this.deathRule()}${this.aliveLiveNote()} Click a time to show that recording.${this.stillToCome()}`, "", this.deathControl())}</div>` : ""}

    ${mites.length ? `
    <div class="grid-2">
      ${figure("chart-zone-scores", 4, "Motion score per mite",
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
      yLabel: "Mites alive (%)",
      yMin: 0, yMax: 100,
      yFormat: (v) => `${Math.round(v)}`,
      series: [
        { name: `Zone ${zone.id}`, values: alive.alive, band: alive.alive_ci, color, step: true, markers: false },
        ...(groupAlive && spansZones
          ? [{ name: `all “${group}”`, values: groupAlive.alive, color: token("--muted"), dashed: true, markers: false, step: true }]
          : []),
      ],
      tooltipExtra: (i) => `<div class="tip-note">${alive.n_alive[i]} of ${mites.length} mites alive</div>`,
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
    <thead><tr><th>Mite</th><th>At ${this.shownTime()}</th><th class="num">Last movement</th><th class="num">Moving</th><th class="num">Mean</th><th class="num">Max</th></tr></thead>
    <tbody>${mites.map((mite) => `
      <tr data-href="${this.miteHref(mite)}" tabindex="0">
        <td><a href="${this.miteHref(mite)}">${esc(mite.id)}</a></td>
        <td>${Markup.movingBadge(this.movingShown(mite))}</td>
        <td class="num">${this.lastMovementText(mite)}</td>
        <td class="num">${mite.n_moving}/${times.length}</td>
        <td class="num">${score(mite.mean_score)}</td>
        <td class="num">${score(mite.max_score)}</td>
      </tr>`).join("")}</tbody>`;
    Markup.wireRowLinks(table);
  }
}
