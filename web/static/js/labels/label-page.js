// The label page, of the analysis and of a live run: the plates over the first
// frame, each named by clicking it (ZoneEditor), every detection a ring that can
// be clicked away as "not a mite", and the groups listed beside. Its button runs
// the analysis of a folder, or starts a live test run.

class LabelPage {
  constructor() {
    this.editor = new ZoneEditor(this);
    $("run-btn").addEventListener("click", () => (ctx.mode === "live" ? live.startRun() : analysis.run()));
    $("zones-per-plate").addEventListener("change", (event) => analysis.setZonesPerPlate(Number(event.target.value)));
  }

  showLoadedStatus() {
    const { session } = ctx;
    const withMites = ctx.labelZones().length;
    $("run-status").className = "hint";
    $("run-status").textContent = ctx.mode === "live"
      ? `Mites detected in ${withMites} of ${session.zones.length} zones on ${session.n_recordings ? "the first recording" : "the camera's newest frame"}.`
      : `${session.n_recordings} recordings loaded · mites detected in ${withMites} of ${session.zones.length} zones.`;
  }

  draw() {
    const { session } = ctx;
    const plate = $("label-plate");
    const place = PlateView.overlay(plate, ctx.fileUrl(session.preview), session.image);
    const groups = ctx.labelGroups();

    session.zones.filter((zone) => !zone.n_mites).forEach((zone) => {
      const box = PlateView.emptyZone(place, zone, `Zone ${zone.id}: no mites detected, nothing to label`);
      box.innerHTML = `<span class="zone-num">${zone.id}</span>`;
      plate.appendChild(box);
    });
    ctx.labelZones().forEach((zone) => plate.append(...this.plateElements(zone, place, groups)));
    // Every detection, on top of the plates, so a false one can be clicked away.
    session.mites.forEach((mite) => plate.appendChild(this.miteMarker(mite, place)));

    this.drawGroupList();
    this.refreshSuggestions();
    this.drawRunButton();
    if (this.editor.zoneId != null) this.editor.start(this.editor.zoneId);
  }

  // A plate to label: its outline, and its name in its label area.
  plateElements(zone, place, groups) {
    const label = zone.label.trim();
    const color = label ? groupColor(label, groups) : null;

    // The plate itself is only an outline, so nothing covers the mites.
    const box = document.createElement("div");
    box.className = "zone labelling";
    box.tabIndex = 0;
    box.setAttribute("role", "button");
    box.dataset.zoneId = zone.id;
    Object.assign(box.style, place(zone.x1, zone.y1, zone.x2, zone.y2));
    if (color) box.style.setProperty("--zone-color", color);
    box.classList.toggle("empty", !label);
    box.setAttribute("aria-label", `Zone ${zone.id}, ${zone.n_mites} mite${zone.n_mites === 1 ? "" : "s"}: ${label || "no label"}${zone.control ? ", negative control" : ""}. Click to edit.`);
    box.innerHTML = `<span class="zone-num">${zone.id}</span>`;

    const rect = PlateView.textRect(zone);
    const text = document.createElement("div");
    text.className = "text-zone";
    text.dataset.zoneId = zone.id;
    Object.assign(text.style, place(rect.x1, rect.y1, rect.x2, rect.y2));
    if (color) text.style.setProperty("--zone-color", color);
    // An unnamed plate shows nothing here, so the writing on the glass stays
    // readable; the area itself is what is clicked.
    const control = zone.control ? "<small>negative control</small>" : "";
    text.title = label ? "" : `Click to name zone ${zone.id}`;
    text.innerHTML = label
      ? `<span class="text-tag">${esc(label)}${control}</span>`
      : control && `<span class="text-tag empty">${control}</span>`;

    // Open on mousedown and keep the focus where it is: a blur would redraw the
    // plate under the pointer, and the click on another plate would be lost.
    for (const element of [box, text]) {
      element.addEventListener("mousedown", (event) => {
        if (event.button !== 0 || event.target.tagName === "INPUT") return;
        event.preventDefault();
        this.editor.start(zone.id);
      });
    }
    box.addEventListener("keydown", (event) => {
      if ((event.key === "Enter" || event.key === " ") && event.target === box) {
        event.preventDefault();
        this.editor.start(zone.id);
      }
    });
    PlateView.linkHover([box, text]);
    return [box, text];
  }

  // A detection's ring, crossed out once it is marked "not a mite".
  miteMarker(mite, place) {
    const marker = document.createElement("div");
    marker.className = "label-mite";
    marker.dataset.miteId = mite.id;
    marker.classList.toggle("rejected", mite.rejected);
    marker.tabIndex = 0;
    marker.setAttribute("role", "button");
    marker.setAttribute("aria-pressed", String(mite.rejected));
    marker.title = mite.rejected
      ? `Mite ${mite.id}: marked as not a mite, left out of the analysis. Click to keep it.`
      : `Mite ${mite.id}: click if this is not a mite, to leave it out of the analysis.`;
    marker.setAttribute("aria-label", marker.title);
    // Placed by its centre; its size is fixed on screen (see .label-mite), since
    // a mite is only a few pixels across once the plate is scaled down.
    const { left, top } = place(mite.x, mite.y, mite.x, mite.y);
    Object.assign(marker.style, { left, top });
    marker.addEventListener("mousedown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      this.toggleMite(mite);
    });
    marker.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        this.toggleMite(mite, true);
      }
    });
    return marker;
  }

  toggleMite(mite, refocus = false) {
    this.editor.close();
    sessionLabels.toggleMite(mite, () => {
      this.draw();
      this.showLoadedStatus();
      if (refocus) document.querySelector(`.label-mite[data-mite-id="${mite.id}"]`)?.focus();
    });
  }

  // The label page's button runs the analysis of a folder, or starts a live test run.
  drawRunButton() {
    const living = ctx.mode === "live";
    $("pool-option").hidden = living;
    this.drawZonesOption(living);
    labelReader.draw();
    if (living) live.drawRunButton();
    else {
      $("run-btn").textContent = "Run analysis";
      $("run-btn").disabled = analysis.running;
    }
  }

  // How many zones each plate is cut into, as saved with the recording. A live
  // run's is among its test run settings, on the camera page.
  drawZonesOption(living) {
    const { session } = ctx;
    $("zones-option").hidden = living;
    if (living) return;
    const select = $("zones-per-plate");
    select.innerHTML = session.zone_layouts.map((zones) => `<option value="${zones}">${zones}</option>`).join("");
    select.value = String(session.zones_per_plate);
    select.disabled = analysis.running;  // a run going on is of the zones it started with
  }

  // Offer labels already typed as autocomplete, so repeating a group is one keystroke.
  refreshSuggestions() {
    $("known-labels").innerHTML = ctx.labelGroups().map((label) => `<option value="${esc(label)}">`).join("");
  }

  drawGroupList() {
    const groups = ctx.labelGroups();
    const zones = ctx.labelZones();
    const zoneList = (list) => `zone${list.length > 1 ? "s" : ""} ${list.map((z) => `${z.id}${z.control ? " (control)" : ""}`).join(", ")}`;
    const rows = groups.map((group) => {
      const inGroup = zones.filter((z) => z.label.trim() === group);
      return `<li><i class="swatch" style="background:${groupColor(group, groups)}"></i>
      <span class="group-name">${esc(group)}</span>
      <span class="hint">${zoneList(inGroup)}</span></li>`;
    });
    const unlabeled = zones.filter((z) => !z.label.trim());
    if (unlabeled.length) {
      rows.push(`<li><i class="swatch" style="background:${token("--series-other")}"></i>
      <span class="group-name muted">unlabeled</span>
      <span class="hint">${zoneList(unlabeled)}</span></li>`);
    }
    $("group-list").innerHTML = rows.join("");
  }
}
