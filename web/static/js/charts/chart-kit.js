// Small hand-written SVG charts, so the page needs no charting library and works
// offline. This file holds what every chart is drawn with: SVG elements, round
// axis ticks, line paths, point glyphs, the legend and the tooltip. The charts
// themselves are LineChart, ScatterChart, RidgelineChart and SparkLine, and
// Charts (charts.js) is what the pages call.
//
// A live run's charts are drawn again with every recording. Given `xDomain`, a
// time chart keeps that axis however far the data reaches, and shades the part
// not recorded yet; given `enterFrom`, the points from that index on are drawn
// in, so each redraw looks like the chart filling in.
//
// The static methods never use `this`, so they can be handed around as callbacks.

class ChartKit {
  static SVG = "http://www.w3.org/2000/svg";

  // Redraws of the charts on the page, run again when the window resizes.
  static live = new Set();

  static el(name, attrs = {}, parent = null) {
    const node = document.createElementNS(ChartKit.SVG, name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (parent) parent.appendChild(node);
    return node;
  }

  // Round tick values ("nice numbers") from min up to the first one at or above max.
  static niceTicks(min, max, count = 5) {
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
  static linePath(xs, ys, step) {
    let d = "";
    let pen = false;
    ys.forEach((y, i) => {
      if (y == null) { pen = false; return; }
      if (!pen) { d += `M${xs[i]},${y}`; pen = true; return; }
      d += step ? `H${xs[i]}V${y}` : `L${xs[i]},${y}`;
    });
    return d;
  }

  static showTooltip(event, html) {
    const tip = document.getElementById("tooltip");
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

  static hideTooltip() {
    document.getElementById("tooltip").hidden = true;
  }

  static escape(text) {
    return String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  }

  // Draw now, and again on every resize for as long as the container is on the
  // page. Only the first drawing draws the new points in; a resize just redraws.
  static keepLive(container, render, options) {
    let first = true;
    const redraw = () => {
      if (!container.isConnected) { ChartKit.live.delete(redraw); return; }
      render(container, first ? options : { ...options, animate: false });
      first = false;
    };
    ChartKit.live.add(redraw);
    redraw();
  }

  // A point glyph. Shapes carry the meaning together with colour, never colour alone.
  static glyph(parent, shape, cx, cy, r, color) {
    const { el } = ChartKit;
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

  // A glyph as a subpath, to share one path between many points (see glyph).
  static glyphPath(shape, cx, cy, r) {
    if (shape === "cross") return `M${cx - r},${cy - r}L${cx + r},${cy + r}M${cx - r},${cy + r}L${cx + r},${cy - r}`;
    if (shape === "square") return `M${cx - r},${cy - r}h${2 * r}v${2 * r}h${-2 * r}z`;
    return `M${cx - r},${cy}a${r},${r} 0 1,0 ${2 * r},0a${r},${r} 0 1,0 ${-2 * r},0z`;
  }

  static glyphPaint(shape, color) {
    if (shape === "cross") return { fill: "none", stroke: color, "stroke-width": 2, "stroke-linecap": "round", class: "glyph" };
    if (shape === "ring") return { fill: "none", stroke: color, "stroke-width": 1.75, class: "glyph" };
    return { fill: color, class: "marker" };
  }

  static glyphMarkup(shape, color) {
    const holder = ChartKit.el("g");
    ChartKit.glyph(holder, shape, 6, 6, 4, color);
    return holder.innerHTML;
  }

  // [{ name, color, shape, dashed }] as legend items; shape "line" for a line key.
  static legendHtml(items) {
    return items.map((item) => {
      const svg = item.dashed
        ? `<svg width="18" height="10" aria-hidden="true"><line x1="0" x2="18" y1="5" y2="5" stroke="${item.color}" stroke-width="2" stroke-dasharray="4 3"/></svg>`
        : item.shape === "line"
          ? `<svg width="18" height="10" aria-hidden="true"><line x1="0" x2="18" y1="5" y2="5" stroke="${item.color}" stroke-width="2"/></svg>`
          : `<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">${ChartKit.glyphMarkup(item.shape, item.color)}</svg>`;
      return `<span class="legend-item">${svg}${ChartKit.escape(item.name)}</span>`;
    }).join("");
  }

  // A legend above the chart in `container`, when there are items.
  static addLegend(container, items) {
    if (!items || !items.length) return;
    const legend = document.createElement("div");
    legend.className = "legend";
    legend.innerHTML = ChartKit.legendHtml(items);
    container.appendChild(legend);
  }

  // The value at fraction `q` of sorted values, between neighbours.
  static quantile(sorted, q) {
    const i = (sorted.length - 1) * q;
    const lo = Math.floor(i);
    return sorted[lo] + (sorted[Math.min(lo + 1, sorted.length - 1)] - sorted[lo]) * (i - lo);
  }

  // A small offset from a row, the same for a point's `key` at every drawing, so
  // equal values stay visible and a redraw does not shuffle the points.
  static jitter(key) {
    let hash = 7;
    for (const char of key) hash = (hash * 31 + char.charCodeAt(0)) % 1009;
    return (hash / 1009 - 0.5) * 0.5;
  }

  // The <svg> of a chart `width` × `height`, with its title when it has one.
  static svg(width, height, title) {
    const svg = ChartKit.el("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%", height, role: "img" });
    if (title) ChartKit.el("title", {}, svg).textContent = title;
    return svg;
  }
}

// Charts re-render themselves at their new width when the window resizes.
{
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      for (const redraw of ChartKit.live) redraw();
    }, 120);
  });
}
