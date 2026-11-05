// The Zones page: a zone mask drawn by hand on a picture, the first frame of a
// recording kept or an image file the page reads itself (it is never sent).
// Mite zones are the plates, text zones their printed-label areas. The zones
// are drawn in an SVG laid over the picture, in the picture's own pixels, which
// is what the mask's file keeps. The numbers the analysis will give the plates,
// and which text zone each plate's name is read from, come from the server.

class ZoneMaker {
  // Zones smaller than this (image px) are a click, not a zone drawn.
  static LEAST = 5;
  // A corner's handle, in screen px.
  static HANDLE = 9;

  constructor() {
    this.zones = [];           // [{type: "mite" | "text", x1, y1, x2, y2}] in image px
    this.numbers = null;       // {ids, text_of}: how the analysis numbers this.zones
    this.selected = null;      // index of the zone picked
    this.kind = "mite";        // what a drag on the picture draws
    this.picture = null;       // {src, width, height}
    this.masks = [];
    this.loaded = "";          // the mask started from ("" a new one)
    this.changed = false;      // zones not saved
    this.drag = null;          // the pointer's gesture going on
    this.started = false;
    this.fileUrl = null;       // the image file chosen, as an object URL

    $("mask-picture").addEventListener("change", (event) => this.usePicture(event.target.value));
    $("mask-file-btn").addEventListener("click", () => $("mask-file").click());
    $("mask-file").addEventListener("change", (event) => this.useFile(event.target.files[0]));
    $("mask-open").addEventListener("change", (event) => this.open(event.target.value));
    $("mask-kind").querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
      this.kind = button.dataset.kind;
      this.drawKind();
    }));
    $("mask-duplicate").addEventListener("click", () => this.duplicate());
    $("mask-remove").addEventListener("click", () => this.remove());
    $("mask-clear").addEventListener("click", () => {
      if (this.zones.length && !confirm("Remove every zone of this mask?")) return;
      this.zones = [];
      this.edited();
    });
    $("mask-save").addEventListener("click", () => this.save());
    $("mask-delete").addEventListener("click", () => this.deleteMask());
    $("mask-plate").addEventListener("keydown", (event) => this.key(event));
    window.addEventListener("beforeunload", (event) => {
      if (this.changed && this.zones.length) event.preventDefault();
    });
  }

  // The page is shown: the first time, the masks and the recordings to draw on.
  async show() {
    this.drawKind();
    if (this.started) { this.draw(); return; }
    this.started = true;
    Hint.busy($("mask-status"), "Reading the masks and the recordings…");
    try {
      const [{ masks }, { recordings }] = await Promise.all([getJson("/api/masks"), getJson("/api/recordings")]);
      this.masks = masks;
      this.recordings = recordings.map((recording) => recording.name);
      this.drawMaskChoices();
      this.drawPictureChoices();
      Hint.note($("mask-status"));
      if (this.recordings.length) await this.usePicture(this.recordings[0]);
      else this.draw();
    } catch (error) {
      this.started = false;
      Hint.error($("mask-status"), error.message);
    }
  }

  drawPictureChoices() {
    const options = this.recordings.map((name) => `<option value="rec:${esc(name)}">${esc(name)}</option>`);
    if (this.fileName) options.unshift(`<option value="file">Image file: ${esc(this.fileName)}</option>`);
    if (!options.length) options.push(`<option value="">No recordings: use an image file</option>`);
    $("mask-picture").innerHTML = options.join("");
  }

  drawMaskChoices() {
    const option = (mask) => `<option value="${esc(mask.name)}">${esc(mask.title)} · ${plural(mask.n_mite_zones, "mite zone")}</option>`;
    $("mask-open").innerHTML = `<option value="">A new, empty mask</option>${this.masks.map(option).join("")}`;
    $("mask-open").value = this.loaded;
    const mask = this.masks.find((m) => m.name === this.loaded);
    $("mask-delete").hidden = !mask || mask.built_in;
  }

  // `value`: "rec:<recording>" (its first frame), a recording's name, or "file".
  async usePicture(value) {
    if (value === "file") return this.showPicture(this.fileUrl);
    const name = value.startsWith("rec:") ? value.slice(4) : value;
    if (!name) return;
    $("mask-picture").value = `rec:${name}`;
    Hint.busy($("mask-status"), `Reading the first frame of ${esc(name)}…`);
    try {
      await this.showPicture(`/api/masks/picture/${encodeURIComponent(name)}`);
      Hint.note($("mask-status"));
    } catch (error) {
      Hint.error($("mask-status"), `The first frame of ${name} could not be read.`);
    }
  }

  useFile(file) {
    if (!file) return;
    if (this.fileUrl) URL.revokeObjectURL(this.fileUrl);
    this.fileUrl = URL.createObjectURL(file);
    this.fileName = file.name;
    this.drawPictureChoices();
    $("mask-picture").value = "file";
    this.showPicture(this.fileUrl).catch(() => Hint.error($("mask-status"), `${file.name} is not a picture the browser can show.`));
    $("mask-file").value = "";
  }

  showPicture(src) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => {
        this.picture = { src, width: image.naturalWidth, height: image.naturalHeight };
        this.draw();
        resolve();
      };
      image.onerror = reject;
      image.src = src;
    });
  }

  // Start from the mask `name` ("" an empty one).
  async open(name) {
    if (this.changed && this.zones.length && !confirm("The zones drawn are not saved. Leave them?")) {
      $("mask-open").value = this.loaded;
      return;
    }
    try {
      const mask = name ? await getJson(`/api/masks/${encodeURIComponent(name)}`) : { zones: [], ids: [], text_of: [], built_in: false };
      this.zones = mask.zones;
      this.numbers = { ids: mask.ids, text_of: mask.text_of };
      this.loaded = name;
      this.selected = null;
      this.changed = false;
      // a built-in mask is a start for one of your own, under another name
      $("mask-name").value = name && !mask.built_in ? name : "";
      this.drawMaskChoices();
      Hint.note($("mask-status"), mask.built_in ? "A built-in mask cannot be changed: save it under a name of your own." : "");
      this.draw();
    } catch (error) {
      Hint.error($("mask-status"), error.message);
    }
  }

  drawKind() {
    $("mask-kind").querySelectorAll("button").forEach((button) => {
      const on = button.dataset.kind === this.kind;
      button.classList.toggle("secondary", !on);
      button.setAttribute("aria-pressed", String(on));
    });
  }

  // --- drawing ---------------------------------------------------------------

  draw() {
    const plate = $("mask-plate");
    if (!this.picture) {
      plate.innerHTML = `<p class="hint mask-empty">Choose a picture to draw the zones on.</p>`;
      this.drawCount();
      return;
    }
    const { src, width, height } = this.picture;
    if (!plate.querySelector("svg") || plate.querySelector("img").getAttribute("src") !== src) {
      plate.innerHTML = `<img src="${esc(src)}" alt="The picture the zones are drawn on" draggable="false">
        <svg class="mask-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"></svg>`;
      this.wire(plate.querySelector("svg"));
    }
    plate.querySelector("svg").setAttribute("viewBox", `0 0 ${width} ${height}`);
    this.drawZones();
  }

  // Image px per screen px.
  scale() {
    const svg = $("mask-plate").querySelector("svg");
    return svg && svg.clientWidth ? this.picture.width / svg.clientWidth : 1;
  }

  drawZones() {
    const svg = $("mask-plate").querySelector("svg");
    if (!svg) return;
    const scale = this.scale();
    const ids = this.numbers?.ids || [];
    const textOf = this.numbers?.text_of || [];
    const parts = this.zones.map((zone, index) => {
      const w = zone.x2 - zone.x1, h = zone.y2 - zone.y1;
      let tag = "";
      if (zone.type === "mite" && ids[index] != null) tag = String(ids[index]);
      if (zone.type === "text") {
        // a text zone names one plate at most (ZoneManager.text_zone_for())
        const plate = textOf.indexOf(index);
        tag = plate >= 0 && ids[plate] != null ? `label of ${ids[plate]}` : "no slide";
      }
      const font = 13 * scale;
      // a plate's number at its top, a text zone's at its bottom: apart where they lie side by side
      const y = zone.type === "text" ? zone.y2 - 4 * scale : zone.y1 + font + 2 * scale;
      return `<g class="mask-zone ${zone.type}${index === this.selected ? " selected" : ""}" data-index="${index}">
        <rect x="${zone.x1}" y="${zone.y1}" width="${w}" height="${h}" vector-effect="non-scaling-stroke"></rect>
        ${tag ? `<text x="${zone.x1 + 4 * scale}" y="${y}" font-size="${font}">${esc(tag)}</text>` : ""}
      </g>`;
    });
    if (this.selected != null && this.zones[this.selected]) {
      const zone = this.zones[this.selected];
      const size = ZoneMaker.HANDLE * scale;
      for (const [corner, x, y] of [["nw", zone.x1, zone.y1], ["ne", zone.x2, zone.y1], ["sw", zone.x1, zone.y2], ["se", zone.x2, zone.y2]]) {
        parts.push(`<rect class="mask-handle ${corner}" data-handle="${corner}" x="${x - size / 2}" y="${y - size / 2}"
          width="${size}" height="${size}" vector-effect="non-scaling-stroke"></rect>`);
      }
    }
    svg.innerHTML = parts.join("");
    this.drawCount();
  }

  drawCount() {
    const mites = this.zones.filter((z) => z.type === "mite").length;
    const texts = this.zones.length - mites;
    const without = this.numbers ? this.zones.filter((z, i) => z.type === "mite" && this.numbers.text_of[i] == null).length : 0;
    const outside = this.picture ? this.zones.filter((z) => z.x2 > this.picture.width || z.y2 > this.picture.height).length : 0;
    const notes = [`${plural(mites, "mite zone")}, ${plural(texts, "text zone")}.`];
    if (mites && without) notes.push(`${without} without a text zone beside it: its label cannot be read from the slide.`);
    if (outside) notes.push(`${plural(outside, "zone")} reach${outside === 1 ? "es" : ""} past this picture: is it of the same camera?`);
    $("mask-count").textContent = notes.join(" ");
    $("mask-duplicate").disabled = $("mask-remove").disabled = this.selected == null;
  }

  // --- the pointer -----------------------------------------------------------

  wire(svg) {
    svg.addEventListener("pointerdown", (event) => this.down(event, svg));
    svg.addEventListener("pointermove", (event) => this.move(event, svg));
    svg.addEventListener("pointerup", (event) => this.up(event, svg));
    svg.addEventListener("pointercancel", (event) => this.up(event, svg));
  }

  // The pointer in image px, inside the picture.
  point(event, svg) {
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const at = point.matrixTransform(svg.getScreenCTM().inverse());
    const clamp = (value, top) => Math.round(Math.min(Math.max(value, 0), top));
    return { x: clamp(at.x, this.picture.width), y: clamp(at.y, this.picture.height) };
  }

  down(event, svg) {
    if (event.button !== 0) return;
    event.preventDefault();
    $("mask-plate").focus();
    const at = this.point(event, svg);
    const handle = event.target.closest("[data-handle]");
    const picked = event.target.closest("[data-index]");
    if (handle && this.selected != null) {
      // the corner across stays where it is
      const zone = this.zones[this.selected];
      const corner = handle.dataset.handle;
      this.drag = { mode: "resize", fixed: { x: corner.includes("w") ? zone.x2 : zone.x1, y: corner.includes("n") ? zone.y2 : zone.y1 } };
    } else if (picked) {
      this.selected = Number(picked.dataset.index);
      const zone = this.zones[this.selected];
      this.drag = { mode: "move", from: at, start: { ...zone } };
    } else {
      this.zones.push({ type: this.kind, x1: at.x, y1: at.y, x2: at.x, y2: at.y });
      this.selected = this.zones.length - 1;
      this.drag = { mode: "draw", fixed: at };
    }
    svg.setPointerCapture(event.pointerId);
    this.drawZones();
  }

  move(event, svg) {
    if (!this.drag) return;
    const at = this.point(event, svg);
    const zone = this.zones[this.selected];
    if (this.drag.mode === "move") {
      const { start, from } = this.drag;
      const dx = Math.min(Math.max(at.x - from.x, -start.x1), this.picture.width - start.x2);
      const dy = Math.min(Math.max(at.y - from.y, -start.y1), this.picture.height - start.y2);
      Object.assign(zone, { x1: start.x1 + dx, x2: start.x2 + dx, y1: start.y1 + dy, y2: start.y2 + dy });
    } else {
      const { fixed } = this.drag;
      Object.assign(zone, { x1: Math.min(fixed.x, at.x), x2: Math.max(fixed.x, at.x), y1: Math.min(fixed.y, at.y), y2: Math.max(fixed.y, at.y) });
    }
    this.drag.moved = true;
    this.drawZones();
  }

  up(event, svg) {
    if (!this.drag) return;
    const { mode, moved } = this.drag;
    this.drag = null;
    if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    const zone = this.zones[this.selected];
    if (mode === "draw" && (zone.x2 - zone.x1 < ZoneMaker.LEAST || zone.y2 - zone.y1 < ZoneMaker.LEAST)) {
      // a click on the picture: picks nothing
      this.zones.splice(this.selected, 1);
      this.selected = null;
      this.drawZones();
      return;
    }
    if (mode === "resize" && (zone.x2 - zone.x1 < ZoneMaker.LEAST || zone.y2 - zone.y1 < ZoneMaker.LEAST)) {
      zone.x2 = Math.max(zone.x2, zone.x1 + ZoneMaker.LEAST);
      zone.y2 = Math.max(zone.y2, zone.y1 + ZoneMaker.LEAST);
    }
    if (moved) this.edited();
    else this.drawZones();
  }

  key(event) {
    if (this.selected == null) return;
    const zone = this.zones[this.selected];
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      this.remove();
      return;
    }
    if (event.key === "Escape") { this.selected = null; this.drawZones(); return; }
    const step = event.shiftKey ? 10 : 1;
    const by = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[event.key];
    if (!by || !this.picture) return;
    event.preventDefault();
    const dx = Math.min(Math.max(by[0], -zone.x1), this.picture.width - zone.x2);
    const dy = Math.min(Math.max(by[1], -zone.y1), this.picture.height - zone.y2);
    Object.assign(zone, { x1: zone.x1 + dx, x2: zone.x2 + dx, y1: zone.y1 + dy, y2: zone.y2 + dy });
    this.edited();
  }

  // --- changes ---------------------------------------------------------------

  remove() {
    if (this.selected == null) return;
    this.zones.splice(this.selected, 1);
    this.selected = null;
    this.edited();
  }

  // A copy of the zone picked just below it (above it where there is no room),
  // for the next plate of a column.
  duplicate() {
    if (this.selected == null) return;
    const zone = this.zones[this.selected];
    const h = zone.y2 - zone.y1;
    const gap = Math.round(h * 0.05);
    const below = !this.picture || zone.y2 + gap + h <= this.picture.height;
    const dy = below ? h + gap : -(h + gap);
    if (zone.y1 + dy < 0) return;
    this.zones.push({ ...zone, y1: zone.y1 + dy, y2: zone.y2 + dy });
    this.selected = this.zones.length - 1;
    this.edited();
  }

  edited() {
    this.changed = true;
    this.drawZones();
    clearTimeout(this.numbering);
    this.numbering = setTimeout(() => this.number(), 150);
  }

  // The numbers the analysis gives the zones drawn, from the server.
  async number() {
    const asked = this.asked = (this.asked || 0) + 1;
    try {
      const numbers = await post("/api/masks/numbers", { zones: this.zones });
      if (asked !== this.asked) return;  // drawn on meanwhile: a newer request follows
      this.numbers = numbers;
      this.drawZones();
    } catch (error) {
      Hint.error($("mask-status"), error.message);
    }
  }

  async save() {
    const name = $("mask-name").value.trim();
    const status = $("mask-status");
    if (!name) { Hint.error(status, "Give the mask a name."); $("mask-name").focus(); return; }
    const existing = this.masks.find((mask) => mask.name === name);
    if (existing && name !== this.loaded && !existing.built_in
      && !confirm(`A mask ${name} is there already. Replace it? The recordings that use it take the new zones at their next analysis.`)) return;
    Hint.busy(status, "Saving…");
    try {
      const response = await fetch(`/api/masks/${encodeURIComponent(name)}`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ zones: this.zones }),
      });
      const mask = await readJson(response, "The mask could not be saved");
      this.masks = (await getJson("/api/masks")).masks;
      Object.assign(this, { loaded: mask.name, changed: false, numbers: { ids: mask.ids, text_of: mask.text_of } });
      this.drawMaskChoices();
      this.drawZones();
      Hint.note(status, `Saved as ${mask.name}. Choose it under Zone mask on a recording's label page.`);
    } catch (error) {
      Hint.error(status, error.message);
    }
  }

  async deleteMask() {
    const name = this.loaded;
    if (!name || !confirm(`Delete the mask ${name}? The recordings that use it go back to one zone per slide.`)) return;
    try {
      const response = await fetch(`/api/masks/${encodeURIComponent(name)}`, { method: "DELETE" });
      this.masks = (await readJson(response, "The mask could not be deleted")).masks;
      this.changed = false;
      await this.open("");
      Hint.note($("mask-status"), `Deleted ${name}.`);
    } catch (error) {
      Hint.error($("mask-status"), error.message);
    }
  }
}
