// One mite: its key figures (its survival among them; a mite never seen moving is
// left out of the survival numbers), a close-up playing the recording shown, its motion
// score over time and a table of its recordings. Its close calls to check by eye
// are asked here (ReviewCheck).

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

    const nCorrected = mite.corrected.filter(Boolean).length;
    const nGone = mite.censored.filter(Boolean).length;
    const { STATES, STATE_NAMES } = ResultsPage;
    const movingNote = [
      nCorrected ? `${nCorrected} call${nCorrected === 1 ? "" : "s"} corrected by hand` : "",
      nGone ? `gone in ${nGone} more` : "",
    ].filter(Boolean).join(", ");
    const review = new ReviewCheck(this);
    const body = this.body;
    body.innerHTML = `
    ${this.staleBanner()}
    ${review.miteNote(mite)}
    <header class="page-head">
      <div>
        <h1>Mite ${this.miteId(mite)}</h1>
        <p class="meta">${this.callBadge(mite, ctx.lastIndex())} in the last recording · <a href="${ctx.href(`zone/${zone.id}`)}">Zone ${zone.id}</a> · ${Markup.groupTag(zone.label || "unlabeled", color)}</p>
        ${this.inStudy(mite) ? "" : `<p class="meta">Never seen moving, so left out of the survival numbers: it may have been dead from the start, or no live mite at all.</p>`}
      </div>
      ${Markup.pager(siblings, siblings.indexOf(mite), (m) => this.miteHref(m), (m) => `Mite ${m.id}`)}
    </header>

    <div class="stats">
      ${stat("Moving in", `${mite.n_moving}/${times.length - nGone}`, movingNote ? `recordings; ${movingNote}` : "recordings above the threshold")}
      ${stat("Last movement", this.lastMovementText(mite), mite.n_moving ? "last recording with movement" : "no movement in any recording")}
      ${stat("Survival", this.survivalText(mite), this.inStudy(mite) ? (this.lifeline(mite).dead ? "time of death" : this.lifeline(mite).lost ? "right-censored where it was last there" : "right-censored") : "")}
      ${stat("Max motion score", score(mite.max_score), `mean ${score(mite.mean_score)} · threshold ${score(results.threshold)}${this.normalizedNote()}`)}
    </div>

    <div class="grid-mite">
      ${this.clipFigure("mite-crop", 1, "Close-up",
        `The recording at ${this.shownTime()}, looped, 56 × 56 px around the mite: ${this.callBadge(mite, ctx.shown)} in it. The dots round the mite are darker where its outline changes more over the frames, and the arrow points to the side most of that change lies on: the longer, the more one-sided; green when the mite is called moving, orange when still.
        Where that is wrong, click the mite to step through moving, still, gone in this recording (e.g. fallen off) and gone from this recording on,
        or choose one in the table below.${review.ask(mite)}`, "crop-wrap square")}
      ${figure("chart-mite", 2, "Motion score over time",
        `${movingBadge(true)} at or above the threshold, ${movingBadge(false)} below it. ${ResultsPage.MOVING_NOTE}${review.review ? ` The shaded band, ${review.bandText()}, holds the scores too close to the threshold to trust.` : ""} Click a time to show that recording.${this.stillToCome()}`)}
    </div>

    ${section("Recordings", `<div class="table-wrap"><table class="clickable" id="recording-table">
        <thead><tr><th class="num">Time</th><th class="num">Motion score</th><th>Movement</th><th></th></tr></thead>
        <tbody>${times.map((t, i) => `<tr data-recording-row="${i}" tabindex="0" class="${i === ctx.shown ? "current" : ""}"
          title="Show this recording above">
          <td class="num">${minutes(t)}</td>
          <td class="num">${score(mite.scores[i])}</td>
          <td>${this.callBadge(mite, i)}${review.mark(mite, i)}</td>
          <td><select class="state-select" data-correct="${i}" aria-label="Mite ${esc(mite.id)} at ${minutes(t)}"
            title="Set by hand what the mite is in this recording. Gone, e.g. fallen off: censored, in this recording or from it on.">
            ${STATES.map((state) => `<option value="${state}"${state === this.callState(mite, i) ? " selected" : ""}>${STATE_NAMES[state]}</option>`).join("")}
          </select></td></tr>`).join("")}</tbody>
      </table></div>
      <p class="caption">A mite <i>gone</i> in a recording, e.g. one that fell off the plate, is censored there: it counts neither as moving nor as still.
        One gone from a recording on leaves the survival numbers at the recording before, alive as far as is known, unless it counted as dead by then.</p>`)}`;
    this.wire(body);
    review.wireMite(body, mite);
    body.querySelectorAll("[data-correct]").forEach((select) => {
      // the row's click and Enter show the recording
      ["click", "keydown"].forEach((type) => select.addEventListener(type, (event) => event.stopPropagation()));
      select.addEventListener("change", () => this.correctCall(mite, Number(select.dataset.correct), select.value));
    });
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
      range: review.review,
      series: [{
        name: `Mite ${mite.id}`,
        values: mite.scores,
        color: token("--ink"),
        width: 1.5,
        pointColors: mite.moving.map((moving, i) => token(mite.censored[i] ? "--muted" : moving ? "--moving" : "--still")),
      }],
      tooltipExtra: (i) => `<div class="tip-note">${mite.censored[i] ? "gone" : mite.moving[i] ? "moving" : "still"}${mite.corrected[i] ? ", corrected by hand" : mite.to_check.includes(i) ? ", to check" : ""}</div>`,
    });
  }

  // 56 × 56 px of the zone's clip around the mite: the crop's view box shows only that part.
  drawCloseUp(mite, zone) {
    const size = 56;
    const crop = this.crop(mite.x - size / 2, mite.y - size / 2, size, size);
    // A click steps the mite to its next state in the recording shown, as on the ground-truth page.
    const { STATES, STATE_NAMES } = ResultsPage;
    const next = STATES[(STATES.indexOf(this.callState(mite, ctx.shown)) + 1) % STATES.length];
    this.miteMarker(crop, mite, 22, {
      withLabel: false,
      onClick: () => this.correctCall(mite),
      hint: `Click: change to ${STATE_NAMES[next]}`,
    });
    $("mite-crop").appendChild(crop);
    this.drawOutlines(crop, zone.id);
    this.playClip(`/api/session/${ctx.sessionId}/clip/${ctx.shown}/${zone.id}`, $("mite-crop"), $("mite-crop").nextElementSibling,
      (clip) => ClipPlayer.onSvg(crop, clip));
  }
}
