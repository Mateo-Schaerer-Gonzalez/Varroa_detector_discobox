// The ground-truth page: one mite in one recording. Its clip, cut close around it
// and looped, beside a picture of where its pixels change; its label to set; and
// the whole plate, small, showing where the mite is. M, S, N and U label it
// moving, still, not a mite or not at all, and a label goes on to the next
// recording; D marks the mite dead from the recording on screen on. ← → move
// between recordings, ↑ ↓ between mites, P plays or pauses. What a label does,
// and every count, is the server's (GroundTruth, classes/truth_draft.py).

class TruthPage {
  // The statuses in the order the counts list them; null is unlabelled.
  static ORDER = ["moving", "still", "not_a_mite", null];
  static NAMES = { moving: "moving", still: "still", not_a_mite: "not a mite" };
  static GLYPHS = { moving: "●", still: "○", not_a_mite: "⊘" };
  static RING = 18;  // pixels of the recording: the ring's radius, clear of a mite's legs

  constructor() {
    $("play-btn").addEventListener("click", () => {
      $("play-btn").textContent = player.toggle() ? "Pause" : "Play";
    });
    document.querySelectorAll(".truth-labels [data-truth]").forEach((button) => button.addEventListener("click", () => {
      button.blur();
      this.label(button.dataset.truth || null);
    }));
    $("truth-dead").addEventListener("click", (event) => { event.currentTarget.blur(); this.dead(); });
    document.addEventListener("keydown", (event) => this.onKey(event));
  }

  // The mites in the order gone through: by their number.
  mites() {
    return cal.data.mites;
  }

  mite() {
    return this.mites().find((mite) => mite.id === cal.miteId) || null;
  }

  draw(miteArg, recordingArg) {
    const mites = this.mites();
    const mite = mites.find((m) => m.id === decodeURIComponent(miteArg ?? ""));
    const recording = Number(recordingArg);
    if (!mite || !(recording >= 0 && recording < cal.nRecordings) || recordingArg === "" || recordingArg == null) {
      // Go to where work is left: the first mite and recording still to label.
      const target = (mite ? [mite.id, cal.recording] : null) || groundTruth.view.next_mite || [mites[0].id, 0];
      location.replace(cal.truthHref(...target));
      return;
    }
    cal.miteId = mite.id;
    cal.recording = recording;
    const index = mites.indexOf(mite);
    const zone = cal.data.zones.find((z) => z.id === mite.zone_id);

    $("truth-title").textContent = `Mite ${mite.id} · ${cal.recordingName(recording)}`;
    const source = cal.data.recordings?.[recording];
    $("truth-meta").innerHTML = `mite ${index + 1} of ${mites.length} · zone ${mite.zone_id}${zone?.label ? ` (${esc(zone.label)})` : ""}
    · <span title="${esc(cal.data.data_dir)}">${esc(folderOf(cal.data.data_dir))}</span>${source ? ` / <code>${esc(source)}</code>` : ""}`;
    $("truth-pager").innerHTML = Markup.pager(mites, index, (m) => cal.truthHref(m.id), (m) => `Mite ${m.id}`);

    this.playClip(mite, recording);
    this.drawRecordingSlider();
    this.drawLabel();
    this.drawMap();
    this.drawCounts();
  }

  // The recording slider, with a mark under each recording in which this mite is labelled.
  drawRecordingSlider() {
    const { times } = cal.data;
    const states = groundTruth.statesOf(this.mite());
    const done = states.map((state) => state !== null);
    const holder = $("rec-tabs");
    holder.innerHTML = RecordingSlider.html({ times, current: cal.recording, done, label: "Recording" });
    RecordingSlider.wire(holder, times, done, (recording) => router.go(cal.truthHref(cal.miteId, recording)));
    $("play-btn").textContent = player.playing ? "Pause" : "Play";
  }

  // A picture of the clip's cut of the recording, with the ring round the mite.
  picture(clip, mite, src) {
    const svg = PlateView.crop(clip.x, clip.y, clip.width, clip.height, src, clip);
    const image = svg.querySelector("image");
    image.setAttribute("x", clip.x);
    image.setAttribute("y", clip.y);
    svg.appendChild(PlateView.svgEl("circle", { cx: mite.x, cy: mite.y, r: Math.max(TruthPage.RING, mite.r * 2.5), class: "truth-ring" }));
    return svg;
  }

  // The recording's frames, looped, and beside them where its pixels change.
  async playClip(mite, recording) {
    const holders = [$("truth-crop"), $("truth-variation")];
    const status = $("clip-status");
    const frameUrl = (name) => `/api/session/${cal.id}/file/${name}`;
    const clipUrl = (m, r) => `/api/calibration/${cal.id}/mite-clip/${r}/${encodeURIComponent(m.id)}`;
    const shown = () => cal.miteId === mite.id && cal.recording === recording && location.hash.startsWith("#/cal/truth");
    holders.forEach((holder) => holder.classList.add("loading"));
    status.className = "";
    status.innerHTML = `<span class="spinner"></span> Loading ${cal.recordingName(recording)}…`;
    let clip = null;
    try {
      // The frames never change, so they need no cache-buster.
      clip = await player.load(clipUrl(mite, recording), frameUrl);
    } catch (error) {
      if (!shown()) return;
      holders.forEach((holder) => { holder.classList.remove("loading"); holder.innerHTML = ""; });
      status.className = "error";
      status.textContent = error.message;
      return;
    }
    if (!clip || !shown()) return;  // the user moved on meanwhile
    const moving = this.picture(clip, mite, clip.frames[0]);
    holders[0].replaceChildren(moving);
    holders[1].replaceChildren(this.picture(clip, mite, frameUrl(clip.variation)));
    holders.forEach((holder) => holder.classList.remove("loading"));
    status.textContent = `${clip.frames.length} frames, played back in real time. The ring marks the mite, in the colour of its label.`;
    this.drawRings();
    player.start(clip, ClipPlayer.onSvg(moving, clip));
    // the next recording, so that a label goes on to it at once
    if (recording + 1 < cal.nRecordings) player.warm(clipUrl(mite, recording + 1), frameUrl);
  }

  state() {
    return groundTruth.stateAt(this.mite(), cal.recording);
  }

  drawRings() {
    document.querySelectorAll(".truth-ring").forEach((ring) => ring.setAttribute("class", `truth-ring ${this.state() || "unset"}`));
  }

  // The label of the mite in the recording on screen: on its buttons and on the rings.
  drawLabel() {
    const state = this.state();
    document.querySelectorAll(".truth-labels [data-truth]").forEach((button) => {
      button.classList.toggle("current", (button.dataset.truth || null) === state);
    });
    this.drawRings();
  }

  // The whole plate, small: the zones, a dot per mite by its status in the
  // recording on screen, and the mite on screen marked.
  drawMap() {
    const map = $("truth-map");
    const place = PlateView.overlay(map, cal.fileUrl(cal.data.preview), cal.data.image);
    cal.data.zones.forEach((zone) => {
      const first = cal.mites(zone.id)[0];
      if (!first) return;
      const link = document.createElement("a");
      link.className = "zone nav-zone";
      link.href = cal.truthHref(first.id);
      link.title = `Zone ${zone.id}: go to its first mite`;
      link.dataset.zoneId = zone.id;
      Object.assign(link.style, place(zone.x1, zone.y1, zone.x2, zone.y2));
      link.innerHTML = `<span class="zone-num">${zone.id}</span>`;
      map.appendChild(link);
    });
    cal.data.mites.forEach((mite) => {
      const dot = document.createElement("a");
      dot.href = cal.truthHref(mite.id);
      dot.title = `Mite ${mite.id}`;
      dot.dataset.miteId = mite.id;
      dot.style.left = percent(mite.x, cal.data.image.width);
      dot.style.top = percent(mite.y, cal.data.image.height);
      map.appendChild(dot);
    });
    this.refreshMap();
  }

  refreshMap() {
    const map = $("truth-map");
    const here = this.mite();
    map.querySelectorAll(".nav-zone").forEach((link) => link.classList.toggle("current", Number(link.dataset.zoneId) === here.zone_id));
    map.querySelectorAll("[data-mite-id]").forEach((dot) => {
      const mite = cal.data.mites.find((m) => m.id === dot.dataset.miteId);
      const state = groundTruth.stateAt(mite, cal.recording);
      dot.className = `mite-dot ${state === "not_a_mite" ? "rejected" : state || "unset"}${mite === here ? " current" : ""}`;
    });
  }

  drawCounts() {
    const { ORDER, NAMES, GLYPHS } = TruthPage;
    const { view } = groundTruth;
    const mite = this.mite();
    const states = groundTruth.statesOf(mite);
    const all = view.counts[cal.recording];
    $("truth-counts").innerHTML = ORDER.map((state) => `
    <li><span class="truth-key ${state || "unset"}" aria-hidden="true">${state ? GLYPHS[state] : "?"}</span>
      <span class="group-name">${state ? NAMES[state] : "unlabelled"}</span>
      <span class="hint">${states.filter((s) => s === state).length} of this mite's recordings · ${all[state || "unset"]} mites in this one</span></li>`).join("");

    const { cells, done, ready } = view;
    $("truth-progress").innerHTML = `<b>${done}</b> of ${cells} mite-recordings labelled · this mite: ${view.mites_done[mite.id]} of ${cal.nRecordings}`;
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

  refreshPanel() {
    this.drawRecordingSlider();
    this.drawLabel();
    this.refreshMap();
    this.drawCounts();
  }

  // Send a change of the mite on screen; true once the server's view with it is shown.
  async change(edit) {
    try {
      return await groundTruth.edit({ mite: cal.miteId, recording: cal.recording, ...edit });
    } catch (error) {
      this.showError(error);
      return false;
    }
  }

  // Label the mite in the recording on screen and go on: to its next recording, or
  // after its last one, and after "not a mite", to the next mite with work left.
  async label(state) {
    const { miteId, recording } = cal;
    if (!await this.change({ action: "set", state })) return;
    if (cal.miteId !== miteId || cal.recording !== recording) return;  // moved on meanwhile
    this.refreshPanel();
    if (state === "not_a_mite" || (state && recording + 1 >= cal.nRecordings)) this.goToWork();
    else if (state) router.go(cal.truthHref(miteId, recording + 1));
  }

  // The mite is dead from the recording on screen on: still in it and in every
  // later one not labelled yet. On to the next mite with work left.
  async dead() {
    const { miteId, recording } = cal;
    if (!await this.change({ action: "dead" })) return;
    if (cal.miteId !== miteId || cal.recording !== recording) return;
    this.refreshPanel();
    this.goToWork();
  }

  // To the first mite and recording still to label; nowhere when all are done.
  goToWork() {
    const next = groundTruth.view.next_mite;
    if (next) router.go(cal.truthHref(...next));
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
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
    if (key === "p") { $("play-btn").click(); return; }
    if (slider) return;
    const labels = { m: "moving", s: "still", n: "not_a_mite", u: null };
    if (key in labels) { event.preventDefault(); this.label(labels[key]); return; }
    if (key === "d") { event.preventDefault(); this.dead(); return; }
    const recordingStep = { ArrowLeft: -1, ArrowRight: 1 }[key];
    const miteStep = { ArrowUp: -1, ArrowDown: 1 }[key];
    if (recordingStep) {
      const next = cal.recording + recordingStep;
      event.preventDefault();
      if (next >= 0 && next < cal.nRecordings) router.go(cal.truthHref(cal.miteId, next));
    } else if (miteStep) {
      const mites = this.mites();
      const next = mites[mites.findIndex((mite) => mite.id === cal.miteId) + miteStep];
      if (next) { event.preventDefault(); router.go(cal.truthHref(next.id)); }
    }
  }
}
