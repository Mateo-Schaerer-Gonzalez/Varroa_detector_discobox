/**
 * Rows of cells over time, each coloured by its value (a raster), with curves in
 * percent over it on a right-hand axis: e.g. every mite's change from one
 * recording to the next, the mites in the order they die, and the survival.
 *
 * options:
 *   x          the columns' times (minutes); a cell lasts until the next one
 *   rows       [{ values, tip(index) -> html, onClick(index) }], the top one first;
 *              a value that is null is left blank
 *   scale      { low, high, mark, format, label }: values coloured from low to high
 *              (log scale), clipped at both ends; `mark` is drawn on the colour bar
 *   overlays   [{ name, values, color, dashed, width, band: { low, high } }]:
 *              percent at each x, 100 at the top, held until the next x
 *   yLabel, overlayLabel, xLabel, height
 */
class RasterChart {
  // From the lowest value to the highest: paper, light blue, blue, dark blue.
  static RAMP = [[255, 255, 255], [156, 195, 238], [42, 120, 214], [13, 47, 94]];
  static LEVELS = 24;

  constructor(container, options) {
    this.container = container;
    this.options = options;
    this.x = options.x;
    this.rows = options.rows;
    this.overlays = options.overlays ?? [];
    this.scale = options.scale;
  }

  draw() {
    const { container, options } = this;
    container.innerHTML = "";
    container.classList.add("chart");
    ChartKit.addLegend(container, this.overlays.map((o) => ({ name: o.name, color: o.color, dashed: o.dashed, shape: "line" })));
    this.layout();
    const svg = ChartKit.svg(this.width, this.height, options.title);
    this.drawCells(svg);
    this.drawOverlays(svg);
    this.drawAxes(svg);
    this.drawColourBar(svg);
    this.wirePointer(svg);
    container.appendChild(svg);
  }

  layout() {
    const { x, options } = this;
    this.width = Math.max(320, this.container.clientWidth || 720);
    this.height = options.height ?? 440;
    const pad = { left: 30, right: 128, top: 12, bottom: 42 };
    this.pad = pad;
    this.plotW = this.width - pad.left - pad.right;
    this.plotH = this.height - pad.top - pad.bottom;
    const step = x.length > 1 ? (x[x.length - 1] - x[0]) / (x.length - 1) : 1;
    this.xMin = x[0];
    this.xMax = x[x.length - 1] + step;  // the last column lasts one step
    this.sx = (v) => pad.left + ((v - this.xMin) / (this.xMax - this.xMin || 1)) * this.plotW;
    this.sy = (percent) => pad.top + this.plotH * (1 - percent / 100);
    this.rowH = this.plotH / Math.max(1, this.rows.length);
  }

  // The level of a value, 0 to LEVELS - 1, on a log scale from low to high.
  level(value) {
    const { low, high } = this.scale;
    const at = (Math.log(Math.max(value, low)) - Math.log(low)) / (Math.log(high) - Math.log(low));
    return Math.round(Math.min(1, Math.max(0, at)) * (RasterChart.LEVELS - 1));
  }

  static colour(level) {
    const ramp = RasterChart.RAMP;
    const at = (level / (RasterChart.LEVELS - 1)) * (ramp.length - 1);
    const i = Math.min(ramp.length - 2, Math.floor(at));
    const f = at - i;
    const rgb = ramp[i].map((c, k) => Math.round(c + (ramp[i + 1][k] - c) * f));
    return `rgb(${rgb.join(",")})`;
  }

  // One rectangle per run of cells of the same level, so a long row of quiet
  // recordings is one shape, not hundreds.
  drawCells(svg) {
    const { el } = ChartKit;
    const { x, sx, rowH, pad } = this;
    const edges = [...x.map(sx), sx(this.xMax)];
    const g = el("g", { class: "raster", "shape-rendering": "crispEdges" }, svg);
    this.rows.forEach((row, r) => {
      const y = pad.top + r * rowH;
      let start = 0;
      for (let i = 1; i <= x.length; i++) {
        const value = row.values[start];
        const levelAt = (index) => (row.values[index] == null ? null : this.level(row.values[index]));
        if (i < x.length && levelAt(i) === levelAt(start)) continue;
        if (value != null && levelAt(start) > 0) {
          el("rect", { x: edges[start], y, width: edges[i] - edges[start], height: rowH + 0.5, fill: RasterChart.colour(levelAt(start)) }, g);
        }
        start = i;
      }
    });
  }

  drawOverlays(svg) {
    const { el } = ChartKit;
    const { x, sx, sy } = this;
    const xs = [...x.map(sx), sx(this.xMax)];
    const held = (values) => [...values.slice(0, x.length), values[Math.min(values.length, x.length) - 1]];
    // A band is held like its curve: each value from its x to the next.
    for (const o of this.overlays) {
      if (!o.band) continue;
      const known = x.map((_t, i) => i).filter((i) => o.band.low[i] != null && o.band.high[i] != null);
      if (!known.length) continue;
      const upper = known.flatMap((i) => [`${xs[i]},${sy(o.band.high[i])}`, `${xs[i + 1]},${sy(o.band.high[i])}`]);
      const lower = [...known].reverse().flatMap((i) => [`${xs[i + 1]},${sy(o.band.low[i])}`, `${xs[i]},${sy(o.band.low[i])}`]);
      el("path", { d: `M${[...upper, ...lower].join("L")}Z`, fill: o.color, class: "band" }, svg);
    }
    for (const o of this.overlays) {
      const ys = held(o.values).map((v) => (v == null ? null : sy(v)));
      el("path", {
        d: ChartKit.linePath(xs, ys, true), fill: "none", stroke: o.color, "stroke-width": o.width ?? 1.75,
        "stroke-linejoin": "round", ...(o.dashed ? { "stroke-dasharray": "6 4" } : {}),
      }, svg);
    }
  }

  drawAxes(svg) {
    const { el } = ChartKit;
    const { pad, plotW, plotH, sx, sy, options } = this;
    const bottom = pad.top + plotH;
    const right = pad.left + plotW;
    const axes = el("g", {}, svg);
    for (const t of ChartKit.niceTicks(this.xMin, this.xMax, 6).filter((t) => t <= this.xMax + 1e-9)) {
      el("line", { x1: sx(t), x2: sx(t), y1: bottom, y2: bottom + 4, class: "tick-mark" }, axes);
      el("text", { x: sx(t), y: bottom + 17, "text-anchor": "middle", class: "tick" }, axes).textContent = `${+t.toFixed(1)}`;
    }
    for (const t of [0, 25, 50, 75, 100]) {
      el("line", { x1: right, x2: right + 4, y1: sy(t), y2: sy(t), class: "tick-mark" }, axes);
      el("text", { x: right + 7, y: sy(t) + 4, class: "tick" }, axes).textContent = `${t}`;
    }
    el("line", { x1: pad.left, x2: right, y1: bottom, y2: bottom, class: "axis" }, axes);
    el("line", { x1: right, x2: right, y1: pad.top, y2: bottom, class: "axis" }, axes);
    el("rect", { x: pad.left, y: pad.top, width: plotW, height: plotH, fill: "none", stroke: token("--rule") }, axes);
    el("text", { x: pad.left + plotW / 2, y: this.height - 6, "text-anchor": "middle", class: "axis-label" }, svg).textContent = options.xLabel ?? "Time (min)";
    const middle = pad.top + plotH / 2;
    el("text", { x: 14, y: middle, "text-anchor": "middle", class: "axis-label", transform: `rotate(-90 14 ${middle})` }, svg).textContent = options.yLabel ?? "";
    const label = right + 40;
    el("text", { x: label, y: middle, "text-anchor": "middle", class: "axis-label", transform: `rotate(90 ${label} ${middle})` }, svg).textContent = options.overlayLabel ?? "";
  }

  // The colour of each level, low at the bottom, with the scale's ends and its mark.
  drawColourBar(svg) {
    const { el } = ChartKit;
    const { pad, plotH, scale } = this;
    const x = pad.left + this.plotW + 62;
    const height = Math.min(plotH, 220);
    const top = pad.top + (plotH - height) / 2;
    const levels = RasterChart.LEVELS;
    for (let level = 0; level < levels; level++) {
      el("rect", { x, y: top + height * (1 - (level + 1) / levels), width: 12, height: height / levels + 0.5, fill: RasterChart.colour(level) }, svg);
    }
    el("rect", { x, y: top, width: 12, height, fill: "none", stroke: token("--rule") }, svg);
    const at = (value) => top + height * (1 - (Math.log(value) - Math.log(scale.low)) / (Math.log(scale.high) - Math.log(scale.low)));
    const format = scale.format ?? ((v) => `${v}`);
    for (const [value, cls] of [[scale.high, "tick"], [scale.low, "tick"], ...(scale.mark != null ? [[scale.mark, "tick mark"]] : [])]) {
      el("line", { x1: x + 12, x2: x + 16, y1: at(value), y2: at(value), class: "tick-mark" }, svg);
      el("text", { x: x + 18, y: at(value) + 4, class: cls }, svg).textContent = format(value);
    }
    if (scale.label) {
      el("text", { x: x + 6, y: top - 4, "text-anchor": "middle", class: "tick" }, svg).textContent = scale.label;
    }
  }

  // One cell under the pointer: its row's tooltip, and a click opens it.
  wirePointer(svg) {
    const { el } = ChartKit;
    const { pad, plotW, plotH, rowH, x } = this;
    const hit = el("rect", { x: pad.left, y: pad.top, width: plotW, height: plotH, fill: "transparent" }, svg);
    const cell = (event) => {
      const box = svg.getBoundingClientRect();
      const px = ((event.clientX - box.left) / box.width) * this.width;
      const py = ((event.clientY - box.top) / box.height) * this.height;
      const row = Math.floor((py - pad.top) / rowH);
      const time = this.xMin + ((px - pad.left) / plotW) * (this.xMax - this.xMin);
      let index = 0;
      while (index + 1 < x.length && x[index + 1] <= time) index++;
      return row >= 0 && row < this.rows.length ? { row: this.rows[row], index } : null;
    };
    hit.addEventListener("mousemove", (event) => {
      const found = cell(event);
      if (!found || !found.row.tip) { ChartKit.hideTooltip(); return; }
      hit.style.cursor = found.row.onClick ? "pointer" : "default";
      ChartKit.showTooltip(event, found.row.tip(found.index));
    });
    hit.addEventListener("mouseleave", ChartKit.hideTooltip);
    hit.addEventListener("click", (event) => {
      const found = cell(event);
      if (found?.row.onClick) found.row.onClick(found.index);
    });
  }
}
