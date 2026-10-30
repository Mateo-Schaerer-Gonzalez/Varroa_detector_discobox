// The label page, of the analysis and of a live run: the plates over the first
// frame, each named by clicking it (ZoneEditor), every detection a ring that can
// be clicked away as "not a mite", mites the detector missed placed by hand
// (HandMites), and the groups listed beside. Its button runs
// the analysis of a folder, or starts a live test run. During a run it also shows
// the mites found to add (AddMites), and its button adds those kept.

class LabelPage {
  constructor() {
    this.editor = new ZoneEditor(this);
    $("run-btn").addEventListener("click", () => (ctx.mode === "live" ? live.startRun() : analysis.run()));
    $("label-cancel-btn").addEventListener("click", () => livePanel.adding.cancel());
    $("zones-per-plate").addEventListener("change", (event) => (ctx.mode === "live" ? live : analysis).setZonesPerPlate(Number(event.target.value)));
    $("min-new-mites").addEventListener("change", (event) => {
      const least = Number(event.target.value);
      if (Number.isInteger(least) && least >= 0) analysis.setMinNewMites(least);
      else this.drawNewMitesOption();
    });
  }

  showLoadedStatus() {
    const { session } = ctx;
    const withMites = ctx.labelZones().length;
    if (session.adding) {
      Hint.note($("run-status"), `${plural(session.mites.length, "mite")} found that ${session.mites.length === 1 ? "is" : "are"} not followed yet; `
        + "those kept are followed from the next recording on.");
      return;
    }
    const added = session.mites.filter((mite) => mite.from > 0);
    const addedNote = added.length
      ? ` ${plural(added.length, "mite")} came after the first recording, from recording `
        + `${Math.min(...added.map((mite) => mite.from)) + 1}: each is shown on the frame it was found on, in yellow. Check them.`
      : "";
    Hint.note($("run-status"), ctx.mode === "live"
      ? `Mites detected in ${withMites} of ${session.zones.length} zones on ${session.n_recordings ? "the first recording" : "the camera's newest frame"}.`
      : `${session.n_recordings} recordings loaded · mites detected in ${withMites} of ${session.zones.length} zones.${addedNote}`);
  }

  // The frames the plate can be shown on: the first, and of a saved live run
  // that added mites, each frame they were found on (`from` its recording).
  steps() {
    const { session } = ctx;
    return !session.adding && session.steps?.length ? session.steps : [{ from: 0, preview: session.preview }];
  }

  // The step shown: the one picked, else the first with mites on it, so a run
  // whose mites were all added later does not open on an empty plate.
  step() {
    const { session } = ctx;
    const steps = this.steps();
    if (session.step == null || session.step >= steps.length) {
      const first = Math.min(...session.mites.map((mite) => mite.from || 0));
      session.step = steps.reduce((found, step, index) => (step.from <= first ? index : found), 0);
    }
    return session.step;
  }

  // The mites on the step's frame: those added up to the next step.
  stepMites(index) {
    const steps = this.steps();
    const until = steps[index + 1]?.from ?? Infinity;
    return ctx.session.mites.filter((mite) => (mite.from || 0) < until);
  }

  drawSteps() {
    const steps = this.steps();
    const box = $("label-steps");
    box.hidden = steps.length < 2;
    if (box.hidden) return;
    const current = this.step();
    box.innerHTML = steps.map((step, index) => {
      const added = this.stepMites(index).filter((mite) => (mite.from || 0) >= step.from).length;
      const text = index === 0 ? "First recording" : `Added at recording ${step.from + 1} (${plural(added, "mite")})`;
      return `<button type="button" class="small${index === current ? "" : " secondary"}" data-step="${index}"
        aria-pressed="${index === current}">${text}</button>`;
    }).join("");
    box.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
      ctx.session.step = Number(button.dataset.step);
      this.editor.close();
      if (ctx.session.step !== 0 && handMites.placing) handMites.setPlacing(false);  // placed on the first frame only
      this.draw();
    }));
  }

  draw() {
    const { session } = ctx;
    const plate = $("label-plate");
    this.drawSteps();
    const steps = this.steps();
    const index = this.step();
    const place = PlateView.overlay(plate, ctx.fileUrl(steps[index].preview), session.image);
    const groups = ctx.labelGroups();

    session.zones.filter((zone) => !zone.n_mites).forEach((zone) => {
      const box = PlateView.emptyZone(place, zone, `Zone ${zone.id}: no mites detected, nothing to label`);
      box.innerHTML = `<span class="zone-num">${zone.id}</span>`;
      plate.appendChild(box);
    });
    ctx.labelZones().forEach((zone) => plate.append(...this.plateElements(zone, place, groups)));
    // Every detection on this frame, on top of the plates, so a false one can be
    // clicked away; those added on it ringed apart.
    this.stepMites(index).forEach((mite) => {
      const marker = plate.appendChild(this.miteMarker(mite, place));
      marker.classList.toggle("added", index > 0 && (mite.from || 0) >= steps[index].from);
    });

    this.drawGroupList();
    this.refreshSuggestions();
    this.drawRunButton();
    handMites.draw();
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

  // A detection's ring, crossed out once it is marked "not a mite"; dashed for a
  // mite placed by hand, which a click takes away.
  miteMarker(mite, place) {
    const marker = document.createElement("div");
    const byHand = this.placedByHand(mite);
    marker.className = "label-mite";
    marker.dataset.miteId = mite.id;
    marker.classList.toggle("rejected", mite.rejected);
    marker.classList.toggle("by-hand", byHand);
    marker.tabIndex = 0;
    marker.setAttribute("role", "button");
    if (!byHand) marker.setAttribute("aria-pressed", String(mite.rejected));
    marker.title = byHand ? `Mite ${mite.id}: placed by hand. Click to take it away.`
      : mite.rejected ? `Mite ${mite.id}: marked as not a mite, left out of the analysis. Click to keep it.`
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

  // A mite placed by hand that can still be taken away: not one of a run under way.
  placedByHand(mite) {
    return Boolean(mite.by_hand && handMites.offered);
  }

  // A mite found to add is only left out of those added, not marked in the ground truth.
  toggleMite(mite, refocus = false) {
    this.editor.close();
    if (this.placedByHand(mite)) {
      handMites.remove(mite);
      return;
    }
    const changed = () => {
      this.draw();
      this.showLoadedStatus();
      if (refocus) document.querySelector(`.label-mite[data-mite-id="${mite.id}"]`)?.focus();
    };
    if (ctx.session.adding) {
      livePanel.adding.toggle(mite);
      changed();
    } else sessionLabels.toggleMite(mite, changed);
  }

  // The label page's button runs the analysis of a folder, or starts a live test run.
  drawRunButton() {
    const living = ctx.mode === "live";
    this.drawZonesOption(living);
    this.drawNewMitesOption();
    labelReader.draw();
    if (living) live.drawRunButton();
    else {
      $("run-btn").textContent = "Run analysis";
      $("run-btn").disabled = analysis.running;
    }
  }

  // How many zones each plate is cut into: one, or two. Saved with the
  // recording; a test run's can change until it starts.
  drawZonesOption(living) {
    const { session } = ctx;
    const select = $("zones-per-plate");
    select.innerHTML = session.zone_layouts.map((zones) => `<option value="${zones}">${zones}</option>`).join("");
    select.value = String(session.zones_per_plate);
    select.disabled = living ? live.started : analysis.running;  // a run going on is of the zones it started with
  }

  // The least mites to appear in a zone at once, after the first recording, to
  // be taken: of a folder of frames only (a saved run's mites are those saved).
  drawNewMitesOption() {
    const setting = ctx.session.new_mites;
    $("new-mites-option").hidden = ctx.mode === "live" || !setting?.applies;
    if (!setting) return;
    $("min-new-mites").value = String(setting.least);
    $("min-new-mites").disabled = analysis.running;
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
