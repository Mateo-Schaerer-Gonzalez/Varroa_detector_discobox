// The calls to check by eye, on the result pages: with a band around the
// threshold (config.yaml, set here), a score in it is too close to trust, and the
// server lists, per mite, the ones its time of death depends on, the latest first
// (results.review, mite.to_check; classes/review_band.py). The overview lists the
// mites to check and sets the band; a mite's page asks about the recording shown,
// keeps the answer (the buttons, or M and S) and goes on to the next close call, of
// this mite or of the next one, whose clip is fetched ahead. A bar says how far
// the checking has got (results.review: n_done of n_asked mites).

class ReviewCheck {
  constructor(page) {
    this.page = page;
  }

  get review() {
    return this.page.results.review || null;
  }

  bandText() {
    return `${score(this.review.low)} to ${score(this.review.high)}`;
  }

  // The mites with calls left to check, those with the most first.
  mites() {
    return this.page.results.mites.filter((mite) => mite.to_check.length)
      .sort((a, b) => b.to_check.length - a.to_check.length);
  }

  // How many of the mites the band asks about have nothing left to check, as a bar.
  progress() {
    const { n_asked: asked, n_done: done } = this.review;
    if (!asked) return "";
    return `<div class="review-progress" role="progressbar" aria-valuemin="0" aria-valuemax="${asked}" aria-valuenow="${done}">
      <div class="progress-bar"><div style="width: ${percent(done, asked)}"></div></div>
      <span class="hint">${done} of ${plural(asked, "mite")} checked</span></div>`;
  }

  // --- the overview

  section() {
    const { results } = this.page;
    const { review } = this;
    const mites = review ? this.mites() : [];
    const intro = !review
      ? `No band is set. With one, a motion score close to the threshold of ${score(results.threshold)} is taken as too close to trust,
        and the ones a mite's time of death depends on are listed here to check by eye.`
      : `A motion score from ${this.bandText()} is too close to the threshold of ${score(results.threshold)} to trust.
        A mite dies after its last movement, so the close calls after its last clear movement decide when it died.
        ${mites.length
          ? `<b>${plural(review.n_recordings, "recording")} of ${plural(review.n_mites, "mite")}</b> ${review.n_recordings === 1 ? "is" : "are"} left to check, the latest of each mite first:
            once one shows the mite moving, the earlier ones are asked for no more.`
          : "<b>Nothing is left to check.</b>"}`;
    const rows = mites.map((mite) => {
      const latest = mite.to_check[0];
      const zone = ctx.zone(mite.zone_id);
      return `<tr data-check-mite="${esc(mite.id)}" tabindex="0" title="Open this mite in its latest recording to check">
        <td>${this.page.miteId(mite)}</td>
        <td>${esc(this.page.zoneName(zone))}</td>
        <td class="num">${mite.to_check.length}</td>
        <td class="num">${minutes(results.times[latest])}</td>
        <td class="num">${score(mite.scores[latest])}</td>
        <td>${this.page.callBadge(mite, latest)}</td></tr>`;
    }).join("");
    const table = mites.length ? `<div class="table-wrap"><table class="clickable" id="review-table">
        <thead><tr><th>Mite</th><th>Zone</th><th class="num">To check</th><th class="num">Latest</th>
          <th class="num">Motion score</th><th>Detector's call</th></tr></thead>
        <tbody>${rows}</tbody></table></div>` : "";
    return Markup.section("To check by eye", `<p class="caption review-intro">${intro}</p>
      ${review ? this.progress() : ""}
      ${table}
      <div class="fig-controls review-band">
        <label class="death-field">Check scores from
          <input type="number" class="number-input" data-band="low" step="any" value="${review ? review.low : ""}" aria-label="Lower edge of the band"></label>
        <label class="death-field">to
          <input type="number" class="number-input" data-band="high" step="any" value="${review ? review.high : ""}" aria-label="Upper edge of the band"></label>
        <button type="button" class="small" data-band-save>Save</button>
        ${review ? `<button type="button" class="small secondary" data-band-clear>No band</button>` : ""}
        <span class="hint band-status">The band holds the threshold; it is kept for every analysis.</span>
      </div>`);
  }

  wire(body) {
    body.querySelectorAll("[data-check-mite]").forEach((row) => {
      const mite = this.page.results.mites.find((m) => m.id === row.dataset.checkMite);
      const open = () => resultsView.openMite(mite, mite.to_check[0]);
      row.addEventListener("click", open);
      row.addEventListener("keydown", (event) => { if (event.key === "Enter") open(); });
    });
    const edge = (name) => {
      const value = body.querySelector(`[data-band="${name}"]`).value;
      return value === "" ? null : Number(value);
    };
    body.querySelector("[data-band-save]")?.addEventListener("click", () => this.saveBand(body, edge("low"), edge("high")));
    body.querySelector("[data-band-clear]")?.addEventListener("click", () => this.saveBand(body, null, null));
  }

  // Save the band (none without both edges); the server sends the results again,
  // with what is to check as the band makes it.
  async saveBand(body, low, high) {
    const workspace = ctx;
    const { sessionId } = workspace;
    const status = body.querySelector(".band-status");
    if ((low == null) !== (high == null)) {
      status.className = "hint error band-status";
      status.textContent = "Give both edges of the band.";
      return;
    }
    try {
      const answer = await post(`/api/session/${sessionId}/review-band`, { low, high });
      if (workspace.sessionId !== sessionId) return;  // another folder or run by now
      workspace.results = answer.results;
      if (workspace.mode === "live" && answer.version != null) live.version = answer.version;
      if (ctx === workspace && /^#\/(live\/)?(results|zone|mite)/.test(location.hash)) resultsView.draw();
    } catch (error) {
      status.className = "hint error band-status";
      status.textContent = error.message;
    }
  }

  // --- a mite's page

  // What is left to check for this mite, above its figures; once it has none, where to go on.
  miteNote(mite) {
    if (!this.review) return "";
    const { times } = this.page.results;
    if (mite.to_check.length) {
      return `<div class="banner review-note"><span><b>${plural(mite.to_check.length, "close call")}</b> ${mite.to_check.length === 1 ? "decides" : "decide"} when this mite died:
        a score from ${this.bandText()} after its last clear movement. Check the latest first.</span>
        <span class="review-times">${mite.to_check.map((recording) =>
          `<button type="button" class="small secondary${recording === ctx.shown ? " current" : ""}" data-check-recording="${recording}">${minutes(times[recording])}</button>`).join("")}</span>
        ${mite.to_check.includes(ctx.shown) ? `<span class="review-now">Is the mite moving at ${minutes(times[ctx.shown])}? ${this.answerButtons()}</span>` : ""}
        ${this.progress()}</div>`;
    }
    if (!mite.checked.some(Boolean)) return "";
    const next = this.mites()[0];
    return `<div class="banner review-note"><span>Nothing is left to check for this mite.</span>
      ${next ? `<a class="button small secondary" href="${this.page.miteHref(next)}" data-check-next="${esc(next.id)}">Next: mite ${esc(next.id)} (${next.to_check.length})</a>`
        : `<a class="button small secondary" href="${ctx.href("results")}">All checked: back to the results</a>`}
      ${this.progress()}</div>`;
  }

  // The question about the recording shown, for the close-up's caption; the note
  // above the page asks it too, where it is on screen without scrolling.
  ask(mite) {
    if (!mite.to_check.includes(ctx.shown)) return "";
    return `<span class="review-ask"><b>Close call:</b> the score here, ${score(mite.scores[ctx.shown])}, is in the band. Is the mite moving in this recording?
      ${this.answerButtons()}</span>`;
  }

  answerButtons() {
    return `<button type="button" class="small" data-answer="moving" title="Key: M">Moving <kbd>M</kbd></button>
      <button type="button" class="small" data-answer="still" title="Key: S">Still <kbd>S</kbd></button>`;
  }

  // "to check" or "checked" beside a recording's call in the mite's table.
  mark(mite, recording) {
    if (mite.to_check.includes(recording)) return ` <span class="check-mark to-check" title="Close to the threshold, and the mite's time of death depends on it">to check</span>`;
    return mite.checked[recording] && !mite.corrected[recording]
      ? ` <span class="check-mark" title="Checked by eye: the detector's call stands">checked</span>` : "";
  }

  wireMite(body, mite) {
    body.querySelectorAll("[data-check-recording]").forEach((button) =>
      button.addEventListener("click", () => resultsView.showRecording(Number(button.dataset.checkRecording))));
    body.querySelectorAll("[data-check-next]").forEach((link) => link.addEventListener("click", (event) => {
      event.preventDefault();
      const next = this.page.results.mites.find((m) => m.id === link.dataset.checkNext);
      resultsView.openMite(next, next.to_check[0]);
    }));
    const answers = body.querySelectorAll("[data-answer]");
    answers.forEach((button) => button.addEventListener("click", () => {
      // Said at once, and no second answer while the first is on its way.
      answers.forEach((other) => { other.disabled = true; });
      button.classList.add("chosen");
      this.answer(mite, button.dataset.answer).finally(() => answers.forEach((other) => { other.disabled = false; }));
    }));
    this.warmNext(mite);
  }

  // Keep the answer for the recording shown, then show the next close call: the
  // mite's own, or with none left the next mite's.
  async answer(mite, state) {
    const page = location.hash;
    if (!await this.page.saveCall(mite, ctx.shown, state, true)) return;
    if (location.hash !== page) { resultsView.draw(); return; }  // another page by now
    const now = ctx.results.mites.find((m) => m.id === mite.id);
    const next = now && now.to_check.length ? now : this.mites()[0];
    if (!next) resultsView.draw();  // all checked
    else if (next === now) { resultsView.setShown(now.to_check[0]); resultsView.draw(); }
    else resultsView.openMite(next, next.to_check[0], true);
  }

  // Fetch ahead the clips an answer may show next: the mite's close call after
  // the one shown (it is still), and the next mite's latest (it is moving, or was the last).
  warmNext(mite) {
    if (!this.review || !mite.to_check.includes(ctx.shown)) return;
    if (ctx.mode === "live" && !(live.status && live.status.save_frames)) return;  // no clips to play
    const own = mite.to_check.find((recording) => recording !== ctx.shown);
    const other = this.mites().find((m) => m.id !== mite.id);
    [own != null && [mite, own], other && [other, other.to_check[0]]].filter(Boolean).forEach(([m, recording]) =>
      player.warm(`/api/session/${ctx.sessionId}/clip/${recording}/${m.zone_id}`, this.page.frameUrl()));
  }
}
