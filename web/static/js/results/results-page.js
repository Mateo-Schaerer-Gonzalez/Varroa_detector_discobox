// What the overview, zone and mite pages share: the recording slider and the
// clip, the time axis of a live run, the time to count a mite as dead, and the
// banner when the labels changed since the run. The numbers come from the server
// with the results: per mite, per zone, per group (group_rows) and the survival
// numbers (results.survival), worked out in classes/movement_stats.py and
// classes/survival.py.

class ResultsPage {
  static MOVING_NOTE = "A mite counts as moving in a recording when its motion score in that recording reaches the threshold, unless its call there was corrected by hand.";

  get results() {
    return ctx.results;
  }

  get body() {
    return $("results-body");
  }

  zoneName(zone) {
    return `Zone ${zone.id}${zone.label ? ` · ${zone.label}` : ""}`;
  }

  miteHref(mite) {
    return ctx.href(`mite/${encodeURIComponent(mite.id)}`);
  }

  shownTime() {
    return minutes(this.results.times[ctx.shown]);
  }

  movingShown(mite) {
    return mite.moving[ctx.shown];
  }

  // The mite's call in a recording, marked when it is the user's, not the detector's.
  callBadge(mite, recording) {
    return Markup.movingBadge(mite.moving[recording]) + (mite.corrected[recording]
      ? ` <span class="corrected-mark" title="Corrected by hand; change it again for the detector's call">corrected</span>` : "");
  }

  // Change the call of a mite in a recording by hand, moving to still or back
  // (classes/call_corrections.py): the server saves it and sends the results
  // again, every number following the change.
  async correctCall(mite, recording = ctx.shown) {
    const workspace = ctx;
    const { sessionId } = workspace;
    Charts.hideTooltip();
    try {
      const answer = await post(`/api/session/${sessionId}/correct`, { mite: mite.id, recording });
      if (workspace.sessionId !== sessionId) return;  // another folder or run by now
      workspace.results = answer.results;
      if (workspace.mode === "live" && answer.version != null) live.version = answer.version;
      if (ctx === workspace && /^#\/(live\/)?(results|zone|mite)/.test(location.hash)) resultsView.draw();
    } catch (error) {
      const status = this.body.querySelector(".clip-status");
      if (status) {
        status.className = "hint clip-status error";
        status.textContent = `Could not change the call: ${error.message}`;
      }
    }
  }

  // Time of the last recording in which the mite moved.
  lastMovementText(mite) {
    return mite.last_movement == null ? "never" : minutes(mite.last_movement);
  }

  breadcrumb(parts) {
    // The overview is the top level, so it needs no trail.
    $("breadcrumb").hidden = parts.length < 2;
    $("breadcrumb").innerHTML = parts
      .map(([text, href], i) =>
        i === parts.length - 1 ? `<span aria-current="page">${esc(text)}</span>` : `<a href="${href}">${esc(text)}</a>`)
      .join(`<span class="crumb-sep" aria-hidden="true">/</span>`);
  }

  // Wire what every result page may hold: "Run again", the death time, the slider.
  wire(body) {
    body.querySelectorAll(".run-trigger").forEach((button) => button.addEventListener("click", () => {
      router.go("#/label");
      analysis.run();
    }));
    this.wireDeathControl(body);
    RecordingSlider.wire(body, this.results.times, null, (index) => resultsView.showRecording(index));
  }

  staleBanner() {
    if (!ctx.labelsChanged) return "";
    return `<div class="banner">Labels or detections changed since this run, so the results below are out of date.
    <button type="button" class="run-trigger small">Run again</button></div>`;
  }

  // --- a live run filling in

  // While a live run goes on, the time axis of every chart covers the whole run as
  // planned so far, so the charts fill in as it goes instead of stretching to each
  // new recording. Null otherwise: a chart's time axis is then its data's.
  timeDomain() {
    const line = ctx.mode === "live" && live.running ? live.status.timeline : null;
    const { times } = this.results;
    return line ? [0, Math.max(line.minutes, times[times.length - 1])] : null;
  }

  stillToCome() {
    return this.timeDomain() ? " The shaded end of the axis is the part of the run still to come." : "";
  }

  // A chart over the recordings' times, marking the one shown; a click on a time shows it.
  timeChart(container, options) {
    Charts.line(container, {
      x: this.results.times,
      xDomain: this.timeDomain(),
      enterFrom: resultsView.enterFrom,
      selected: ctx.shown,
      onXClick: (index) => resultsView.showRecording(index),
      ...options,
    });
  }

  // --- alive or dead

  deathRule() {
    const wait = this.results.death_minutes || 0;
    return wait
      ? `A mite counts as dead once it has been still for ${minutes(wait)}, from the recording after its last movement on; until it has been still that long, it counts as alive, as it may yet move.
      ${ResultsPage.LEFT_OUT_RULE}`
      : `A mite counts as alive up to the last recording in which it moved, and as dead from the next one on. ${ResultsPage.LEFT_OUT_RULE}`;
  }

  // --- in the study or left out

  static LEFT_OUT_RULE = `Only the mites seen moving at least once are in the survival numbers: a mite never seen moving
    may have been dead from the start, or no live mite at all, so it is left out, its id greyed out and struck through.`;

  // A mite's lifeline, the server's (results.survival.mites): {in_study, time, dead}.
  lifeline(mite) {
    return this.results.survival.mites?.[mite.id] || { in_study: true, time: null, dead: null };
  }

  inStudy(mite) {
    return this.lifeline(mite).in_study;
  }

  // "died at 10 min", "alive at 20 min (censored)" or "left out: never seen moving".
  survivalText(mite) {
    const { in_study: inStudy, time, dead } = this.lifeline(mite);
    if (!inStudy) return "left out: never seen moving";
    if (time == null) return "–";
    return dead ? `died at ${minutes(time)}` : `alive at ${minutes(time)} (censored)`;
  }

  // The mite's id, as a link when `href`, greyed out and struck through when left out.
  miteId(mite, href = "") {
    const text = href ? `<a href="${href}">${esc(mite.id)}</a>` : esc(mite.id);
    return this.inStudy(mite) ? text : `<span class="left-out-id" title="Never seen moving: left out of the survival numbers">${text}</span>`;
  }

  // "2 mites never seen moving are left out. " for `n` of them; "" for none.
  leftOutNote(n) {
    return n ? `${n} mite${n === 1 ? "" : "s"} never seen moving ${n === 1 ? "is" : "are"} left out. ` : "";
  }

  // The shaded band of the survival rate charts (results.survival: alive_ci).
  aliveBandNote() {
    return `The survival rate is the Kaplan–Meier estimate. The shaded band around a curve is its 95% confidence interval (Greenwood's formula on the log-log scale);
      the fewer the mites, the wider it is, and it has no width where all or none of them are alive.`;
  }

  // While a live run goes on, a mite still since its last movement may yet move again.
  aliveLiveNote() {
    return this.timeDomain() && !this.results.death_minutes
      ? " While the run goes on, a mite still since its last movement may yet move again and count as alive until then." : "";
  }

  // In the analysis of a folder, the time a mite must be still to count as dead can
  // be changed on the page: it is saved with the recordings, and the server sends
  // the survival numbers again, with no need to run the analysis again. A live run
  // takes it from its settings.
  deathControl() {
    if (ctx.mode !== "analysis") return "";
    const [lowest, highest] = this.results.death_range;
    return `<label class="death-field">Dead when still for
      <input type="number" class="number-input" data-death min="${lowest}" max="${highest}" step="1" value="${this.results.death_minutes || 0}"
        title="0: a mite counts as dead from the recording after its last movement"> min</label>
    <span class="hint death-status"></span>`;
  }

  wireDeathControl(body) {
    body.querySelectorAll("[data-death]").forEach((input) => input.addEventListener("change", async () => {
      const status = input.closest(".fig-controls").querySelector(".death-status");
      const { results } = this;
      try {
        const saved = await post(`/api/session/${ctx.sessionId}/death`, { minutes: Number(input.value) });
        results.death_minutes = saved.death_minutes;
        if (saved.survival) results.survival = saved.survival;
        // Unless another folder or page is shown by now.
        if (ctx.results === results && /^#\/(live\/)?(results|zone|mite)/.test(location.hash)) resultsView.draw();
      } catch (error) {
        status.className = "hint error death-status";
        status.textContent = error.message;
      }
    }));
  }

  // --- the recording on screen

  // A figure playing the recording shown, with the recording slider above it; the
  // clip goes in the element with `id`, its loading status below it.
  clipFigure(id, number, title, caption, extraClass = "") {
    return `<figure class="fig">
      <div class="fig-title">${title}</div>
      <div class="rec-bar">${RecordingSlider.html({ times: this.results.times, current: ctx.shown })}</div>
      <div id="${id}" class="${extraClass}"></div>
      <p class="hint clip-status"></p>
      <figcaption><b>Fig. ${number}.</b> ${caption}</figcaption>
    </figure>`;
  }

  // Load a clip of the recording shown and play it; `place(clip)` returns its `show`.
  // Until it plays, `wrap` shows the first frame dimmed.
  async playClip(url, wrap, status, place) {
    wrap.classList.add("loading");
    status.className = "hint clip-status";
    status.innerHTML = `<span class="spinner"></span> Loading the recording at ${this.shownTime()}…`;
    try {
      // The frames of a recording never change, so they need no cache-buster.
      const clip = await player.load(url, (name) => `/api/session/${ctx.sessionId}/file/${name}`);
      if (!clip) return;
      wrap.classList.remove("loading");
      status.textContent = `Recording at ${this.shownTime()}: ${clip.frames.length} frames, looped in real time.`;
      player.playing = true;
      player.start(clip, place(clip));
    } catch (error) {
      wrap.classList.remove("loading");
      status.className = "hint clip-status error";
      status.textContent = `${error.message} Showing the first frame.`;
    }
  }

  // A crop of the first frame.
  crop(x, y, w, h) {
    return PlateView.crop(x, y, w, h, ctx.fileUrl(this.results.preview), this.results.image);
  }

  // ● and ○ per recording, the one on screen underlined, those corrected by hand boxed.
  movementGlyphs(mite) {
    return `<div class="tip-glyphs">${mite.moving.map((moving, i) =>
      `<span class="${moving ? "moving" : "still"}${i === ctx.shown ? " current" : ""}${mite.corrected[i] ? " corrected" : ""}">${moving ? "●" : "○"}</span>`).join("")}</div>`;
  }

  // A ring around a mite, coloured by its movement in the recording shown, dashed
  // when that call was corrected by hand. The whole disc inside the ring is its
  // hover and click target; the label is not. `hint` says what `onClick` does.
  miteMarker(svg, mite, radius, { withLabel = true, onClick = null, hint = "" } = {}) {
    const moving = this.movingShown(mite);
    const corrected = mite.corrected[ctx.shown];
    const g = PlateView.svgEl("g", {
      class: `mite-marker ${moving ? "moving" : "still"}${corrected ? " corrected" : ""}${this.inStudy(mite) ? "" : " left-out"}`,
    });
    g.append(
      PlateView.svgEl("circle", { cx: mite.x, cy: mite.y, r: radius + 3, class: "hit" }),
      PlateView.svgEl("circle", { cx: mite.x, cy: mite.y, r: radius, class: "ring" }),
    );
    if (withLabel) {
      const text = PlateView.svgEl("text", { x: mite.x + radius + 4, y: mite.y - radius, "font-size": radius * 1.1 });
      text.textContent = mite.id;
      g.appendChild(text);
    }
    if (onClick) {
      g.style.cursor = "pointer";
      g.addEventListener("click", onClick);
      g.addEventListener("mousemove", (event) => Charts.showTooltip(event,
        `<div class="tip-title">Mite ${esc(mite.id)}</div>${this.callBadge(mite, ctx.shown)} at ${this.shownTime()}
       ${this.movementGlyphs(mite)}<div class="tip-note">${this.survivalText(mite)}</div><div class="tip-hint">${hint}</div>`));
      g.addEventListener("mouseleave", Charts.hideTooltip);
    }
    svg.appendChild(g);
  }

  // A zone's outline over its crop, in its group's colour.
  zoneOutline(zone, color) {
    const outline = PlateView.svgEl("rect", {
      x: zone.x1, y: zone.y1, width: zone.x2 - zone.x1, height: zone.y2 - zone.y1, class: "zone-outline",
    });
    outline.style.stroke = color;
    return outline;
  }
}
