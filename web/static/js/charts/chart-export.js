// A chart as a standalone SVG or PNG file: its styles written onto each element
// (the page's stylesheet does not travel with the file), a white background, and
// the title and legend, which live in the page's HTML, drawn in above the chart.

class ChartExport {
  static STYLE_PROPS = [
    "fill", "fill-opacity", "stroke", "stroke-width", "stroke-dasharray", "stroke-opacity",
    "stroke-linecap", "stroke-linejoin", "opacity", "visibility", "paint-order",
    "font-family", "font-size", "font-weight", "font-style",
  ];

  static #canvas = null;

  // Save the chart in `container` as `filename`.svg or, at `scale` times its size, .png.
  static async download(container, { title = "", filename = "chart", format = "svg", scale = 3, legend = null } = {}) {
    const exported = ChartExport.svg(container, title, legend);
    if (!exported) return;
    const svgBlob = new Blob([exported.markup], { type: "image/svg+xml" });
    if (format === "svg") { ChartExport.saveBlob(svgBlob, `${filename}.svg`); return; }

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
    canvas.toBlob((blob) => ChartExport.saveBlob(blob, `${filename}.png`), "image/png");
  }

  // `legend`: an element holding the legend when it is not in the container,
  // e.g. one legend shared by small multiples.
  static svg(container, title = "", legend = null) {
    const copy = ChartExport.redrawnCopy(container);
    try {
      return new ChartExport(copy || container, title, legend).build();
    } finally {
      copy?.remove();
    }
  }

  // The chart drawn again, at the same width, for a file: nothing marks the
  // recording on screen, and `container.exportAdjust(options)`, when the page set
  // one, takes out whatever else only makes sense on the page. Null when the
  // chart cannot be redrawn; the chart on the page is then used as it is.
  static redrawnCopy(container) {
    if (!container.chartRedraw) return null;
    const copy = document.createElement("div");
    copy.style.cssText = `position:absolute;left:-10000px;top:0;width:${container.clientWidth}px`;
    document.body.appendChild(copy);
    const adjust = container.exportAdjust || ((options) => options);
    container.chartRedraw(copy, (options) => adjust({ ...options, selected: null, animate: false }));
    return copy;
  }

  // Copy the computed style of each element of `from` onto its twin in `to`.
  static inlineStyles(from, to) {
    const style = getComputedStyle(from);
    to.setAttribute("style", ChartExport.STYLE_PROPS.map((prop) => `${prop}:${style.getPropertyValue(prop)}`).join(";"));
    [...from.children].forEach((child, i) => ChartExport.inlineStyles(child, to.children[i]));
  }

  static measure(text, font) {
    ChartExport.#canvas ??= document.createElement("canvas").getContext("2d");
    ChartExport.#canvas.font = font;
    return ChartExport.#canvas.measureText(text).width;
  }

  static saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  constructor(container, title, legendHolder) {
    this.container = container;
    this.title = title;
    this.legendHolder = legendHolder;
  }

  // { markup, width, height } of the file, or null when there is no chart.
  build() {
    const { el } = ChartKit;
    const chart = this.container.querySelector(":scope > svg");
    if (!chart) return null;
    const [, , width, height] = chart.getAttribute("viewBox").split(" ").map(Number);
    this.width = width;
    this.font = getComputedStyle(this.container).fontFamily;

    const svg = el("svg", { width });
    const body = el("g", {}, svg);
    let top = 12;
    top = this.drawTitle(body, top);
    top = this.drawLegend(body, top);

    const copy = chart.cloneNode(true);
    ChartExport.inlineStyles(chart, copy);
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

  drawTitle(body, top) {
    if (!this.title) return top;
    ChartKit.el("text", { x: 8, y: top + 14, "font-family": this.font, "font-size": 15, "font-weight": 600, fill: "#1f2328" }, body).textContent = this.title;
    return top + 26;
  }

  // The legend, item by item: its glyph (a small SVG or a coloured bar) and its name.
  drawLegend(body, top) {
    const { el } = ChartKit;
    const { width, font } = this;
    const items = [...(this.legendHolder || this.container.querySelector(":scope > .legend") || document.createElement("div"))
      .querySelectorAll(".legend-item")];
    if (!items.length) return top;
    let x = 8;
    top += 4;
    for (const item of items) {
      const name = item.textContent.trim();
      const key = item.querySelector("svg");
      // An item that does not fit on this line starts the next one.
      const itemWidth = (key ? Number(key.getAttribute("width")) + 6 : 22) + ChartExport.measure(name, `12px ${font}`);
      if (x > 8 && x + itemWidth > width - 8) {
        x = 8;
        top += 20;
      }
      if (key) {
        const copy = key.cloneNode(true);
        ChartExport.inlineStyles(key, copy);
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
      x += ChartExport.measure(name, `12px ${font}`) + 16;
    }
    return top + 20;
  }
}
