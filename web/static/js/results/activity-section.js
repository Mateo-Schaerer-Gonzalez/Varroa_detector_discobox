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
// where they were (rotators), each as a clock face of its body's turn, and the
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
        `Each mite's path across the recordings: where its image sits against its image in the first recording (px, py, in pixels), from light (first recording) to dark (last), starting on the mite's centre.
        Behind the path, the mite's outline in the first recording, at its own scale, to read which way it drifted against its body: the two scales differ, so read the path's length off its bar (bottom left) against the mite's size (bottom right), not against the outline.
        The mites are ranked by how far they sit from their zone's median path, what the plate under them did
        (the 95th percentile over the recordings, so one bad measurement does not rank a mite).
        After them come the fly-offs: each one's path until it flew off, then a dashed black line out of the square the way it walked off
        (once a mite has walked, it no longer looks like its first image, and its path says nothing). The rotators are left out for the same reason; they are under Unusual activity.
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
      ${rotators.length ? `<div class="block">${figure("activity-rotators", first + 2 + (flyOffs.length ? 1 : 0), "Rotators",
        `Each mite whose body turned past ${turnLimit}° where it is, as a clock face: the grey line is the long axis of its body in its first recordings,
        the purple one in its last, and the shaded wedge the turn between them. Its outline in the first recording is drawn behind,
        its outline in the last one lighter, both at the first one's scale (far larger than in the picture). A rotator stays in the analysis.
        Select a mite to open it.`, "mover-grid")}</div>`
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

  // One small square per mite, its path coloured by time from its centre.
  drawMovers() {
    const grid = $("activity-movers");
    grid.innerHTML = "";
    const n = this.results.times.length;
    this.activity.movers.forEach((mover) => {
      const card = document.createElement("a");
      card.className = "mover-card";
      const known = this.results.mites.some((mite) => mite.id === mover.id);
      if (known) card.href = ctx.href(`mite/${encodeURIComponent(mover.id)}`);
      const flown = mover.flew_off != null;
      card.innerHTML = `<div class="mover-head"><b>Mite ${esc(mover.id)}</b> <span class="muted">zone ${esc(mover.zone)} · ${
        flown ? `flew off at ${this.at(mover.flew_off)}` : `${mover.away.toFixed(2)} px`}</span></div>`;
      const points = mover.dx.map((x, i) => (x == null || mover.dy[i] == null ? null : [x, mover.dy[i], i]));
      const shown = points.filter(Boolean);
      // the path starts on the mite's centre, the middle of the square; 99% of it
      // on the square, so one far-off registration does not shrink the rest
      const [ox, oy] = shown.length ? shown[0] : [0, 0];
      const reach = shown.map((p) => Math.max(Math.abs(p[0] - ox), Math.abs(p[1] - oy))).sort((a, b) => a - b);
      const half = Math.max(reach.length ? reach[Math.ceil(reach.length * 0.99) - 1] : 0, 0.25) * 1.15;
      const size = 150;
      const sx = (x) => ((x - ox + half) / (2 * half)) * size;
      const sy = (y) => ((y - oy + half) / (2 * half)) * size;
      const svg = PlateView.svgEl("svg", { viewBox: `0 0 ${size} ${size}`, class: "mover-plot", role: "img",
        "aria-label": `Path of mite ${mover.id} across the recordings` });
      svg.appendChild(PlateView.svgEl("rect", { x: 0, y: 0, width: size, height: size, class: "mover-frame" }));
      shown.slice(1).forEach((p, i) => {
        const q = shown[i];
        svg.appendChild(PlateView.svgEl("line", { x1: sx(q[0]), y1: sy(q[1]), x2: sx(p[0]), y2: sy(p[1]),
          stroke: ActivitySection.timeColor(p[2] / Math.max(1, n - 1)), class: "mover-step" }));
      });
      // a fly-off: from where it was last measured, out of the square the way it walked off
      if (flown && mover.walk) {
        const [lx, ly] = shown.length ? shown[shown.length - 1] : [ox, oy];
        const exit = PlateView.svgEl("line", { x1: sx(lx), y1: sy(ly), x2: sx(lx) + mover.walk[0] * 2 * size, y2: sy(ly) + mover.walk[1] * 2 * size,
          class: "mover-step mover-exit" });
        const tip = PlateView.svgEl("title", {});
        tip.textContent = `Mite ${mover.id} walked off this way at ${this.at(mover.flew_off)}`;
        exit.appendChild(tip);
        svg.appendChild(exit);
      }
      // the path's scale as a bar, so it is not read at the outline's (drawMoverOutlines)
      const bar = ActivitySection.barLength(0.4 * 2 * half);
      const barEnd = 6 + (bar / (2 * half)) * size;
      svg.appendChild(PlateView.svgEl("line", { x1: 6, y1: size - 14, x2: barEnd, y2: size - 14, class: "mover-bar" }));
      const scale = PlateView.svgEl("text", { x: 6, y: size - 4, class: "mover-scale" });
      scale.textContent = `path ${bar} px`;
      svg.appendChild(scale);
      svg.dataset.miteId = mover.id;
      svg.dataset.zone = mover.zone;
      card.appendChild(svg);
      grid.appendChild(card);
    });
    this.drawMoverOutlines(grid);
  }

  // Behind each path, the mite's outline in the first recording (classes/outline_view.py),
  // at its own scale and centred, to read which way the path runs against its body.
  // Where the server has no outline (no frames kept), the path stays alone.
  async drawMoverOutlines(grid) {
    const { sessionId } = ctx;
    const plots = [...grid.querySelectorAll(".mover-plot")];
    for (const zone of new Set(plots.map((svg) => svg.dataset.zone))) {
      const outlines = await this.outlines(0, zone);
      if (!grid.isConnected || ctx.sessionId !== sessionId) return;
      if (!outlines) continue;
      plots.filter((svg) => svg.dataset.zone === zone).forEach((svg) => {
        const outline = outlines[svg.dataset.miteId];
        if (!outline || !outline.dots.length) return;
        const body = ActivitySection.outlineShape(outline, svg.viewBox.baseVal.width, "mover-body");
        const tip = PlateView.svgEl("title", {});
        const across = (2 * ActivitySection.reach(outline)).toFixed(0);
        tip.textContent = `Mite ${svg.dataset.miteId}'s outline in the first recording, ${across} px across`;
        body.appendChild(tip);
        svg.querySelector(".mover-frame").after(body);
        const width = svg.viewBox.baseVal.width;
        const label = PlateView.svgEl("text", { x: width - 6, y: width - 4, class: "mover-scale mover-size" });
        label.textContent = `mite ${across} px across`;
        svg.appendChild(label);
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

  // A clock face per rotator: the long axis of its body in its first recordings
  // and in its last through the middle, the turn between them shaded, over its
  // outline in its first recording and, lighter, in its last.
  drawRotators() {
    const grid = $("activity-rotators");
    grid.innerHTML = "";
    const size = 150;
    const middle = size / 2;
    const hand = 0.47 * size;
    const along = (degrees, length) => [middle + Math.cos((degrees * Math.PI) / 180) * length, middle + Math.sin((degrees * Math.PI) / 180) * length];
    this.activity.rotators.forEach((rotator) => {
      const card = document.createElement("a");
      card.className = "mover-card";
      if (this.results.mites.some((mite) => mite.id === rotator.id)) card.href = ctx.href(`mite/${encodeURIComponent(rotator.id)}`);
      const { angle_first: first, turned: turn } = rotator;
      card.innerHTML = `<div class="mover-head"><b>Mite ${esc(rotator.id)}</b> <span class="muted">zone ${esc(rotator.zone)} · ${Math.abs(turn).toFixed(0)}° ${
        turn >= 0 ? "clockwise" : "anticlockwise"} from ${this.at(rotator.from)}</span></div>`;
      const svg = PlateView.svgEl("svg", { viewBox: `0 0 ${size} ${size}`, class: "mover-plot", role: "img",
        "aria-label": `Mite ${rotator.id}'s body turned ${Math.abs(turn).toFixed(0)} degrees` });
      svg.appendChild(PlateView.svgEl("rect", { x: 0, y: 0, width: size, height: size, class: "mover-frame" }));
      // the wedge on both sides of the middle: an axis has no head and tail
      [0, 180].forEach((half) => {
        const [x1, y1] = along(first + half, hand);
        const [x2, y2] = along(first + turn + half, hand);
        svg.appendChild(PlateView.svgEl("path", { class: "rotator-wedge",
          d: `M${middle},${middle} L${x1.toFixed(1)},${y1.toFixed(1)} A${hand},${hand} 0 0 ${turn >= 0 ? 1 : 0} ${x2.toFixed(1)},${y2.toFixed(1)} Z` }));
      });
      [[first, "rotator-axis first", "first"], [first + turn, "rotator-axis last", "last"]].forEach(([degrees, cls, which]) => {
        const [x1, y1] = along(degrees, hand);
        const [x2, y2] = along(degrees + 180, hand);
        const line = PlateView.svgEl("line", { x1, y1, x2, y2, class: cls });
        const tip = PlateView.svgEl("title", {});
        tip.textContent = `The long axis of its body in its ${which} recordings: ${(((degrees % 180) + 180) % 180).toFixed(0)}°`;
        line.appendChild(tip);
        svg.appendChild(line);
      });
      svg.appendChild(PlateView.svgEl("circle", { cx: middle, cy: middle, r: 2.2, class: "rotator-pin" }));
      Object.assign(svg.dataset, { miteId: rotator.id, zone: rotator.zone });
      card.appendChild(svg);
      grid.appendChild(card);
    });
    this.drawRotatorOutlines(grid);
  }

  // Behind each clock face, the rotator's outline in the first recording it was
  // measured in and, lighter, in the last, both at the first one's scale.
  async drawRotatorOutlines(grid) {
    const { sessionId } = ctx;
    for (const rotator of this.activity.rotators) {
      const first = await this.outlines(rotator.first_seen, rotator.zone);
      const last = await this.outlines(rotator.last_seen, rotator.zone);
      if (!grid.isConnected || ctx.sessionId !== sessionId) return;
      const svg = [...grid.querySelectorAll(".mover-plot")].find((plot) => plot.dataset.miteId === rotator.id);
      const [before, after] = [first?.[rotator.id], last?.[rotator.id]];
      if (!svg || !before || !before.dots.length) continue;
      const size = svg.viewBox.baseVal.width;
      const k = (0.4 * size) / ActivitySection.reach(before);
      const frame = svg.querySelector(".mover-frame");
      const shapes = [[before, "mover-body", rotator.first_seen]];
      if (after && after.dots.length) shapes.push([after, "rotator-last", rotator.last_seen]);
      // the first drawn over the last, both under the clock's hands
      shapes.forEach(([outline, cls, recording]) => {
        const shape = ActivitySection.outlineShape(outline, size, cls, k);
        const tip = PlateView.svgEl("title", {});
        tip.textContent = `Mite ${rotator.id}'s outline at ${this.at(recording)}`;
        shape.appendChild(tip);
        frame.after(shape);
      });
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
}
