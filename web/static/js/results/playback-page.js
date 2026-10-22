// The playback: every mite's whole video, its recordings one after the other,
// laid out by zone, all on one timer at the top of the page. The server cuts,
// per recording and zone, one picture with a row per mite and a column per
// frame (pipeline.playback_sheet); each mite's square shows its part of the
// frame the timer is on. The fly-offs, left out of the analysis, play too.

class PlaybackPage extends ResultsPage {
  static SPEEDS = [1, 2, 4, 8, 16];
  static AHEAD = 2;        // recordings fetched ahead of the one playing
  static MIN_DELAY = 15;   // ms between frames at the most

  constructor() {
    super();
    this.sessionId = null;
    this.timeline = null;
    this.sheets = new Map();  // "recording/zone" -> {promise, sheet, image, error}
    this.at = 0;              // the frame shown, counted over every recording
    this.playing = true;
    this.speed = 1;
    this.timer = null;
  }

  show() {
    this.breadcrumb([["Results", ctx.href("results")], ["Playback", ctx.href("playback")]]);
    // A live run's new recording draws the page again: it plays on where it is.
    if (this.sessionId === ctx.sessionId && $("playback-grid")?.isConnected) {
      this.load(true);
      return;
    }
    this.stop();
    if (this.sessionId !== ctx.sessionId) {
      Object.assign(this, { sessionId: ctx.sessionId, at: 0, playing: true });
      this.sheets.clear();
    }
    this.body.innerHTML = `
    ${this.staleBanner()}
    <header class="page-head">
      <div>
        <h1>Playback</h1>
        <p class="meta">${esc($("folder-name").textContent)} · every mite's recordings one after the other, by zone</p>
      </div>
    </header>
    <div class="playback-bar" id="playback-bar">
      <button type="button" class="small" id="playback-play">Pause</button>
      <input type="range" id="playback-slider" min="0" max="0" value="0" aria-label="Frame shown">
      <label class="playback-speed">Speed <select id="playback-speed">
        ${PlaybackPage.SPEEDS.map((speed) => `<option value="${speed}"${speed === this.speed ? " selected" : ""}>${speed}×</option>`).join("")}
      </select></label>
      <span class="playback-time" id="playback-time"><span class="spinner"></span> Loading…</span>
    </div>
    <p class="hint clip-status" id="playback-status"></p>
    <div id="playback-grid" class="playback-zones"></div>
    <p class="caption">Each square is a mite's box and a few pixels round it, as recorded (not moved back by the plate's shake), every frame of each recording
      in real time at 1×; between two recordings the time the box waited is skipped. The time is at the top, with the frame and the recording.
      A square's edge is the mite's call in the recording playing: ${Markup.movingBadge(true)} or ${Markup.movingBadge(false)}, grey where it is gone or set aside.
      A mite added during a live run is black before it was added, and one counted dead is black once it is no longer followed: nothing of them was saved there.
      The fly-offs, left out of the analysis, are at the end of their zone. Select a mite to open it.</p>`;
    this.wireBar();
    this.load(false);
  }

  wireBar() {
    $("playback-play").addEventListener("click", () => {
      this.playing = !this.playing;
      $("playback-play").textContent = this.playing ? "Pause" : "Play";
      if (this.playing) this.tick();
      else clearTimeout(this.timer);
    });
    $("playback-slider").addEventListener("input", (event) => this.seek(Number(event.target.value)));
    $("playback-speed").addEventListener("change", (event) => { this.speed = Number(event.target.value); });
  }

  // What to play, from the server; `again` when the page is up already (a live run grew).
  async load(again) {
    const { sessionId } = ctx;
    let timeline;
    try {
      timeline = await getJson(`/api/session/${sessionId}/playback`, "Could not load the recordings");
    } catch (error) {
      if (ctx.sessionId !== sessionId || !$("playback-status")) return;
      Hint.error($("playback-status"), error.message, "clip-status");
      $("playback-time").textContent = "";
      return;
    }
    if (ctx.sessionId !== sessionId || !$("playback-grid")?.isConnected) return;
    this.timeline = timeline;
    // where each recording starts, counted in frames over all of them
    this.starts = [];
    let total = 0;
    timeline.recordings.forEach((recording) => { this.starts.push(total); total += recording.frames; });
    this.total = total;
    this.at = Math.min(this.at, Math.max(0, total - 1));
    $("playback-slider").max = Math.max(0, total - 1);
    if (!again) this.drawGrid();
    this.paint();
    if (this.playing) this.tick();
  }

  // One box per zone with mites, a square per mite in it.
  drawGrid() {
    const grid = $("playback-grid");
    const byZone = new Map();
    this.timeline.mites.forEach((mite) => {
      if (!byZone.has(mite.zone_id)) byZone.set(mite.zone_id, []);
      byZone.get(mite.zone_id).push(mite);
    });
    const groups = ctx.resultGroups();
    const known = new Set(this.results.mites.map((mite) => mite.id));
    this.zones = this.results.zones.filter((zone) => byZone.has(zone.id)).map((zone) => zone.id);
    grid.innerHTML = this.zones.map((zoneId) => {
      const zone = ctx.zone(zoneId);
      const group = zone.label || "unlabeled";
      return `<section class="playback-zone" data-zone="${zoneId}">
        <div class="playback-zone-head"><a href="${ctx.href(`zone/${zoneId}`)}"><b>Zone ${zoneId}</b></a> ${Markup.groupTag(group, groupColor(group, groups))}</div>
        <div class="playback-mites">${byZone.get(zoneId).map((mite) => `
          <a class="playback-card"${known.has(mite.id) ? ` href="${ctx.href(`mite/${encodeURIComponent(mite.id)}`)}"` : ""} data-mite-id="${esc(mite.id)}">
            <div class="mover-head"><b>Mite ${esc(mite.id)}</b> <span class="muted playback-call"></span></div>
            <canvas width="${this.timeline.tile}" height="${this.timeline.tile}" aria-label="Mite ${esc(mite.id)}'s recording"></canvas>
          </a>`).join("")}</div>
      </section>`;
    }).join("");
    this.canvases = new Map();
    grid.querySelectorAll(".playback-card").forEach((card) => {
      const canvas = card.querySelector("canvas");
      this.canvases.set(card.dataset.miteId, { card, context: canvas.getContext("2d"), zone: Number(card.closest(".playback-zone").dataset.zone) });
    });
    this.flyOffs = new Map(this.timeline.mites.filter((mite) => mite.flew_off != null).map((mite) => [mite.id, mite.flew_off]));
    this.shownRecording = null;
  }

  // (recording, frame in it) of the frame `at`.
  locate(at) {
    let recording = this.starts.length - 1;
    while (recording > 0 && this.starts[recording] > at) recording -= 1;
    return [recording, at - this.starts[recording]];
  }

  // The pictures of a recording's zones, fetched once; the few around the one
  // playing are kept.
  fetchSheets(recording) {
    const { sessionId } = ctx;
    this.zones.forEach((zone) => {
      const key = `${recording}/${zone}`;
      if (this.sheets.has(key)) return;
      const entry = {};
      entry.promise = getJson(`/api/session/${sessionId}/playback/${recording}/${zone}`, "Could not cut the recording")
        .then((sheet) => new Promise((resolve, reject) => {
          const image = new Image();
          image.onload = () => resolve(Object.assign(entry, { sheet, image, rows: new Map(sheet.mites.map((id, row) => [id, row])) }));
          image.onerror = () => reject(new Error("Could not load the recording"));
          image.src = this.frameUrl()(sheet.sheet);
        }))
        .catch((error) => { entry.error = error; })
        .finally(() => {
          entry.done = true;
          if (this.sessionId === sessionId && this.locate(this.at)[0] === recording) this.paint();
        });
      this.sheets.set(key, entry);
    });
  }

  ready(recording) {
    return this.zones.every((zone) => this.sheets.get(`${recording}/${zone}`)?.done);
  }

  // Fetch the recording playing and the next few; forget those far from it.
  prepare(recording) {
    const n = this.timeline.recordings.length;
    const wanted = new Set(Array.from({ length: PlaybackPage.AHEAD + 1 }, (_, ahead) => (recording + ahead) % n));
    [...wanted].forEach((r) => this.fetchSheets(r));
    [...this.sheets.keys()].forEach((key) => {
      if (!wanted.has(Number(key.split("/")[0])) && this.sheets.get(key).done) this.sheets.delete(key);
    });
  }

  seek(at) {
    this.at = at;
    this.paint();
  }

  // Show the frame `at` in every square, and the time.
  paint() {
    if (!this.timeline || !this.total || !$("playback-grid")?.isConnected) return;
    const [recording, frame] = this.locate(this.at);
    this.prepare(recording);
    const { tile } = this.timeline;
    const failed = [];
    this.canvases.forEach(({ context }, miteId) => {
      const zone = this.canvases.get(miteId).zone;
      const entry = this.sheets.get(`${recording}/${zone}`);
      if (entry?.error) failed.push(zone);
      if (!entry?.image || !entry.rows.has(miteId)) return;
      context.drawImage(entry.image, Math.min(frame, entry.sheet.frames - 1) * tile, entry.rows.get(miteId) * tile, tile, tile, 0, 0, tile, tile);
    });
    const time = this.results.times[recording];
    const frames = this.timeline.recordings[recording].frames;
    $("playback-time").innerHTML = `<b>${time == null ? "–" : minutes(time)}</b> · recording ${recording + 1} of ${this.timeline.recordings.length} · frame ${frame + 1} of ${frames}${
      this.ready(recording) ? "" : ` <span class="spinner"></span>`}`;
    $("playback-slider").value = this.at;
    const status = $("playback-status");
    const zones = [...new Set(failed)];
    status.className = zones.length ? "hint clip-status error" : "hint clip-status";
    status.textContent = zones.length
      ? `Zone${zones.length === 1 ? "" : "s"} ${zones.join(", ")}: ${this.sheets.get(`${recording}/${zones[0]}`).error.message}` : "";
    if (recording !== this.shownRecording) this.drawCalls(recording);
  }

  // Each square's edge: the mite's call in the recording playing.
  drawCalls(recording) {
    this.shownRecording = recording;
    const byId = new Map(this.results.mites.map((mite) => [mite.id, mite]));
    this.canvases.forEach(({ card }, miteId) => {
      const mite = byId.get(miteId);
      let state = "gone";
      let text = "–";
      const unfollowed = mite && recording < mite.moving.length ? this.unfollowed(mite, recording) : null;
      if (unfollowed) {
        // a live run's mite not added yet, or counted dead: nothing saved, the square is black
        state = unfollowed === "not added yet" ? "gone" : "still";
        text = unfollowed;
      } else if (mite && recording < mite.moving.length) {
        const call = this.callState(mite, recording);
        const aside = this.setAside(mite, recording);
        state = aside || call.startsWith("gone") ? "gone" : call;
        text = aside ? "set aside" : state;
      } else if (this.flyOffs.has(miteId)) {
        text = recording >= this.flyOffs.get(miteId) ? "flown off" : "fly-off";
      }
      card.dataset.state = state;
      card.querySelector(".playback-call").textContent = text;
    });
    // A zone whose mites a live run all added later is not there before then.
    document.querySelectorAll("#playback-grid .playback-zone").forEach((section) => {
      const zone = ctx.zone(Number(section.dataset.zone));
      section.hidden = Boolean(zone) && recording < this.clockOf(zone).start;
    });
  }

  // The next frame after its delay, waiting for its recording when it has not come yet.
  tick() {
    clearTimeout(this.timer);
    if (!this.playing || !this.total) return;
    if (!$("playback-grid")?.isConnected || $("view-results").hidden) { this.stop(); return; }
    const [recording] = this.locate(this.at);
    const next = (this.at + 1) % this.total;
    const [nextRecording] = this.locate(next);
    if (this.ready(nextRecording)) {
      this.at = next;
      this.paint();
    } else {
      this.prepare(nextRecording);
    }
    const delay = this.timeline.recordings[recording].interval_ms / this.speed;
    this.timer = setTimeout(() => this.tick(), Math.max(PlaybackPage.MIN_DELAY, delay));
  }

  stop() {
    clearTimeout(this.timer);
    this.timer = null;
  }
}
