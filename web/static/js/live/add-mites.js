// Adding mites during a test run, from the live panel: the server lights the
// plates between two recordings and detects the mites not followed yet
// (pipeline.live_find_mites); they show on that frame, all ticked, and a click on
// one leaves it out. The ones ticked are followed from the next recording on
// (pipeline.live_add_mites), numbered after the mites of their zone.

class AddMites {
  constructor(holder) {
    this.holder = holder;
    this.found = null;   // {image, width, height, mites}: what the server found last
    this.chosen = new Set();  // indices of the mites to add
    this.busy = false;
    this.message = "";
    holder.addEventListener("click", (event) => {
      const box = event.target.closest("[data-mite]");
      if (box) { this.toggle(Number(box.dataset.mite)); return; }
      const button = event.target.closest("[data-add-action]");
      if (button) this[button.dataset.addAction]();
    });
  }

  // Light the plates and look for mites; refused while a recording is due or going on.
  async find() {
    Object.assign(this, { busy: true, message: "", found: null });
    this.draw();
    try {
      this.found = await post(`/api/live/${live.id}/find-mites`);
      this.found.stamp = Date.now();  // the image is written anew each time
      this.chosen = new Set(this.found.mites.map((_mite, i) => i));
      if (!this.found.mites.length) Object.assign(this, { found: null, message: "No mite found that is not followed already." });
    } catch (error) {
      this.message = error.message;
    } finally {
      this.busy = false;
      this.draw();
    }
  }

  toggle(index) {
    if (this.chosen.has(index)) this.chosen.delete(index); else this.chosen.add(index);
    this.draw();
  }

  async add() {
    const boxes = this.found.mites.filter((_mite, i) => this.chosen.has(i)).map((m) => [m.x1, m.y1, m.x2, m.y2]);
    this.busy = true;
    this.draw();
    try {
      live.status = await post(`/api/live/${live.id}/add-mites`, { boxes });
      this.found = null;
      this.message = `${plural(boxes.length, "mite")} will be followed from the next recording on.`;
    } catch (error) {
      this.message = error.message;
    } finally {
      this.busy = false;
      this.draw();
      livePanel.draw();
    }
  }

  cancel() {
    Object.assign(this, { found: null, message: "" });
    this.draw();
  }

  draw() {
    const holder = this.holder;
    if (!this.found) {
      holder.hidden = !this.message && !this.busy;
      holder.innerHTML = this.busy ? `<p class="hint"><span class="spinner"></span> Lighting the plates and looking for mites…</p>`
        : `<p class="hint">${esc(this.message)}</p>`;
      return;
    }
    holder.hidden = false;
    const { image, width, height, mites } = this.found;
    const pad = 6;
    const boxes = mites.map((m, i) => `<rect data-mite="${i}" class="add-mite${this.chosen.has(i) ? " chosen" : ""}"
      x="${m.x1 - pad}" y="${m.y1 - pad}" width="${m.x2 - m.x1 + 2 * pad}" height="${m.y2 - m.y1 + 2 * pad}">
      <title>Zone ${m.zone_id}, at ${m.x}, ${m.y}: ${this.chosen.has(i) ? "to add (click to leave out)" : "left out (click to add)"}</title></rect>`).join("");
    holder.innerHTML = `
    <p class="hint">${plural(mites.length, "mite")} found that ${mites.length === 1 ? "is" : "are"} not followed yet. Click one to leave it out, or to add it again.</p>
    <svg class="add-mites-image" viewBox="0 0 ${width} ${height}" role="img" aria-label="The plates, with the mites found">
      <image href="/api/session/${live.id}/file/${image}?t=${this.found.stamp}" width="${width}" height="${height}"></image>
      ${boxes}
    </svg>
    <div class="row">
      <button type="button" class="small" data-add-action="add"${this.chosen.size && !this.busy ? "" : " disabled"}>Add ${plural(this.chosen.size, "mite")}</button>
      <button type="button" class="secondary small" data-add-action="cancel"${this.busy ? " disabled" : ""}>Cancel</button>
    </div>
    ${this.message ? `<p class="hint error">${esc(this.message)}</p>` : ""}`;
  }
}
