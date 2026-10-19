// On the results overview, two sections drawn from results.activity (worked out
// in classes/unusual_activity.py): the plate's shake, and the unusual activity.
//
// Plate shake: the median shake of the mites per recording, to spot a recording
// or a stretch of time in which the plate shook, and the mites that drifted
// furthest from their zone, each as its path (px, py) across the recordings.
//
// Unusual activity: the mites that flew off (came unglued and walked off; left
// out of the analysis) with their tracks over the plate, the mites that turned
// where they were (rotators), a clip of each, the recordings of the other mites
// in which one walked by set aside, and the recordings set aside.

class ActivitySection {
  // Time runs from light to dark in one hue, as in the notebooks.
  static TIME = ["#c9dcf3", "#2a78d6", "#0d2f5e"];

  constructor(page) {
    this.page = page;
    this.players = [];
  }

  get results() {
    return this.page.results;
  }

  get activity() {
    return this.results.activity;
  }

  // The colour of `share` (0 to 1) of the way through time.
  static timeColor(share) {
    const stops = ActivitySection.TIME.map((hex) => [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16)));
    const at = Math.min(Math.max(share, 0), 1) * (stops.length - 1);
    const [from, to] = [stops[Math.floor(at)], stops[Math.min(Math.ceil(at), stops.length - 1)]];
    const mix = from.map((value, i) => Math.round(value + (to[i] - value) * (at - Math.floor(at))));
    return `rgb(${mix.join(",")})`;
  }

  at(recording) {
    return minutes(this.results.times[recording]);
  }

  miteLink(id) {
    const known = this.results.mites.some((mite) => mite.id === id);
    return known ? `<a href="${ctx.href(`mite/${encodeURIComponent(id)}`)}">${esc(id)}</a>` : esc(id);
  }

  // --- the sections' HTML, numbered from `first`

  html(first) {
    if (!this.activity) return "";
    const { figure, section, stat } = Markup;
    const { fly_offs: flyOffs, rotators, disturbed, movers, turn_limit: turnLimit } = this.activity;
    const shake = `
      <div class="block">${figure("chart-shake", first, "Plate shake per recording",
        `In each recording, how far each mite's patch moved from the recording's first frame at most, as its own shift measures it; the line is the median over the mites in their place.
        A recording or a stretch of time above the rest is one in which the plate shook more: a door, a fan, a bench knocked.
        Each mite's patch is moved back by the plate's shift, the median of all the mites' own, before it is scored.
        Click a time to show that recording.${this.page.stillToCome()}`)}</div>
      <div class="block">${figure("activity-movers", first + 1, `The ${movers.length} mites that drifted furthest`,
        `Each mite's path across the recordings: where its image sits against its image in the first recording (px, py, in pixels), from light (first recording) to dark (last).
        The dashed grey path is the median of its zone, what the plate under it did; a glued mite follows it. The mites are ranked by how far they sit from their zone's path
        (the 95th percentile over the recordings, so one bad measurement does not rank a mite). The fly-offs and the rotators are left out: once a mite has walked or turned,
        it no longer looks like its first image, and its path says nothing; they are under Unusual activity.
        Select a mite to open it.`, "mover-grid")}</div>`;

    const nAside = disturbed.length;
    const activity = `
      <div class="stats">
        ${stat("Fly-offs", flyOffs.length, "left out of the analysis")}
        ${stat("Rotators", rotators.length, `turned more than ${turnLimit}°`)}
        ${stat("Recordings set aside", nAside, "a mite walked by")}
      </div>
      ${flyOffs.length ? `<div class="block">${figure("activity-tracks", first + 2, "Fly-off tracks",
        `The first frame with the track of every mite that flew off: from where it was detected (its id, white dot) to where it was last followed,
        from light (when it left its place) to dark (when it stopped walking).
        Rings mark the mites it disturbed (their recordings are set aside) and, in purple, the rotators. Hover a track for its times.`, "plate activity-plate")}</div>` : ""}
      <div id="activity-events" class="activity-events"></div>
      ${nAside ? section("Recordings set aside", `<div class="table-wrap"><table id="activity-aside"></table></div>
        <p class="caption">In these recordings the mite's call is set aside: censored, it counts neither as moving nor as still, as a mite marked gone in one recording.
        A mite walked by: a blob that is no mite in its place, and was elsewhere the recording before, came within reach of the patch the mite is scored on,
        or a fly-off's track passed there while it lay against the mite. Set the call by hand on the mite's page to count it again.</p>`) : ""}`;

    return `${section("Plate shake", shake)}${section("Unusual activity", this.activity.measured ? activity
      : `<p class="caption">Not measured for these results: run the analysis again.</p>`)}`;
  }

  // --- drawing, once the HTML is on the page

  draw() {
    if (!this.activity) return;
    this.drawShake();
    this.drawMovers();
    if (!this.activity.measured) return;
    if (this.activity.fly_offs.length) this.drawTracks();
    this.drawEvents();
    this.drawAside();
  }

  drawShake() {
    const { shake } = this.activity;
    const top = Math.max(...shake.filter((value) => value != null), 0);
    this.page.timeChart($("chart-shake"), {
      yLabel: "Median shake (px)",
      yMin: 0,
      yMax: Math.max(0.3, top * 1.15),
      yFormat: (v) => v.toFixed(2),
      threshold: top > 0.25 ? { value: 0.5, label: "0.5 px" } : null,
      series: [{ name: "median shake", values: shake, color: token("--series-1"), markers: false }],
    });
  }

  // One small square per mite, its path coloured by time over its zone's, dashed.
  drawMovers() {
    const grid = $("activity-movers");
    grid.innerHTML = "";
    const n = this.results.times.length;
    this.activity.movers.forEach((mover) => {
      const card = document.createElement("a");
      card.className = "mover-card";
      const known = this.results.mites.some((mite) => mite.id === mover.id);
      if (known) card.href = ctx.href(`mite/${encodeURIComponent(mover.id)}`);
      card.innerHTML = `<div class="mover-head"><b>Mite ${esc(mover.id)}</b> <span class="muted">zone ${esc(mover.zone)} · ${mover.away.toFixed(2)} px</span></div>`;
      const points = mover.dx.map((x, i) => (x == null || mover.dy[i] == null ? null : [x, mover.dy[i], i]));
      const zone = mover.zone_dx.map((x, i) => (x == null || mover.zone_dy[i] == null ? null : [x, mover.zone_dy[i]]));
      const seen = [...points, ...zone].filter(Boolean);
      // 98% of the path on the square: one far-off registration does not shrink the rest
      const range = (k) => {
        const values = seen.map((p) => p[k]).sort((a, b) => a - b);
        return [values[Math.floor(values.length * 0.01)], values[Math.ceil(values.length * 0.99) - 1]];
      };
      const [[x0, x1], [y0, y1]] = [range(0), range(1)];
      const half = Math.max((x1 - x0) / 2, (y1 - y0) / 2, 0.25) * 1.15;
      const [cx, cy] = [(x0 + x1) / 2, (y0 + y1) / 2];
      const size = 150;
      const sx = (x) => ((x - cx + half) / (2 * half)) * size;
      const sy = (y) => ((y - cy + half) / (2 * half)) * size;
      const svg = PlateView.svgEl("svg", { viewBox: `0 0 ${size} ${size}`, class: "mover-plot", role: "img",
        "aria-label": `Path of mite ${mover.id} across the recordings` });
      svg.appendChild(PlateView.svgEl("rect", { x: 0, y: 0, width: size, height: size, class: "mover-frame" }));
      const path = (list) => list.filter(Boolean).map((p, i) => `${i ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join("");
      svg.appendChild(PlateView.svgEl("path", { d: path(zone), class: "mover-zone" }));
      const shown = points.filter(Boolean);
      shown.slice(1).forEach((p, i) => {
        const q = shown[i];
        svg.appendChild(PlateView.svgEl("line", { x1: sx(q[0]), y1: sy(q[1]), x2: sx(p[0]), y2: sy(p[1]),
          stroke: ActivitySection.timeColor(p[2] / Math.max(1, n - 1)), class: "mover-step" }));
      });
      const scale = PlateView.svgEl("text", { x: 4, y: size - 4, class: "mover-scale" });
      scale.textContent = `${(2 * half).toFixed(2)} px across`;
      svg.appendChild(scale);
      card.appendChild(svg);
      grid.appendChild(card);
    });
  }

  // The tracks over the first frame, in picture pixels: an SVG laid over the picture.
  drawTracks() {
    const { results } = this;
    const plate = $("activity-tracks");
    PlateView.overlay(plate, ctx.fileUrl(results.preview), results.image);
    const svg = PlateView.svgEl("svg", { viewBox: `0 0 ${results.image.width} ${results.image.height}`, class: "track-layer",
      preserveAspectRatio: "none" });
    const ring = (x, y, cls, label, title) => {
      const g = PlateView.svgEl("g", { class: cls });
      g.appendChild(PlateView.svgEl("circle", { cx: x, cy: y, r: 13 }));
      const text = PlateView.svgEl("text", { x: x + 16, y: y - 8 });
      text.textContent = label;
      const tip = PlateView.svgEl("title", {});
      tip.textContent = title;
      g.append(text, tip);
      svg.appendChild(g);
    };
    const disturbedBy = new Set(this.activity.fly_offs.flatMap((flyOff) => flyOff.near));
    results.mites.filter((mite) => disturbedBy.has(mite.id)).forEach((mite) =>
      ring(mite.x, mite.y, "track-disturbed", mite.id, `Mite ${mite.id}: a fly-off walked by`));
    this.activity.rotators.forEach((rotator) =>
      ring(rotator.x, rotator.y, "track-rotator", rotator.id, `Mite ${rotator.id} turned ${rotator.turn}° from ${this.at(rotator.from)}`));
    this.activity.fly_offs.forEach((flyOff) => {
      const g = PlateView.svgEl("g", { class: "track" });
      const track = flyOff.track;
      const span = Math.max(1, flyOff.walked_to - flyOff.from);
      g.appendChild(PlateView.svgEl("polyline", { points: track.map(([, x, y]) => `${x},${y}`).join(" "), class: "track-edge" }));
      track.slice(1).forEach(([recording, x, y], i) => {
        const [, px, py] = track[i];
        g.appendChild(PlateView.svgEl("line", { x1: px, y1: py, x2: x, y2: y, stroke: ActivitySection.timeColor((recording - flyOff.from) / span) }));
      });
      g.appendChild(PlateView.svgEl("circle", { cx: flyOff.x, cy: flyOff.y, r: 6, class: "track-start" }));
      const label = PlateView.svgEl("text", { x: flyOff.x + 9, y: flyOff.y - 9, class: "track-label" });
      label.textContent = flyOff.id;
      const tip = PlateView.svgEl("title", {});
      tip.textContent = `Mite ${flyOff.id} flew off at ${this.at(flyOff.from)}, walked until ${this.at(flyOff.walked_to)}`;
      g.append(label, tip);
      svg.appendChild(g);
    });
    plate.appendChild(svg);
  }

  // A card per fly-off and per rotator, each with its clip: a fly-off's played on
  // request, a rotator's at once.
  drawEvents() {
    const container = $("activity-events");
    const { fly_offs: flyOffs, rotators } = this.activity;
    const events = [
      ...flyOffs.map((event) => ({ kind: "fly_off", event, title: `Fly-off · mite ${event.id}`,
        text: `Zone ${esc(event.zone)}. ${event.marked ? "Marked <i>not a mite</i> by hand; " : "Left out of the analysis; "}
          left its place at ${this.at(event.from)} and walked until ${this.at(event.walked_to)}.
          ${event.near.length ? `It walked by ${event.near.map((id) => this.miteLink(id)).join(", ")}: those recordings are set aside.` : "It disturbed no other mite."}` })),
      ...rotators.map((event) => ({ kind: "rotator", event, title: `Rotator · mite ${event.id}`,
        text: `Zone ${esc(event.zone)}. Its body turned past ${this.activity.turn_limit}° from ${this.at(event.from)}, ${event.turn}° at most.
          It stays in the analysis: ${this.miteLink(event.id)}.` })),
    ];
    if (!events.length) {
      container.innerHTML = `<p class="caption">No mite flew off or turned in these recordings.</p>`;
      return;
    }
    // Of a session saved as the mites' ROIs, a fly-off's walk across the plate was not saved.
    const playable = (kind) => kind !== "fly_off" || !this.page.onlyMiteClips();
    container.innerHTML = events.map(({ kind, event, title, text }, index) => `
      <figure class="fig activity-card">
        <div class="fig-title">${esc(title)}</div>
        <p class="activity-text">${text}</p>
        <div class="activity-clip" data-index="${index}"><img alt="${esc(title)}" hidden></div>
        <p class="hint clip-status">${kind === "rotator" ? `<span class="muted">Waiting for the clips before it…</span>`
          : playable(kind) ? `<button type="button" class="secondary small" data-play="${index}">Play the recordings</button>
          <span class="muted">from the recording before it left to the one after it stopped, one after the other</span>`
          : `<span class="muted">Only the mites' surroundings are saved of these recordings, so its walk cannot be played.</span>`}</p>
      </figure>`).join("");
    const clip = (index) => [events[index], container.querySelector(`.activity-clip[data-index="${index}"]`)];
    container.querySelectorAll("[data-play]").forEach((button) => button.addEventListener("click", () => {
      this.play(...clip(Number(button.dataset.play)), button.closest(".clip-status"));
    }));
    this.playRotators(events, clip);
  }

  // The rotators' clips play on their own, cut one after the other so the
  // server is not asked for all of them at once.
  async playRotators(events, clip) {
    for (const [index, { kind }] of events.entries()) {
      if (kind !== "rotator") continue;
      const [event, wrap] = clip(index);
      if (!wrap.isConnected) return;  // the page is gone
      await this.play(event, wrap, wrap.nextElementSibling);
    }
  }

  async play({ kind, event }, wrap, status) {
    const player = this.players[wrap.dataset.index] || (this.players[wrap.dataset.index] = new ClipPlayer());
    const img = wrap.querySelector("img");
    status.className = "hint clip-status";
    status.innerHTML = `<span class="spinner"></span> Cutting the recordings…`;
    try {
      const clip = await player.load(`/api/session/${ctx.sessionId}/activity-clip/${kind}/${encodeURIComponent(event.id)}`, this.page.frameUrl());
      if (!clip) return;
      img.hidden = false;
      const [first, last] = clip.recordings;
      status.textContent = `${this.at(first)} to ${this.at(last)}: ${last - first + 1} recordings, ${clip.frames.length} frames, looped.`;
      player.playing = true;
      player.start(clip, (src) => {
        if (!img.isConnected) player.stop();  // the page is gone
        else img.src = src;
      });
    } catch (error) {
      status.className = "hint clip-status error";
      status.textContent = error.message;
    }
  }

  drawAside() {
    const table = $("activity-aside");
    if (!table) return;
    table.innerHTML = `
      <thead><tr><th>Mite</th><th class="num">Recording</th></tr></thead>
      <tbody>${this.activity.disturbed.map((row) => `<tr>
        <td>${this.miteLink(row.mite)}</td><td class="num">${this.at(row.recording)}</td></tr>`).join("")}</tbody>`;
  }

  // Stop the clips when the page goes.
  stop() {
    this.players.forEach((player) => player && player.stop());
  }
}
