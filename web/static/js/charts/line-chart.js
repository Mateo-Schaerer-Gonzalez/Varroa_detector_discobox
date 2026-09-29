/**
 * A time series with axes, legend and a hover tooltip.
 *
 * options:
 *   x           shared x values (time in minutes)
 *   series      [{ name, values, color, width, step, faint, markers, pointColors,
 *                  legend, tooltip, onClick, band }]
 *               band: { low, high }, e.g. a confidence interval, shaded in the
 *               series' colour beneath every line and given in the tooltip
 *   yLabel, xLabel, yMin, yMax, height
 *   yFormat     value -> text, for axis ticks and the tooltip
 *   threshold   { value, label } drawn as a dashed reference line
 *   selected    index of the x value to mark, e.g. the recording on screen
 *   onXClick    index -> called when the chart is clicked away from a clickable line
 *   xDomain     [min, max] of the x axis, e.g. a whole live run; the part past
 *               the last x value is shaded as still to come
 *   enterFrom   index of the first new x value, whose points are drawn in
 */
class LineChart {
  static show(container, options) {
    const render = (target, opts) => new LineChart(target, opts).draw();
    container.chartRedraw = (target, adjust) => render(target, adjust(options));
    ChartKit.keepLive(container, render, options);
  }

  constructor(container, options) {
    this.container = container;
    this.options = options;
    this.x = options.x;
    this.series = options.series;
    this.yFormat = options.yFormat ?? ((v) => `${+v.toFixed(2)}`);
    this.hovered = null;  // the clickable or faint line under the pointer
  }

  draw() {
    const { container, options } = this;
    container.innerHTML = "";
    container.classList.add("chart");

    const legendSeries = this.series.filter((s) => s.legend !== false);
    if (legendSeries.length >= 2 || options.forceLegend) container.appendChild(this.legend(legendSeries));
    this.layout(legendSeries);

    const svg = ChartKit.svg(this.width, this.height, options.title);
    this.drawAxes(svg);
    this.drawThreshold(svg);

    const { el } = ChartKit;
    const { pad, plotH } = this;
    this.xs = this.x.map(this.sx);
    if (options.selected != null && this.xs[options.selected] != null) {
      const at = this.xs[options.selected];
      el("line", { x1: at, x2: at, y1: pad.top, y2: pad.top + plotH, class: "selected-x" }, svg);
    }
    const crosshair = el("line", { y1: pad.top, y2: pad.top + plotH, class: "crosshair", visibility: "hidden" }, svg);

    this.drawEndLabels(svg, this.drawSeries(svg));
    this.wirePointer(svg, crosshair);
    container.appendChild(svg);
  }

  legend(items) {
    const legend = document.createElement("div");
    legend.className = "legend";
    legend.innerHTML = items
      .map((s) => `<span class="legend-item"><i style="background:${s.color}${s.dashed ? ";height:0;border-top:2px dashed " + s.color : ""}"></i>${ChartKit.escape(s.name)}</span>`)
      .join("");
    return legend;
  }

  // Sizes, the axes' ranges and the scales from data to pixels.
  layout(legendSeries) {
    const { options, x } = this;
    const threshold = options.threshold;
    this.height = options.height ?? 280;
    this.width = Math.max(280, this.container.clientWidth || 640);
    // Room on the right for direct labels when there are few enough to fit.
    this.directLabels = legendSeries.length >= 1 && legendSeries.length <= 4 && this.width > 480 && !options.noDirectLabels;
    const pad = { left: 56, right: this.directLabels ? 96 : 16, top: 14, bottom: 42 };
    this.pad = pad;
    this.plotW = this.width - pad.left - pad.right;
    this.plotH = this.height - pad.top - pad.bottom;

    const allValues = this.series.flatMap((s) => [...s.values, ...(s.band ? [...s.band.low, ...s.band.high] : [])].filter((v) => v != null));
    if (threshold) allValues.push(threshold.value);
    const yMin = options.yMin ?? Math.min(0, ...allValues);
    let yMax = options.yMax ?? Math.max(...allValues, yMin + 1);
    this.yTicks = ChartKit.niceTicks(yMin, yMax);
    if (options.yMax == null) yMax = Math.max(yMax, this.yTicks[this.yTicks.length - 1]);
    Object.assign(this, { yMin, yMax });

    const domain = options.xDomain;
    this.xMin = domain ? Math.min(domain[0], x[0]) : x[0];
    this.xMax = domain ? Math.max(domain[1], x[x.length - 1]) : x.length > 1 ? x[x.length - 1] : x[0] + 1;
    this.sx = (v) => pad.left + ((v - this.xMin) / (this.xMax - this.xMin || 1)) * this.plotW;
    this.sy = (v) => pad.top + this.plotH - ((v - yMin) / (yMax - yMin || 1)) * this.plotH;
  }

  // Left and bottom axes with outward tick marks, as in a printed figure;
  // the grid behind the data stays very faint.
  drawAxes(svg) {
    const { el } = ChartKit;
    const { pad, plotW, plotH, sx, sy, x, yMin, yMax, xMin, xMax, height } = this;
    const domain = this.options.xDomain;
    const grid = el("g", { class: "grid" }, svg);
    const axes = el("g", {}, svg);
    const bottom = pad.top + plotH;
    for (const t of this.yTicks) {
      if (t < yMin - 1e-9 || t > yMax + 1e-9) continue;
      el("line", { x1: pad.left, x2: pad.left + plotW, y1: sy(t), y2: sy(t) }, grid);
      el("line", { x1: pad.left - 4, x2: pad.left, y1: sy(t), y2: sy(t), class: "tick-mark" }, axes);
      el("text", { x: pad.left - 7, y: sy(t) + 4, "text-anchor": "end", class: "tick" }, axes).textContent = this.yFormat(t);
    }
    // Still to come: the part of a whole run's axis past the last recording.
    const lastX = sx(x[x.length - 1]);
    if (domain && pad.left + plotW - lastX > 1) {
      el("rect", { x: lastX, y: pad.top, width: pad.left + plotW - lastX, height: plotH, class: "pending" }, grid);
      if (pad.left + plotW - lastX > 70) {
        el("text", { x: pad.left + plotW - 6, y: pad.top + 14, "text-anchor": "end", class: "pending-label" }, grid).textContent = "still to come";
      }
    }
    const xTicks = x.length <= 10 && !domain ? x : ChartKit.niceTicks(xMin, xMax, 6).filter((t) => t <= xMax + 1e-9);
    for (const t of xTicks) {
      el("line", { x1: sx(t), x2: sx(t), y1: bottom, y2: bottom + 4, class: "tick-mark" }, axes);
      el("text", { x: sx(t), y: bottom + 17, "text-anchor": "middle", class: "tick" }, axes).textContent = `${+t.toFixed(1)}`;
    }
    el("line", { x1: pad.left, x2: pad.left + plotW, y1: bottom, y2: bottom, class: "axis" }, axes);
    el("line", { x1: pad.left, x2: pad.left, y1: pad.top, y2: bottom, class: "axis" }, axes);
    el("text", { x: pad.left + plotW / 2, y: height - 6, "text-anchor": "middle", class: "axis-label" }, svg).textContent = this.options.xLabel ?? "Time (min)";
    el("text", { x: 14, y: pad.top + plotH / 2, "text-anchor": "middle", class: "axis-label", transform: `rotate(-90 14 ${pad.top + plotH / 2})` }, svg).textContent = this.options.yLabel ?? "";
  }

  drawThreshold(svg) {
    const { threshold } = this.options;
    if (!threshold) return;
    const { el } = ChartKit;
    const { pad, plotW } = this;
    const y = this.sy(threshold.value);
    el("line", { x1: pad.left, x2: pad.left + plotW, y1: y, y2: y, class: "threshold" }, svg);
    el("text", { x: pad.left + plotW - 4, y: y - 6, "text-anchor": "end", class: "threshold-label" }, svg).textContent = threshold.label;
  }

  // Every line, faint ones first so the emphasised ones sit on top. Returns the
  // direct labels to put at the lines' ends.
  drawSeries(svg) {
    const { el, linePath } = ChartKit;
    const { options, xs, x } = this;
    const ordered = [...this.series].sort((a, b) => (b.faint ? 1 : 0) - (a.faint ? 1 : 0));
    const endLabels = [];
    // The bands first, so that every line sits on top of them.
    for (const s of this.series) {
      if (s.band) el("path", { d: this.bandPath(s.band, s.step), fill: s.color, class: "band" }, svg);
    }
    // New points: the line on from the last old one is drawn in, their markers pop in.
    const enter = options.animate !== false && options.enterFrom > 0 && options.enterFrom < x.length ? options.enterFrom : null;

    for (const s of ordered) {
      const ys = s.values.map((v) => (v == null ? null : this.sy(v)));
      const d = linePath(xs, ys, s.step);
      const g = el("g", { class: `series${s.faint ? " faint" : ""}` }, svg);
      const stroke = {
        fill: "none", stroke: s.color, "stroke-width": s.width ?? 1.75,
        "stroke-linejoin": "round", "stroke-linecap": "round",
        ...(s.dashed ? { "stroke-dasharray": "6 5" } : {}),
      };
      if (enter == null || s.dashed) el("path", { d, ...stroke }, g);
      else {
        el("path", { d: linePath(xs.slice(0, enter), ys.slice(0, enter), s.step), ...stroke }, g);
        el("path", { d: linePath(xs.slice(enter - 1), ys.slice(enter - 1), s.step), ...stroke, pathLength: 1, class: "enter-line" }, g);
      }

      if (s.markers !== false && !s.faint) {
        ys.forEach((y, i) => {
          if (y == null) return;
          el("circle", {
            cx: xs[i], cy: y, r: 3.5, fill: s.pointColors ? s.pointColors[i] : s.color,
            class: `marker${enter != null && i >= enter ? " enter-mark" : ""}`,
          }, g);
        });
      }

      if (this.directLabels && s.legend !== false) {
        const last = ys.map((y, i) => [y, i]).filter(([y]) => y != null).pop();
        if (last) endLabels.push({ name: s.name, x: xs[last[1]] + 8, y: last[0] + 4 });
      }

      // A wide invisible stroke makes thin lines easy to hover and click.
      if (s.onClick || s.faint) {
        const hit = el("path", { d, fill: "none", stroke: "transparent", "stroke-width": 12, class: "hit" }, g);
        hit.addEventListener("mouseenter", () => { this.hovered = s; g.classList.add("hover"); });
        hit.addEventListener("mouseleave", () => { this.hovered = null; g.classList.remove("hover"); });
        if (s.onClick) {
          hit.style.cursor = "pointer";
          hit.addEventListener("click", () => s.onClick());
        }
      }
    }
    return endLabels;
  }

  // The corners of a line through the points, a staircase when `step`.
  static corners(xs, ys, step) {
    const points = [];
    ys.forEach((y, i) => {
      if (step && i > 0) points.push([xs[i], ys[i - 1]]);
      points.push([xs[i], y]);
    });
    return points;
  }

  // The area between a band's `low` and `high`: one closed shape per stretch of
  // time points without a gap, along `high` and back along `low`.
  bandPath({ low, high }, step) {
    const { xs, sy } = this;
    let d = "";
    let stretch = [];
    const close = () => {
      if (stretch.length) {
        const x = stretch.map((i) => xs[i]);
        const top = LineChart.corners(x, stretch.map((i) => sy(high[i])), step);
        const bottom = LineChart.corners(x, stretch.map((i) => sy(low[i])), step).reverse();
        d += `M${[...top, ...bottom].map(([px, py]) => `${px},${py}`).join("L")}Z`;
      }
      stretch = [];
    };
    low.forEach((value, i) => {
      if (value == null || high[i] == null) close();
      else stretch.push(i);
    });
    close();
    return d;
  }

  // Lines ending at the same value would print their names on top of each
  // other; working up from the x axis, lift each label clear of the one below.
  drawEndLabels(svg, endLabels) {
    endLabels.sort((a, b) => b.y - a.y);
    endLabels.forEach((label, i) => {
      if (i > 0) label.y = Math.min(label.y, endLabels[i - 1].y - 14);
      ChartKit.el("text", { x: label.x, y: label.y, class: "direct-label" }, svg).textContent = label.name;
    });
  }

  // The time point nearest the pointer, or -1 outside the plot.
  nearest(svg, event) {
    const { pad, plotW, xs } = this;
    const box = svg.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * this.width;
    if (px < pad.left - 10 || px > pad.left + plotW + 10) return -1;
    let index = 0;
    xs.forEach((value, i) => { if (Math.abs(value - px) < Math.abs(xs[index] - px)) index = i; });
    return index;
  }

  // A click picks a time point; hovering shows a crosshair and a tooltip there.
  wirePointer(svg, crosshair) {
    const { options, series, xs, x } = this;
    const { escape, showTooltip, hideTooltip } = ChartKit;
    if (options.onXClick) {
      svg.style.cursor = "pointer";
      svg.addEventListener("click", (event) => {
        if (this.hovered && this.hovered.onClick) return;  // the line's own click wins
        const index = this.nearest(svg, event);
        if (index >= 0) options.onXClick(index);
      });
    }

    svg.addEventListener("mousemove", (event) => {
      const index = this.nearest(svg, event);
      if (index < 0) { crosshair.setAttribute("visibility", "hidden"); hideTooltip(); return; }
      crosshair.setAttribute("x1", xs[index]);
      crosshair.setAttribute("x2", xs[index]);
      crosshair.setAttribute("visibility", "visible");

      const { hovered } = this;
      const band = (s) => (s.band && s.band.low[index] != null
        ? `<span class="tip-band">(${this.yFormat(s.band.low[index])}–${this.yFormat(s.band.high[index])})</span>` : "");
      const rows = series
        .filter((s) => s.tooltip !== false || s === hovered)
        .filter((s) => s.values[index] != null)
        .map((s) => `<div class="tip-row${s === hovered ? " tip-hovered" : ""}"><i style="background:${s.color}"></i>` +
          `<span>${escape(s.name)}</span><b>${this.yFormat(s.values[index])}</b>${band(s)}</div>`);
      const extra = options.tooltipExtra ? options.tooltipExtra(index) : "";
      const hint = hovered && hovered.onClick ? `<div class="tip-hint">Click to open ${escape(hovered.name)}</div>`
        : options.onXClick ? `<div class="tip-hint">Click to show this recording</div>` : "";
      showTooltip(event, `<div class="tip-title">${+x[index].toFixed(1)} min</div>${rows.join("")}${extra}${hint}`);
    });
    svg.addEventListener("mouseleave", () => { crosshair.setAttribute("visibility", "hidden"); hideTooltip(); });
  }
}

/** A bare mini line in a hairline frame, 0..1 on y, for the zone cards: evenly
 *  spaced, or at the times `x` on the axis `xDomain` (by default theirs). */
class SparkLine {
  static draw(container, { values, color, step = true, height = 40, x = null, xDomain = null }) {
    const { el } = ChartKit;
    const width = 160;
    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none", class: "spark", "aria-hidden": "true" });
    const [lo, hi] = xDomain || (x ? [x[0], x[x.length - 1]] : [0, values.length - 1]);
    const at = (i) => ((x ? x[i] : i) - lo) / (hi - lo || 1);
    const xs = values.map((_, i) => 3 + at(i) * (width - 6));
    const ys = values.map((v) => (v == null ? null : 3 + (1 - v) * (height - 6)));
    const lastX = xs[xs.length - 1];
    if (xDomain && width - 3 - lastX > 1) el("rect", { x: lastX, y: 1, width: width - 3 - lastX, height: height - 2, class: "pending" }, svg);
    el("rect", { x: 0.5, y: 0.5, width: width - 1, height: height - 1, class: "spark-frame", "vector-effect": "non-scaling-stroke" }, svg);
    el("path", { d: ChartKit.linePath(xs, ys, step), fill: "none", stroke: color, "stroke-width": 1.75, "vector-effect": "non-scaling-stroke" }, svg);
    container.appendChild(svg);
  }
}
