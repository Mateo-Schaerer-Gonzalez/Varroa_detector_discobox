// Small hand-written SVG charts, so the page needs no charting library and works
// offline. Charts.line (time series with axes, legend, hover tooltip),
// Charts.scatter (x-y points and lines, for the calibration report) and
// Charts.spark (a bare mini line for the zone cards).

const Charts = (() => {
  const SVG = "http://www.w3.org/2000/svg";
  const tooltip = () => document.getElementById("tooltip");

  function el(name, attrs = {}, parent = null) {
    const node = document.createElementNS(SVG, name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (parent) parent.appendChild(node);
    return node;
  }

  // Round tick values ("nice numbers") from min up to the first one at or above max.
  function niceTicks(min, max, count = 5) {
    if (min === max) max = min + 1;
    const raw = (max - min) / count;
    const magnitude = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((f) => f * magnitude).find((s) => s >= raw);
    const ticks = [];
    for (let v = Math.ceil(min / step - 1e-9) * step; v < max + step * (1 - 1e-9); v += step) ticks.push(+v.toFixed(10));
    return ticks;
  }

  // Path through the points, skipping gaps (null values). `step` draws a
  // staircase that holds each value until the next time point.
  function linePath(xs, ys, step) {
    let d = "";
    let pen = false;
    ys.forEach((y, i) => {
      if (y == null) { pen = false; return; }
      if (!pen) { d += `M${xs[i]},${y}`; pen = true; return; }
      d += step ? `H${xs[i]}V${y}` : `L${xs[i]},${y}`;
    });
    return d;
  }

  function showTooltip(event, html) {
    const tip = tooltip();
    tip.innerHTML = html;
    tip.hidden = false;
    const { innerWidth, innerHeight } = window;
    const box = tip.getBoundingClientRect();
    let left = event.clientX + 14;
    let top = event.clientY + 14;
    if (left + box.width > innerWidth - 8) left = event.clientX - box.width - 14;
    if (top + box.height > innerHeight - 8) top = event.clientY - box.height - 14;
    tip.style.left = `${Math.max(8, left)}px`;
    tip.style.top = `${Math.max(8, top)}px`;
  }

  const hideTooltip = () => { tooltip().hidden = true; };

  const escape = (text) => String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  // Charts re-render themselves at their new width when the window resizes.
  const live = new Set();
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      for (const redraw of live) redraw();
    }, 120);
  });

  /**
   * options:
   *   x           shared x values (time in minutes)
   *   series      [{ name, values, color, width, step, faint, markers, pointColors,
   *                  legend, tooltip, onClick }]
   *   yLabel, xLabel, yMin, yMax, height
   *   yFormat     value -> text, for axis ticks and the tooltip
   *   threshold   { value, label } drawn as a dashed reference line
   */
  function line(container, options) {
    keepLive(container, () => draw(container, options));
  }

  // Draw now, and again on every resize for as long as the container is on the page.
  function keepLive(container, render) {
    const redraw = () => {
      if (!container.isConnected) { live.delete(redraw); return; }
      render();
    };
    live.add(redraw);
    render();
  }

  function draw(container, options) {
    const {
      x, series, yLabel = "", xLabel = "Time (min)", height = 280,
      yFormat = (v) => `${+v.toFixed(2)}`, threshold = null,
    } = options;

    container.innerHTML = "";
    container.classList.add("chart");

    const legendSeries = series.filter((s) => s.legend !== false);
    if (legendSeries.length >= 2 || options.forceLegend) {
      const legend = document.createElement("div");
      legend.className = "legend";
      legend.innerHTML = legendSeries
        .map((s) => `<span class="legend-item"><i style="background:${s.color}${s.dashed ? ";height:0;border-top:2px dashed " + s.color : ""}"></i>${escape(s.name)}</span>`)
        .join("");
      container.appendChild(legend);
    }

    const width = Math.max(280, container.clientWidth || 640);
    // Room on the right for direct labels when there are few enough to fit.
    const directLabels = legendSeries.length >= 1 && legendSeries.length <= 4 && width > 480 && !options.noDirectLabels;
    const pad = { left: 56, right: directLabels ? 96 : 16, top: 14, bottom: 42 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;

    const allValues = series.flatMap((s) => s.values.filter((v) => v != null));
    if (threshold) allValues.push(threshold.value);
    let yMin = options.yMin ?? Math.min(0, ...allValues);
    let yMax = options.yMax ?? Math.max(...allValues, yMin + 1);
    const yTicks = niceTicks(yMin, yMax);
    if (options.yMax == null) yMax = Math.max(yMax, yTicks[yTicks.length - 1]);

    const xMin = x[0];
    const xMax = x.length > 1 ? x[x.length - 1] : x[0] + 1;
    const sx = (v) => pad.left + ((v - xMin) / (xMax - xMin || 1)) * plotW;
    const sy = (v) => pad.top + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;

    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%", height, role: "img" });
    if (options.title) el("title", {}, svg).textContent = options.title;

    // Left and bottom axes with outward tick marks, as in a printed figure;
    // the grid behind the data stays very faint.
    const grid = el("g", { class: "grid" }, svg);
    const axes = el("g", {}, svg);
    const bottom = pad.top + plotH;
    for (const t of yTicks) {
      if (t < yMin - 1e-9 || t > yMax + 1e-9) continue;
      el("line", { x1: pad.left, x2: pad.left + plotW, y1: sy(t), y2: sy(t) }, grid);
      el("line", { x1: pad.left - 4, x2: pad.left, y1: sy(t), y2: sy(t), class: "tick-mark" }, axes);
      el("text", { x: pad.left - 7, y: sy(t) + 4, "text-anchor": "end", class: "tick" }, axes).textContent = yFormat(t);
    }
    const xTicks = x.length <= 10 ? x : niceTicks(xMin, xMax, 6);
    for (const t of xTicks) {
      el("line", { x1: sx(t), x2: sx(t), y1: bottom, y2: bottom + 4, class: "tick-mark" }, axes);
      el("text", { x: sx(t), y: bottom + 17, "text-anchor": "middle", class: "tick" }, axes).textContent = `${+t.toFixed(1)}`;
    }
    el("line", { x1: pad.left, x2: pad.left + plotW, y1: bottom, y2: bottom, class: "axis" }, axes);
    el("line", { x1: pad.left, x2: pad.left, y1: pad.top, y2: bottom, class: "axis" }, axes);
    el("text", { x: pad.left + plotW / 2, y: height - 6, "text-anchor": "middle", class: "axis-label" }, svg).textContent = xLabel;
    el("text", { x: 14, y: pad.top + plotH / 2, "text-anchor": "middle", class: "axis-label", transform: `rotate(-90 14 ${pad.top + plotH / 2})` }, svg).textContent = yLabel;

    if (threshold) {
      const y = sy(threshold.value);
      el("line", { x1: pad.left, x2: pad.left + plotW, y1: y, y2: y, class: "threshold" }, svg);
      el("text", { x: pad.left + plotW - 4, y: y - 6, "text-anchor": "end", class: "threshold-label" }, svg).textContent = threshold.label;
    }

    const xs = x.map(sx);
    const crosshair = el("line", { y1: pad.top, y2: pad.top + plotH, class: "crosshair", visibility: "hidden" }, svg);

    // Faint lines first so the emphasised ones sit on top.
    const ordered = [...series].sort((a, b) => (b.faint ? 1 : 0) - (a.faint ? 1 : 0));
    let hovered = null;
    const endLabels = [];

    for (const s of ordered) {
      const ys = s.values.map((v) => (v == null ? null : sy(v)));
      const d = linePath(xs, ys, s.step);
      const g = el("g", { class: `series${s.faint ? " faint" : ""}` }, svg);
      el("path", {
        d, fill: "none", stroke: s.color, "stroke-width": s.width ?? 1.75,
        "stroke-linejoin": "round", "stroke-linecap": "round",
        ...(s.dashed ? { "stroke-dasharray": "6 5" } : {}),
      }, g);

      if (s.markers !== false && !s.faint) {
        ys.forEach((y, i) => {
          if (y == null) return;
          el("circle", { cx: xs[i], cy: y, r: 3.5, fill: s.pointColors ? s.pointColors[i] : s.color, class: "marker" }, g);
        });
      }

      if (directLabels && s.legend !== false) {
        const last = ys.map((y, i) => [y, i]).filter(([y]) => y != null).pop();
        if (last) endLabels.push({ name: s.name, x: xs[last[1]] + 8, y: last[0] + 4 });
      }

      // A wide invisible stroke makes thin lines easy to hover and click.
      if (s.onClick || s.faint) {
        const hit = el("path", { d, fill: "none", stroke: "transparent", "stroke-width": 12, class: "hit" }, g);
        hit.addEventListener("mouseenter", () => { hovered = s; g.classList.add("hover"); });
        hit.addEventListener("mouseleave", () => { hovered = null; g.classList.remove("hover"); });
        if (s.onClick) {
          hit.style.cursor = "pointer";
          hit.addEventListener("click", () => s.onClick());
        }
      }
    }

    // Lines ending at the same value would print their names on top of each
    // other; working up from the x axis, lift each label clear of the one below.
    endLabels.sort((a, b) => b.y - a.y);
    endLabels.forEach((label, i) => {
      if (i > 0) label.y = Math.min(label.y, endLabels[i - 1].y - 14);
      el("text", { x: label.x, y: label.y, class: "direct-label" }, svg).textContent = label.name;
    });

    // Crosshair + tooltip at the nearest time point.
    svg.addEventListener("mousemove", (event) => {
      const box = svg.getBoundingClientRect();
      const px = ((event.clientX - box.left) / box.width) * width;
      if (px < pad.left - 10 || px > pad.left + plotW + 10) { crosshair.setAttribute("visibility", "hidden"); hideTooltip(); return; }
      let index = 0;
      xs.forEach((value, i) => { if (Math.abs(value - px) < Math.abs(xs[index] - px)) index = i; });
      crosshair.setAttribute("x1", xs[index]);
      crosshair.setAttribute("x2", xs[index]);
      crosshair.setAttribute("visibility", "visible");

      const rows = series
        .filter((s) => s.tooltip !== false || s === hovered)
        .filter((s) => s.values[index] != null)
        .map((s) => `<div class="tip-row${s === hovered ? " tip-hovered" : ""}"><i style="background:${s.color}"></i>` +
          `<span>${escape(s.name)}</span><b>${yFormat(s.values[index])}</b></div>`);
      const extra = options.tooltipExtra ? options.tooltipExtra(index) : "";
      const hint = hovered && hovered.onClick ? `<div class="tip-hint">Click to open ${escape(hovered.name)}</div>` : "";
      showTooltip(event, `<div class="tip-title">${+x[index].toFixed(1)} min</div>${rows.join("")}${extra}${hint}`);
    });
    svg.addEventListener("mouseleave", () => { crosshair.setAttribute("visibility", "hidden"); hideTooltip(); });

    container.appendChild(svg);
  }

  // A point glyph. Shapes carry the meaning together with colour, never colour alone.
  function glyph(parent, shape, cx, cy, r, color) {
    if (shape === "cross") {
      const g = el("g", { stroke: color, "stroke-width": 2, "stroke-linecap": "round", class: "glyph" }, parent);
      el("line", { x1: cx - r, y1: cy - r, x2: cx + r, y2: cy + r }, g);
      el("line", { x1: cx - r, y1: cy + r, x2: cx + r, y2: cy - r }, g);
      return g;
    }
    if (shape === "square") {
      return el("rect", { x: cx - r, y: cy - r, width: 2 * r, height: 2 * r, fill: color, class: "marker" }, parent);
    }
    if (shape === "ring") {
      return el("circle", { cx, cy, r, fill: "none", stroke: color, "stroke-width": 1.75, class: "glyph" }, parent);
    }
    return el("circle", { cx, cy, r, fill: color, class: "marker" }, parent);
  }

  function legendHtml(items) {
    return items.map((item) => {
      const svg = item.dashed
        ? `<svg width="18" height="10" aria-hidden="true"><line x1="0" x2="18" y1="5" y2="5" stroke="${item.color}" stroke-width="2" stroke-dasharray="4 3"/></svg>`
        : item.shape === "line"
          ? `<svg width="18" height="10" aria-hidden="true"><line x1="0" x2="18" y1="5" y2="5" stroke="${item.color}" stroke-width="2"/></svg>`
          : `<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">${glyphMarkup(item.shape, item.color)}</svg>`;
      return `<span class="legend-item">${svg}${escape(item.name)}</span>`;
    }).join("");
  }

  function glyphMarkup(shape, color) {
    const holder = el("g");
    glyph(holder, shape, 6, 6, 4, color);
    return holder.innerHTML;
  }

  /**
   * An x-y chart with numeric axes: points, lines and dashed reference lines.
   *
   * options:
   *   points      [{ x, y, color, shape ("circle" | "cross" | "square" | "ring"),
   *                  r, tip (tooltip html), label, labelDy, onClick, hidden (hover target only) }]
   *   lines       [{ points: [[x, y], ...], color, width, dashed }]
   *   refX, refY  [{ value, label }] vertical / horizontal dashed reference lines
   *   xLabel, yLabel, xMin, xMax, yMin, yMax, height
   *   square      height follows the width (up to `height`), for ROC curves
   *   xFormat, yFormat   value -> tick text
   *   yCategories [{ value, label }] named rows instead of numeric y ticks
   *   legend      [{ name, color, shape }] (shape "line" for a line key)
   */
  function scatter(container, options) {
    keepLive(container, () => drawScatter(container, options));
  }

  function drawScatter(container, options) {
    const {
      points = [], lines = [], refX = [], refY = [], xLabel = "", yLabel = "",
      xFormat = (v) => `${+v.toFixed(2)}`, yFormat = (v) => `${+v.toFixed(2)}`,
    } = options;

    container.innerHTML = "";
    container.classList.add("chart");
    if (options.legend && options.legend.length) {
      const legend = document.createElement("div");
      legend.className = "legend";
      legend.innerHTML = legendHtml(options.legend);
      container.appendChild(legend);
    }

    const width = Math.max(260, container.clientWidth || 640);
    const pad = { left: options.yCategories ? 70 : 56, right: 16, top: 14, bottom: 42 };
    const height = options.square
      ? Math.min(options.height ?? 380, width - pad.left - pad.right + pad.top + pad.bottom)
      : options.height ?? 280;
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;

    // A free end of an axis gets a little room so no point sits on the frame.
    const extent = (values, fixedMin, fixedMax) => {
      let lo = Math.min(...values);
      let hi = Math.max(...values);
      if (!(hi > lo)) { lo -= 1; hi += 1; }
      const margin = (hi - lo) * 0.05;
      return [fixedMin ?? lo - margin, fixedMax ?? hi + margin];
    };
    const [xMin, xMax] = extent(
      [...points.map((p) => p.x), ...lines.flatMap((l) => l.points.map((p) => p[0])), ...refX.map((r) => r.value)],
      options.xMin, options.xMax);
    const [yMin, yMax] = extent(
      [...points.map((p) => p.y), ...lines.flatMap((l) => l.points.map((p) => p[1])), ...refY.map((r) => r.value)],
      options.yMin, options.yMax);
    const sx = (v) => pad.left + ((v - xMin) / (xMax - xMin)) * plotW;
    const sy = (v) => pad.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
    const inside = (t, lo, hi) => t >= lo - 1e-9 && t <= hi + 1e-9;

    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%", height, role: "img" });
    if (options.title) el("title", {}, svg).textContent = options.title;

    const grid = el("g", { class: "grid" }, svg);
    const axes = el("g", {}, svg);
    const bottom = pad.top + plotH;
    const yTicks = options.yCategories || niceTicks(yMin, yMax).filter((t) => inside(t, yMin, yMax)).map((value) => ({ value, label: yFormat(value) }));
    for (const { value, label } of yTicks) {
      el("line", { x1: pad.left, x2: pad.left + plotW, y1: sy(value), y2: sy(value) }, grid);
      el("line", { x1: pad.left - 4, x2: pad.left, y1: sy(value), y2: sy(value), class: "tick-mark" }, axes);
      el("text", { x: pad.left - 7, y: sy(value) + 4, "text-anchor": "end", class: "tick" }, axes).textContent = label;
    }
    for (const t of niceTicks(xMin, xMax, 6).filter((t) => inside(t, xMin, xMax))) {
      el("line", { x1: sx(t), x2: sx(t), y1: pad.top, y2: bottom }, grid);
      el("line", { x1: sx(t), x2: sx(t), y1: bottom, y2: bottom + 4, class: "tick-mark" }, axes);
      el("text", { x: sx(t), y: bottom + 17, "text-anchor": "middle", class: "tick" }, axes).textContent = xFormat(t);
    }
    el("line", { x1: pad.left, x2: pad.left + plotW, y1: bottom, y2: bottom, class: "axis" }, axes);
    el("line", { x1: pad.left, x2: pad.left, y1: pad.top, y2: bottom, class: "axis" }, axes);
    el("text", { x: pad.left + plotW / 2, y: height - 6, "text-anchor": "middle", class: "axis-label" }, svg).textContent = xLabel;
    el("text", { x: 14, y: pad.top + plotH / 2, "text-anchor": "middle", class: "axis-label", transform: `rotate(-90 14 ${pad.top + plotH / 2})` }, svg).textContent = yLabel;

    // Reference lines; labels of vertical ones stack down so they never overlap.
    refY.forEach(({ value, label }) => {
      el("line", { x1: pad.left, x2: pad.left + plotW, y1: sy(value), y2: sy(value), class: "threshold" }, svg);
      if (label) el("text", { x: pad.left + plotW - 4, y: sy(value) - 6, "text-anchor": "end", class: "threshold-label" }, svg).textContent = label;
    });
    [...refX].sort((a, b) => a.value - b.value).forEach(({ value, label }, i) => {
      el("line", { x1: sx(value), x2: sx(value), y1: pad.top, y2: bottom, class: "threshold" }, svg);
      if (!label) return;
      const right = sx(value) < pad.left + plotW * 0.7;
      el("text", {
        x: sx(value) + (right ? 5 : -5), y: pad.top + 11 + i * 14,
        "text-anchor": right ? "start" : "end", class: "threshold-label",
      }, svg).textContent = label;
    });

    for (const l of lines) {
      const d = l.points.map(([x, y], i) => `${i ? "L" : "M"}${sx(x)},${sy(y)}`).join("");
      el("path", {
        d, fill: "none", stroke: l.color, "stroke-width": l.width ?? 2,
        "stroke-linejoin": "round", "stroke-linecap": "round",
        ...(l.dashed ? { "stroke-dasharray": "5 4" } : {}),
      }, svg);
    }

    for (const p of points) {
      const cx = sx(p.x);
      const cy = sy(p.y);
      const r = p.r ?? 4;
      const g = el("g", { class: "point" }, svg);
      if (!p.hidden) glyph(g, p.shape, cx, cy, r, p.color);
      if (p.label) {
        el("text", { x: cx + r + 5, y: cy + 4 + (p.labelDy || 0), class: "point-label" }, g).textContent = p.label;
      }
      if (p.tip || p.onClick) {
        // The hit area is larger than the mark, so small points are easy to hover.
        const hit = el("circle", { cx, cy, r: r + 5, fill: "transparent", class: "hit" }, g);
        hit.addEventListener("mousemove", (event) => { g.classList.add("hover"); if (p.tip) showTooltip(event, p.tip); });
        hit.addEventListener("mouseleave", () => { g.classList.remove("hover"); hideTooltip(); });
        if (p.onClick) {
          hit.style.cursor = "pointer";
          hit.addEventListener("click", p.onClick);
        }
      }
    }

    container.appendChild(svg);
  }

  /** A bare mini line in a hairline frame, 0..1 on y, for the zone cards. */
  function spark(container, { values, color, step = true, height = 40 }) {
    const width = 160;
    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none", class: "spark", "aria-hidden": "true" });
    const xs = values.map((_, i) => 3 + (i / Math.max(1, values.length - 1)) * (width - 6));
    const ys = values.map((v) => (v == null ? null : 3 + (1 - v) * (height - 6)));
    el("rect", { x: 0.5, y: 0.5, width: width - 1, height: height - 1, class: "spark-frame", "vector-effect": "non-scaling-stroke" }, svg);
    el("path", { d: linePath(xs, ys, step), fill: "none", stroke: color, "stroke-width": 1.75, "vector-effect": "non-scaling-stroke" }, svg);
    container.appendChild(svg);
  }

  return { line, scatter, spark, legendHtml, showTooltip, hideTooltip, escape };
})();
