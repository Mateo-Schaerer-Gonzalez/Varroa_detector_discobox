// TEMPORARY, with overlap.html. The page of the ground-truth check: one
// mite-recording at a time, its clip looped beside a picture of where its pixels
// change, its label to set, and the list to go through, by hand or cycling on its
// own. ← → move, M S U label, Z takes the last label back, Space starts or stops
// the autocycle, P plays or pauses the clip. The list is OverlapCheck's, the
// figures are OverlapFigures'.

class OverlapPage {
  static NAMES = { moving: "moving", still: "still" };
  static GLYPHS = { moving: "●", still: "○" };
  static WHERE = { in: "in the overlap", below: "below the overlap", above: "above the overlap" };
  static RING = 18;  // pixels of the recording: the ring's radius, clear of a mite's legs

  constructor() {
    this.list = [];     // the datapoints shown, in the order gone through
    this.index = 0;
    this.auto = false;  // cycling on its own
    this.dwell = null;  // the timer to the next datapoint while cycling
    this.asked = 0;     // counts the lists asked for, so a late reply is dropped

    $("ov-prev").addEventListener("click", (event) => { event.currentTarget.blur(); this.step(-1); });
    $("ov-next").addEventListener("click", (event) => { event.currentTarget.blur(); this.step(1); });
    document.querySelectorAll(".ov-labels [data-state]").forEach((button) => button.addEventListener("click", () => {
      button.blur();
      this.setLabel(button.dataset.state || null);
    }));
    $("ov-undo").addEventListener("click", (event) => { event.currentTarget.blur(); this.undo(); });
    $("ov-auto").addEventListener("change", (event) => { event.currentTarget.blur(); this.setAuto(event.currentTarget.checked); });
    $("ov-seconds").addEventListener("change", (event) => { event.currentTarget.blur(); this.startDwell(); });
    $("ov-play").addEventListener("click", (event) => {
      event.currentTarget.blur();
      event.currentTarget.textContent = player.toggle() ? "Pause" : "Play";
    });
    $("ov-speed").addEventListener("change", (event) => { event.currentTarget.blur(); this.setSpeed(); });

    ["ov-low", "ov-high"].forEach((id) => $(id).addEventListener("change", (event) => { event.currentTarget.blur(); this.setBand(); }));
    $("ov-suggested").addEventListener("click", (event) => { event.currentTarget.blur(); this.reload({ low: null, high: null }); });
    $("ov-beyond").addEventListener("change", (event) => { event.currentTarget.blur(); this.reload({ beyond: event.currentTarget.checked }); });
    $("ov-datasets").addEventListener("change", () => this.setDatasets());
    $("ov-refresh").addEventListener("click", (event) => { event.currentTarget.blur(); this.reload(); });
    $("ov-show").addEventListener("change", (event) => { event.currentTarget.blur(); check.show = event.currentTarget.value; this.refreshList(); });
    $("ov-order").addEventListener("change", (event) => { event.currentTarget.blur(); check.order = event.currentTarget.value; this.refreshList(); });
    $("ov-table").addEventListener("click", (event) => {
      const row = event.target.closest("tr[data-index]");
      if (row) this.go(Number(row.dataset.index));
    });

    document.addEventListener("keydown", (event) => this.onKey(event));
    // A hidden window does not cycle on: nobody is watching.
    document.addEventListener("visibilitychange", () => { if (document.hidden) this.stopDwell(); else this.startDwell(); });
    let resized = null;
    window.addEventListener("resize", () => {
      clearTimeout(resized);
      resized = setTimeout(() => { if (check.data) this.drawFigures(); }, 120);
    });
  }

  current() {
    return this.list[this.index] || null;
  }

  // --- the list

  // Ask the server for the list again, with `change` to what it is asked with.
  async reload(change = {}) {
    const first = !check.data;
    const status = first ? $("ov-loading") : $("ov-status");
    const asked = ++this.asked;
    this.stopDwell();
    status.className = "hint";
    status.innerHTML = `<span class="spinner"></span> ${first
      ? "Scoring the saved ground truth… the first time, and after a change to the scoring code, every frame is decoded, which takes a couple of minutes."
      : "Listing…"}`;
    try {
      await check.load(change);
    } catch (error) {
      if (asked !== this.asked) return;
      status.className = "hint error";
      status.textContent = error.message;
      if (!first) { this.drawSide(); this.startDwell(); }
      return;
    }
    if (asked !== this.asked) return;
    status.textContent = "";
    $("ov-loading").hidden = true;
    $("ov-page").hidden = false;
    this.drawSide();
    this.refreshList();
  }

  // The overlap's edges as typed; an edge left empty is the suggested one.
  setBand() {
    const edge = (id) => ($(id).value.trim() === "" ? null : Number($(id).value));
    const [low, high] = [edge("ov-low"), edge("ov-high")];
    if ([low, high].some((value) => value !== null && !(value >= 0))) {
      $("ov-status").className = "hint error";
      $("ov-status").textContent = "The overlap's edges are scores: numbers from 0 up.";
      return;
    }
    this.reload({ low, high });
  }

  // Other datasets have another overlap: back to the suggested one.
  setDatasets() {
    const datasets = [...document.querySelectorAll("#ov-datasets input:checked")].map((input) => input.value);
    this.reload({ datasets, low: null, high: null });
  }

  // Show the list as filtered and ordered now, staying on the datapoint on screen when it is still in it.
  refreshList() {
    const key = this.current() && OverlapCheck.key(this.current());
    this.list = check.points();
    this.index = Math.max(0, this.list.findIndex((point) => OverlapCheck.key(point) === key));
    this.drawTable();
    this.draw();
  }

  go(index) {
    if (!this.list.length) return;
    this.index = ((index % this.list.length) + this.list.length) % this.list.length;  // past the last one comes the first
    this.draw();
  }

  step(by) {
    this.go(this.index + by);
  }

  // --- drawing

  static labelHtml(label) {
    return label
      ? `<span class="truth-key ${label}" aria-hidden="true">${OverlapPage.GLYPHS[label]}</span>${OverlapPage.NAMES[label]}`
      : `<span class="truth-key unset" aria-hidden="true">?</span>unlabelled`;
  }

  static count(n) {
    return n.toLocaleString("en-US");
  }

  // The side panel: what was scored, where the overlap lies and what is in it.
  drawSide() {
    const { data, request } = check;
    const { counts, band, suggested } = data;
    const { count } = OverlapPage;
    const params = Object.entries(data.metric_params).map(([name, value]) => `${name} ${value}`).join(", ");
    $("ov-summary").innerHTML = `Scored with <code>${esc(data.metric)}</code>${params ? ` (${esc(params)})` : ""}:
      ${count(counts.n_moving)} mite-recordings labelled moving, ${count(counts.n_still)} labelled still.`;

    $("ov-low").value = band ? band.low : "";
    $("ov-high").value = band ? band.high : "";
    $("ov-suggested").disabled = request.low === null && request.high === null;
    $("ov-band-note").textContent = !band
      ? "A score separates the two labels here: they do not clearly overlap. Type a range of scores to look at one all the same."
      : `In it: ${count(counts.moving)} labelled moving, ${count(counts.still)} labelled still.${
        suggested ? "" : " (The labels themselves suggest none here.)"}`;
    $("ov-beyond").checked = request.beyond;
    $("ov-beyond").disabled = !band;
    $("ov-beyond-text").textContent = `Also the ${count(counts.moving_below)} labelled moving below it and the ${count(counts.still_above)} labelled still above it`;

    $("ov-datasets").innerHTML = data.datasets.map((dataset) => `
      <label class="control-check" title="${esc(dataset.id)}">
        <input type="checkbox" value="${esc(dataset.id)}"${dataset.chosen ? " checked" : ""}>
        <span>${esc(dataset.name)} <span class="hint">${count(dataset.n_moving)} moving, ${count(dataset.n_still)} still</span></span>
      </label>`).join("");
    this.drawChanged();
  }

  drawChanged() {
    const n = check.changedCount();
    $("ov-changed").textContent = n ? `${plural(n, "label")} changed since this page opened.` : "No label changed yet.";
    $("ov-undo").disabled = !check.changes.length;
  }

  rowHtml(point, index) {
    const was = check.was(point);
    return `<td class="num">${index + 1}</td>
      ${this.manyDatasets ? `<td title="${esc(point.dataset_name)}">${esc(shorten(point.dataset_name, 14))}</td>` : ""}
      <td class="num">${esc(point.mite_id)}</td>
      <td class="num">${point.recording + 1}</td>
      <td class="num">${OverlapFigures.score(point.score)}</td>
      <td>${OverlapPage.labelHtml(point.movement)}${was ? ` <span class="ov-was">was ${was.label ? OverlapPage.NAMES[was.label] : "unlabelled"}</span>` : ""}</td>`;
  }

  drawTable() {
    this.manyDatasets = new Set(check.data.datapoints.map((point) => point.dataset)).size > 1;
    $("ov-table").innerHTML = `<thead><tr><th class="num">#</th>${this.manyDatasets ? "<th>dataset</th>" : ""}
      <th class="num">mite</th><th class="num">rec.</th><th class="num">score</th><th>label</th></tr></thead>
      <tbody>${this.list.map((point, index) => `<tr data-index="${index}">${this.rowHtml(point, index)}</tr>`).join("")}</tbody>`;
  }

  // The datapoint on screen.
  draw() {
    const point = this.current();
    Charts.hideTooltip();
    $("ov-empty").hidden = Boolean(point);
    $("ov-datapoint").hidden = !point;
    $("ov-position").textContent = point ? `${this.index + 1} of ${this.list.length}` : "";
    if (!point) {
      player.stop();
      this.stopDwell();
      $("ov-empty").textContent = check.data.datapoints.length
        ? "None of the datapoints listed is shown: choose another one under Show."
        : "Nothing to check: no mite-recording lies in this overlap.";
      this.drawFigures();
      return;
    }
    $("ov-title").textContent = `Mite ${point.mite_id} · recording ${point.recording + 1}`;
    const beyond = { below: ", although labelled moving", above: ", although labelled still" }[point.where] || "";
    $("ov-meta").innerHTML = `<span title="${esc(point.dataset)}">${esc(point.dataset_name)}</span>
      · ${duration(point.time * 60)} into the run · zone ${point.zone_id}${point.group && point.group !== "unlabeled" ? ` (${esc(point.group)})` : ""}
      · score <b>${OverlapFigures.score(point.score)}</b>, ${OverlapPage.WHERE[point.where]}${beyond}`;

    const rows = $("ov-table").tBodies[0].rows;
    [...rows].forEach((row, index) => row.classList.toggle("current", index === this.index));
    const row = rows[this.index];
    const holder = $("ov-list");
    // keep the row on screen in the list, which scrolls on its own
    if (row.offsetTop < holder.scrollTop + 30) holder.scrollTop = row.offsetTop - 30;
    else if (row.offsetTop + row.offsetHeight > holder.scrollTop + holder.clientHeight) holder.scrollTop = row.offsetTop + row.offsetHeight - holder.clientHeight;

    this.drawLabel();
    this.drawFigures();
    this.playClip(point);
  }

  // The label of the datapoint on screen: on its buttons, on the rings, in the list.
  drawLabel() {
    const point = this.current();
    if (!point) return;
    document.querySelectorAll(".ov-labels [data-state]").forEach((button) => {
      button.classList.toggle("current", (button.dataset.state || null) === point.movement);
    });
    document.querySelectorAll(".ov-ring").forEach((ring) => ring.setAttribute("class", `ov-ring ${point.movement || "unset"}`));
    const was = check.was(point);
    const status = $("ov-label-status");
    status.className = "hint";
    status.textContent = was ? `Changed here: it was ${was.label ? OverlapPage.NAMES[was.label] : "unlabelled"}.` : "";
    const row = $("ov-table").tBodies[0].rows[this.index];
    if (row) row.innerHTML = this.rowHtml(point, this.index);
  }

  drawFigures() {
    const point = this.current();
    const { data } = check;
    OverlapFigures.histogram($("ov-histogram"), { histogram: data.histogram, band: data.band, score: point ? point.score : null, metric: data.metric });
    if (point) OverlapFigures.trace($("ov-trace"), { ...check.mite(point), recording: point.recording, band: data.band });
  }

  // --- the clip

  static clipUrl(point) {
    return `/api/overlap/clip/${encodeURIComponent(point.dataset)}/${encodeURIComponent(point.mite_id)}/${point.recording}`;
  }

  static frameUrl(name) {
    return `/api/overlap/file/${name}`;
  }

  // A picture of the clip's cut of the recording, with the ring round the mite.
  static picture(clip, point, src) {
    const svg = PlateView.crop(clip.x, clip.y, clip.width, clip.height, src, clip);
    const image = svg.querySelector("image");
    image.setAttribute("x", clip.x);
    image.setAttribute("y", clip.y);
    svg.appendChild(PlateView.svgEl("circle", { cx: point.x, cy: point.y, r: Math.max(OverlapPage.RING, point.r * 2.5), class: `ov-ring ${point.movement || "unset"}` }));
    return svg;
  }

  speed() {
    return Number($("ov-speed").value) || 1;
  }

  setSpeed() {
    if (!this.clip) return;
    player.interval = this.clip.interval_ms / this.speed();
    player.startTimer();
  }

  // The recording's frames, looped, and beside them where its pixels change.
  async playClip(point) {
    const holders = [$("ov-clip"), $("ov-variation")];
    const status = $("ov-clip-status");
    this.stopDwell();
    this.clip = null;
    holders.forEach((holder) => holder.classList.add("loading"));
    status.className = "hint";
    status.innerHTML = `<span class="spinner"></span> Loading…`;
    let clip = null;
    try {
      clip = await player.load(OverlapPage.clipUrl(point), OverlapPage.frameUrl);
    } catch (error) {
      if (point !== this.current()) return;
      holders.forEach((holder) => { holder.classList.remove("loading"); holder.innerHTML = ""; });
      status.className = "hint error";
      status.textContent = error.message;
      this.startDwell();
      return;
    }
    if (!clip || point !== this.current()) return;  // the user moved on meanwhile
    const moving = OverlapPage.picture(clip, point, clip.frames[0]);
    holders[0].replaceChildren(moving);
    holders[1].replaceChildren(OverlapPage.picture(clip, point, OverlapPage.frameUrl(clip.variation)));
    holders.forEach((holder) => holder.classList.remove("loading"));
    status.textContent = `${clip.frames.length} frames at ${Math.round(1000 / clip.interval_ms)} a second, looped${this.speed() === 1 ? "" : `, slowed down`}. The ring marks the mite, in the colour of its label.`;
    this.clip = clip;
    player.start({ ...clip, interval_ms: clip.interval_ms / this.speed() }, ClipPlayer.onSvg(moving, clip));
    $("ov-play").textContent = player.playing ? "Pause" : "Play";
    // the next one, so that going on shows it at once
    if (this.list.length > 1) player.warm(OverlapPage.clipUrl(this.list[(this.index + 1) % this.list.length]), OverlapPage.frameUrl);
    this.startDwell();
  }

  // --- labelling

  async setLabel(state) {
    const point = this.current();
    if (!point || point.movement === state) return;
    await this.change(() => check.label(point, state));
  }

  undo() {
    if (!check.changes.length) return null;
    return this.change(() => check.undo());
  }

  // Make a change of a label and show it: `send` resolves with the datapoint changed, if still listed.
  async change(send) {
    const status = $("ov-label-status");
    status.className = "hint";
    status.textContent = "Saving…";
    let point;
    try {
      point = await send();
    } catch (error) {
      status.className = "hint error";
      status.textContent = `Not saved: ${error.message}`;
      return;
    }
    this.drawChanged();
    const index = point ? this.list.indexOf(point) : -1;
    if (index >= 0 && index !== this.index) { this.go(index); return; }  // a label taken back: show where
    this.drawLabel();
    this.drawFigures();
    this.startDwell();
  }

  // --- cycling

  setAuto(on) {
    this.auto = on;
    $("ov-auto").checked = on;
    this.startDwell();
  }

  stopDwell() {
    clearTimeout(this.dwell);
    this.dwell = null;
    const bar = $("ov-dwell-bar");
    bar.style.transition = "none";
    bar.style.width = "0";
  }

  // Count down to the next datapoint, from the start; nothing unless cycling.
  startDwell() {
    this.stopDwell();
    if (!this.auto || document.hidden || this.list.length < 2) return;
    const seconds = Math.min(600, Math.max(0.5, Number($("ov-seconds").value) || 4));
    const bar = $("ov-dwell-bar");
    bar.getBoundingClientRect();  // the bar starts again from empty
    bar.style.transition = `width ${seconds}s linear`;
    bar.style.width = "100%";
    this.dwell = setTimeout(() => this.step(1), seconds * 1000);
  }

  onKey(event) {
    if (!check.data || event.altKey || event.ctrlKey || event.metaKey) return;
    // In a field its keys are its own.
    if (event.target.tagName === "SELECT" || (event.target.tagName === "INPUT" && event.target.type !== "checkbox")) return;
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
    const act = {
      ArrowLeft: () => this.step(-1),
      ArrowRight: () => this.step(1),
      m: () => this.setLabel("moving"),
      s: () => this.setLabel("still"),
      u: () => this.setLabel(null),
      z: () => this.undo(),
      p: () => $("ov-play").click(),
      " ": () => this.setAuto(!this.auto),
    }[key];
    if (!act) return;
    event.preventDefault();
    act();
  }
}
