/**
 * An x-y chart with numeric axes: points, lines and dashed reference lines.
 *
 * options:
 *   points      [{ x, y, color, shape ("circle" | "cross" | "square" | "ring"),
 *                  r, tip (tooltip html), label, labelDy, onClick, hidden (hover target only),
 *                  enter (new: pops in) }]
 *   lines       [{ points: [[x, y], ...], color, width, dashed }]
 *   refX, refY  [{ value, label }] vertical / horizontal dashed reference lines
 *   xLabel, yLabel, xMin, xMax, yMin, yMax, height
 *   square      height follows the width (up to `height`), for ROC curves
 *   xFormat, yFormat   value -> tick text
 *   yCategories [{ value, label, muted }] named rows instead of numeric y ticks; a
 *               muted one is greyed out, e.g. a row left out of the numbers
 *   boxes       [{ y, lo, q1, median, q3, hi, color, halfHeight, tip }] box and
 *               whiskers along x, centred on row y, drawn behind the points
 *   notes       [{ y, text }] a word on a row with nothing drawn in it
 *   padLeft     room for the y tick labels
 *   legend      [{ name, color, shape }] (shape "line" for a line key)
 */
class ScatterChart {
  static show(container, options) {
    const render = (target, opts) => new ScatterChart(target, opts).draw();
    container.chartRedraw = (target, adjust) => render(target, adjust(options));
    ChartKit.keepLive(container, render, options);
  }

  constructor(container, options) {
    this.container = container;
    this.options = options;
    this.points = options.points || [];
    this.lines = options.lines || [];
    this.refX = options.refX || [];
    this.refY = options.refY || [];
    this.boxes = options.boxes || [];
  }

  draw() {
    const { container, options } = this;
    container.innerHTML = "";
    container.classList.add("chart");
    ChartKit.addLegend(container, options.legend);
    this.layout();

    const svg = ChartKit.svg(this.width, this.height, options.title);
    this.drawAxes(svg);
    this.drawReferenceLines(svg);
    this.drawBoxes(svg);
    for (const note of options.notes || []) {
      ChartKit.el("text", { x: this.pad.left + 8, y: this.sy(note.y) + 4, class: "row-note" }, svg).textContent = note.text;
    }
    this.drawLines(svg);
    this.wirePointer(svg, this.drawPoints(svg));
    container.appendChild(svg);
  }

  // Sizes, the axes' ranges and the scales from data to pixels.
  layout() {
    const { options, points, lines, refX, refY, boxes } = this;
    this.width = Math.max(260, this.container.clientWidth || 640);
    const pad = { left: options.padLeft ?? (options.yCategories ? 70 : 56), right: 16, top: 14, bottom: 42 };
    this.pad = pad;
    this.height = options.square
      ? Math.min(options.height ?? 380, this.width - pad.left - pad.right + pad.top + pad.bottom)
      : options.height ?? 280;
    this.plotW = this.width - pad.left - pad.right;
    this.plotH = this.height - pad.top - pad.bottom;

    // A free end of an axis gets a little room so no point sits on the frame.
    // A loop, not Math.min(...values): too many values overflow the call stack.
    const extent = (values, fixedMin, fixedMax) => {
      let lo = Infinity;
      let hi = -Infinity;
      for (const v of values) { if (v < lo) lo = v; if (v > hi) hi = v; }
      if (!(hi > lo)) { lo -= 1; hi += 1; }
      const margin = (hi - lo) * 0.05;
      return [fixedMin ?? lo - margin, fixedMax ?? hi + margin];
    };
    [this.xMin, this.xMax] = extent(
      [...points.map((p) => p.x), ...lines.flatMap((l) => l.points.map((p) => p[0])), ...refX.map((r) => r.value),
        ...boxes.flatMap((b) => [b.lo, b.hi])],
      options.xMin, options.xMax);
    [this.yMin, this.yMax] = extent(
      [...points.map((p) => p.y), ...lines.flatMap((l) => l.points.map((p) => p[1])), ...refY.map((r) => r.value)],
      options.yMin, options.yMax);
    this.sx = (v) => pad.left + ((v - this.xMin) / (this.xMax - this.xMin)) * this.plotW;
    this.sy = (v) => pad.top + this.plotH - ((v - this.yMin) / (this.yMax - this.yMin)) * this.plotH;
  }

  drawAxes(svg) {
    const { el, niceTicks } = ChartKit;
    const { options, pad, plotW, plotH, sx, sy, xMin, xMax, yMin, yMax, height } = this;
    const xFormat = options.xFormat ?? ((v) => `${+v.toFixed(2)}`);
    const yFormat = options.yFormat ?? ((v) => `${+v.toFixed(2)}`);
    const inside = (t, lo, hi) => t >= lo - 1e-9 && t <= hi + 1e-9;
    const grid = el("g", { class: "grid" }, svg);
    const axes = el("g", {}, svg);
    const bottom = pad.top + plotH;
    const yTicks = options.yCategories || niceTicks(yMin, yMax).filter((t) => inside(t, yMin, yMax)).map((value) => ({ value, label: yFormat(value) }));
    for (const { value, label, muted } of yTicks) {
      el("line", { x1: pad.left, x2: pad.left + plotW, y1: sy(value), y2: sy(value) }, grid);
      el("line", { x1: pad.left - 4, x2: pad.left, y1: sy(value), y2: sy(value), class: "tick-mark" }, axes);
      el("text", { x: pad.left - 7, y: sy(value) + 4, "text-anchor": "end", class: muted ? "tick muted-tick" : "tick" }, axes).textContent = label;
    }
    for (const t of niceTicks(xMin, xMax, 6).filter((t) => inside(t, xMin, xMax))) {
      el("line", { x1: sx(t), x2: sx(t), y1: pad.top, y2: bottom }, grid);
      el("line", { x1: sx(t), x2: sx(t), y1: bottom, y2: bottom + 4, class: "tick-mark" }, axes);
      el("text", { x: sx(t), y: bottom + 17, "text-anchor": "middle", class: "tick" }, axes).textContent = xFormat(t);
    }
    el("line", { x1: pad.left, x2: pad.left + plotW, y1: bottom, y2: bottom, class: "axis" }, axes);
    el("line", { x1: pad.left, x2: pad.left, y1: pad.top, y2: bottom, class: "axis" }, axes);
    el("text", { x: pad.left + plotW / 2, y: height - 6, "text-anchor": "middle", class: "axis-label" }, svg).textContent = options.xLabel ?? "";
    el("text", { x: 14, y: pad.top + plotH / 2, "text-anchor": "middle", class: "axis-label", transform: `rotate(-90 14 ${pad.top + plotH / 2})` }, svg).textContent = options.yLabel ?? "";
  }

  // Reference lines; labels of vertical ones stack down so they never overlap.
  drawReferenceLines(svg) {
    const { el } = ChartKit;
    const { pad, plotW, plotH, sx, sy } = this;
    const bottom = pad.top + plotH;
    this.refY.forEach(({ value, label }) => {
      el("line", { x1: pad.left, x2: pad.left + plotW, y1: sy(value), y2: sy(value), class: "threshold" }, svg);
      if (label) el("text", { x: pad.left + plotW - 4, y: sy(value) - 6, "text-anchor": "end", class: "threshold-label" }, svg).textContent = label;
    });
    [...this.refX].sort((a, b) => a.value - b.value).forEach(({ value, label }, i) => {
      el("line", { x1: sx(value), x2: sx(value), y1: pad.top, y2: bottom, class: "threshold" }, svg);
      if (!label) return;
      const right = sx(value) < pad.left + plotW * 0.7;
      el("text", {
        x: sx(value) + (right ? 5 : -5), y: pad.top + 11 + i * 14,
        "text-anchor": right ? "start" : "end", class: "threshold-label",
      }, svg).textContent = label;
    });
  }

  // Box: the middle half of the values, a line at the median; whiskers to lo and hi.
  drawBoxes(svg) {
    const { el, showTooltip, hideTooltip } = ChartKit;
    const { sx, sy } = this;
    const ppu = this.plotH / (this.yMax - this.yMin);  // pixels per unit of y
    for (const b of this.boxes) {
      const cy = sy(b.y);
      const h = (b.halfHeight ?? 0.3) * ppu;
      const g = el("g", { class: "box", stroke: b.color }, svg);
      el("line", { x1: sx(b.lo), x2: sx(b.q1), y1: cy, y2: cy }, g);
      el("line", { x1: sx(b.q3), x2: sx(b.hi), y1: cy, y2: cy }, g);
      el("line", { x1: sx(b.lo), x2: sx(b.lo), y1: cy - h / 2, y2: cy + h / 2 }, g);
      el("line", { x1: sx(b.hi), x2: sx(b.hi), y1: cy - h / 2, y2: cy + h / 2 }, g);
      el("rect", { x: sx(b.q1), y: cy - h, width: Math.max(1, sx(b.q3) - sx(b.q1)), height: 2 * h, class: "box-body" }, g);
      el("line", { x1: sx(b.median), x2: sx(b.median), y1: cy - h, y2: cy + h, class: "box-median" }, g);
      if (b.tip) {
        // The whole box and its whiskers; the points drawn over it keep their own tooltips.
        const hit = el("rect", { x: sx(b.lo) - 4, y: cy - h - 4, width: sx(b.hi) - sx(b.lo) + 8, height: 2 * h + 8, fill: "transparent", stroke: "none", class: "hit" }, g);
        hit.addEventListener("mousemove", (event) => { g.classList.add("hover"); showTooltip(event, b.tip); });
        hit.addEventListener("mouseleave", () => { g.classList.remove("hover"); hideTooltip(); });
      }
    }
  }

  drawLines(svg) {
    for (const l of this.lines) {
      const d = l.points.map(([x, y], i) => `${i ? "L" : "M"}${this.sx(x)},${this.sy(y)}`).join("");
      ChartKit.el("path", {
        d, fill: "none", stroke: l.color, "stroke-width": l.width ?? 2,
        "stroke-linejoin": "round", "stroke-linecap": "round",
        ...(l.dashed ? { "stroke-dasharray": "5 4" } : {}),
      }, svg);
    }
  }

  // A plain point is one subpath of a path shared with every point of the same
  // look, so thousands of points stay a handful of elements. A point that pops
  // in or carries a label keeps its own element. Returns the points to hover or
  // click, in screen coordinates.
  drawPoints(svg) {
    const { el, glyph, glyphPath, glyphPaint } = ChartKit;
    const shared = new Map();
    const targets = [];
    for (const p of this.points) {
      const cx = this.sx(p.x);
      const cy = this.sy(p.y);
      const r = p.r ?? 4;
      if (p.tip || p.onClick) targets.push({ p, cx, cy, r });
      if (p.hidden) continue;
      const entering = p.enter && this.options.animate !== false;
      if (entering || p.label) {
        const g = el("g", { class: `point${entering ? " enter-mark" : ""}` }, svg);
        glyph(g, p.shape, cx, cy, r, p.color);
        if (p.label) el("text", { x: cx + r + 5, y: cy + 4 + (p.labelDy || 0), class: "point-label" }, g).textContent = p.label;
        continue;
      }
      const key = `${p.shape}|${p.color}`;
      if (!shared.has(key)) shared.set(key, { shape: p.shape, color: p.color, d: [] });
      shared.get(key).d.push(glyphPath(p.shape, cx, cy, r));
    }
    for (const { shape, color, d } of shared.values()) {
      el("path", { d: d.join(""), ...glyphPaint(shape, color) }, svg);
    }
    return targets;
  }

  // One listener for every point: the nearest within reach of the pointer, whose
  // reach is larger than its mark, so small points are easy to hover.
  wirePointer(svg, targets) {
    if (!targets.length) return;
    const { el, glyph, showTooltip, hideTooltip } = ChartKit;
    const { width, height } = this;
    const hoverMark = el("g", { class: "point hover", "pointer-events": "none" }, svg);
    let current = null;
    const at = (event) => {
      const box = svg.getBoundingClientRect();
      const px = ((event.clientX - box.left) / box.width) * width;
      const py = ((event.clientY - box.top) / box.height) * height;
      let best = null;
      let bestDistance = Infinity;
      for (const t of targets) {
        const dx = t.cx - px;
        const dy = t.cy - py;
        const distance = dx * dx + dy * dy;
        const reach = t.r + 5;
        if (distance <= reach * reach && distance < bestDistance) { best = t; bestDistance = distance; }
      }
      return best;
    };
    svg.addEventListener("mousemove", (event) => {
      const t = at(event);
      if (t !== current) {
        current = t;
        hoverMark.innerHTML = "";
        if (t && !t.p.hidden) glyph(hoverMark, t.p.shape, t.cx, t.cy, t.r, t.p.color);
        svg.style.cursor = t && t.p.onClick ? "pointer" : "";
        // Off every point, a box under the pointer shows its own tooltip.
        if (!t && !event.target.classList.contains("hit")) hideTooltip();
      }
      if (t && t.p.tip) showTooltip(event, typeof t.p.tip === "function" ? t.p.tip() : t.p.tip);
    });
    svg.addEventListener("mouseleave", () => {
      current = null;
      hoverMark.innerHTML = "";
      hideTooltip();
    });
    svg.addEventListener("click", (event) => {
      const t = at(event);
      if (t && t.p.onClick) t.p.onClick(event);
    });
  }
}
