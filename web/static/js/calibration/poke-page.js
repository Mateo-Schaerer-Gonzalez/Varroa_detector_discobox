// The poke-test page: the whole plate, and the rounds in which the mites were
// poked by hand between two recordings. A click gives a mite the result chosen
// above the plate, in the round chosen beside it: it moved (alive up to then),
// it did not (dead from then on), or it was not poked; a click on a zone's
// number gives it to the zone's mites not poked yet. Every change is saved at
// once, and what it does is the server's (classes/poke_test.py).

class PokePage {
  static NAMES = { moved: "moved", unmoved: "did not move", unset: "not poked" };

  constructor() {
    this.view = null;                // the server's view of the poke test; null until loaded
    this.shownFor = null;            // the session and dataset that view belongs to
    this.after = null;               // the round shown: the recording it was poked after
    this.brush = "moved";            // what a click gives a mite: "moved", "unmoved" or "" (not poked)
    this.queue = Promise.resolve();  // the changes, sent one after another

    document.querySelectorAll("#poke-brush [data-poke]").forEach((button) => button.addEventListener("click", () => {
      button.blur();
      this.brush = button.dataset.poke;
      this.drawBrush();
    }));
    $("poke-add").addEventListener("click", () => this.addRound());
    $("poke-report-btn").addEventListener("click", () => this.showReport());
  }

  key() {
    return `${cal.id}/${cal.datasetId}`;
  }

  round() {
    return this.view?.rounds.find((round) => round.after === this.after) || null;
  }

  // "after recording 3 (20 min)"; -1 is before the first recording.
  static when(after, times) {
    return after < 0 ? "before the first recording" : `after recording ${after + 1} (${minutes(times[after])})`;
  }

  async draw() {
    const key = this.key();
    if (this.shownFor !== key) { this.view = null; this.after = null; }
    this.drawMeta();
    this.setStatus("");
    try {
      const view = await getJson(`/api/calibration/${cal.id}/poke`, "Could not load the poke test");
      if (key !== this.key()) return;
      this.take(view, key);
    } catch (error) {
      this.setStatus(error.message, true);
      return;
    }
    this.drawMap();
    this.refresh();
  }

  drawMeta() {
    $("poke-meta").innerHTML = `<span title="${esc(cal.data.data_dir)}">${esc(folderOf(cal.data.data_dir))}</span>
    · ${plural(cal.nRecordings, "recording")}${cal.liveNote()}`;
  }

  // A live test run analysed another recording: a round can be poked after it.
  grown() {
    this.drawMeta();
    if (this.view && this.shownFor === this.key()) this.drawRounds();
  }

  take(view, key = this.key()) {
    this.view = view;
    this.shownFor = key;
    // the round shown stays; without it, the last one
    if (!this.round()) this.after = view.rounds.length ? view.rounds[view.rounds.length - 1].after : null;
  }

  setStatus(text, error = false) {
    $("poke-status").className = error ? "hint error" : "hint";
    $("poke-status").textContent = text;
  }

  // Send a change, after the ones before it, and show the view the server sends back.
  edit(change) {
    const key = this.key();
    const id = cal.id;
    const sent = this.queue.then(() => post(`/api/calibration/${id}/poke`, change)).then((view) => {
      if (key !== this.key()) return;
      this.take(view, key);
      cal.markReportStale();
      this.setStatus("");
      this.refresh();
    });
    this.queue = sent.catch((error) => { if (key === this.key()) this.setStatus(`Not saved: ${error.message}`, true); });
    return this.queue;
  }

  // --- the plate

  // The picture of the plate as at the round shown: poked before recording
  // `after` + 1, so as that recording (Calibration.previewFor()).
  roundPreview() {
    return cal.previewFor(this.round() ? this.after + 1 : 0);
  }

  // The zones, each with its number to click, and a ring round every mite that can
  // be poked, on the plate as at the round shown.
  drawMap() {
    const map = $("poke-map");
    this.shownPreview = this.roundPreview();
    const place = PlateView.overlay(map, cal.fileUrl(this.shownPreview), cal.data.image);
    const poked = new Set(this.view.mites);
    cal.data.zones.forEach((zone) => {
      if (!cal.mites(zone.id).some((mite) => poked.has(mite.id))) return;
      const box = document.createElement("div");
      box.className = "zone poke-zone";
      box.dataset.zoneId = zone.id;
      Object.assign(box.style, place(zone.x1, zone.y1, zone.x2, zone.y2));
      const number = document.createElement("button");
      number.type = "button";
      number.className = "zone-num";
      number.textContent = zone.id;
      number.addEventListener("click", () => this.fillZone(zone.id));
      box.appendChild(number);
      map.appendChild(box);
    });
    cal.data.mites.filter((mite) => poked.has(mite.id)).forEach((mite) => {
      const ring = document.createElement("button");
      ring.type = "button";
      ring.dataset.miteId = mite.id;
      ring.style.left = percent(mite.x, cal.data.image.width);
      ring.style.top = percent(mite.y, cal.data.image.height);
      ring.addEventListener("click", () => this.poke(mite.id));
      map.appendChild(ring);
    });
  }

  poke(miteId) {
    if (!this.round()) { this.setStatus("Add a poke round first.", true); return; }
    if (this.round().not_added_ids?.includes(miteId)) return;  // not there to poke in this round
    this.edit({ action: "set", after: this.after, mite: miteId, state: this.brush || null });
  }

  fillZone(zoneId) {
    if (!this.round()) { this.setStatus("Add a poke round first.", true); return; }
    this.edit({ action: "fill", after: this.after, zone: zoneId, state: this.brush || null });
  }

  // --- the rounds

  addRound() {
    this.after = Number($("poke-after").value);
    this.edit({ action: "add", after: this.after });
  }

  removeRound(after) {
    const round = this.view.rounds.find((r) => r.after === after);
    const n = Object.keys(round.states).length;
    if (n && !confirm(`Remove the poke round ${PokePage.when(after, cal.data.times)}, with its ${plural(n, "mite")}?`)) return;
    this.edit({ action: "remove", after });
  }

  refresh() {
    this.drawBrush();
    this.drawRounds();
    const round = this.round();
    if (this.roundPreview() !== this.shownPreview) this.drawMap();
    // A mite added to a live run after the round has no ring: it is not on the plate yet.
    const later = new Set(round?.not_added_ids || []);
    document.querySelectorAll("#poke-map [data-mite-id]").forEach((ring) => {
      const state = round?.states[ring.dataset.miteId] || "unset";
      ring.className = `poke-mite ${state}`;
      ring.hidden = later.has(ring.dataset.miteId);
      ring.title = `Mite ${ring.dataset.miteId}: ${PokePage.NAMES[state]}`;
    });
    document.querySelectorAll("#poke-map .poke-zone").forEach((box) => {
      box.hidden = cal.mites(Number(box.dataset.zoneId)).every((mite) => later.has(mite.id) || !this.view.mites.includes(mite.id));
    });
    $("poke-map").classList.toggle("no-round", !round);
  }

  drawBrush() {
    document.querySelectorAll("#poke-brush [data-poke]").forEach((button) => {
      button.classList.toggle("current", button.dataset.poke === this.brush);
    });
  }

  drawRounds() {
    const { times } = cal.data;
    const { rounds } = this.view;
    const taken = new Set(rounds.map((round) => round.after));
    $("poke-rounds").innerHTML = rounds.length ? rounds.map((round) => `
      <li class="${round.after === this.after ? "current" : ""}">
        <button type="button" class="link group-name" data-round="${round.after}">${PokePage.when(round.after, times)}</button>
        <button type="button" class="secondary small" data-remove="${round.after}" title="Remove this round">Remove</button>
        <span class="hint">${round.counts.moved} moved · ${round.counts.unmoved} did not · ${round.counts.unset} not poked${
          round.counts.not_added ? ` · ${round.counts.not_added} not added yet` : ""}</span>
      </li>`).join("") : `<li><span class="hint">No round yet. Choose when you poked, and add it.</span></li>`;
    document.querySelectorAll("#poke-rounds [data-round]").forEach((button) => button.addEventListener("click", () => {
      this.after = Number(button.dataset.round);
      this.refresh();
    }));
    document.querySelectorAll("#poke-rounds [data-remove]").forEach((button) => button.addEventListener("click", () => {
      this.removeRound(Number(button.dataset.remove));
    }));

    // When a new round was poked: after any recording without a round yet, the last one first.
    const free = [...times.map((_time, index) => index).reverse(), -1].filter((after) => !taken.has(after));
    $("poke-after").innerHTML = free.map((after) => `<option value="${after}">${PokePage.when(after, times)}</option>`).join("");
    $("poke-add").disabled = !free.length;
  }

  // --- the report

  // The test report, which sets the pokes against the detector's calls.
  async showReport() {
    const button = $("poke-report-btn");
    button.disabled = true;
    $("poke-status").className = "hint";
    $("poke-status").innerHTML = `<span class="spinner"></span> Comparing… the first time a dataset meets the benchmark this takes about a minute.`;
    try {
      await this.queue;
      cal.setMode("test");
      cal.takeReport(await cal.requestReport());
      this.setStatus("");
      router.go("#/cal/report");
    } catch (error) {
      this.setStatus(error.message, true);
    } finally {
      button.disabled = false;
    }
  }
}
