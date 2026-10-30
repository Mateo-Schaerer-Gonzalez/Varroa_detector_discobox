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
    // Every mite runs on its own timer: a mite a live run added later from the
    // recording it was added in, which is its 0; the recordings before are not its.
    const own = this.clockOf(mite);
    const nNotYet = own.start;
    const mine = (i) => i >= nNotYet;
    const nAside = mite.censored.filter((gone, i) => gone && mine(i) && this.setAside(mite, i)).length;
    const nGone = mite.censored.filter((gone, i) => gone && mine(i)).length - nAside;
    const { STATES, STATE_NAMES } = ResultsPage;
    const movingNote = [
      nCorrected ? `${nCorrected} call${nCorrected === 1 ? "" : "s"} corrected by hand` : "",
      nGone ? `gone in ${nGone} more` : "",
      nAside ? `set aside in ${nAside} more (disturbed)` : "",
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
        ${nNotYet ? `<p class="meta">Added during the run, at ${minutes(times[nNotYet])}: its times below count from then, its own 0.</p>` : ""}
        ${this.inStudy(mite) ? "" : `<p class="meta">Never seen moving, so left out of the survival numbers: it may have been dead from the start, or no live mite at all.</p>`}
      </div>
      ${Markup.pager(siblings, siblings.indexOf(mite), (m) => this.miteHref(m), (m) => `Mite ${m.id}`)}
    </header>

    <div class="stats">
      ${stat("Moving in", `${mite.n_moving}/${times.length - nNotYet - nGone}`, movingNote ? `recordings; ${movingNote}` : "recordings above the threshold")}
      ${stat("Last movement", this.lastMovementText(mite), mite.n_moving ? (nNotYet ? "after it was added" : "last recording with movement") : "no movement in any recording")}
      ${stat("Survival", this.survivalText(mite), this.inStudy(mite) ? (this.lifeline(mite).dead ? "time of death" : this.lifeline(mite).lost ? "right-censored where it was last there" : "right-censored") : "")}
      ${stat("Max motion score", score(mite.max_score), `mean ${score(mite.mean_score)} · threshold ${score(results.threshold)}${this.normalizedNote()}`)}
    </div>

    <div class="grid-mite">
      ${this.clipFigure("mite-crop", 1, "Close-up",
        `The recording at ${this.shownTime()}, 56 × 56 px around the mite: ${this.callBadge(mite, ctx.shown)} in it. The frame is green when the mite is called moving, orange when still, grey when gone, dashed when the call was corrected by hand. The dots round the mite are darker where its outline changes more over the frames.
        Where that is wrong, click the mite to switch it between moving and still, or choose a call in the table below.${review.ask(mite)}`, "crop-wrap square")}
      ${figure("chart-mite", 2, "Motion score over time",
        `${movingBadge(true)} at or above the threshold, ${movingBadge(false)} below it. ${ResultsPage.MOVING_NOTE}${review.review ? ` The shaded band, ${review.bandText()}, holds the scores too close to the threshold to trust.` : ""} Click a time to show that recording.${this.stillToCome()}`)}
    </div>

    ${section("Recordings", `<div class="table-wrap"><table class="clickable" id="recording-table">
        <thead><tr><th class="num">${nNotYet ? "Since added" : "Time"}</th><th class="num">Motion score</th><th>Movement</th><th></th></tr></thead>
        <tbody>${own.times.map((t, k) => [t, k + nNotYet]).map(([t, i]) => `<tr data-recording-row="${i}" tabindex="0" class="${i === ctx.shown ? "current" : ""}"
          title="Show this recording above${nNotYet ? ` (at ${minutes(times[i])} of the run)` : ""}">
          <td class="num">${minutes(t)}</td>
          <td class="num">${score(mite.scores[i])}</td>
          <td>${this.callBadge(mite, i)}${review.mark(mite, i)}</td>
          <td>${this.unfollowed(mite, i) ? "" : `<select class="state-select" data-correct="${i}" aria-label="Mite ${esc(mite.id)} at ${minutes(t)}"
            title="Set by hand what the mite is in this recording. Gone, e.g. fallen off: censored, in this recording or from it on.">
            ${STATES.map((state) => `<option value="${state}"${state === this.callState(mite, i) ? " selected" : ""}>${STATE_NAMES[state]}</option>`).join("")}
          </select>`}</td></tr>`).join("")}</tbody>
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
    this.drawScoreChart(mite, review);
  }

  // The motion score over the mite's own timer: its recordings only, from 0 where
  // it was added (a mite there from the start: the run's times).
  drawScoreChart(mite, review) {
    const { results } = this;
    const clock = this.clockOf(mite);
    this.clockChart($("chart-mite"), clock, {
      xLabel: clock.start ? "Time since the mite was added (min)" : undefined,
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
      tooltipExtra: (i) => `<div class="tip-note">${this.unfollowed(mite, i) || (mite.censored[i] ? "gone" : mite.moving[i] ? "moving" : "still")}${
        mite.corrected[i] ? ", corrected by hand" : mite.to_check.includes(i) ? ", to check" : ""}${clock.start ? ` · at ${minutes(results.times[i])} of the run` : ""}</div>`,
    });
  }

  // 56 × 56 px of the zone's clip, or of the mite's own, around the mite: the crop's view box shows only that part.
  drawCloseUp(mite, zone) {
    const size = 56;
    const crop = this.crop(mite.x - size / 2, mite.y - size / 2, size, size);
    // A click turns the mite's call in the recording shown from moving to still or back
    // (a gone one to moving); gone is set in the table, the tracking finds fly-offs itself.
    const next = this.callState(mite, ctx.shown) === "moving" ? "still" : "moving";
    this.miteMarker(crop, mite, 22, {
      withLabel: false,
      onClick: () => this.correctCall(mite, ctx.shown, next),
      hint: `Click: change to ${next}`,
    });
    $("mite-crop").appendChild(crop);
    ResultsPage.frameCall($("mite-crop"), this.shownState(mite), mite.corrected[ctx.shown]);
    this.drawOutlines(crop, zone.id);
    this.playClip(this.miteClipUrl(mite, ctx.shown), $("mite-crop"), $("mite-crop").nextElementSibling,
      (clip) => {
        if (clip.mite) MitePage.centreOn(crop, clip.mite, size);
        return ClipPlayer.onSvg(crop, clip);
      });
  }

  // The close-up and the mite's ring moved to where a live run followed the mite
  // in the recording shown (the clip's "mite"); its outline is drawn there already.
  static centreOn(crop, at, size) {
    crop.setAttribute("viewBox", `${at.x - size / 2} ${at.y - size / 2} ${size} ${size}`);
    crop.querySelectorAll(".mite-marker > circle").forEach((circle) => {
      circle.setAttribute("cx", at.x);
      circle.setAttribute("cy", at.y);
    });
  }
}
