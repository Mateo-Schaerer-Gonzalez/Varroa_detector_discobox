// The results overview: key figures, the plate map playing the recording shown,
// the survival rate by group, the survival against the negative control, movement
// per zone, the group summary and the score figures.

class OverviewPage extends ResultsPage {
  show() {
    const { results } = this;
    this.breadcrumb([["Results", ctx.href("results")]]);
    const { summary, times } = results;
    const groups = ctx.resultGroups();
    const body = this.body;
    const span = times.length > 1 ? `over ${minutes(times[times.length - 1] - times[0])}` : "";
    const { stat, figure, section, movingBadge } = Markup;

    body.innerHTML = `
    ${this.staleBanner()}
    <header class="page-head">
      <div>
        <h1>Results</h1>
        <p class="meta">${esc($("folder-name").textContent)} · ${results.n_recordings} recordings ${span} · movement threshold ${this.thresholdText()}</p>
      </div>
    </header>

    <div class="stats">
      ${stat("Mites detected", summary.n_mites)}
      ${stat("Moving in the last recording", `${summary.n_moving_last} <small>(${pct(summary.n_moving_last / summary.n_mites)})</small>`)}
      ${stat("Groups", summary.n_groups)}
      ${stat("Recordings", results.n_recordings, span)}
    </div>

    <div class="clip-block">
      ${this.clipFigure("result-plate", 1, `Plate map · recording at ${this.shownTime()}`,
        `The recording at ${this.shownTime()}, looped, with every detected mite ${movingBadge(true)} or ${movingBadge(false)} in it.
        Choose a recording above, or click a time in a chart. Select a zone to open it.`, "plate")}
    </div>

    <div class="block">
      ${figure("chart-group-alive", 2, "Survival rate by group",
        `Survival rate of each group's mites in each recording, pooling every zone with that label. ${this.aliveBandNote()} ${this.deathRule()}
        ${this.leftOutNote(results.survival.n_left_out)}${this.aliveLiveNote()}
        Click a time to show that recording.${this.stillToCome()}`, "", this.deathControl())}
    </div>

    ${section("Survival against the negative control", `<div class="table-wrap"><table id="logrank-table"></table></div>
      <p class="caption" id="logrank-caption"></p>`)}

    ${section("Movement per zone", `<div id="zone-cards" class="zone-cards"></div>
      <p class="caption">Fraction of each zone's mites moving in each recording, on a 0–100% scale; the number is how many moved in the last recording.
        Zones without mites are left out. Select a zone to open it.${this.stillToCome()}</p>`)}

    ${section("Group summary", `<div class="table-wrap"><table id="group-table"></table></div>
      <p class="caption"><b>Moving</b> is the share of all mite-recordings in which the mite moved.</p>`)}

    <div class="block">${figure("chart-group-scores", 3, "Motion scores by group",
      `Every mite in every recording at its motion score, one row per group, pooling every zone with that label: ${movingBadge(true)} at or above ${this.ownThreshold() ? "the mite's own threshold" : "the threshold (dashed line)"},
      ${movingBadge(false)} below it; the number is the group's mites. Points of the recording shown are drawn larger. Select a point to open that mite in that recording.`)}</div>

    <div class="block">${figure("chart-moving-scores", 4, "Motion scores of moving mites by group",
      `Only the recordings in which a mite moved, so the many still ones do not pull the distribution down: how strongly each group's mites move when they do.
      The box spans the middle half of these scores with a line at the median; the whiskers reach the furthest scores within 1.5 box lengths.
      The number is how many moving mite-recordings the row holds. Same scale as Fig. 3. Hover a box for its numbers; select a point to open that mite in that recording.`)}</div>

    <div class="block">${figure("chart-intervals", 5, "Rest between movements, per zone",
      `For every mite, each rest: the time from a recording in which it moved, through at least one in which it was ${movingBadge(false)}, to the next one in which it moved,
      pooled per zone and coloured by group. Moving in two recordings in a row is no rest, so the shortest rest is two times between recordings.
      Each ridge is a smoothed distribution scaled to its own peak, with a tick along its base for every rest and a line at the median.
      <span id="intervals-left"></span>Hover a ridge for its numbers; select it to open the zone.`)}</div>

    ${section("Files", `<ul class="files">
        <li><a href="${ctx.fileUrl(results.excel)}" download>${esc(results.excel)}</a> <span class="muted">measurements, group summary and movement over time</span></li>
      </ul>
      <p class="caption">${this.resultsFolderNote()}Every chart above can be downloaded as SVG or PNG from the buttons beside its title.</p>`)}`;
    this.wire(body);

    this.timeChart($("chart-group-alive"), {
      yLabel: "Survival rate (%)",
      yMin: 0, yMax: 100,
      yFormat: (v) => `${Math.round(v)}`,
      series: results.survival.groups.map(({ group, alive, alive_ci, n_mites: n }) => ({
        name: `${group} (${n})`,
        values: alive,
        band: alive_ci,
        color: groupColor(group, groups),
        step: true,
        markers: false,
      })),
    });

    this.drawPlate(groups);
    this.drawZoneCards(groups);
    this.drawGroupTable(groups);
    new SurvivalTable(this, groups).draw($("logrank-table"), $("logrank-caption"));
    new ScoreFigures(this, groups).draw();
  }

  // Where the workbook and figures are saved on disk: results/<recording>/.
  resultsFolderNote() {
    const dir = ctx.mode === "live" ? live.status && live.status.out_dir : ctx.session && ctx.session.results_dir;
    if (!dir) return "";
    const short = dir.split(/[\\/]/).filter(Boolean).slice(-2).join("/");
    return `The workbook and the figures are saved in <code title="${esc(dir)}">${esc(short)}/</code>, replaced when this recording is analysed again. `;
  }

  // The plate map: a link per zone with mites, a dot per mite, over the recording shown.
  drawPlate(groups) {
    const { results } = this;
    const plate = $("result-plate");
    const place = PlateView.overlay(plate, ctx.fileUrl(results.preview), results.image);

    results.zones.filter((zone) => !zone.n_mites).forEach((zone) => {
      plate.appendChild(PlateView.emptyZone(place, zone, `Zone ${zone.id}: no mites detected`));
    });

    const nMovingShown = (zone) => zone.n_moving[ctx.shown];
    ctx.zonesWithMites().forEach((zone) => {
      const color = groupColor(zone.label || "unlabeled", groups);
      const link = document.createElement("a");
      link.className = "zone result";
      link.href = ctx.href(`zone/${zone.id}`);
      link.setAttribute("aria-label", `Zone ${zone.id}, ${zone.label || "unlabeled"}, ${zone.n_mites ? `${nMovingShown(zone)} of ${zone.n_mites} mites moving at ${this.shownTime()}` : "no mites"}`);
      Object.assign(link.style, place(zone.x1, zone.y1, zone.x2, zone.y2));
      link.style.setProperty("--zone-color", color);
      link.innerHTML = `<span class="zone-num">${zone.id}</span>`;

      // Name and count go in the plate's label area, clear of the mite dots.
      const rect = PlateView.textRect(zone);
      const text = document.createElement("a");
      text.className = "text-zone";
      text.href = link.href;
      text.tabIndex = -1;
      Object.assign(text.style, place(rect.x1, rect.y1, rect.x2, rect.y2));
      text.style.setProperty("--zone-color", color);
      const count = zone.n_mites ? `${nMovingShown(zone)}/${zone.n_mites} moving at ${this.shownTime()}` : "no mites";
      text.title = `Zone ${zone.id} · ${zone.label || "unlabeled"} · ${count}`;
      text.innerHTML = `<span class="text-tag">${esc(zone.label || "unlabeled")}
      <small>${zone.n_mites ? `${nMovingShown(zone)}/${zone.n_mites}` : "–"}</small></span>`;

      PlateView.linkHover([link, text]);
      plate.append(link, text);
    });

    // A dot per mite: moving or still in the recording shown.
    results.mites.forEach((mite) => {
      const dot = document.createElement("span");
      dot.className = `mite-dot ${mite.censored[ctx.shown] ? "rejected" : this.movingShown(mite) ? "moving" : "still"}`;
      dot.style.left = percent(mite.x, results.image.width);
      dot.style.top = percent(mite.y, results.image.height);
      plate.appendChild(dot);
    });

    // The whole plate, scaled down; the zones and dots sit on it in percent.
    const img = plate.querySelector("img");
    this.playClip(`/api/session/${ctx.sessionId}/clip/${ctx.shown}`, plate, plate.nextElementSibling, () => (src) => { img.src = src; });
  }

  // Small multiples: one framed mini plot of the fraction moving per zone.
  drawZoneCards(groups) {
    const container = $("zone-cards");
    ctx.zonesWithMites().forEach((zone) => {
      const color = groupColor(zone.label || "unlabeled", groups);
      const card = document.createElement("a");
      card.className = "zone-card";
      card.href = ctx.href(`zone/${zone.id}`);
      card.innerHTML = `
      <div class="zone-card-head">
        <span class="zone-card-id">Zone ${zone.id}</span>
        <span class="zone-card-value" title="moving in the last recording">${zone.n_mites ? `${zone.n_moving_last}/${zone.n_mites}` : "–"}</span>
      </div>
      <div class="zone-card-group">${Markup.groupTag(zone.label || "unlabeled", color)}</div>`;
      const plot = document.createElement("div");
      plot.className = "zone-card-plot";
      Charts.spark(plot, { values: zone.moving, color, step: false, x: this.results.times, xDomain: this.timeDomain() });
      card.appendChild(plot);
      container.appendChild(card);
    });
  }

  drawGroupTable(groups) {
    const columns = [
      ["group", "Group"], ["n_mites", "Mites"], ["fraction_moving", "Moving"],
      ["n_moving_last_recording", "Moving in last recording"],
      ["mean_score", "Mean score"], ["std_score", "SD"], ["median_score", "Median"],
    ];
    const format = (key, value) => (key === "fraction_moving" ? pct(value) : key.endsWith("score") ? score(value) : esc(value));
    $("group-table").innerHTML = `
    <thead><tr>${columns.map(([key, name]) => `<th class="${key === "group" ? "" : "num"}">${name}</th>`).join("")}</tr></thead>
    <tbody>${this.results.summary.groups.map((row) => `<tr>${columns.map(([key]) =>
      key === "group"
        ? `<td>${Markup.groupTag(row.group, groupColor(row.group, groups))}</td>`
        : `<td class="num">${format(key, row[key])}</td>`).join("")}</tr>`).join("")}</tbody>`;
  }
}
