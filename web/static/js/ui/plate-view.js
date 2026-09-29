// Drawing on pictures of the plate: zones and dots laid over the first frame in
// percent, and crops of it drawn as SVG.

class PlateView {
  static SVG = "http://www.w3.org/2000/svg";

  // Put the picture `src` of size `image` in `container`; returns a function
  // placing a rectangle of picture pixels on it, in percent, so what is placed
  // tracks the picture as it scales.
  static overlay(container, src, image) {
    container.innerHTML = "";
    const img = document.createElement("img");
    img.src = src;
    img.alt = "First frame of the recording";
    // Its size holds its place while it loads, so a page drawn again does not jump.
    img.width = image.width;
    img.height = image.height;
    container.appendChild(img);
    return (x1, y1, x2, y2) => ({
      left: percent(x1, image.width),
      top: percent(y1, image.height),
      width: percent(x2 - x1, image.width),
      height: percent(y2 - y1, image.height),
    });
  }

  // Where a plate's name goes: its printed-label area, or, for a plate without one,
  // a strip along its top edge.
  static textRect(zone) {
    if (zone.text_zone) return zone.text_zone;
    return { x1: zone.x1, y1: zone.y1, x2: zone.x2, y2: zone.y1 + (zone.y2 - zone.y1) * 0.2 };
  }

  // Hovering either the plate or its name highlights both, so the pairing is visible.
  static linkHover(elements) {
    elements.forEach((element) => {
      element.addEventListener("mouseenter", () => elements.forEach((e) => e.classList.add("hot")));
      element.addEventListener("mouseleave", () => elements.forEach((e) => e.classList.remove("hot")));
    });
  }

  // A zone without mites: only a faint outline, nothing to open or read there.
  static emptyZone(place, zone, title) {
    const box = document.createElement("div");
    box.className = "zone no-mites";
    box.title = title;
    Object.assign(box.style, place(zone.x1, zone.y1, zone.x2, zone.y2));
    return box;
  }

  // A crop of a picture of size `size`, drawn as SVG so the viewBox does the cropping.
  static crop(x, y, w, h, src, size) {
    const svg = document.createElementNS(PlateView.SVG, "svg");
    svg.setAttribute("viewBox", `${x} ${y} ${w} ${h}`);
    svg.setAttribute("class", "crop");
    const image = document.createElementNS(PlateView.SVG, "image");
    image.setAttribute("href", src);
    image.setAttribute("width", size.width);
    image.setAttribute("height", size.height);
    svg.appendChild(image);
    return svg;
  }

  // A crop of a zone with some margin round it.
  static zoneCrop(zone, src, size, margin = 20) {
    return PlateView.crop(zone.x1 - margin, zone.y1 - margin, zone.x2 - zone.x1 + 2 * margin, zone.y2 - zone.y1 + 2 * margin, src, size);
  }

  // The radius of the rings round the mites in a zone crop.
  static ringRadius(zone) {
    return Math.max(10, (zone.x2 - zone.x1) / 28);
  }

  static svgEl(name, attrs) {
    const node = document.createElementNS(PlateView.SVG, name);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    return node;
  }
}
