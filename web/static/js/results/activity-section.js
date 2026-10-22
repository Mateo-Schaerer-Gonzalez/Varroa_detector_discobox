// On the results overview, two sections drawn from results.activity (worked out
// in classes/unusual_activity.py): the plate's shake, and the unusual activity.
//
// Plate shake: the median shake of the mites per recording, to spot a recording
// or a stretch of time in which the plate shook, and the mites that drifted
// furthest from their zone, each as its path (px, py) across the recordings,
// with the fly-offs' paths until they flew off and the way they walked off.
//
// Unusual activity: the mites that flew off (came unglued and walked off; left
// out of the analysis) with their tracks over the plate, the mites that turned
// where they were (rotators), each as how far its body turned over time, and the
// recordings of the other mites set aside because one walked by.

class ActivitySection {
  // Time runs from light to dark in one hue, as in the notebooks.
  static TIME = ["#c9dcf3", "#2a78d6", "#0d2f5e"];

  constructor(page) {
    this.page = page;
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
        `Each mite's path across the recordings: where its image sits against its image in the first recording (px, py, in pixels; for a mite added during a live run, the recording it was added in, and its zone from there), from light (first recording) to dark (last), starting on the mite's centre.
        Behind the path, the mite's outline in the first recording, at the same scale (the bar, bottom left), to read how far and which way it drifted against its body;
        <i>Path</i> zooms in until the path fills the square, the outline with it.
        The mites are ranked by how far they sit from their zone's median path, what the plate under them did
        (the 95th percentile over the recordings, so one bad measurement does not rank a mite).
        After them come the fly-offs: each one's path until it flew off, then a dashed black line out of the square the way it walked off
        (once a mite has walked, it no longer looks like its first image, and its path says nothing). The rotators are left out for the same reason; they are under Unusual activity.
        Select a mite to open it.`, "mover-grid", `<span class="muted">Scale</span>
        <div class="segmented" role="group" aria-label="Scale of the paths">
          <button type="button" data-zoom="mite" class="small">Mite</button>
          <button type="button" data-zoom="path" class="small secondary">Path</button>
        </div>`)}</div>`;

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
      ${rotators.length ? `<div class="block">${figure("activity-rotators", first + 2 + (flyOffs.length ? 1 : 0), "Rotators",
        `Each mite whose body turned past ${turnLimit}° where it is: how far the long axis of its body has turned from its first recordings, in each recording
        (the median of five recordings round it, so one bad measurement does not show), clockwise on the picture up, anticlockwise down.
        The shaded band is within ${turnLimit}°; a mite outside it in three recordings is a rotator. An axis has no head and tail, so a turn reads at most 90° either way.
        A rotator stays in the analysis. Click a time to show that recording; select a mite to open it.`, "rotator-grid")}</div>`
        : `<p class="caption">No mite turned past ${turnLimit}° in these recordings.</p>`}
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
    if (this.activity.rotators.length) this.drawRotators();
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

  // One small square per mite, its path coloured by time from its centre, at the
  // mite's scale or, zoomed in, the path's.
  drawMovers() {
    const grid = $("activity-movers");
    grid.innerHTML = "";
    const plots = new Map();  // svg -> its mover
    const outlines = new Map();  // svg -> its mite's outline, once the server sent it
    const buttons = grid.closest("figure").querySelectorAll("[data-zoom]");
    const show = () => buttons.forEach((button) => button.classList.toggle("secondary", (button.dataset.zoom === "path") !== Boolean(this.zoomed)));
    show();
    buttons.forEach((button) => (button.onclick = () => {
      this.zoomed = button.dataset.zoom === "path";
      show();
      plots.forEach((mover, svg) => this.drawMover(svg, mover, outlines.get(svg) || null, this.zoomed));
    }));
    this.activity.movers.forEach((mover) => {
      const card = document.createElement("a");
      card.className = "mover-card";
      const known = this.results.mites.some((mite) => mite.id === mover.id);
      if (known) card.href = ctx.href(`mite/${encodeURIComponent(mover.id)}`);
      const flown = mover.flew_off != null;
      card.innerHTML = `<div class="mover-head"><b>Mite ${esc(mover.id)}</b> <span class="muted">zone ${esc(mover.zone)} · ${
        flown ? `flew off at ${this.at(mover.flew_off)}` : `${mover.away.toFixed(2)} px`}</span></div>`;
      const svg = PlateView.svgEl("svg", { viewBox: "0 0 150 150", class: "mover-plot", role: "img",
        "aria-label": `Path of mite ${mover.id} across the recordings` });
      svg.dataset.miteId = mover.id;
      svg.dataset.zone = mover.zone;
      this.drawMover(svg, mover, null, this.zoomed);
      plots.set(svg, mover);
      card.appendChild(svg);
      grid.appendChild(card);
    });
    this.drawMoverOutlines(grid, plots, (svg, outline) => {
      outlines.set(svg, outline);
      this.drawMover(svg, plots.get(svg), outline, this.zoomed);
    });
  }

  // One mite's square: its path and, behind it, its outline in the first recording
  // (classes/outline_view.py; null until the server sends it, or where it has none),
  // both at the mite's scale (its outline reaching 40% of the square), so the path
  // reads against the size of the mite; the path starts on the mite's centre, the
  // middle of the square. `zoomed`, or without an outline, the square holds 99% of
  // the path instead, so one far-off registration does not shrink the rest.
  drawMover(svg, mover, outline, zoomed) {
    svg.innerHTML = "";
    const size = 150;
    const n = this.results.times.length;
    const shown = mover.dx.map((x, i) => (x == null || mover.dy[i] == null ? null : [x, mover.dy[i], i])).filter(Boolean);
    const [ox, oy] = shown.length ? shown[0] : [0, 0];
    const reach = shown.map((p) => Math.max(Math.abs(p[0] - ox), Math.abs(p[1] - oy))).sort((a, b) => a - b);
    const path = Math.max(reach.length ? reach[Math.ceil(reach.length * 0.99) - 1] : 0, 0.25) * 1.15;
    const half = outline && !zoomed ? ActivitySection.reach(outline) / 0.8 : path;
    const k = size / (2 * half);  // units a pixel
    const sx = (x) => size / 2 + (x - ox) * k;
    const sy = (y) => size / 2 + (y - oy) * k;
    svg.appendChild(PlateView.svgEl("rect", { x: 0, y: 0, width: size, height: size, class: "mover-frame" }));
    if (outline) {
      const body = ActivitySection.outlineShape(outline, size, "mover-body", k);
      const tip = PlateView.svgEl("title", {});
      tip.textContent = `Mite ${mover.id}'s outline in the first recording, ${(2 * ActivitySection.reach(outline)).toFixed(0)} px across`;
      body.appendChild(tip);
      svg.appendChild(body);
    }
    shown.slice(1).forEach((p, i) => {
      const q = shown[i];
      svg.appendChild(PlateView.svgEl("line", { x1: sx(q[0]), y1: sy(q[1]), x2: sx(p[0]), y2: sy(p[1]),
        stroke: ActivitySection.timeColor(p[2] / Math.max(1, n - 1)), class: "mover-step" }));
    });
    // a fly-off: from where it was last measured, out of the square the way it walked off
    if (mover.flew_off != null && mover.walk) {
      const [lx, ly] = shown.length ? shown[shown.length - 1] : [ox, oy];
      const exit = PlateView.svgEl("line", { x1: sx(lx), y1: sy(ly), x2: sx(lx) + mover.walk[0] * 2 * size, y2: sy(ly) + mover.walk[1] * 2 * size,
        class: "mover-step mover-exit" });
      const tip = PlateView.svgEl("title", {});
      tip.textContent = `Mite ${mover.id} walked off this way at ${this.at(mover.flew_off)}`;
      exit.appendChild(tip);
      svg.appendChild(exit);
    }
    const bar = ActivitySection.barLength(0.4 * 2 * half);
    svg.appendChild(PlateView.svgEl("line", { x1: 6, y1: size - 14, x2: 6 + bar * k, y2: size - 14, class: "mover-bar" }));
    const scale = PlateView.svgEl("text", { x: 6, y: size - 4, class: "mover-scale" });
    scale.textContent = `${bar} px`;
    svg.appendChild(scale);
  }

  // Each mite's outline handed to `found(svg, outline)`, zone by zone as the server
  // sends them. Where it has none (no frames kept), the path stays alone.
  // Each mover's outline in its first recording: the run's first, or the one a live
  // run added it in (mover.start), where its path starts.
  async drawMoverOutlines(grid, plots, found) {
    const { sessionId } = ctx;
    const first = (mover) => `${mover.start || 0}/${mover.zone}`;
    for (const key of new Set([...plots.values()].map(first))) {
      const [recording, zone] = key.split("/");
      const outlines = await this.outlines(Number(recording), zone);
      if (!grid.isConnected || ctx.sessionId !== sessionId) return;
      if (!outlines) continue;
      plots.forEach((mover, svg) => {
        const outline = outlines[mover.id];
        if (first(mover) === key && outline && outline.dots.length) found(svg, outline);
      });
    }
  }

  // The outlines of the mites of zone `zone` in `recording` (the server's, kept
  // once worked out), or null where it has none (no frames kept).
  async outlines(recording, zone) {
    try {
      return await readJson(await fetch(`/api/session/${ctx.sessionId}/outline/${recording}/${encodeURIComponent(zone)}`));
    } catch {
      return null;
    }
  }

  // The longest of 1, 2 or 5 times a power of ten that is at most `most` pixels.
  static barLength(most) {
    const ten = 10 ** Math.floor(Math.log10(most));
    const length = [5, 2, 1].map((k) => k * ten).find((value) => value <= most);
    return Number(length.toPrecision(1));
  }

  // How far an outline reaches from its centre, in pixels of the recording.
  static reach(outline) {
    return Math.max(...outline.dots.map(([x, y]) => Math.hypot(x - outline.x, y - outline.y)), 1e-6);
  }

  // An outline as a polygon centred in a square of `size`, `k` units a pixel
  // (by default, reaching 40% of the square).
  static outlineShape(outline, size, cls, k = (0.4 * size) / ActivitySection.reach(outline)) {
    const points = outline.dots.map(([x, y]) =>
      `${(size / 2 + (x - outline.x) * k).toFixed(1)},${(size / 2 + (y - outline.y) * k).toFixed(1)}`).join(" ");
    return PlateView.svgEl("polygon", { points, class: cls });
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

  // A small chart per rotator: how far its body has turned from its first
  // recordings, recording by recording (the server's rotator.turns), the turn
  // within the limit shaded.
  drawRotators() {
    const grid = $("activity-rotators");
    grid.innerHTML = "";
    const limit = this.activity.turn_limit;
    this.activity.rotators.forEach((rotator) => {
      const card = document.createElement("div");
      card.className = "rotator-card";
      const known = this.results.mites.some((mite) => mite.id === rotator.id);
      const name = known ? `<a href="${ctx.href(`mite/${encodeURIComponent(rotator.id)}`)}">Mite ${esc(rotator.id)}</a>` : `Mite ${esc(rotator.id)}`;
      const turn = rotator.turned;
      card.innerHTML = `<div class="mover-head"><b>${name}</b> <span class="muted">zone ${esc(rotator.zone)} · ${Math.abs(turn).toFixed(0)}° ${
        turn >= 0 ? "clockwise" : "anticlockwise"}, past ${limit}° from ${this.at(rotator.from)}</span></div><div class="rotator-chart"></div>`;
      grid.appendChild(card);
      const top = Math.max(...rotator.turns.filter((value) => value != null).map(Math.abs), limit);
      const reach = Math.min(90, Math.ceil((top * 1.15) / 10) * 10);
      this.page.timeChart(card.querySelector(".rotator-chart"), {
        height: 200,
        yLabel: "Turn (°)",
        yMin: -reach,
        yMax: reach,
        yFormat: (v) => `${v.toFixed(0)}°`,
        threshold: { value: 0, label: "0°" },
        range: { low: -limit, high: limit },
        series: [{ name: `mite ${rotator.id}`, values: rotator.turns, color: token("--series-7"), markers: false }],
        noDirectLabels: true,
      });
    });
  }

  drawAside() {
    const table = $("activity-aside");
    if (!table) return;
    table.innerHTML = `
      <thead><tr><th>Mite</th><th class="num">Recording</th></tr></thead>
      <tbody>${this.activity.disturbed.map((row) => `<tr>
        <td>${this.miteLink(row.mite)}</td><td class="num">${this.at(row.recording)}</td></tr>`).join("")}</tbody>`;
  }
}
