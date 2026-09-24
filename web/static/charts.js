// Small hand-written SVG charts, so the page needs no charting library and works
// offline. Charts.line (time series with axes, legend, hover tooltip),
// Charts.scatter (x-y points, lines and boxes), Charts.ridgeline (one smoothed
// distribution per row, overlapping) and Charts.spark (a bare mini line for the
// zone cards).
//
// A live run's charts are drawn again with every recording. Given `xDomain`, a
// time chart keeps that axis however far the data reaches, and shades the part
// not recorded yet; given `enterFrom`, the points from that index on are drawn
// in, so each redraw looks like the chart filling in.

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
   *   selected    index of the x value to mark, e.g. the recording on screen
   *   onXClick    index -> called when the chart is clicked away from a clickable line
   *   xDomain     [min, max] of the x axis, e.g. a whole live run; the part past
   *               the last x value is shaded as still to come
   *   enterFrom   index of the first new x value, whose points are drawn in
   */
  function line(container, options) {
    container.chartRedraw = (target, adjust) => draw(target, adjust(options));
    keepLive(container, draw, options);
  }

  // Draw now, and again on every resize for as long as the container is on the
  // page. Only the first drawing draws the new points in; a resize just redraws.
  function keepLive(container, render, options) {
    let first = true;
    const redraw = () => {
      if (!container.isConnected) { live.delete(redraw); return; }
      render(container, first ? options : { ...options, animate: false });
      first = false;
    };
    live.add(redraw);
    redraw();
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

    const domain = options.xDomain;
    const xMin = domain ? Math.min(domain[0], x[0]) : x[0];
    const xMax = domain ? Math.max(domain[1], x[x.length - 1]) : x.length > 1 ? x[x.length - 1] : x[0] + 1;
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
    // Still to come: the part of a whole run's axis past the last recording.
    const lastX = sx(x[x.length - 1]);
    if (domain && pad.left + plotW - lastX > 1) {
      el("rect", { x: lastX, y: pad.top, width: pad.left + plotW - lastX, height: plotH, class: "pending" }, grid);
      if (pad.left + plotW - lastX > 70) {
        el("text", { x: pad.left + plotW - 6, y: pad.top + 14, "text-anchor": "end", class: "pending-label" }, grid).textContent = "still to come";
      }
    }
    const xTicks = x.length <= 10 && !domain ? x : niceTicks(xMin, xMax, 6).filter((t) => t <= xMax + 1e-9);
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
    if (options.selected != null && xs[options.selected] != null) {
      el("line", { x1: xs[options.selected], x2: xs[options.selected], y1: pad.top, y2: pad.top + plotH, class: "selected-x" }, svg);
    }
    const crosshair = el("line", { y1: pad.top, y2: pad.top + plotH, class: "crosshair", visibility: "hidden" }, svg);

    // Faint lines first so the emphasised ones sit on top.
    const ordered = [...series].sort((a, b) => (b.faint ? 1 : 0) - (a.faint ? 1 : 0));
    let hovered = null;
    const endLabels = [];
    // New points: the line on from the last old one is drawn in, their markers pop in.
    const enter = options.animate !== false && options.enterFrom > 0 && options.enterFrom < x.length ? options.enterFrom : null;

    for (const s of ordered) {
      const ys = s.values.map((v) => (v == null ? null : sy(v)));
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

    // The time point nearest the pointer, or -1 outside the plot.
    const nearest = (event) => {
      const box = svg.getBoundingClientRect();
      const px = ((event.clientX - box.left) / box.width) * width;
      if (px < pad.left - 10 || px > pad.left + plotW + 10) return -1;
      let index = 0;
      xs.forEach((value, i) => { if (Math.abs(value - px) < Math.abs(xs[index] - px)) index = i; });
      return index;
    };
    if (options.onXClick) {
      svg.style.cursor = "pointer";
      svg.addEventListener("click", (event) => {
        if (hovered && hovered.onClick) return;  // the line's own click wins
        const index = nearest(event);
        if (index >= 0) options.onXClick(index);
      });
    }

    // Crosshair + tooltip at the nearest time point.
    svg.addEventListener("mousemove", (event) => {
      const index = nearest(event);
      if (index < 0) { crosshair.setAttribute("visibility", "hidden"); hideTooltip(); return; }
      crosshair.setAttribute("x1", xs[index]);
      crosshair.setAttribute("x2", xs[index]);
      crosshair.setAttribute("visibility", "visible");

      const rows = series
        .filter((s) => s.tooltip !== false || s === hovered)
        .filter((s) => s.values[index] != null)
        .map((s) => `<div class="tip-row${s === hovered ? " tip-hovered" : ""}"><i style="background:${s.color}"></i>` +
          `<span>${escape(s.name)}</span><b>${yFormat(s.values[index])}</b></div>`);
      const extra = options.tooltipExtra ? options.tooltipExtra(index) : "";
      const hint = hovered && hovered.onClick ? `<div class="tip-hint">Click to open ${escape(hovered.name)}</div>`
        : options.onXClick ? `<div class="tip-hint">Click to show this recording</div>` : "";
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
   *                  r, tip (tooltip html), label, labelDy, onClick, hidden (hover target only),
   *                  enter (new: pops in) }]
   *   lines       [{ points: [[x, y], ...], color, width, dashed }]
   *   refX, refY  [{ value, label }] vertical / horizontal dashed reference lines
   *   xLabel, yLabel, xMin, xMax, yMin, yMax, height
   *   square      height follows the width (up to `height`), for ROC curves
   *   xFormat, yFormat   value -> tick text
   *   yCategories [{ value, label }] named rows instead of numeric y ticks
   *   boxes       [{ y, lo, q1, median, q3, hi, color, halfHeight, tip }] box and
   *               whiskers along x, centred on row y, drawn behind the points
   *   notes       [{ y, text }] a word on a row with nothing drawn in it
   *   padLeft     room for the y tick labels
   *   legend      [{ name, color, shape }] (shape "line" for a line key)
   */
  function scatter(container, options) {
    container.chartRedraw = (target, adjust) => drawScatter(target, adjust(options));
    keepLive(container, drawScatter, options);
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
    const boxes = options.boxes || [];
    const pad = { left: options.padLeft ?? (options.yCategories ? 70 : 56), right: 16, top: 14, bottom: 42 };
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
      [...points.map((p) => p.x), ...lines.flatMap((l) => l.points.map((p) => p[0])), ...refX.map((r) => r.value),
        ...boxes.flatMap((b) => [b.lo, b.hi])],
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

    // Box: the middle half of the values, a line at the median; whiskers to lo and hi.
    const ppu = plotH / (yMax - yMin);  // pixels per unit of y
    for (const b of boxes) {
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
    for (const note of options.notes || []) {
      el("text", { x: pad.left + 8, y: sy(note.y) + 4, class: "row-note" }, svg).textContent = note.text;
    }

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
      const g = el("g", { class: `point${p.enter && options.animate !== false ? " enter-mark" : ""}` }, svg);
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

  /** A bare mini line in a hairline frame, 0..1 on y, for the zone cards: evenly
   *  spaced, or at the times `x` on the axis `xDomain` (by default theirs). */
  function spark(container, { values, color, step = true, height = 40, x = null, xDomain = null }) {
    const width = 160;
    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none", class: "spark", "aria-hidden": "true" });
    const [lo, hi] = xDomain || (x ? [x[0], x[x.length - 1]] : [0, values.length - 1]);
    const at = (i) => ((x ? x[i] : i) - lo) / (hi - lo || 1);
    const xs = values.map((_, i) => 3 + at(i) * (width - 6));
    const ys = values.map((v) => (v == null ? null : 3 + (1 - v) * (height - 6)));
    const lastX = xs[xs.length - 1];
    if (xDomain && width - 3 - lastX > 1) el("rect", { x: lastX, y: 1, width: width - 3 - lastX, height: height - 2, class: "pending" }, svg);
    el("rect", { x: 0.5, y: 0.5, width: width - 1, height: height - 1, class: "spark-frame", "vector-effect": "non-scaling-stroke" }, svg);
    el("path", { d: linePath(xs, ys, step), fill: "none", stroke: color, "stroke-width": 1.75, "vector-effect": "non-scaling-stroke" }, svg);
    container.appendChild(svg);
  }

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
  function ridgeline(container, options) {
    container.chartRedraw = (target, adjust) => drawRidgeline(target, adjust(options));
    keepLive(container, drawRidgeline, options);
  }

  function quantile(sorted, q) {
    const i = (sorted.length - 1) * q;
    const lo = Math.floor(i);
    return sorted[lo] + (sorted[Math.min(lo + 1, sorted.length - 1)] - sorted[lo]) * (i - lo);
  }

  // Silverman's rule of thumb, no less than `floor`.
  function kernelBandwidth(values, floor) {
    const n = values.length;
    if (!n) return floor;
    const sorted = [...values].sort((a, b) => a - b);
    const mean = values.reduce((a, b) => a + b, 0) / n;
    const sd = Math.sqrt(values.reduce((sum, v) => sum + (v - mean) ** 2, 0) / Math.max(1, n - 1));
    const iqr = quantile(sorted, 0.75) - quantile(sorted, 0.25);
    const spread = Math.min(sd, iqr / 1.34) || sd;
    return Math.max(0.9 * spread * n ** -0.2, floor);
  }

  function drawRidgeline(container, options) {
    const { rows, xLabel = "", xFormat = (v) => `${+v.toFixed(2)}`, rowHeight = 30, overlap = 1.6 } = options;

    container.innerHTML = "";
    container.classList.add("chart");
    if (options.legend && options.legend.length) {
      const legend = document.createElement("div");
      legend.className = "legend";
      legend.innerHTML = legendHtml(options.legend);
      container.appendChild(legend);
    }

    const width = Math.max(260, container.clientWidth || 640);
    const peak = rowHeight * overlap;
    const pad = { left: options.padLeft ?? 130, right: 16, top: Math.max(14, peak - rowHeight + 8), bottom: 42 };
    const plotW = width - pad.left - pad.right;
    const bottom = pad.top + rows.length * rowHeight;
    const height = bottom + pad.bottom;
    const xMin = options.xMin ?? 0;
    const xMax = options.xMax > xMin ? options.xMax : xMin + 1;
    const sx = (v) => pad.left + ((v - xMin) / (xMax - xMin)) * plotW;

    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%", height, role: "img" });
    if (options.title) el("title", {}, svg).textContent = options.title;

    const grid = el("g", { class: "grid" }, svg);
    const axes = el("g", {}, svg);
    for (const t of niceTicks(xMin, xMax, 6).filter((t) => t >= xMin - 1e-9 && t <= xMax + 1e-9)) {
      el("line", { x1: sx(t), x2: sx(t), y1: pad.top - peak + rowHeight, y2: bottom }, grid);
      el("line", { x1: sx(t), x2: sx(t), y1: bottom, y2: bottom + 4, class: "tick-mark" }, axes);
      el("text", { x: sx(t), y: bottom + 17, "text-anchor": "middle", class: "tick" }, axes).textContent = xFormat(t);
    }
    el("line", { x1: pad.left, x2: pad.left + plotW, y1: bottom, y2: bottom, class: "axis" }, axes);
    el("text", { x: pad.left + plotW / 2, y: height - 6, "text-anchor": "middle", class: "axis-label" }, svg).textContent = xLabel;

    // One bandwidth for every row, so each is smoothed alike.
    const h = options.bandwidth ?? kernelBandwidth(rows.flatMap((row) => row.values), Math.max(options.minBandwidth ?? 0, (xMax - xMin) / 200));
    const samples = 160;
    const at = Array.from({ length: samples + 1 }, (_, k) => xMin + (k / samples) * (xMax - xMin));
    const kernel = (t, v) => Math.exp(-0.5 * ((t - v) / h) ** 2);

    // The top row first, so each lower ridge is drawn in front of the one above it.
    rows.forEach((row, i) => {
      const base = pad.top + (i + 1) * rowHeight;
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
    });

    container.appendChild(svg);
  }

  // --- export ----------------------------------------------------------------------
  //
  // A chart as a standalone SVG file: its styles written onto each element (the
  // page's stylesheet does not travel with the file), a white background, and the
  // title and legend, which live in the page's HTML, drawn in above the chart.

  const STYLE_PROPS = [
    "fill", "fill-opacity", "stroke", "stroke-width", "stroke-dasharray", "stroke-opacity",
    "stroke-linecap", "stroke-linejoin", "opacity", "visibility", "paint-order",
    "font-family", "font-size", "font-weight", "font-style",
  ];

  // Copy the computed style of each element of `from` onto its twin in `to`.
  function inlineStyles(from, to) {
    const style = getComputedStyle(from);
    to.setAttribute("style", STYLE_PROPS.map((prop) => `${prop}:${style.getPropertyValue(prop)}`).join(";"));
    [...from.children].forEach((child, i) => inlineStyles(child, to.children[i]));
  }

  const measure = (() => {
    const context = document.createElement("canvas").getContext("2d");
    return (text, font) => { context.font = font; return context.measureText(text).width; };
  })();

  // The chart drawn again, at the same width, for a file: nothing marks the
  // recording on screen, and `container.exportAdjust(options)`, when the page set
  // one, takes out whatever else only makes sense on the page. Null when the
  // chart cannot be redrawn; the chart on the page is then used as it is.
  function exportCopy(container) {
    if (!container.chartRedraw) return null;
    const copy = document.createElement("div");
    copy.style.cssText = `position:absolute;left:-10000px;top:0;width:${container.clientWidth}px`;
    document.body.appendChild(copy);
    const adjust = container.exportAdjust || ((options) => options);
    container.chartRedraw(copy, (options) => adjust({ ...options, selected: null, animate: false }));
    return copy;
  }

  // `legend`: an element holding the legend when it is not in the container,
  // e.g. one legend shared by small multiples.
  function exportSvg(container, title = "", legend = null) {
    const copy = exportCopy(container);
    try {
      return exportDrawn(copy || container, title, legend);
    } finally {
      copy?.remove();
    }
  }

  function exportDrawn(container, title, legendHolder) {
    const chart = container.querySelector(":scope > svg");
    if (!chart) return null;
    const [, , width, height] = chart.getAttribute("viewBox").split(" ").map(Number);
    const font = getComputedStyle(container).fontFamily;

    const svg = el("svg", { width });
    const body = el("g", {}, svg);
    let top = 12;
    if (title) {
      el("text", { x: 8, y: top + 14, "font-family": font, "font-size": 15, "font-weight": 600, fill: "#1f2328" }, body).textContent = title;
      top += 26;
    }

    // The legend, item by item: its glyph (a small SVG or a coloured bar) and its name.
    const items = [...(legendHolder || container.querySelector(":scope > .legend") || document.createElement("div"))
      .querySelectorAll(".legend-item")];
    if (items.length) {
      let x = 8;
      top += 4;
      for (const item of items) {
        const name = item.textContent.trim();
        const key = item.querySelector("svg");
        // An item that does not fit on this line starts the next one.
        const itemWidth = (key ? Number(key.getAttribute("width")) + 6 : 22) + measure(name, `12px ${font}`);
        if (x > 8 && x + itemWidth > width - 8) {
          x = 8;
          top += 20;
        }
        if (key) {
          const copy = key.cloneNode(true);
          inlineStyles(key, copy);
          const w = Number(key.getAttribute("width"));
          const h = Number(key.getAttribute("height"));
          copy.setAttribute("x", x);
          copy.setAttribute("y", top + 7 - h / 2);
          body.appendChild(copy);
          x += w + 6;
        } else {
          const bar = getComputedStyle(item.querySelector("i"));
          const dashed = bar.borderTopStyle === "dashed";
          el("line", {
            x1: x, x2: x + 16, y1: top + 7, y2: top + 7, "stroke-width": 2,
            stroke: dashed ? bar.borderTopColor : bar.backgroundColor, ...(dashed ? { "stroke-dasharray": "4 3" } : {}),
          }, body);
          x += 22;
        }
        el("text", { x, y: top + 11, "font-family": font, "font-size": 12, fill: "#3d434b" }, body).textContent = name;
        x += measure(name, `12px ${font}`) + 16;
      }
      top += 20;
    }

    const copy = chart.cloneNode(true);
    inlineStyles(chart, copy);
    // Only the page has a pointer and a recording on screen.
    copy.querySelectorAll(".hit, .crosshair, .selected-x").forEach((node) => node.remove());
    Object.entries({ x: 0, y: top, width, height }).forEach(([k, v]) => copy.setAttribute(k, v));
    copy.removeAttribute("style");
    body.appendChild(copy);

    const total = top + height + 8;
    svg.setAttribute("height", total);
    svg.setAttribute("viewBox", `0 0 ${width} ${total}`);
    svg.insertBefore(el("rect", { width, height: total, fill: "#fff" }), body);
    return { markup: new XMLSerializer().serializeToString(svg), width, height: total };
  }

  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // Save the chart in `container` as `filename`.svg or, at `scale` times its size, .png.
  async function download(container, { title = "", filename = "chart", format = "svg", scale = 3, legend = null } = {}) {
    const exported = exportSvg(container, title, legend);
    if (!exported) return;
    const svgBlob = new Blob([exported.markup], { type: "image/svg+xml" });
    if (format === "svg") { saveBlob(svgBlob, `${filename}.svg`); return; }

    const image = new Image();
    const url = URL.createObjectURL(svgBlob);
    await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject; image.src = url; });
    const canvas = document.createElement("canvas");
    canvas.width = exported.width * scale;
    canvas.height = exported.height * scale;
    const context = canvas.getContext("2d");
    context.scale(scale, scale);
    context.drawImage(image, 0, 0, exported.width, exported.height);
    URL.revokeObjectURL(url);
    canvas.toBlob((blob) => saveBlob(blob, `${filename}.png`), "image/png");
  }

  return { line, scatter, ridgeline, spark, legendHtml, showTooltip, hideTooltip, escape, exportSvg, download, quantile };
})();
