// The calibration window. The user marks each detected mite alive or dead by hand,
// in every recording, and the detector's calls are compared with theirs.
//
//   #/cal/open                              choose calibrate or test, then the recordings
//   #/cal/truth/<zone id>/<recording>       enter the ground truth, zone by zone
//   #/cal/report                            the calibration or the test report
//
// Loads after app.js and reuses its helpers ($, post, go, stat, figure, cropSvg,
// plateOverlay, wireFolderPicker, ...).

const cal = {
  mode: "calibrate",  // "calibrate" or "test"
  id: null,           // server session id
  data: null,         // the opened folder: zones, mite positions, times -- no scores
  truth: {},          // mite id -> one status per recording ("alive" | "dead" | "not_a_mite" | null)
  report: null,       // what the last evaluation returned
  reportStale: false, // the ground truth changed after that evaluation
  zoneId: null,       // the zone shown on the ground-truth page
  recording: 0,       // the recording shown on the ground-truth page
  playing: true,      // whether the recording's frames play in a loop
  stamp: 0,           // cache-buster for files that change between evaluations
};

// Clicking a mite steps through these; null is unlabelled.
const TRUTH_CYCLE = [null, "alive", "dead", "not_a_mite"];
const TRUTH_NAMES = { alive: "alive", dead: "dead", not_a_mite: "not a mite" };
const TRUTH_GLYPHS = { alive: "●", dead: "✕", not_a_mite: "⊘" };

const calFileUrl = (name) => `/api/session/${cal.id}/file/${name}?t=${cal.stamp}`;
const thr = (value) => Number(value).toFixed(2);
const nRecordings = () => cal.data.n_recordings;
const calMites = (zoneId) => cal.data.mites.filter((mite) => mite.zone_id === zoneId);
// Only zones with a detected mite need visiting.
const calZones = () => cal.data.zones.filter((zone) => calMites(zone.id).length);
const calZone = (id) => cal.data.zones.find((zone) => zone.id === id);

const statesOf = (mite) => cal.truth[mite.id] || Array(nRecordings()).fill(null);
const stateAt = (mite, recording) => statesOf(mite)[recording] || null;
const isRejected = (mite) => statesOf(mite).includes("not_a_mite");
// A mite marked "not a mite" needs nothing more in any recording.
const cellDone = (mite, recording) => isRejected(mite) || stateAt(mite, recording) != null;
const recordingDone = (zoneId, recording) => calMites(zoneId).every((mite) => cellDone(mite, recording));
const recordingName = (recording) => `recording ${recording + 1} (${minutes(cal.data.times[recording])})`;
const truthHref = (zoneId, recording = cal.recording) => `#/cal/truth/${zoneId}/${recording}`;

// --- routing -------------------------------------------------------------------

function routeCalibration(sub, ...args) {
  const wanted = ["open", "truth", "report"].includes(sub) ? sub : "open";
  let step = wanted;
  if (step === "report" && !cal.report) step = cal.data ? "truth" : "open";
  if (step === "truth" && !cal.data) step = "open";
  if (step !== wanted) { location.replace(`#/cal/${step}`); return; }

  stopClip();
  showView(`cal-${step}`);
  document.querySelectorAll("#steps-cal a").forEach((link) => {
    link.classList.toggle("active", link.dataset.step === step);
    const available = link.dataset.step === "open" || (link.dataset.step === "truth" && cal.data) || (link.dataset.step === "report" && cal.report);
    link.classList.toggle("disabled", !available);
  });
  Charts.hideTooltip();

  if (step === "truth") drawTruthView(...args);
  if (step === "report") drawReport();
  window.scrollTo(0, 0);
}

// --- 1 · opening a calibration recording ------------------------------------------

const modeRadios = document.querySelectorAll('input[name="cal-mode"]');
modeRadios.forEach((radio) => radio.addEventListener("change", () => { cal.mode = radio.value; }));
// The browser may restore the last choice on reload.
cal.mode = document.querySelector('input[name="cal-mode"]:checked').value;

function setCalMode(mode) {
  cal.mode = mode;
  modeRadios.forEach((radio) => { radio.checked = radio.value === mode; });
}

async function openCalibration(dataDir) {
  const status = $("cal-open-status");
  status.className = "hint";
  status.innerHTML = `<span class="spinner"></span> Detecting and scoring the mites… every frame is decoded, this takes a while.`;
  try {
    const data = await post("/api/calibration", { data_dir: dataDir });
    Object.assign(cal, {
      id: data.session_id, data, truth: { ...data.truth }, report: null, reportStale: false,
      zoneId: null, recording: 0, stamp: Date.now(),
    });
    $("folder-name").textContent = data.data_dir.split(/[\\/]/).filter(Boolean).pop();
    $("folder-name").title = data.data_dir;
    status.textContent = "";
    go("#/cal/truth");
  } catch (error) {
    status.className = "hint error";
    status.textContent = error.message;
  }
}

wireFolderPicker("cal-", openCalibration);

// --- 2 · entering the ground truth ---------------------------------------------------

function drawTruthView(zoneArg, recordingArg) {
  const zones = calZones();
  const zone = zones.find((z) => String(z.id) === zoneArg);
  const recording = Number(recordingArg);
  if (!zone || !(recording >= 0 && recording < nRecordings()) || recordingArg === "") {
    // Go to where work is left: the first zone and recording with an unlabelled mite.
    let target = zone ? [zone.id, cal.recording] : null;
    if (!target) {
      for (const z of zones) {
        const r = cal.data.times.findIndex((_t, i) => !recordingDone(z.id, i));
        if (r >= 0) { target = [z.id, r]; break; }
      }
    }
    target = target || [zones[0].id, 0];
    location.replace(truthHref(...target));
    return;
  }
  cal.zoneId = zone.id;
  cal.recording = recording;
  const index = zones.indexOf(zone);

  $("truth-title").textContent = `Zone ${zone.id} · ${recordingName(recording)}`;
  $("truth-meta").innerHTML = `${zone.label ? `${esc(zone.label)} · ` : ""}zone ${index + 1} of ${zones.length} with mites`;
  $("truth-pager").innerHTML = pager(zones, index, (z) => truthHref(z.id), (z) => `Zone ${z.id}`);

  const margin = 20;
  const crop = cropSvg(
    zone.x1 - margin, zone.y1 - margin, zone.x2 - zone.x1 + 2 * margin, zone.y2 - zone.y1 + 2 * margin,
    calFileUrl(cal.data.preview), cal.data.image,
  );
  const radius = Math.max(10, (zone.x2 - zone.x1) / 28);
  calMites(zone.id).forEach((mite) => crop.appendChild(truthMarker(mite, radius)));
  $("truth-crop").innerHTML = "";
  $("truth-crop").appendChild(crop);
  playClip(crop, zone.id, recording);

  drawRecordingTabs();
  drawTruthMap();
  drawTruthCounts();
}

// One tab per recording; a tick once every mite of this zone is labelled in it.
function drawRecordingTabs() {
  $("rec-tabs").innerHTML = cal.data.times.map((time, recording) => {
    const done = recordingDone(cal.zoneId, recording);
    const current = recording === cal.recording;
    return `<a href="${truthHref(cal.zoneId, recording)}" class="rec-tab${current ? " current" : ""}${done ? " done" : ""}"
      ${current ? 'aria-current="page"' : ""} title="${recordingName(recording)}${done ? ", labelled" : ""}">
      ${done ? '<span aria-hidden="true">✓</span>' : ""}${minutes(time)}</a>`;
  }).join("");
  $("play-btn").textContent = cal.playing ? "Pause" : "Play";
}

// --- the recording's frames, looped over the zone crop

const clip = { timer: null, token: 0, frames: [], index: 0, image: null, interval: 100 };

function stopClip() {
  clearInterval(clip.timer);
  clip.timer = null;
  clip.token += 1;
}

function startClipTimer() {
  clearInterval(clip.timer);
  if (!cal.playing || clip.frames.length < 2) return;
  clip.timer = setInterval(() => {
    clip.index = (clip.index + 1) % clip.frames.length;
    clip.image.setAttribute("href", clip.frames[clip.index]);
  }, clip.interval);
}

async function playClip(svg, zoneId, recording) {
  stopClip();
  const token = clip.token;
  const wrap = $("truth-crop");
  const status = $("clip-status");
  wrap.classList.add("loading");
  status.className = "hint";
  status.innerHTML = `<span class="spinner"></span> Loading ${recordingName(recording)}…`;
  try {
    const response = await fetch(`/api/calibration/${cal.id}/clip/${recording}/${zoneId}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Could not load the recording");
    // The frames never change, so they need no cache-buster.
    const frames = data.frames.map((name) => `/api/session/${cal.id}/file/${name}`);
    await Promise.all(frames.map((src) => new Promise((resolve) => {
      const image = new Image();
      image.onload = image.onerror = resolve;
      image.src = src;
    })));
    if (token !== clip.token) return;  // the user moved on meanwhile

    const image = svg.querySelector("image");
    Object.entries({ x: data.x, y: data.y, width: data.width, height: data.height, href: frames[0] })
      .forEach(([key, value]) => image.setAttribute(key, value));
    Object.assign(clip, { frames, index: 0, image, interval: data.interval_ms });
    wrap.classList.remove("loading");
    status.textContent = `${frames.length} frames, played back in real time.`;
    startClipTimer();
  } catch (error) {
    if (token !== clip.token) return;
    status.className = "hint error";
    status.textContent = error.message;
  }
}

$("play-btn").addEventListener("click", () => {
  cal.playing = !cal.playing;
  $("play-btn").textContent = cal.playing ? "Pause" : "Play";
  if (cal.playing) startClipTimer();
  else clearInterval(clip.timer);
});

// --- marking mites

// A clickable ring around one mite in the zone crop, showing its ground truth in
// the recording on screen.
function truthMarker(mite, radius) {
  const ns = "http://www.w3.org/2000/svg";
  const r = Math.max(radius, mite.r * 1.6);
  const g = document.createElementNS(ns, "g");
  g.setAttribute("tabindex", "0");
  g.setAttribute("role", "button");

  const hit = document.createElementNS(ns, "circle");
  Object.entries({ cx: mite.x, cy: mite.y, r: r * 1.5, class: "hit" }).forEach(([k, v]) => hit.setAttribute(k, v));
  const ring = document.createElementNS(ns, "circle");
  Object.entries({ cx: mite.x, cy: mite.y, r, class: "ring" }).forEach(([k, v]) => ring.setAttribute(k, v));
  const text = document.createElementNS(ns, "text");
  Object.entries({ x: mite.x + r + 4, y: mite.y - r * 0.6, "font-size": radius * 0.8 }).forEach(([k, v]) => text.setAttribute(k, v));
  g.append(hit, ring, text);

  const state = () => stateAt(mite, cal.recording);
  const describe = () => (state() ? TRUTH_NAMES[state()] : "unlabelled");
  const update = () => {
    g.setAttribute("class", `truth-marker ${state() || "unset"}`);
    text.textContent = `${mite.id} ${state() ? TRUTH_GLYPHS[state()] : "?"}`;
    g.setAttribute("aria-label", `Mite ${mite.id}: ${describe()} in ${recordingName(cal.recording)}. Click to change.`);
  };
  const tip = (event) => Charts.showTooltip(event,
    `<div class="tip-title">Mite ${esc(mite.id)}</div>${describe()} in ${recordingName(cal.recording)}
     <div class="tip-note">${statesOf(mite).map((s) => (s ? TRUTH_GLYPHS[s] : "?")).join(" ")}</div>
     <div class="tip-hint">Click: next status · Shift-click: previous</div>`);
  const cycle = (event, backwards) => {
    const n = TRUTH_CYCLE.length;
    const i = TRUTH_CYCLE.indexOf(state());
    setTruth(mite, cal.recording, TRUTH_CYCLE[(i + (backwards ? n - 1 : 1)) % n]);
    update();
    refreshTruthPanel();
    if (event.type === "click") tip(event);
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

// Set one mite's status in one recording.
//
// A death is permanent, and a mite alive now was alive before, so marking a mite
// dead also marks it dead in the later recordings that are still unlabelled, and
// marking it alive marks the earlier unlabelled ones alive. Labels already
// entered are never overwritten. "Not a mite" is about the detection, not about
// a recording, so it applies to every recording, and leaving it clears them all.
//
// Clicking through the statuses passes "alive" on the way to "dead", so the cells
// filled by a mite's last change are emptied again when the same cell changes
// once more; only the fill of the status the user settles on stays.
const lastFill = {};  // mite id -> { recording, cells: [index, ...] }

function setTruth(mite, recording, state) {
  const n = nRecordings();
  let states = statesOf(mite).slice();
  const previous = lastFill[mite.id];
  if (previous && previous.recording === recording) previous.cells.forEach((i) => { states[i] = null; });
  delete lastFill[mite.id];

  if (state === "not_a_mite") {
    states = Array(n).fill("not_a_mite");
  } else {
    if (isRejected(mite)) states = Array(n).fill(null);
    states[recording] = state;
    const cells = [];
    const range = state === "dead" ? [recording + 1, n] : state === "alive" ? [0, recording] : [0, 0];
    for (let i = range[0]; i < range[1]; i += 1) {
      if (!states[i]) { states[i] = state; cells.push(i); }
    }
    if (cells.length) lastFill[mite.id] = { recording, cells };
  }
  if (states.some(Boolean)) cal.truth[mite.id] = states;
  else delete cal.truth[mite.id];
  if (cal.report) cal.reportStale = true;
  scheduleTruthSave();
}

let truthSaveTimer = null;
function scheduleTruthSave() {
  clearTimeout(truthSaveTimer);
  truthSaveTimer = setTimeout(async () => {
    try {
      await post(`/api/calibration/${cal.id}/truth`, { truth: cal.truth });
    } catch (error) {
      $("evaluate-status").className = "hint error";
      $("evaluate-status").textContent = `Could not save the ground truth: ${error.message}`;
    }
  }, 400);
}

function refreshTruthPanel() {
  drawRecordingTabs();
  refreshTruthMap();
  drawTruthCounts();
}

// The whole plate, small: which zones are done, and a dot per mite by its status
// in the recording on screen.
function drawTruthMap() {
  const map = $("truth-map");
  const place = plateOverlay(map, calFileUrl(cal.data.preview), cal.data.image);
  calZones().forEach((zone) => {
    const link = document.createElement("a");
    link.className = "zone nav-zone";
    link.href = truthHref(zone.id);
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
  refreshTruthMap();
}

function refreshTruthMap() {
  const map = $("truth-map");
  map.querySelectorAll(".nav-zone").forEach((link) => {
    const id = Number(link.dataset.zoneId);
    const done = cal.data.times.filter((_t, recording) => recordingDone(id, recording)).length;
    link.classList.toggle("current", id === cal.zoneId);
    link.classList.toggle("done", done === nRecordings());
    link.title = `Zone ${id}: ${done} of ${nRecordings()} recordings labelled`;
  });
  map.querySelectorAll("[data-mite-id]").forEach((dot) => {
    const state = stateAt(cal.data.mites.find((m) => m.id === dot.dataset.miteId), cal.recording);
    dot.className = `mite-dot ${state === "not_a_mite" ? "rejected" : state || "unset"}`;
  });
}

function drawTruthCounts() {
  const here = calMites(cal.zoneId);
  const all = cal.data.mites;
  const count = (list, state) => list.filter((mite) => stateAt(mite, cal.recording) === state).length;
  $("truth-counts").innerHTML = [...TRUTH_CYCLE.slice(1), null].map((state) => `
    <li><span class="truth-key ${state || "unset"}" aria-hidden="true">${state ? TRUTH_GLYPHS[state] : "?"}</span>
      <span class="group-name">${state ? TRUTH_NAMES[state] : "unlabelled"}</span>
      <span class="hint">${count(here, state)} here · ${count(all, state)} in this recording</span></li>`).join("");

  const cells = all.length * nRecordings();
  const done = all.reduce((sum, mite) => sum + cal.data.times.filter((_t, r) => cellDone(mite, r)).length, 0);
  $("truth-progress").innerHTML = `<b>${done}</b> of ${cells} mite-recordings labelled`;
  $("truth-progress-bar").style.width = `${(done / cells) * 100}%`;

  const ready = all.some((mite) => !isRejected(mite) && statesOf(mite).some((s) => s === "alive" || s === "dead"));
  $("evaluate-btn").disabled = !ready;
  $("evaluate-btn").textContent = cal.mode === "test" ? "Show test report" : "Show calibration";
  const status = $("evaluate-status");
  if (!status.classList.contains("error")) {
    status.textContent = ready
      ? (done < cells ? "Unlabelled mite-recordings are left out of the report." : "")
      : "Mark at least one mite alive or dead.";
  }
}

// Buttons acting on the zone on screen, in the recording on screen.
document.querySelectorAll(".zone-actions [data-fill]").forEach((button) => button.addEventListener("click", () => {
  const fill = button.dataset.fill;
  const recording = cal.recording;
  calMites(cal.zoneId).forEach((mite) => {
    if (fill === "clear") {
      if (!isRejected(mite)) setTruth(mite, recording, null);
    } else if (!cellDone(mite, recording)) {
      const state = fill === "previous" ? (recording > 0 ? stateAt(mite, recording - 1) : null) : fill;
      if (state) setTruth(mite, recording, state);
    }
  });
  drawTruthView(String(cal.zoneId), String(recording));
}));

// ← → move between zones, ↑ ↓ between recordings, P plays or pauses.
document.addEventListener("keydown", (event) => {
  if (!location.hash.startsWith("#/cal/truth") || !cal.data) return;
  if (event.target.tagName === "INPUT" || event.altKey || event.ctrlKey || event.metaKey) return;
  if (event.key === "p" || event.key === "P") { $("play-btn").click(); return; }
  const zoneStep = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
  const recordingStep = { ArrowUp: -1, ArrowDown: 1 }[event.key];
  if (zoneStep) {
    const zones = calZones();
    const next = zones[zones.findIndex((zone) => zone.id === cal.zoneId) + zoneStep];
    if (next) { event.preventDefault(); go(truthHref(next.id)); }
  } else if (recordingStep) {
    const next = cal.recording + recordingStep;
    event.preventDefault();
    if (next >= 0 && next < nRecordings()) go(truthHref(cal.zoneId, next));
  }
});

async function evaluate() {
  const button = $("evaluate-btn");
  const status = $("evaluate-status");
  button.disabled = true;
  status.className = "hint";
  status.innerHTML = `<span class="spinner"></span> Comparing…`;
  try {
    cal.report = await post(`/api/calibration/${cal.id}/evaluate`, { truth: cal.truth });
    cal.reportStale = false;
    cal.stamp = Date.now();
    status.textContent = "";
    go("#/cal/report");
  } catch (error) {
    status.className = "hint error";
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

$("evaluate-btn").addEventListener("click", evaluate);

// --- 3 · the report ----------------------------------------------------------------------

const truthColor = (truth) => token(truth === "alive" ? "--good" : "--critical");
const truthShape = (truth) => (truth === "alive" ? "circle" : "cross");

const OUTCOME_NAMES = {
  alive_ok: "alive, called alive",
  dead_ok: "dead, called dead",
  alive_missed: "alive, called dead",
  dead_missed: "dead, called alive",
};

function observationTip(row, r) {
  return `<div class="tip-title">Mite ${esc(row.mite_id)} · zone ${row.zone_id} · ${minutes(row.time)}</div>
    <div>${OUTCOME_NAMES[row.outcome]}</div>
    <div class="tip-note">score from here on ${thr(row.score)} · this recording ${thr(row.recording_score)}</div>
    <div class="tip-note">threshold in use ${thr(r.threshold)}</div>
    <div class="tip-hint">Click to see it</div>`;
}
const openObservation = (row) => () => go(truthHref(row.zone_id, row.recording));

const aucText = (r) => (r.auc == null ? "–" : r.auc.toFixed(3));
const oneClassNote = (r) =>
  `All ${r.n_observations} labelled mite-recordings are ${r.n_alive ? "alive" : "dead"}, so there is no ROC curve and no threshold to suggest: that needs alive and dead ones.`;

function drawReport() {
  const r = cal.report;
  const testing = cal.mode === "test";
  const body = $("report-body");
  const left = [
    r.n_not_a_mite ? `${r.n_not_a_mite} detection${r.n_not_a_mite > 1 ? "s" : ""} not a mite, left out` : "",
    r.n_unlabelled ? `${r.n_unlabelled} mite-recordings unlabelled, left out` : "",
  ].filter(Boolean).join(" · ");

  body.innerHTML = `
    ${cal.reportStale ? `<div class="banner">The ground truth changed since this report.
      <button type="button" id="report-refresh" class="small">Update</button></div>` : ""}
    <header class="page-head">
      <div>
        <h1>${testing ? "Threshold test" : "Calibration"}</h1>
        <p class="meta">${esc($("folder-name").textContent)} · metric <code>${esc(r.metric)}</code> ·
          ${r.n_mites} mite${r.n_mites === 1 ? "" : "s"} over ${r.times.length} recordings: ${r.n_alive} alive and ${r.n_dead} dead mite-recordings</p>
        ${left ? `<p class="meta">${left}</p>` : ""}
      </div>
      <div class="row">
        <div class="segmented" role="group" aria-label="Report">
          <button type="button" data-mode="calibrate" class="small ${testing ? "secondary" : ""}">Calibration</button>
          <button type="button" data-mode="test" class="small ${testing ? "" : "secondary"}">Test</button>
        </div>
        <a class="button secondary small" href="#/cal/truth">Edit ground truth</a>
      </div>
    </header>
    ${testing ? testReport(r) : calibrateReport(r)}
    ${section("Survival per group", `<div id="group-legend" class="legend"></div><div id="group-survival" class="group-cards"></div>
      <p class="caption">Each group's survival by the ground truth and as called by the detector, on the same mites. Groups are the plate labels.</p>`)}
    ${section("Files", `<ul class="files">
      <li><a href="${calFileUrl(r.excel)}" download>${esc(r.excel)}</a>
        <span class="muted">every labelled mite-recording with its scores and outcome, the survival curves, the ROC curve and the summary</span></li></ul>`)}`;

  body.querySelectorAll(".segmented [data-mode]").forEach((button) => button.addEventListener("click", () => {
    setCalMode(button.dataset.mode);
    drawReport();
  }));
  $("report-refresh")?.addEventListener("click", evaluate);

  if (testing) drawTestFigures(r);
  else drawCalibrateFigures(r);
  drawGroupSurvival(r, testing ? thresholdMarks(r).slice(0, 1) : thresholdMarks(r));
}

// The thresholds to show: the one in use and, when there is one, the suggestion.
function thresholdMarks(r) {
  const marks = [{ key: "current", name: "in use", value: r.threshold, confusion: r.current, color: token("--series-1") }];
  if (r.suggested_threshold != null) {
    marks.push({ key: "suggested", name: "suggested", value: r.suggested_threshold, confusion: r.best, color: token("--series-2") });
  }
  return marks;
}

const rocCaption = (r) =>
  `Every possible threshold, from the highest (bottom left) to the lowest (top right). AUC ${aucText(r)}. Hover the curve for the threshold at each step.`;
const stripCaption =
  "Each labelled mite-recording at the highest score the mite reaches from that recording on: a mite is called alive while it still moves in this or a later recording, so everything right of a line is called alive. Select a point to see that mite.";
const survivalCaption =
  "Fraction of the labelled mites alive at each recording, by your ground truth (black) and as called by the detector. The detector counts a mite alive until its last recording with movement above the threshold.";

// --- calibrate: pick a threshold and save it

function calibrateReport(r) {
  const errors = (c) => c.alive_missed + c.dead_missed;
  if (r.suggested_threshold == null) {
    return `<div class="banner">${oneClassNote(r)}</div>
      <div class="grid-2">
        ${figure("chart-survival", 1, "Survival: ground truth and detector", survivalCaption)}
        ${section("Threshold in use", comparisonTable(r))}
      </div>`;
  }
  const same = Math.abs(r.suggested_threshold - r.threshold) < 0.005;
  return `
    <div class="stats">
      ${stat("Suggested threshold", thr(r.suggested_threshold), same ? "the one in use" : `in use: ${thr(r.threshold)}`)}
      ${stat("Accuracy", pct(r.best.accuracy), `in use: ${pct(r.current.accuracy)}`)}
      ${stat("Mite-recordings called wrong", errors(r.best), `in use: ${errors(r.current)}`)}
      ${stat("AUC", aucText(r), "1 = perfect separation, 0.5 = chance")}
    </div>

    ${section("Save the threshold", `
      <div class="row save-threshold">
        <label for="threshold-input">Movement threshold</label>
        <input id="threshold-input" type="number" step="0.01" min="0" value="${thr(r.suggested_threshold)}">
        <button type="button" id="save-threshold">Save to config.yaml</button>
        <span id="save-status" class="hint"></span>
      </div>
      <p class="hint">The suggestion maximises the fraction of alive mite-recordings called alive plus the fraction of dead ones called dead,
        and sits halfway between the two nearest scores. Every analysis started after saving uses the new value.
        Check it with the <b>Test</b> report on a <em>different</em> recording: on this one it looks better than it will be.</p>`)}

    <div class="grid-2">
      ${figure("chart-survival", 1, "Survival: ground truth and detector", survivalCaption)}
      ${figure("chart-roc", 2, "ROC curve", rocCaption(r))}
    </div>

    <div class="grid-2">
      ${figure("chart-strip", 3, "Scores by ground truth", stripCaption)}
      ${section("In use and suggested", comparisonTable(r))}
    </div>`;
}

function comparisonTable(r) {
  const rows = [["in use", r.current], ...(r.best ? [["suggested", r.best]] : [])];
  return `<div class="table-wrap"><table>
    <thead><tr><th>Threshold</th><th class="num">Value</th><th class="num">Accuracy</th>
      <th class="num">Alive called dead</th><th class="num">Dead called alive</th></tr></thead>
    <tbody>${rows.map(([name, c]) => `<tr>
      <td>${name}</td><td class="num">${thr(c.threshold)}</td><td class="num">${pct(c.accuracy)}</td>
      <td class="num">${c.alive_missed}</td><td class="num">${c.dead_missed}</td></tr>`).join("")}</tbody>
  </table></div>
  <p class="caption">Counted over mite-recordings.</p>`;
}

function drawCalibrateFigures(r) {
  const marks = thresholdMarks(r);
  drawSurvival($("chart-survival"), r.survival, r.times, marks);
  if (r.suggested_threshold == null) return;
  drawRoc($("chart-roc"), r, marks);
  drawStrip($("chart-strip"), r, marks);
  $("save-threshold").addEventListener("click", saveThreshold);
}

async function saveThreshold() {
  const value = Number($("threshold-input").value);
  const status = $("save-status");
  if (!(value > 0)) {
    status.className = "hint error";
    status.textContent = "Enter a positive number.";
    return;
  }
  try {
    const saved = (await post("/api/threshold", { value })).threshold;
    cal.data.threshold = saved;
    // Evaluate again, so "in use" is the value just saved.
    cal.report = await post(`/api/calibration/${cal.id}/evaluate`, { truth: cal.truth });
    cal.stamp = Date.now();
    drawReport();
    $("save-status").className = "hint";
    $("save-status").textContent = `Saved ${thr(saved)} to config.yaml. Analyses started from now on use it.`;
  } catch (error) {
    status.className = "hint error";
    status.textContent = error.message;
  }
}

// --- test: how good is the threshold in use, and where does it go wrong

function testReport(r) {
  const c = r.current;
  const nAlive = c.alive_ok + c.alive_missed;
  const nDead = c.dead_ok + c.dead_missed;
  return `
    <div class="stats">
      ${stat("Accuracy", pct(c.accuracy), `threshold ${thr(r.threshold)}`)}
      ${stat("Alive called alive", pct(c.sensitivity), `${c.alive_ok} of ${nAlive} · sensitivity`)}
      ${stat("Dead called dead", pct(c.specificity), `${c.dead_ok} of ${nDead} · specificity`)}
      ${stat("AUC", aucText(r), "1 = perfect separation, 0.5 = chance")}
    </div>

    <div class="grid-2">
      ${figure("chart-survival", 1, "Survival: ground truth and detector", survivalCaption)}
      ${figure("confusion", 2, "Confusion matrix",
        `Ground truth against the detector's call at the threshold in use (${thr(r.threshold)}), one count per mite-recording. Percentages are of each row, and the shading follows them.`)}
    </div>

    <div class="grid-2">
      <figure class="fig">
        <div class="fig-title fig-title-row">Where the errors are
          <select id="map-recording" aria-label="Recording">
            <option value="">all recordings</option>
            ${r.times.map((time, i) => `<option value="${i}">${minutes(time)}</option>`).join("")}
          </select>
        </div>
        <div id="outcome-map" class="plate outcome-map"></div>
        <div id="outcome-legend" class="legend map-legend"></div>
        <figcaption><b>Fig. 3.</b> Every labelled mite on the first frame. Mites called right in every selected recording are faint rings;
          a mite called wrong at least once is coloured by its more frequent error. Hover a mite for its recordings, select it to see it.</figcaption>
      </figure>
      ${r.roc ? figure("chart-roc", 4, "ROC curve", rocCaption(r)) : section("ROC curve", `<p class="hint">${oneClassNote(r)}</p>`)}
    </div>

    <div class="grid-2">
      ${r.roc ? figure("chart-strip", 5, "Scores by ground truth", stripCaption) : ""}
      ${section("Per zone", `<div class="table-wrap"><table class="clickable" id="zone-errors"></table></div>
        <p class="caption">Counts are mite-recordings. Select a zone to review its ground truth.</p>`)}
    </div>`;
}

function drawTestFigures(r) {
  const marks = thresholdMarks(r).slice(0, 1);
  drawSurvival($("chart-survival"), r.survival, r.times, marks);
  $("confusion").innerHTML = confusionTable(r.current);
  const drawMap = () => drawOutcomeMap(r, $("map-recording").value);
  $("map-recording").addEventListener("change", drawMap);
  drawMap();
  if (r.roc) {
    drawRoc($("chart-roc"), r, marks);
    drawStrip($("chart-strip"), r, marks);
  }
  drawZoneErrors(r);
}

function confusionTable(c) {
  const nAlive = c.alive_ok + c.alive_missed;
  const nDead = c.dead_ok + c.dead_missed;
  const cell = (n, of) => `<td class="cm" style="--f:${of ? n / of : 0}"><b>${n}</b><small>${of ? pct(n / of) : "–"}</small></td>`;
  return `<table class="confusion">
    <thead>
      <tr><th rowspan="2">Ground truth</th><th colspan="2" class="cm-group">Called by the detector</th><th rowspan="2" class="num">Total</th></tr>
      <tr><th class="cm-col">alive</th><th class="cm-col">dead</th></tr>
    </thead>
    <tbody>
      <tr><td>${statusBadge(true)}</td>${cell(c.alive_ok, nAlive)}${cell(c.alive_missed, nAlive)}<td class="num">${nAlive}</td></tr>
      <tr><td>${statusBadge(false)}</td>${cell(c.dead_missed, nDead)}${cell(c.dead_ok, nDead)}<td class="num">${nDead}</td></tr>
    </tbody>
  </table>`;
}

// --- figures shared by both reports

// Ground truth survival (black) against the detector's, one line per threshold.
// The ground truth comes last so it is drawn on top where the lines coincide.
function survivalSeries(curves, marks, { legend = true } = {}) {
  const asPercent = (values) => values.map((v) => (v == null ? null : v * 100));
  return [
    ...marks.map((mark) => ({
      name: `detector, ${mark.name} ${thr(mark.value)}`,
      values: asPercent(curves[mark.key]),
      color: mark.color, step: true, dashed: true, legend,
    })),
    { name: "ground truth", values: asPercent(curves.truth), color: token("--ink"), width: 2.25, step: true, legend },
  ];
}

function drawSurvival(container, curves, times, marks) {
  Charts.line(container, {
    x: times,
    yLabel: "Mites alive (%)",
    yMin: 0, yMax: 100,
    yFormat: (v) => `${Math.round(v)}`,
    noDirectLabels: true,
    series: survivalSeries(curves, marks),
    tooltipExtra: (i) => `<div class="tip-note">${curves.n[i]} mites labelled</div>`,
  });
}

// Small multiples: one survival chart per group, sharing one legend.
function drawGroupSurvival(r, marks) {
  $("group-legend").innerHTML = Charts.legendHtml(survivalSeries(r.survival, marks).map((s) => ({
    name: s.name, color: s.color, ...(s.dashed ? { dashed: true } : { shape: "line" }),
  })));
  const container = $("group-survival");
  r.group_survival.forEach((group) => {
    const card = document.createElement("div");
    card.className = "group-card";
    card.innerHTML = `<div class="group-card-head">${groupTag(group.group, token(group.group === "unlabeled" ? "--series-other" : "--muted"))}
      <span class="hint">${group.n_mites} mite${group.n_mites === 1 ? "" : "s"}</span></div>`;
    const plot = document.createElement("div");
    card.appendChild(plot);
    container.appendChild(card);
    Charts.line(plot, {
      x: r.times,
      height: 190,
      yLabel: "Alive (%)",
      yMin: 0, yMax: 100,
      yFormat: (v) => `${Math.round(v)}`,
      series: survivalSeries(group, marks, { legend: false }),
      tooltipExtra: (i) => `<div class="tip-note">${group.n[i]} mites labelled</div>`,
    });
  });
}

// Alive observations in one row, dead in the other, jittered so equal scores stay visible.
function drawStrip(container, r, marks) {
  // A fixed jitter per observation, so a redraw does not shuffle the points.
  const jitter = (key) => {
    let hash = 7;
    for (const char of key) hash = (hash * 31 + char.charCodeAt(0)) % 1009;
    return (hash / 1009 - 0.5) * 0.5;
  };
  Charts.scatter(container, {
    height: 220,
    points: r.observations.map((row) => ({
      x: row.score,
      y: (row.truth === "alive" ? 1 : 0) + jitter(`${row.mite_id}/${row.recording}`),
      color: truthColor(row.truth),
      shape: truthShape(row.truth),
      r: 3.5,
      tip: observationTip(row, r),
      onClick: openObservation(row),
    })),
    refX: marks.map((mark) => ({ value: mark.value, label: `${mark.name} ${thr(mark.value)}` })),
    yCategories: [{ value: 0, label: "✕ dead" }, { value: 1, label: "● alive" }],
    yMin: -0.5, yMax: 1.5,
    xMin: 0,
    xLabel: "Highest motion score from that recording on",
  });
}

function drawRoc(container, r, marks) {
  const { fpr, tpr, thresholds } = r.roc;
  const percentFormat = (v) => `${Math.round(v * 100)}%`;
  Charts.scatter(container, {
    square: true,
    height: 400,
    xMin: 0, xMax: 1, yMin: 0, yMax: 1,
    xFormat: percentFormat,
    yFormat: percentFormat,
    xLabel: "Dead called alive (false positive rate)",
    yLabel: "Alive called alive",
    lines: [
      { points: [[0, 0], [1, 1]], color: token("--muted"), width: 1, dashed: true },
      { points: fpr.map((f, i) => [f, tpr[i]]), color: token("--ink"), width: 2 },
    ],
    points: [
      // Every step of the curve can be hovered for its threshold.
      ...fpr.slice(1).map((f, i) => ({
        x: f, y: tpr[i + 1], r: 3, hidden: true,
        tip: `<div class="tip-title">threshold ${thr(thresholds[i + 1])}</div>
          <div>${percentFormat(tpr[i + 1])} of alive mite-recordings called alive</div>
          <div>${percentFormat(f)} of dead mite-recordings called alive</div>`,
      })),
      ...marks.map((mark, i) => {
        const c = mark.confusion;
        const f = c.dead_missed / (c.dead_ok + c.dead_missed);
        return {
          // the second label goes under its point, so close thresholds stay readable
          x: f, y: c.sensitivity, r: 6, color: mark.color, label: `${mark.name} ${thr(mark.value)}`, labelDy: i ? 16 : 0,
          tip: `<div class="tip-title">${mark.name}: ${thr(mark.value)}</div>
            <div>${percentFormat(c.sensitivity)} of alive mite-recordings called alive</div>
            <div>${percentFormat(f)} of dead mite-recordings called alive</div>`,
        };
      }),
    ],
    legend: [
      { name: "ROC", color: token("--ink"), shape: "line" },
      { name: "chance", color: token("--muted"), dashed: true },
      ...marks.map((mark) => ({ name: `${mark.name} threshold`, color: mark.color, shape: "circle" })),
    ],
  });
}

// --- where the errors are (test report)

function drawOutcomeMap(r, recordingValue) {
  const container = $("outcome-map");
  const rows = recordingValue === "" ? r.observations : r.observations.filter((row) => row.recording === Number(recordingValue));
  const place = plateOverlay(container, calFileUrl(cal.data.preview), cal.data.image);
  cal.data.zones.forEach((zone) => {
    const box = document.createElement("div");
    box.className = "zone passive";
    Object.assign(box.style, place(zone.x1, zone.y1, zone.x2, zone.y2));
    container.appendChild(box);
  });

  // One dot per mite; its class is its more frequent error, if it has any.
  const byMite = new Map();
  rows.forEach((row) => {
    if (!byMite.has(row.mite_id)) byMite.set(row.mite_id, []);
    byMite.get(row.mite_id).push(row);
  });
  const counts = { correct: 0, alive_missed: 0, dead_missed: 0 };
  byMite.forEach((miteRows) => {
    const first = miteRows[0];
    const aliveMissed = miteRows.filter((row) => row.outcome === "alive_missed");
    const deadMissed = miteRows.filter((row) => row.outcome === "dead_missed");
    const kind = !aliveMissed.length && !deadMissed.length ? "correct"
      : aliveMissed.length >= deadMissed.length ? "alive_missed" : "dead_missed";
    counts[kind] += 1;

    const dot = document.createElement("span");
    dot.className = `outcome-dot ${kind}`;
    dot.style.left = percent(first.x, cal.data.image.width);
    dot.style.top = percent(first.y, cal.data.image.height);
    const list = (errs) => errs.map((row) => minutes(row.time)).join(", ");
    dot.addEventListener("mousemove", (event) => Charts.showTooltip(event,
      `<div class="tip-title">Mite ${esc(first.mite_id)} · zone ${first.zone_id}</div>
       <div>${aliveMissed.length + deadMissed.length} of ${miteRows.length} recordings called wrong</div>
       ${aliveMissed.length ? `<div class="tip-note">alive, called dead: ${list(aliveMissed)}</div>` : ""}
       ${deadMissed.length ? `<div class="tip-note">dead, called alive: ${list(deadMissed)}</div>` : ""}
       <div class="tip-hint">Click to see it</div>`));
    dot.addEventListener("mouseleave", Charts.hideTooltip);
    const worst = [...aliveMissed, ...deadMissed][0] || first;
    dot.addEventListener("click", openObservation(worst));
    container.appendChild(dot);
  });

  $("outcome-legend").innerHTML = Charts.legendHtml([
    { name: `always right (${counts.correct})`, color: token("--muted"), shape: "ring" },
    { name: `alive, called dead (${counts.alive_missed})`, color: token("--series-2"), shape: "circle" },
    { name: `dead, called alive (${counts.dead_missed})`, color: token("--series-7"), shape: "square" },
  ]);
}

function drawZoneErrors(r) {
  const table = $("zone-errors");
  table.innerHTML = `
    <thead><tr><th>Zone</th><th>Label</th><th class="num">Mites</th><th class="num">Alive</th><th class="num">Dead</th>
      <th class="num">Called wrong</th></tr></thead>
    <tbody>${r.zones.map((zone) => `
      <tr data-href="${truthHref(zone.id, 0)}" tabindex="0">
        <td><a href="${truthHref(zone.id, 0)}">Zone ${zone.id}</a></td>
        <td>${esc(calZone(zone.id)?.label || "")}</td>
        <td class="num">${zone.n_mites}</td>
        <td class="num">${zone.n_alive}</td><td class="num">${zone.n_dead}</td>
        <td class="num${zone.n_errors ? " error" : ""}">${zone.n_errors} <small class="muted">(${pct(zone.n_errors / zone.n_observations)})</small></td>
      </tr>`).join("")}</tbody>`;
  table.querySelectorAll("tr[data-href]").forEach((row) => {
    row.addEventListener("click", () => go(row.dataset.href));
    row.addEventListener("keydown", (event) => { if (event.key === "Enter") go(row.dataset.href); });
  });
}

// app.js and this file are both loaded: start.
route();
