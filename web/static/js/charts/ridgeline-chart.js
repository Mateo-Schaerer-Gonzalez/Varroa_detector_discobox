/**
 * One distribution per row, each a smoothed density (a Gaussian kernel's)
 * scaled to its own peak and rising into the row above: a ridgeline plot. A
 * tick along the base marks every value and a line the median.
 *
 * options:
 *   rows          [{ label, color, values, tip (tooltip html), onClick }], top to bottom
 *   xMin, xMax, xLabel, xFormat, padLeft
 *   rowHeight     pixels per row (default 30)
 *   overlap       a ridge's peak, in rows (default 1.6)
 *   bandwidth     the kernel's; by default one for all rows, from all their values
 *   minBandwidth  the least bandwidth, e.g. half the step of values that come in steps
 *   legend        [{ name, color, shape }]
 */
class RidgelineChart {
  static SAMPLES = 160;  // points along x at which each density is drawn

  static show(container, options) {
    const render = (target, opts) => new RidgelineChart(target, opts).draw();
    container.chartRedraw = (target, adjust) => render(target, adjust(options));
    ChartKit.keepLive(container, render, options);
  }

  // Silverman's rule of thumb, no less than `floor`.
  static kernelBandwidth(values, floor) {
    const { quantile } = ChartKit;
    const n = values.length;
    if (!n) return floor;
    const sorted = [...values].sort((a, b) => a - b);
    const mean = values.reduce((a, b) => a + b, 0) / n;
    const sd = Math.sqrt(values.reduce((sum, v) => sum + (v - mean) ** 2, 0) / Math.max(1, n - 1));
    const iqr = quantile(sorted, 0.75) - quantile(sorted, 0.25);
    const spread = Math.min(sd, iqr / 1.34) || sd;
    return Math.max(0.9 * spread * n ** -0.2, floor);
  }

  constructor(container, options) {
    this.container = container;
    this.options = options;
    this.rows = options.rows;
    this.rowHeight = options.rowHeight ?? 30;
    this.xFormat = options.xFormat ?? ((v) => `${+v.toFixed(2)}`);
  }

  draw() {
    const { container, options } = this;
    container.innerHTML = "";
    container.classList.add("chart");
    ChartKit.addLegend(container, options.legend);
    this.layout();

    const svg = ChartKit.svg(this.width, this.height, options.title);
    this.drawAxis(svg);
    // One bandwidth for every row, so each is smoothed alike.
    const { xMin, xMax } = this;
    const h = options.bandwidth ?? RidgelineChart.kernelBandwidth(
      this.rows.flatMap((row) => row.values), Math.max(options.minBandwidth ?? 0, (xMax - xMin) / 200));
    // The top row first, so each lower ridge is drawn in front of the one above it.
    this.rows.forEach((row, i) => this.drawRidge(svg, row, i, h));
    container.appendChild(svg);
  }

  layout() {
    const { options, rowHeight } = this;
    this.width = Math.max(260, this.container.clientWidth || 640);
    this.peak = rowHeight * (options.overlap ?? 1.6);
    const pad = { left: options.padLeft ?? 130, right: 16, top: Math.max(14, this.peak - rowHeight + 8), bottom: 42 };
    this.pad = pad;
    this.plotW = this.width - pad.left - pad.right;
    this.bottom = pad.top + this.rows.length * rowHeight;
    this.height = this.bottom + pad.bottom;
    this.xMin = options.xMin ?? 0;
    this.xMax = options.xMax > this.xMin ? options.xMax : this.xMin + 1;
    this.sx = (v) => pad.left + ((v - this.xMin) / (this.xMax - this.xMin)) * this.plotW;
  }

  drawAxis(svg) {
    const { el } = ChartKit;
    const { pad, plotW, sx, xMin, xMax, bottom, height, peak, rowHeight } = this;
    const grid = el("g", { class: "grid" }, svg);
    const axes = el("g", {}, svg);
    for (const t of ChartKit.niceTicks(xMin, xMax, 6).filter((t) => t >= xMin - 1e-9 && t <= xMax + 1e-9)) {
      el("line", { x1: sx(t), x2: sx(t), y1: pad.top - peak + rowHeight, y2: bottom }, grid);
      el("line", { x1: sx(t), x2: sx(t), y1: bottom, y2: bottom + 4, class: "tick-mark" }, axes);
      el("text", { x: sx(t), y: bottom + 17, "text-anchor": "middle", class: "tick" }, axes).textContent = this.xFormat(t);
    }
    el("line", { x1: pad.left, x2: pad.left + plotW, y1: bottom, y2: bottom, class: "axis" }, axes);
    el("text", { x: pad.left + plotW / 2, y: height - 6, "text-anchor": "middle", class: "axis-label" }, svg).textContent = this.options.xLabel ?? "";
  }

  // Row `i`'s ridge, smoothed with the kernel bandwidth `h`.
  drawRidge(svg, row, i, h) {
    const { el, quantile, showTooltip, hideTooltip } = ChartKit;
    const { pad, sx, xMin, xMax, peak } = this;
    const samples = RidgelineChart.SAMPLES;
    const at = Array.from({ length: samples + 1 }, (_, k) => xMin + (k / samples) * (xMax - xMin));
    const kernel = (t, v) => Math.exp(-0.5 * ((t - v) / h) ** 2);

    const base = pad.top + (i + 1) * this.rowHeight;
    const density = at.map((t) => row.values.reduce((sum, v) => sum + kernel(t, v), 0));
    const top = Math.max(...density) || 1;
    const ys = density.map((d) => base - (d / top) * peak);
    const outline = at.map((t, k) => `${k ? "L" : "M"}${sx(t)},${ys[k]}`).join("");
    const area = `${outline}L${sx(xMax)},${base}L${sx(xMin)},${base}Z`;

    const g = el("g", { class: "ridge" }, svg);
    el("path", { d: area, class: "ridge-under" }, g);
    const fill = el("path", { d: area, fill: row.color, class: "ridge-fill" }, g);
    el("path", { d: outline, fill: "none", stroke: row.color, class: "ridge-line" }, g);
    for (const v of row.values) {
      el("line", { x1: sx(v), x2: sx(v), y1: base, y2: base - 5, stroke: row.color, class: "ridge-rug" }, g);
    }
    const median = quantile([...row.values].sort((a, b) => a - b), 0.5);
    const k = Math.round(((median - xMin) / (xMax - xMin)) * samples);
    el("line", { x1: sx(median), x2: sx(median), y1: base, y2: ys[Math.max(0, Math.min(samples, k))], class: "ridge-median" }, g);
    el("text", { x: pad.left - 8, y: base - 4, "text-anchor": "end", class: "tick" }, g).textContent = row.label;

    if (row.tip || row.onClick) {
      fill.classList.add("hit-area");
      fill.addEventListener("mousemove", (event) => { g.classList.add("hover"); if (row.tip) showTooltip(event, row.tip); });
      fill.addEventListener("mouseleave", () => { g.classList.remove("hover"); hideTooltip(); });
      if (row.onClick) {
        fill.style.cursor = "pointer";
        fill.addEventListener("click", row.onClick);
      }
    }
  }
}
