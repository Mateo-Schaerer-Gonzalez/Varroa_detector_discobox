// One mite: its key figures (its survival among them; a mite never seen moving is
// left out of the survival numbers), a close-up playing the recording shown, its motion
// score over time and a table of its recordings.

class MitePage extends ResultsPage {
  show(miteId) {
    const { results } = this;
    const mite = results.mites.find((m) => m.id === miteId);
    if (!mite) { location.replace(ctx.href("results")); return; }
    const zone = ctx.zone(mite.zone_id);
    const siblings = ctx.mitesIn(zone.id);
    const { times } = results;
    const color = groupColor(zone.label || "unlabeled", ctx.resultGroups());
    const { stat, figure, section, movingBadge } = Markup;
    this.breadcrumb([["Results", ctx.href("results")], [this.zoneName(zone), ctx.href(`zone/${zone.id}`)], [`Mite ${mite.id}`, ""]]);

    const body = this.body;
    body.innerHTML = `
    ${this.staleBanner()}
    <header class="page-head">
      <div>
        <h1>Mite ${this.miteId(mite)}</h1>
        <p class="meta">${movingBadge(mite.moving[ctx.lastIndex()])} in the last recording · <a href="${ctx.href(`zone/${zone.id}`)}">Zone ${zone.id}</a> · ${Markup.groupTag(zone.label || "unlabeled", color)}</p>
        ${this.inStudy(mite) ? "" : `<p class="meta">Never seen moving, so left out of the survival numbers: it may have been dead from the start, or no live mite at all.</p>`}
      </div>
      ${Markup.pager(siblings, siblings.indexOf(mite), (m) => this.miteHref(m), (m) => `Mite ${m.id}`)}
    </header>

    <div class="stats">
      ${stat("Moving in", `${mite.n_moving}/${times.length}`, "recordings above the threshold")}
      ${stat("Last movement", this.lastMovementText(mite), mite.n_moving ? "last recording with movement" : "no movement in any recording")}
      ${stat("Survival", this.survivalText(mite), this.inStudy(mite) ? (this.lifeline(mite).dead ? "time of death" : "right-censored") : "")}
      ${stat("Max motion score", score(mite.max_score), `mean ${score(mite.mean_score)} · threshold ${score(results.threshold)}`)}
    </div>

    <div class="grid-mite">
      ${this.clipFigure("mite-crop", 1, "Close-up",
        `The recording at ${this.shownTime()}, looped, 140 × 140 px around the mite: ${movingBadge(this.movingShown(mite))} in it.`, "crop-wrap square")}
      ${figure("chart-mite", 2, "Motion score over time",
        `${movingBadge(true)} at or above the threshold, ${movingBadge(false)} below it. ${ResultsPage.MOVING_NOTE} Click a time to show that recording.${this.stillToCome()}`)}
    </div>

    ${section("Recordings", `<div class="table-wrap"><table class="clickable" id="recording-table">
        <thead><tr><th class="num">Time</th><th class="num">Motion score</th><th>Movement</th></tr></thead>
        <tbody>${times.map((t, i) => `<tr data-recording-row="${i}" tabindex="0" class="${i === ctx.shown ? "current" : ""}"
          title="Show this recording above">
          <td class="num">${minutes(t)}</td>
          <td class="num">${score(mite.scores[i])}</td>
          <td>${movingBadge(mite.moving[i])}</td></tr>`).join("")}</tbody>
      </table></div>`)}`;
    this.wire(body);
    body.querySelectorAll("[data-recording-row]").forEach((row) => {
      const index = Number(row.dataset.recordingRow);
      row.addEventListener("click", () => resultsView.showRecording(index));
      row.addEventListener("keydown", (event) => { if (event.key === "Enter") resultsView.showRecording(index); });
    });

    this.drawCloseUp(mite, zone);
    this.timeChart($("chart-mite"), {
      yLabel: "Motion score",
      noDirectLabels: true,
      threshold: { value: results.threshold, label: "threshold" },
      series: [{
        name: `Mite ${mite.id}`,
        values: mite.scores,
        color: token("--ink"),
        width: 1.5,
        pointColors: mite.moving.map((moving) => token(moving ? "--moving" : "--still")),
      }],
      tooltipExtra: (i) => `<div class="tip-note">${mite.moving[i] ? "moving" : "still"}</div>`,
    });
  }

  // 140 × 140 px of the zone's clip around the mite: the crop's view box shows only that part.
  drawCloseUp(mite, zone) {
    const size = 140;
    const crop = this.crop(mite.x - size / 2, mite.y - size / 2, size, size);
    this.miteMarker(crop, mite, 22, { withLabel: false });
    $("mite-crop").appendChild(crop);
    this.playClip(`/api/session/${ctx.sessionId}/clip/${ctx.shown}/${zone.id}`, $("mite-crop"), $("mite-crop").nextElementSibling,
      (clip) => ClipPlayer.onSvg(crop, clip));
  }
}
