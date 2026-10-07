// The ground-truth page: one zone in one recording, its clip looped, each mite a
// ring to click through moving, still and not a mite; beside it the whole plate,
// the counts and the progress. ← → move between zones, ↑ ↓ between recordings,
// P plays or pauses, D marks the zone's unlabelled mites dead. What a click does, and every count, is the server's
// (GroundTruth, classes/truth_draft.py).

class TruthPage {
  // The statuses in the order the counts list them; null is unlabelled.
  static ORDER = ["moving", "still", "not_a_mite", null];
  static NAMES = { moving: "moving", still: "still", not_a_mite: "not a mite" };
  static GLYPHS = { moving: "●", still: "○", not_a_mite: "⊘" };

  constructor() {
    $("play-btn").addEventListener("click", () => {
      $("play-btn").textContent = player.toggle() ? "Pause" : "Play";
    });
    // Buttons acting on the zone on screen, in the recording on screen.
    document.querySelectorAll(".zone-actions [data-fill]").forEach((button) => button.addEventListener("click", () => this.fill(button.dataset.fill)));
    document.addEventListener("keydown", (event) => this.onKey(event));
  }

  draw(zoneArg, recordingArg) {
    const zones = cal.zones();
    const zone = zones.find((z) => String(z.id) === zoneArg);
    const recording = Number(recordingArg);
    if (!zone || !(recording >= 0 && recording < cal.nRecordings) || recordingArg === "") {
      // Go to where work is left: the first zone and recording with an unlabelled mite.
      const target = (zone ? [zone.id, cal.recording] : null) || groundTruth.view.next || [zones[0].id, 0];
      location.replace(cal.truthHref(...target));
      return;
    }
    cal.zoneId = zone.id;
    cal.recording = recording;
    const index = zones.indexOf(zone);

    $("truth-title").textContent = `Zone ${zone.id} · ${cal.recordingName(recording)}`;
    const source = cal.data.recordings?.[recording];
    $("truth-meta").innerHTML = `${zone.label ? `${esc(zone.label)} · ` : ""}zone ${index + 1} of ${zones.length} with mites
    · <span title="${esc(cal.data.data_dir)}">${esc(folderOf(cal.data.data_dir))}</span>${source ? ` / <code>${esc(source)}</code>` : ""}`;
    $("truth-pager").innerHTML = Markup.pager(zones, index, (z) => cal.truthHref(z.id), (z) => `Zone ${z.id}`);

    const crop = PlateView.zoneCrop(zone, cal.fileUrl(cal.data.preview), cal.data.image);
    const radius = PlateView.ringRadius(zone);
    cal.mites(zone.id).forEach((mite) => crop.appendChild(this.marker(mite, radius)));
    $("truth-crop").innerHTML = "";
    $("truth-crop").appendChild(crop);
    this.playClip(crop, zone.id, recording);

    this.drawRecordingSlider();
    this.drawMap();
    this.drawCounts();
  }

  // The recording slider, with a mark under each recording in which every mite of
  // this zone is labelled.
  drawRecordingSlider() {
    const { times } = cal.data;
    const { done } = groundTruth.zone(cal.zoneId);
    const holder = $("rec-tabs");
    holder.innerHTML = RecordingSlider.html({ times, current: cal.recording, done, label: "Recording" });
    RecordingSlider.wire(holder, times, done, (recording) => router.go(cal.truthHref(cal.zoneId, recording)));
    $("play-btn").textContent = player.playing ? "Pause" : "Play";
  }

  // The recording's frames, looped over the zone crop.
  async playClip(svg, zoneId, recording) {
    const wrap = $("truth-crop");
    const status = $("clip-status");
    wrap.classList.add("loading");
    status.className = "hint";
    status.innerHTML = `<span class="spinner"></span> Loading ${cal.recordingName(recording)}…`;
    try {
      // The frames never change, so they need no cache-buster.
      const clip = await player.load(`/api/calibration/${cal.id}/clip/${recording}/${zoneId}`, (name) => `/api/session/${cal.id}/file/${name}`);
      if (!clip) return;  // the user moved on meanwhile
      wrap.classList.remove("loading");
      status.textContent = `${clip.frames.length} frames, played back in real time.`;
      player.start(clip, ClipPlayer.onSvg(svg, clip));
    } catch (error) {
      status.className = "hint error";
      status.textContent = error.message;
    }
  }

  // A clickable ring around one mite in the zone crop, showing its ground truth in
  // the recording on screen.
  marker(mite, radius) {
    const { NAMES, GLYPHS } = TruthPage;
    const r = Math.max(radius, mite.r * 1.6);
    const g = PlateView.svgEl("g", { tabindex: "0", role: "button" });
    const text = PlateView.svgEl("text", { x: mite.x + r + 4, y: mite.y - r * 0.6, "font-size": radius * 0.8 });
    g.append(
      PlateView.svgEl("circle", { cx: mite.x, cy: mite.y, r: r * 1.5, class: "hit" }),
      PlateView.svgEl("circle", { cx: mite.x, cy: mite.y, r, class: "ring" }),
      text,
    );

    const state = () => groundTruth.stateAt(mite, cal.recording);
    const describe = () => (state() ? NAMES[state()] : "unlabelled");
    const update = () => {
      g.setAttribute("class", `truth-marker ${state() || "unset"}`);
      text.textContent = `${mite.id} ${state() ? GLYPHS[state()] : "?"}`;
      g.setAttribute("aria-label", `Mite ${mite.id}: ${describe()} in ${cal.recordingName(cal.recording)}. Click to change.`);
    };
    const tip = (event) => Charts.showTooltip(event,
      `<div class="tip-title">Mite ${esc(mite.id)}</div>${describe()} in ${cal.recordingName(cal.recording)}
     <div class="tip-note">${groundTruth.statesOf(mite).map((s) => (s ? GLYPHS[s] : "?")).join(" ")}</div>
     <div class="tip-hint">Click: next status · Shift-click: previous</div>`);
    // The server steps the mite to its next status (the previous one with Shift).
    const cycle = async (event, backwards) => {
      try {
        if (!await groundTruth.edit({ action: "cycle", mite: mite.id, recording: cal.recording, backwards })) return;
      } catch (error) {
        this.showError(error);
        return;
      }
      update();
      this.refreshPanel();
      if (event.type === "click" && g.isConnected) tip(event);
    };

    g.addEventListener("click", (event) => cycle(event, event.shiftKey));
    g.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); cycle(event, event.shiftKey); }
    });
    g.addEventListener("mousemove", tip);
    g.addEventListener("mouseleave", Charts.hideTooltip);
    update();
    return g;
  }

  refreshPanel() {
    this.drawRecordingSlider();
    this.refreshMap();
    this.drawCounts();
  }

  // The whole plate, small: which zones are done, and a dot per mite by its status
  // in the recording on screen.
  drawMap() {
    const map = $("truth-map");
    const place = PlateView.overlay(map, cal.fileUrl(cal.data.preview), cal.data.image);
    cal.zones().forEach((zone) => {
      const link = document.createElement("a");
      link.className = "zone nav-zone";
      link.href = cal.truthHref(zone.id);
      link.dataset.zoneId = zone.id;
      Object.assign(link.style, place(zone.x1, zone.y1, zone.x2, zone.y2));
      link.innerHTML = `<span class="zone-num">${zone.id}</span>`;
      map.appendChild(link);
    });
    cal.data.mites.forEach((mite) => {
      const dot = document.createElement("span");
      dot.dataset.miteId = mite.id;
      dot.style.left = percent(mite.x, cal.data.image.width);
      dot.style.top = percent(mite.y, cal.data.image.height);
      map.appendChild(dot);
    });
    this.refreshMap();
  }

  refreshMap() {
    const map = $("truth-map");
    map.querySelectorAll(".nav-zone").forEach((link) => {
      const id = Number(link.dataset.zoneId);
      const zone = groundTruth.zone(id);
      link.classList.toggle("current", id === cal.zoneId);
      link.classList.toggle("done", zone.complete);
      link.title = `Zone ${id}: ${zone.n_done} of ${cal.nRecordings} recordings labelled`;
    });
    map.querySelectorAll("[data-mite-id]").forEach((dot) => {
      const state = groundTruth.stateAt(cal.data.mites.find((m) => m.id === dot.dataset.miteId), cal.recording);
      dot.className = `mite-dot ${state === "not_a_mite" ? "rejected" : state || "unset"}`;
    });
  }

  drawCounts() {
    const { ORDER, NAMES, GLYPHS } = TruthPage;
    const { view } = groundTruth;
    const here = groundTruth.zone(cal.zoneId).counts[cal.recording];
    const all = view.counts[cal.recording];
    $("truth-counts").innerHTML = ORDER.map((state) => `
    <li><span class="truth-key ${state || "unset"}" aria-hidden="true">${state ? GLYPHS[state] : "?"}</span>
      <span class="group-name">${state ? NAMES[state] : "unlabelled"}</span>
      <span class="hint">${here[state || "unset"]} here · ${all[state || "unset"]} all zones</span></li>`).join("");

    const { cells, done, ready } = view;
    $("truth-progress").innerHTML = `<b>${done}</b> of ${cells} mite-recordings labelled`;
    $("truth-progress-bar").style.width = `${(done / cells) * 100}%`;
    groundTruth.drawSaveButton();

    $("evaluate-btn").disabled = !ready;
    $("evaluate-btn").textContent = cal.mode === "test" ? "Show test report" : "Show calibration";
    const status = $("evaluate-status");
    if (!status.classList.contains("error")) {
      status.textContent = ready
        ? (done < cells ? "Unlabelled mite-recordings are left out of the report." : "")
        : "Mark at least one mite moving or still.";
    }
  }

  // Label every unlabelled mite of the zone on screen, in the recording on screen:
  // "moving", "still", "previous" (as in the recording before), or "clear" it;
  // "dead" labels them still from the recording on screen to the last one.
  async fill(kind) {
    const { zoneId, recording } = cal;
    try {
      await groundTruth.edit({ action: "fill", zone: zoneId, recording, kind });
    } catch (error) {
      this.showError(error);
      return;
    }
    if (cal.zoneId === zoneId && cal.recording === recording) this.draw(String(zoneId), String(recording));
  }

  // A change the server refused, or could not be reached for.
  showError(error) {
    $("evaluate-status").className = "hint error";
    $("evaluate-status").textContent = `Could not change the ground truth: ${error.message}`;
  }

  onKey(event) {
    if (!location.hash.startsWith("#/cal/truth") || !cal.data) return;
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    // On the recording slider the arrows move the slider itself; P still plays.
    const slider = event.target.type === "range";
    if (event.target.tagName === "INPUT" && !slider) return;
    if (event.key === "p" || event.key === "P") { $("play-btn").click(); return; }
    if (slider) return;
    if (event.key === "d" || event.key === "D") { this.fill("dead"); return; }
    const zoneStep = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
    const recordingStep = { ArrowUp: -1, ArrowDown: 1 }[event.key];
    if (zoneStep) {
      const zones = cal.zones();
      const next = zones[zones.findIndex((zone) => zone.id === cal.zoneId) + zoneStep];
      if (next) { event.preventDefault(); router.go(cal.truthHref(next.id)); }
    } else if (recordingStep) {
      const next = cal.recording + recordingStep;
      event.preventDefault();
      if (next >= 0 && next < cal.nRecordings) router.go(cal.truthHref(cal.zoneId, next));
    }
  }
}
