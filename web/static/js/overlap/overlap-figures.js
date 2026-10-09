// TEMPORARY, with overlap.html. The two figures of the ground-truth check: how
// many recordings of each label have each score, with the overlap shaded
// (histogram), and one mite's scores and labels over its run (trace). The
// numbers are the server's (classes/truth_overlap.py); this only draws them.

class OverlapFigures {
  static NAMES = { moving: "labelled moving", still: "labelled still" };
  static FLOOR = 0.01;  // the lowest score the trace's axis shows; lower ones are drawn there
  static LIFT = 0.35;   // how far above the histogram's baseline a single recording stands, in powers of ten

  // A score as text: three significant digits.
  static score(value) {
    return value == null ? "–" : String(+Number(value).toPrecision(3));
  }

  // Where `value` lies between `low` and `high` on a logarithmic axis, 0 to 1.
  static along(value, low, high) {
    const log = (v) => Math.log10(Math.min(Math.max(v, low), high));
    return (log(value) - log(low)) / (log(high) - log(low));
  }

  // The powers of ten from `low` to `high`.
  static decades(low, high) {
    const ticks = [];
    for (let power = Math.ceil(Math.log10(low) - 1e-9); 10 ** power <= high * (1 + 1e-9); power++) ticks.push(+(10 ** power).toPrecision(1));
    return ticks;
  }

  static colors() {
    return { moving: token("--moving"), still: token("--still") };
  }

  // A tooltip's row for one label: its colour, its name and a value.
  static tipRow(label, value) {
    return `<div class="tip-row"><i style="background:${OverlapFigures.colors()[label]}"></i><span>${OverlapFigures.NAMES[label]}</span>${value}</div>`;
  }

  // The recordings of each label by score, the overlap `band` shaded and the
  // score of the datapoint on screen marked.
  static histogram(container, { histogram, band, score, metric }) {
    const { el } = ChartKit;
    const colors = OverlapFigures.colors();
    container.innerHTML = "";
    ChartKit.addLegend(container, ["still", "moving"].map((label) => ({ name: OverlapFigures.NAMES[label], color: colors[label], shape: "line" })));

    const width = Math.max(container.clientWidth, 280);
    const height = 200;
    const box = { left: 44, right: 12, top: 18, bottom: 40 };
    const base = height - box.bottom;
    const { edges } = histogram;
    const [first, last] = [edges[0], edges[edges.length - 1]];
    const x = (value) => box.left + OverlapFigures.along(value, first, last) * (width - box.left - box.right);
    const most = Math.max(1, ...histogram.still, ...histogram.moving);
    const y = (count) => (count
      ? base - ((Math.log10(count) + OverlapFigures.LIFT) / (Math.log10(most) + OverlapFigures.LIFT)) * (base - box.top)
      : base);

    const svg = ChartKit.svg(width, height, `Recordings labelled still and labelled moving by their ${metric} score`);
    const grid = el("g", { class: "grid" }, svg);
    OverlapFigures.decades(1, most).forEach((count) => {
      el("line", { x1: box.left, x2: width - box.right, y1: y(count), y2: y(count) }, grid);
      el("text", { x: box.left - 6, y: y(count) + 4, "text-anchor": "end", class: "tick" }, svg).textContent = count.toLocaleString("en-US");
    });
    el("text", { x: 0, y: 10, class: "tick" }, svg).textContent = "recordings";

    if (band) {
      el("rect", { x: x(band.low), y: box.top, width: Math.max(1, x(band.high) - x(band.low)), height: base - box.top, class: "range" }, svg);
      el("text", { x: (x(band.low) + x(band.high)) / 2, y: box.top - 5, "text-anchor": "middle", class: "threshold-label" }, svg).textContent = "overlap";
    }

    el("line", { x1: box.left, x2: width - box.right, y1: base, y2: base, class: "axis" }, svg);
    OverlapFigures.decades(first, last).forEach((tick) => {
      el("line", { x1: x(tick), x2: x(tick), y1: base, y2: base + 4, class: "tick-mark" }, svg);
      el("text", { x: x(tick), y: base + 16, "text-anchor": "middle", class: "tick" }, svg).textContent = tick;
    });
    el("text", { x: (box.left + width - box.right) / 2, y: height - 4, "text-anchor": "middle", class: "axis-label" }, svg)
      .textContent = `${metric} score`;

    // Each label as a staircase over the bins, from the baseline and back to it.
    ["still", "moving"].forEach((label) => {
      const counts = histogram[label];
      let d = `M${x(edges[0])},${base}`;
      counts.forEach((count, bin) => { d += `V${y(count)}H${x(edges[bin + 1])}`; });
      el("path", { d: `${d}V${base}`, fill: "none", stroke: colors[label], "stroke-width": 2, "stroke-linejoin": "round" }, svg);
    });

    if (score != null) el("line", { x1: x(score), x2: x(score), y1: box.top, y2: base, class: "selected-x" }, svg);

    // One strip per bin to hover: how many recordings of each label it holds.
    histogram.still.forEach((still, bin) => {
      const strip = el("rect", { x: x(edges[bin]), y: box.top, width: x(edges[bin + 1]) - x(edges[bin]), height: base - box.top, class: "ov-bin" }, svg);
      const range = bin === 0
        ? `up to ${OverlapFigures.score(edges[1])}`
        : `${OverlapFigures.score(edges[bin])} to ${OverlapFigures.score(edges[bin + 1])}`;
      strip.addEventListener("mousemove", (event) => Charts.showTooltip(event,
        `<div class="tip-title">Score ${range}</div>${OverlapFigures.tipRow("still", still)}${OverlapFigures.tipRow("moving", histogram.moving[bin])}`));
      strip.addEventListener("mouseleave", Charts.hideTooltip);
    });
    container.appendChild(svg);
  }

  // One mite over its run: its score in every recording, the overlap `band`
  // shaded, its labels as ticks under the scores (`states`: a letter per
  // recording, m, s or -), and the recording on screen marked.
  static trace(container, { scores, states, recording, band }) {
    const { el } = ChartKit;
    const colors = OverlapFigures.colors();
    container.innerHTML = "";
    const n = scores.length;
    const width = Math.max(container.clientWidth, 320);
    const height = 182;
    const box = { left: 52, right: 12, top: 12, bottom: 64 };
    const base = height - box.bottom;
    const rows = { moving: base + 14, still: base + 26 };  // the top of each label's row of ticks
    const rowHeight = 7;
    const floor = OverlapFigures.FLOOR;
    const top = Math.max(1, ...scores, band ? band.high : 0) * 1.3;
    const x = (index) => box.left + (n > 1 ? index / (n - 1) : 0.5) * (width - box.left - box.right);
    const y = (value) => base - OverlapFigures.along(value, floor, top) * (base - box.top);

    const svg = ChartKit.svg(width, height, "The mite's score and labels in every recording");
    const grid = el("g", { class: "grid" }, svg);
    OverlapFigures.decades(floor, top).forEach((tick) => {
      el("line", { x1: box.left, x2: width - box.right, y1: y(tick), y2: y(tick) }, grid);
      el("text", { x: box.left - 6, y: y(tick) + 4, "text-anchor": "end", class: "tick" }, svg).textContent = tick;
    });
    if (band) {
      el("rect", { x: box.left, y: y(band.high), width: width - box.left - box.right, height: Math.max(1, y(band.low) - y(band.high)), class: "range" }, svg);
      el("text", { x: width - box.right - 4, y: y(band.high) - 4, "text-anchor": "end", class: "threshold-label" }, svg).textContent = "overlap";
    }
    el("line", { x1: box.left, x2: width - box.right, y1: base, y2: base, class: "axis" }, svg);
    el("path", { d: ChartKit.linePath(scores.map((_, index) => x(index)), scores.map(y)), fill: "none", stroke: token("--ink"), "stroke-width": 1.25, "stroke-linejoin": "round" }, svg);

    // The labels: a tick in the upper row where moving, in the lower row where still.
    const tick = Math.max(1, Math.min(8, (width - box.left - box.right) / Math.max(n - 1, 1) - 0.5));
    Object.entries({ moving: "m", still: "s" }).forEach(([label, letter]) => {
      el("text", { x: box.left - 6, y: rows[label] + rowHeight, "text-anchor": "end", class: "tick" }, svg).textContent = label;
      let d = "";
      [...states].forEach((state, index) => { if (state === letter) d += `M${x(index) - tick / 2},${rows[label]}h${tick}v${rowHeight}h${-tick}z`; });
      if (d) el("path", { d, fill: colors[label] }, svg);
    });

    const ticksEnd = rows.still + rowHeight;
    const marks = n > 12 ? ChartKit.niceTicks(0, n, 6).filter((value) => value >= 1 && value <= n) : scores.map((_, index) => index + 1);
    marks.forEach((value) => {
      el("line", { x1: x(value - 1), x2: x(value - 1), y1: ticksEnd + 2, y2: ticksEnd + 6, class: "tick-mark" }, svg);
      el("text", { x: x(value - 1), y: ticksEnd + 18, "text-anchor": "middle", class: "tick" }, svg).textContent = value;
    });
    el("text", { x: (box.left + width - box.right) / 2, y: height - 2, "text-anchor": "middle", class: "axis-label" }, svg).textContent = "recording";

    el("line", { x1: x(recording), x2: x(recording), y1: box.top, y2: ticksEnd, class: "selected-x" }, svg);
    el("circle", { cx: x(recording), cy: y(scores[recording]), r: 4, fill: token("--ink"), class: "marker" }, svg);

    // Hovering reads off the nearest recording.
    const crosshair = el("line", { y1: box.top, y2: ticksEnd, class: "crosshair", visibility: "hidden" }, svg);
    const over = el("rect", { x: box.left, y: box.top, width: width - box.left - box.right, height: ticksEnd - box.top, fill: "transparent" }, svg);
    over.addEventListener("mousemove", (event) => {
      const bounds = svg.getBoundingClientRect();
      const at = ((event.clientX - bounds.left) / bounds.width) * width;
      const index = Math.max(0, Math.min(n - 1, Math.round(((at - box.left) / (width - box.left - box.right)) * (n - 1))));
      crosshair.setAttribute("x1", x(index));
      crosshair.setAttribute("x2", x(index));
      crosshair.setAttribute("visibility", "visible");
      const label = { m: "labelled moving", s: "labelled still" }[states[index]] || "unlabelled";
      Charts.showTooltip(event, `<div class="tip-title">Recording ${index + 1}</div>score ${OverlapFigures.score(scores[index])}<div class="tip-note">${label}</div>`);
    });
    over.addEventListener("mouseleave", () => { crosshair.setAttribute("visibility", "hidden"); Charts.hideTooltip(); });
    container.appendChild(svg);
  }
}
