// Calibration, in the same window as the analysis. The user marks, for each detected
// mite and each recording, whether it moves, and the detector's calls are compared with theirs.
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
  data: null,         // the opened folder: zones, mite positions, times -- no scores; null when only pooling saved data
  datasetId: null,    // the saved dataset the opened folder's ground truth goes to
  datasets: [],       // every saved dataset, as listed by the server
  selected: [],       // ids of the saved datasets the report pools
  truth: {},          // mite id -> one status per recording ("moving" | "still" | "not_a_mite" | null)
  report: null,       // what the last evaluation returned
  reportStale: false, // the ground truth changed after that evaluation
  zoneId: null,       // the zone shown on the ground-truth page
  recording: 0,       // the recording shown on the ground-truth page
  shownThreshold: "best", // confusion matrix of the calibration tab: "best" or "current"
  stamp: 0,           // cache-buster for files that change between evaluations
  scores: null,       // the movement scores the server offers, and the one in config.yaml
  metric: null,       // the movement score to report with, { name, params }; null: config.yaml's
  mapDataset: null,   // the dataset the error map of a pooled report shows
};

// Clicking a mite steps through these; null is unlabelled.
const TRUTH_CYCLE = [null, "moving", "still", "not_a_mite"];
const TRUTH_NAMES = { moving: "moving", still: "still", not_a_mite: "not a mite" };
const TRUTH_GLYPHS = { moving: "●", still: "○", not_a_mite: "⊘" };

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
const folderOf = (path) => String(path || "").split(/[\\/]/).filter(Boolean).pop() || "";
const truthHref = (zoneId, recording = cal.recording) => `#/cal/truth/${zoneId}/${recording}`;

// --- routing -------------------------------------------------------------------

function routeCalibration(sub, ...args) {
  const wanted = ["open", "truth", "report"].includes(sub) ? sub : "open";
  let step = wanted;
  if (step === "report" && !cal.report) step = cal.data ? "truth" : "open";
  if (step === "truth" && !cal.data) step = "open";
  if (step !== wanted) { location.replace(`#/cal/${step}`); return; }

  showView(`cal-${step}`);
  document.querySelectorAll("#steps-cal a[data-step]").forEach((link) => {
    link.classList.toggle("active", link.dataset.step === step);
    const available = link.dataset.step === "open" || (link.dataset.step === "truth" && cal.data) || (link.dataset.step === "report" && cal.report);
    link.classList.toggle("disabled", !available);
  });
  Charts.hideTooltip();

  if (step === "open") { refreshDatasets(); refreshRecordings(); }
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

// Start labelling what the server opened: a folder just detected, or a saved dataset.
// Callers first save or drop the unsaved changes (openWithTruthSaved), so that
// reopening the dataset just edited shows what was saved.
function startCalibration(data) {
  Object.assign(cal, {
    id: data.session_id, report: null, reportStale: false, selected: [data.dataset_id],
  });
  showDataset(data);
  go("#/cal/truth");
}

// Put a dataset on the ground-truth page; the report and the pooled datasets stay.
function showDataset(data) {
  Object.assign(cal, {
    data, truth: { ...data.truth }, datasetId: data.dataset_id,
    zoneId: null, recording: 0, stamp: Date.now(),
  });
  forgetTruthChanges();
  setFolder("cal", folderOf(data.data_dir), data.data_dir);
}

// Go to one mite in one recording of any saved dataset, e.g. a point of a pooled
// report. Another dataset than the one on the ground-truth page is opened in its
// place, in the same session, so the report stays.
async function goToMite(datasetId, zoneId, recording) {
  if (!(cal.data && cal.datasetId === datasetId)) {
    try {
      await saveOrDropChanges();
      showDataset(await post(`/api/calibration/${cal.id}/dataset/${encodeURIComponent(datasetId)}`, {}));
    } catch (error) {
      alert(`Could not open that recording: ${error.message}`);
      return;
    }
  }
  go(truthHref(zoneId, recording));
}

// Before another dataset replaces the one on screen: ask whether to save its
// unsaved changes, and wait for a save under way, so the server reads the ground
// truth with them. Throws when the save fails; the changes then stay on screen.
async function saveOrDropChanges() {
  if (truthUnsaved() && confirm("Save your changes to the ground truth first?\n\nOK saves them, Cancel discards them.")) {
    await flushTruthSave();
  } else {
    await truthSaving.catch(() => {});
  }
}

async function openWithTruthSaved(status, open) {
  try {
    await saveOrDropChanges();
  } catch (error) {
    status.className = "hint error";
    status.textContent = `Not opened: the last changes could not be saved (${error.message}).`;
    return;
  }
  await open();
}

const openCalibration = (dataDir) => openWithTruthSaved($("cal-open-status"), async () => {
  const status = $("cal-open-status");
  status.className = "hint";
  status.innerHTML = `<span class="spinner"></span> Detecting and scoring the mites… every frame is decoded, this takes a while.`;
  try {
    const data = await post("/api/calibration", { data_dir: dataDir });
    status.textContent = "";
    startCalibration(data);
  } catch (error) {
    status.className = "hint error";
    status.textContent = error.message;
  }
});

wireFolderPicker("cal-", openCalibration);

// --- saved ground truth: reopen one, or pool several into a report

const savedDate = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
const labelsText = (d) => `${d.n_moving} moving · ${d.n_still} still`;

async function fetchDatasets() {
  const response = await fetch("/api/calibration/datasets", { cache: "no-store" });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Could not list the saved ground truth");
  cal.datasets = data.datasets;
  return cal.datasets;
}

async function refreshDatasets() {
  const table = $("dataset-table");
  try {
    await fetchDatasets();
  } catch (error) {
    table.innerHTML = `<tbody><tr><td class="error">${esc(error.message)}</td></tr></tbody>`;
    return;
  }
  if (!cal.datasets.length) {
    table.innerHTML = `<tbody><tr><td class="muted">Nothing saved yet. Label a calibration recording and it appears here.</td></tr></tbody>`;
    $("pool-btn").disabled = true;
    return;
  }
  table.innerHTML = `
    <thead><tr><th aria-label="Pool"></th><th>Recording</th><th>Saved</th>
      <th class="num">Recordings</th><th class="num">Mites</th><th>Labels</th><th></th></tr></thead>
    <tbody>${cal.datasets.map((d) => `
      <tr>
        <td><input type="checkbox" class="pool-check" value="${esc(d.id)}" aria-label="Pool ${esc(d.name)}"></td>
        <td title="${esc(d.data_dir)}">${esc(d.name)}${d.recordings_available ? "" : ' <span class="muted">· recordings moved and not copied, no clips or new scores</span>'}</td>
        <td>${savedDate(d.saved_at)}</td>
        <td class="num">${d.n_recordings}</td>
        <td class="num">${d.n_mites}</td>
        <td>${labelsText(d)}</td>
        <td class="row-actions">
          <button type="button" class="secondary small" data-open="${esc(d.id)}">Open</button>
          <button type="button" class="secondary small" data-delete="${esc(d.id)}">Delete</button>
        </td>
      </tr>`).join("")}</tbody>`;

  const checks = [...table.querySelectorAll(".pool-check")];
  const update = () => { $("pool-btn").disabled = !checks.some((c) => c.checked); };
  checks.forEach((check) => check.addEventListener("change", update));
  update();
  table.querySelectorAll("[data-open]").forEach((button) => button.addEventListener("click", () => openDataset(button.dataset.open)));
  table.querySelectorAll("[data-delete]").forEach((button) => button.addEventListener("click", () => deleteDataset(button.dataset.delete)));
}

const openDataset = (id) => openWithTruthSaved($("pool-status"), async () => {
  const status = $("pool-status");
  status.className = "hint";
  status.innerHTML = `<span class="spinner"></span> Opening…`;
  try {
    const data = await post(`/api/calibration/datasets/${encodeURIComponent(id)}/open`, {});
    status.textContent = "";
    startCalibration(data);
  } catch (error) {
    status.className = "hint error";
    status.textContent = error.message;
  }
});

async function deleteDataset(id) {
  const dataset = cal.datasets.find((d) => d.id === id);
  const question = `Delete the saved ground truth of "${dataset.name}"?\n\n`
    + "The ground_truth.json next to its recordings stays, so opening that folder again brings the labels back.";
  if (!confirm(question)) return;
  const status = $("pool-status");
  try {
    const response = await fetch(`/api/calibration/datasets/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (!response.ok) throw new Error((await response.json()).detail || "Could not delete");
    cal.selected = cal.selected.filter((s) => s !== id);
    status.textContent = "";
    refreshDatasets();
  } catch (error) {
    status.className = "hint error";
    status.textContent = error.message;
  }
}

// A report on saved datasets alone, with no recording opened for labelling.
$("pool-btn").addEventListener("click", () => openWithTruthSaved($("pool-status"), async () => {
  const ids = [...document.querySelectorAll(".pool-check:checked")].map((c) => c.value);
  const status = $("pool-status");
  status.className = "hint";
  status.innerHTML = `<span class="spinner"></span> Comparing…`;
  try {
    const { session_id } = await post("/api/calibration/pooled", {});
    Object.assign(cal, {
      id: session_id, data: null, truth: {}, datasetId: null, selected: ids,
      report: null, reportStale: false, stamp: Date.now(),
    });
    forgetTruthChanges();
    cal.report = await requestReport();
    setFolder("cal", `${ids.length} saved dataset${ids.length === 1 ? "" : "s"}`);
    status.textContent = "";
    go("#/cal/report");
  } catch (error) {
    status.className = "hint error";
    status.textContent = error.message;
  }
}));

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
  const source = cal.data.recordings?.[recording];
  $("truth-meta").innerHTML = `${zone.label ? `${esc(zone.label)} · ` : ""}zone ${index + 1} of ${zones.length} with mites
    · <span title="${esc(cal.data.data_dir)}">${esc(folderOf(cal.data.data_dir))}</span>${source ? ` / <code>${esc(source)}</code>` : ""}`;
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
  $("play-btn").textContent = player.playing ? "Pause" : "Play";
}

// --- the recording's frames, looped over the zone crop (app.js's player)

async function playClip(svg, zoneId, recording) {
  const wrap = $("truth-crop");
  const status = $("clip-status");
  wrap.classList.add("loading");
  status.className = "hint";
  status.innerHTML = `<span class="spinner"></span> Loading ${recordingName(recording)}…`;
  try {
    // The frames never change, so they need no cache-buster.
    const clip = await loadClip(`/api/calibration/${cal.id}/clip/${recording}/${zoneId}`, (name) => `/api/session/${cal.id}/file/${name}`);
    if (!clip) return;  // the user moved on meanwhile
    wrap.classList.remove("loading");
    status.textContent = `${clip.frames.length} frames, played back in real time.`;
    startPlayer(clip, clipOnSvg(svg, clip));
  } catch (error) {
    status.className = "hint error";
    status.textContent = error.message;
  }
}

$("play-btn").addEventListener("click", () => {
  $("play-btn").textContent = togglePlaying() ? "Pause" : "Play";
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
// Movement is judged recording by recording -- a mite still in one recording may
// move in the next -- so only this recording changes. "Not a mite" is about the
// detection, not about a recording, so it applies to every recording. Leaving it
// brings back the statuses the mite had before this page marked it, so clicking
// through "not a mite" on the way from still to moving loses nothing; a mite
// marked in another window, or before the dataset was opened, is left unlabelled.
function setTruth(mite, recording, state) {
  const n = nRecordings();
  const before = statesOf(mite);
  const rejected = isRejected(mite);
  let states;
  if (state === "not_a_mite") {
    if (!rejected) labelsBeforeRejection[mite.id] = before;
    states = Array(n).fill("not_a_mite");
  } else {
    states = (rejected ? labelsBeforeRejection[mite.id] || Array(n).fill(null) : before).slice();
    delete labelsBeforeRejection[mite.id];
    states[recording] = state;
  }
  if (states.some(Boolean)) cal.truth[mite.id] = states;
  else delete cal.truth[mite.id];
  if (cal.report) cal.reportStale = true;
  // Only the recordings that changed are saved.
  const changed = unsavedTruth[mite.id] || {};
  states.forEach((s, r) => { if (s !== before[r]) changed[r] = s; });
  if (Object.keys(changed).length) unsavedTruth[mite.id] = changed;
  drawSaveButton();
}

// --- saving: changes wait on screen until "Save changes", or showing a report
//
// Saving also brings the library's copy of the recordings up to date, which is
// too slow to do on every click. Only the statuses changed here are sent, mite by
// mite and recording by recording; the server applies them to what is saved,
// which another window may have changed meanwhile, so a save never undoes a
// change made elsewhere, even one this page has not caught up with. Saves go one
// after another, so a slow one is never overtaken by the next.

let unsavedTruth = {};  // mite id -> { recording: status } changed on screen and not saved yet
let labelsBeforeRejection = {};  // mite id -> its statuses before it was marked "not a mite" here
let truthSaving = Promise.resolve();
let truthSavesUnderWay = 0;
// Counts the saves started and the datasets shown: a reply about the saved ground
// truth is out of date once another save has started or another dataset is shown.
let truthEpoch = 0;

const truthUnsaved = () => Object.keys(unsavedTruth).length > 0;

// Another dataset replaces the one on screen, whose changes are saved or dropped by now.
function forgetTruthChanges() {
  unsavedTruth = {};
  labelsBeforeRejection = {};
  truthEpoch++;
  drawSaveButton();
}

function drawSaveButton() {
  const button = $("save-truth-btn");
  const n = Object.keys(unsavedTruth).length;
  button.disabled = !n || truthSavesUnderWay > 0;
  button.textContent = truthSavesUnderWay ? "Saving…"
    : n ? `Save changes (${n} mite${n === 1 ? "" : "s"})` : "All changes saved";
}

$("save-truth-btn").addEventListener("click", () => flushTruthSave().catch(() => {}));

// Save what is waiting, now; resolves once it and every earlier save are done.
// The dataset is taken when called, so a dataset opened next never gets them.
function flushTruthSave() {
  const changes = unsavedTruth;
  if (!truthUnsaved()) return truthSaving.catch(() => {});  // nothing new: wait for any save under way
  const { id: sessionId, data } = cal;
  const epoch = ++truthEpoch;
  unsavedTruth = {};
  truthSavesUnderWay++;
  drawSaveButton();
  truthSaving = truthSaving.catch(() => {}).then(async () => {
    const status = $("evaluate-status");
    let saved;
    try {
      const body = JSON.stringify({ truth: changes });
      const response = await fetch(`/api/calibration/${sessionId}/truth`, {
        method: "POST",
        // keepalive: a save under way still lands when the window reloads or
        // closes; browsers refuse it for a body over 64 KB
        keepalive: body.length < 60000,
        headers: { "Content-Type": "application/json" },
        body,
      });
      saved = await response.json();
      if (!response.ok) throw new Error(saved.detail || "Request failed");
    } catch (error) {
      if (data === cal.data) keepUnsaved(changes);
      status.className = "hint error";
      status.dataset.saveError = "1";
      status.textContent = `Could not save the ground truth: ${error.message}. Click "Save changes" to try again.`;
      throw error;
    } finally {
      truthSavesUnderWay--;
      drawSaveButton();
    }
    if (status.classList.contains("error") && status.dataset.saveError) {
      status.className = "hint";
      delete status.dataset.saveError;
      if (cal.data && data === cal.data) drawTruthCounts();
    }
    // What is saved now, with any change from another window, unless a later save will say.
    if (epoch === truthEpoch && data === cal.data) showSavedTruth(saved.truth);
  });
  return truthSaving;
}

// A failed save's changes wait for the next save: those still on screen, as a
// status changed again since is saved with its own change.
function keepUnsaved(changes) {
  Object.entries(changes).forEach(([id, statuses]) => {
    const shown = statesOf({ id });
    Object.entries(statuses).forEach(([recording, state]) => {
      const waiting = unsavedTruth[id] || {};
      if (shown[recording] === state && !(recording in waiting)) unsavedTruth[id] = { ...waiting, [recording]: state };
    });
  });
}

// A mite's statuses after changes of some of its recordings, as the server
// applies them (calibration.apply_changes).
function applyChanges(states, changes, n) {
  const changed = Object.entries(changes);
  if (!changed.length) return states || Array(n).fill(null);
  if (changed.some(([, state]) => state === "not_a_mite")) return Array(n).fill("not_a_mite");
  const result = states && !states.includes("not_a_mite") ? states.slice() : Array(n).fill(null);
  changed.forEach(([recording, state]) => { result[recording] = state; });
  return result;
}

const sameTruth = (a, b) => Object.keys(a).length === Object.keys(b).length
  && Object.keys(a).every((id) => JSON.stringify(a[id]) === JSON.stringify(b[id]));

// Show the ground truth as saved, which another window may have changed, with the
// changes not saved yet on top.
function showSavedTruth(saved) {
  const truth = { ...saved };
  Object.entries(unsavedTruth).forEach(([id, changes]) => {
    const states = applyChanges(truth[id], changes, nRecordings());
    if (states.some(Boolean)) truth[id] = states;
    else delete truth[id];
  });
  // Statuses to bring back belong to "not a mite" marks still on screen.
  Object.keys(labelsBeforeRejection).forEach((id) => {
    if (!(truth[id] || []).includes("not_a_mite")) delete labelsBeforeRejection[id];
  });
  if (sameTruth(truth, cal.truth)) return;
  cal.truth = truth;
  if (cal.report) cal.reportStale = true;
  if (location.hash.startsWith("#/cal/truth")) drawTruthView(String(cal.zoneId), String(cal.recording));
}

// Closing or reloading the window with changes not saved yet, or still saving, asks first.
window.addEventListener("beforeunload", (event) => {
  if (!truthUnsaved() && !truthSavesUnderWay) return;
  event.preventDefault();
  event.returnValue = "";
});

// Coming back to this window, or to calibration from the analysis (app.js's
// setMode): show the ground truth as saved, which the analysis or another window,
// e.g. marking a detection "not a mite" before a run, may have changed.
async function reloadTruth() {
  if (!cal.data || !cal.id || document.visibilityState !== "visible") return;
  // A reply is up to date only if no save lands while it is on its way.
  while (truthSavesUnderWay) await truthSaving.catch(() => {});
  const { id: sessionId, data } = cal;
  if (!data) return;
  const epoch = truthEpoch;
  try {
    const response = await fetch(`/api/calibration/${sessionId}/truth`, { cache: "no-store" });
    const saved = await response.json();
    if (!response.ok) throw new Error(saved.detail || "Could not load the ground truth");
    if (epoch === truthEpoch && data === cal.data) showSavedTruth(saved.truth);
  } catch {
    // the page keeps what it shows; the next change saves as usual
  }
}
window.addEventListener("focus", reloadTruth);
document.addEventListener("visibilitychange", reloadTruth);

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
      <span class="hint">${count(here, state)} here · ${count(all, state)} all zones</span></li>`).join("");

  const cells = all.length * nRecordings();
  const done = all.reduce((sum, mite) => sum + cal.data.times.filter((_t, r) => cellDone(mite, r)).length, 0);
  $("truth-progress").innerHTML = `<b>${done}</b> of ${cells} mite-recordings labelled`;
  $("truth-progress-bar").style.width = `${(done / cells) * 100}%`;
  drawSaveButton();

  const ready = all.some((mite) => !isRejected(mite) && statesOf(mite).some((s) => s === "moving" || s === "still"));
  $("evaluate-btn").disabled = !ready;
  $("evaluate-btn").textContent = cal.mode === "test" ? "Show test report" : "Show calibration";
  const status = $("evaluate-status");
  if (!status.classList.contains("error")) {
    status.textContent = ready
      ? (done < cells ? "Unlabelled mite-recordings are left out of the report." : "")
      : "Mark at least one mite moving or still.";
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
    cal.report = await requestReport();
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

// Save the changes still unsaved and compare the saved ground truth, pooled over
// the chosen datasets and scored with the chosen movement score. The saved
// datasets and the movement scores on offer are refreshed alongside, for the
// report's pickers.
async function requestReport() {
  await flushTruthSave();
  const [report] = await Promise.all([
    post(`/api/calibration/${cal.id}/evaluate`, {
      datasets: cal.selected, metric: cal.metric?.name ?? null, params: cal.metric?.params ?? null,
    }),
    fetchDatasets().catch(() => cal.datasets),
    fetchScores().catch(() => cal.scores),
  ]);
  return report;
}

async function fetchScores() {
  const response = await fetch("/api/calibration/metrics");
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Could not list the movement scores");
  cal.scores = data;
  return data;
}

// Evaluate again after changing what the report uses. On failure `undo` puts the
// choice back and the error shows in the element `statusId`.
async function reportAgain(statusId, undo) {
  $(statusId).className = "hint";
  $(statusId).innerHTML = `<span class="spinner"></span> Scoring and comparing… the first time a dataset meets a movement score its recordings are decoded, which takes a while.`;
  try {
    cal.report = await requestReport();
    cal.reportStale = false;
    cal.stamp = Date.now();
    drawReport();
  } catch (error) {
    undo();
    drawReport();
    $(statusId).className = "hint error";
    $(statusId).textContent = error.message;
  }
}

// --- 3 · the report ----------------------------------------------------------------------
//
// Each (mite, recording) you labelled moving or still is compared with the
// detector's call: moving when that recording's score reaches the threshold.

const called = (c, truth, call) => c[`${truth}_called_${call}`];
const aucText = (r) => (r.auc == null ? "–" : r.auc.toFixed(3));
const oneClassNote = (r) =>
  `All ${r.n_moving + r.n_still} labels are ${r.n_moving ? "moving" : "still"}, so there is no ROC curve and no threshold to suggest: that needs both moving and still labels.`;

const pooled = (r) => r.datasets.length > 1;
// Where a row comes from: the recording folder and, when known, the recording in it.
const sourceText = (row) => `${esc(row.dataset_name)}${row.recording_name ? ` / ${esc(row.recording_name)}` : ""}`;

function observationTip(row, r) {
  return `<div class="tip-title">Mite ${esc(row.mite_id)} · zone ${row.zone_id} · ${minutes(row.time)}</div>
    <div class="tip-note">${sourceText(row)}</div>
    <div>labelled ${row.movement}, called ${row.outcome.split("_called_")[1]}</div>
    <div class="tip-note">score ${thr(row.score)}${r.threshold_fits ? ` · threshold in use ${thr(r.threshold)}` : ""}</div>
    <div class="tip-hint">Click to see it in its recording</div>`;
}
// Every observation, from whichever dataset, opens its mite in its recording.
const openObservation = (row) => () => goToMite(row.dataset, row.zone_id, row.recording);

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
        <p class="meta">${pooled(r) ? `${r.datasets.length} datasets pooled` : `<span title="${esc(r.datasets[0].data_dir)}">${esc(r.datasets[0].name)}</span>`} ·
          movement score <code>${esc(scoreText(r.metric, r.metric_params))}</code> ·
          ${r.n_mites} mite${r.n_mites === 1 ? "" : "s"} over ${r.times.length} recordings ·
          ${r.n_moving} moving and ${r.n_still} still labels</p>
        ${left ? `<p class="meta">${left}</p>` : ""}
      </div>
      <div class="row">
        <div class="segmented" role="group" aria-label="Report">
          <button type="button" data-mode="calibrate" class="small ${testing ? "secondary" : ""}">Calibration</button>
          <button type="button" data-mode="test" class="small ${testing ? "" : "secondary"}">Test</button>
        </div>
        ${cal.data ? '<a class="button secondary small" href="#/cal/truth">Edit ground truth</a>' : ""}
      </div>
    </header>
    ${section("Data used", datasetPicker(r))}
    ${section("Movement score", scorePicker(r))}
    ${r.threshold_fits ? "" : `<div class="banner">The threshold in use, ${thr(r.threshold)}, was set for
      <code>${esc(scoreText(r.in_use.metric, r.in_use.params))}</code>. These scores are
      <code>${esc(scoreText(r.metric, r.metric_params))}</code>, on another scale, so figures "in use" say little:
      look at the suggested threshold, and save it with this movement score to use it.</div>`}
    ${testing ? testReport(r) : calibrateReport(r)}
    ${testing ? section("Mites moving per group", `<div id="group-legend" class="legend"></div><div id="group-moving" class="group-cards"></div>
      <p class="caption">Each group's fraction of mites moving in each recording, by the ground truth and as called by the detector, on the same mites. Groups are the plate labels.${poolNote(r)}</p>`) : ""}
    ${section("Files", `<ul class="files">
      <li><a href="${calFileUrl(r.excel)}" download>${esc(r.excel)}</a>
        <span class="muted">every labelled mite-recording with its score and outcome, the fraction moving per recording, the ROC curve and the summary</span></li></ul>`)}`;

  body.querySelectorAll(".segmented [data-mode]").forEach((button) => button.addEventListener("click", () => {
    setCalMode(button.dataset.mode);
    drawReport();
  }));
  $("report-refresh")?.addEventListener("click", evaluate);
  wireDatasetPicker();
  wireScorePicker(r);

  // Groups matter to a test of the threshold, not to finding one.
  if (testing) {
    drawTestFigures(r);
    drawGroupMoving(r, thresholdMarks(r).slice(0, 1));
  } else {
    drawCalibrateFigures(r);
  }
}

// The datasets that can be pooled: those whose recordings can still be scored.
const poolable = () => cal.datasets.filter((d) => d.recordings_available);
// The report pools more than the dataset on the ground-truth page.
const pooling = () => cal.selected.some((id) => id !== cal.datasetId);

// Which saved datasets the report pools. With a dataset open for labelling, a
// toggle pools the other saved ground truth with it or not; ticking a dataset
// compares again at once.
function datasetPicker(r) {
  const used = new Map(r.datasets.map((d) => [d.id, d]));
  const toggle = cal.datasetId ? `
    <label class="pool-toggle">
      <input type="checkbox" id="pool-toggle" ${pooling() ? "checked" : ""} ${poolable().some((d) => d.id !== cal.datasetId) ? "" : "disabled"}>
      <span><b>Pool with saved ground truth from other recordings</b>
        <span class="hint">Old recordings are scored again with the movement score below, from their saved copy, never from old scores.</span></span>
    </label>` : "";
  const shown = !cal.datasetId || pooling();
  const rows = cal.datasets.map((d) => {
    const inReport = used.get(d.id);
    const open = d.id === cal.datasetId;
    return `<li><label class="dataset-option">
      <input type="checkbox" class="dataset-check" value="${esc(d.id)}" ${cal.selected.includes(d.id) ? "checked" : ""}
        ${d.recordings_available ? "" : "disabled"}>
      <span class="group-name" title="${esc(d.data_dir)}">${esc(d.name)}${open ? ' <span class="muted">(on the ground-truth page)</span>' : ""}</span>
      <span class="hint">${d.recordings_available ? "" : "recordings moved and not copied, cannot be scored · "}${savedDate(d.saved_at)} ·
        ${d.n_recordings} recordings · ${d.n_mites} mites · ${labelsText(d)}${inReport ? ` · <b>${inReport.n_observations}</b> in this report` : ""}</span>
    </label></li>`;
  }).join("");
  return `${toggle}
    ${shown ? `<ul class="group-list dataset-list">${rows}</ul>` : ""}
    <p id="dataset-status" class="hint">${pooled(r)
      ? "The mite-recordings of all ticked datasets are pooled. For the charts over time, recordings are lined up by their order (first, second, …) at their mean time. Click any mite in the charts, the map or the table to open it in its own recording."
      : cal.datasetId ? "Only the recording on the ground-truth page is used." : "Tick more datasets to pool their labels, for a threshold based on more data."}</p>`;
}

function wireDatasetPicker() {
  const change = (chosen) => {
    const before = cal.selected;
    cal.selected = chosen;
    reportAgain("dataset-status", () => { cal.selected = before; });
  };
  $("pool-toggle")?.addEventListener("change", (event) => {
    change(event.target.checked ? [cal.datasetId, ...poolable().map((d) => d.id).filter((id) => id !== cal.datasetId)] : [cal.datasetId]);
  });
  document.querySelectorAll(".dataset-check").forEach((check) => check.addEventListener("change", () => {
    const chosen = [...document.querySelectorAll(".dataset-check:checked")].map((c) => c.value);
    if (!chosen.length) {
      check.checked = true;
      $("dataset-status").className = "hint error";
      $("dataset-status").textContent = "Keep at least one dataset.";
      return;
    }
    change(chosen);
  }));
}

// --- the movement score the report is scored with

// e.g. "topN_variability (n=10)"
function scoreText(metric, params) {
  const list = Object.entries(params || {}).map(([k, v]) => `${k}=${v}`).join(", ");
  return list ? `${metric} (${list})` : metric;
}

// Choose a metric and its parameters, and score again with them. Nothing is
// written to config.yaml until a threshold is saved with them.
function scorePicker(r) {
  if (!cal.scores) return `<p class="hint">Movement scores could not be listed.</p>`;
  const options = cal.scores.metrics.map((m) =>
    `<option value="${esc(m.name)}" ${m.name === r.metric ? "selected" : ""}>${esc(m.name)}${m.name === cal.scores.in_use.metric ? " (config.yaml)" : ""}</option>`).join("");
  return `<div class="row score-picker">
      <label for="score-metric">Metric</label>
      <select id="score-metric">${options}</select>
      <span id="score-params" class="row"></span>
      <button type="button" id="score-apply" class="small">Score again</button>
      <button type="button" id="score-reset" class="small secondary" ${r.threshold_fits ? "hidden" : ""}>Back to config.yaml's</button>
    </div>
    <p id="score-description" class="hint"></p>
    <p id="score-status" class="hint">In use for analyses: <code>${esc(scoreText(cal.scores.in_use.metric, cal.scores.in_use.params))}</code>
      with threshold ${thr(cal.scores.in_use.threshold)}. Try another here; saving a threshold below saves the movement score with it.</p>`;
}

function wireScorePicker(r) {
  if (!cal.scores) return;
  const select = $("score-metric");
  const showParams = () => {
    const metric = cal.scores.metrics.find((m) => m.name === select.value);
    // the report's own values for its metric, else config.yaml's or the defaults
    const values = metric.name === r.metric ? r.metric_params : metric.params;
    $("score-params").innerHTML = Object.entries(metric.defaults).map(([name, fallback]) => `
      <label class="param">${esc(name)}
        <input type="number" data-param="${esc(name)}" min="${Number.isInteger(fallback) ? 1 : 0}" step="${Number.isInteger(fallback) ? 1 : "any"}"
          value="${values[name] ?? fallback}" title="default ${fallback}"></label>`).join("")
      || '<span class="hint">no parameters</span>';
    $("score-description").textContent = metric.description;
  };
  select.addEventListener("change", showParams);
  showParams();

  const status = $("score-status");
  $("score-apply").addEventListener("click", () => {
    const params = {};
    for (const input of document.querySelectorAll("#score-params [data-param]")) {
      const value = Number(input.value);
      if (!(value > 0)) {
        status.className = "hint error";
        status.textContent = `${input.dataset.param} must be a positive number.`;
        return;
      }
      params[input.dataset.param] = value;
    }
    const before = cal.metric;
    cal.metric = { name: select.value, params };
    reportAgain("score-status", () => { cal.metric = before; });
  });
  $("score-reset").addEventListener("click", () => {
    const before = cal.metric;
    cal.metric = null;
    reportAgain("score-status", () => { cal.metric = before; });
  });
}

// The thresholds to show: the one in use and, when there is one, the suggestion.
function thresholdMarks(r) {
  const marks = [{ key: "current", name: "in use", value: r.threshold, confusion: r.current, color: token("--series-1") }];
  if (r.suggested_threshold != null) {
    marks.push({ key: "suggested", name: "suggested", value: r.suggested_threshold, confusion: r.best, color: token("--series-2") });
  }
  return marks;
}

// --- key figures and the confusion matrix, shared by both tabs

// A stat tile for one kind of label, e.g. still called still, with the other call beside it.
function outcomeStat(title, c, truth, other, compare = null) {
  const total = c[`n_${truth}`];
  const right = called(c, truth, truth);
  const note = [`${right} of ${total} · ${called(c, truth, other)} called ${other}`];
  if (compare) note.push(`in use: ${called(compare, truth, truth)} of ${total}`);
  return stat(title, total ? pct(right / total) : "–", note.join(" · "));
}

function confusionTable(c) {
  const cell = (truth, call) => {
    const count = called(c, truth, call);
    const of = c[`n_${truth}`];
    return `<td class="cm" style="--f:${of ? count / of : 0}">
      <b>${count}</b><small>${of ? pct(count / of) : "–"}</small>
      <span class="cm-name">${truth} called ${call}</span></td>`;
  };
  return `<table class="confusion">
    <thead>
      <tr><th rowspan="2">Ground truth</th><th colspan="2" class="cm-group">Called by the detector</th><th rowspan="2" class="num">Total</th></tr>
      <tr><th class="cm-col">moving</th><th class="cm-col">still</th></tr>
    </thead>
    <tbody>
      <tr><td>${movingBadge(true)}</td>${cell("moving", "moving")}${cell("moving", "still")}<td class="num">${c.n_moving}</td></tr>
      <tr><td>${movingBadge(false)}</td>${cell("still", "moving")}${cell("still", "still")}<td class="num">${c.n_still}</td></tr>
    </tbody>
  </table>`;
}

const confusionCaption =
  "The ground truth against the detector's call, which is moving when that recording's score reaches the threshold. One count per mite-recording; percentages are of each row.";
const rocCaption = (r) =>
  `Every possible threshold, from the highest (bottom left) to the lowest (top right). AUC ${aucText(r)}. Hover the curve for the threshold at each step.`;
const stripCaption =
  "Each labelled mite-recording at its motion score. Everything right of a line is called moving at that threshold. Select a point to see that mite.";
const overTimeCaption = (r) =>
  `Fraction of the labelled mites moving in each recording: by the ground truth (black) and as called by the detector.${poolNote(r, r.moving_over_time.n)}`;

// Pooled datasets need not cover every recording, e.g. recordings of different
// lengths, so the fractions over time can rest on different numbers of mites.
function poolNote(r, counts = null) {
  if (!pooled(r)) return "";
  const known = (counts || []).filter((n) => n != null);
  const range = known.length && Math.min(...known) !== Math.max(...known)
    ? ` (here from ${Math.min(...known)} to ${Math.max(...known)})` : "";
  return ` <b>Pooled:</b> not every recording has the same number of mites${range}, e.g. when the datasets have recordings of different lengths,
    so later recordings may rest on fewer mites. Hover a point for its count.`;
}

// --- calibrate: pick a threshold and save it

function calibrateReport(r) {
  if (r.suggested_threshold == null) {
    return `<div class="banner">${oneClassNote(r)}</div>
      <div class="stats">
        ${stat("Called right", pct(r.current.accuracy), `threshold in use ${thr(r.threshold)}`)}
        ${outcomeStat("Moving called moving", r.current, "moving", "still")}
        ${outcomeStat("Still called still", r.current, "still", "moving")}
        ${stat("AUC", "–", "needs moving and still labels")}
      </div>
      <div class="grid-2">
        ${figure("confusion", 1, "Confusion matrix at the threshold in use", confusionCaption)}
        ${figure("chart-over-time", 2, "Mites moving: ground truth and the detector", overTimeCaption(r))}
      </div>`;
  }
  const same = Math.abs(r.suggested_threshold - r.threshold) < 0.005;
  const shown = cal.shownThreshold === "current" ? "current" : "best";
  return `
    <div class="stats">
      ${stat("Suggested threshold", thr(r.suggested_threshold), same ? "the one in use" : `in use: ${thr(r.threshold)}`)}
      ${stat("Called right", pct(r.best.accuracy), `in use: ${pct(r.current.accuracy)}`)}
      ${outcomeStat("Moving called moving", r.best, "moving", "still", r.current)}
      ${outcomeStat("Still called still", r.best, "still", "moving", r.current)}
    </div>
    <p class="caption">Key figures at the suggested threshold, per mite-recording; "in use" is the threshold in config.yaml.</p>

    <div class="grid-2">
      <figure class="fig">
        <div class="fig-title fig-title-row">Confusion matrix
          <div class="segmented" role="group" aria-label="Threshold shown">
            <button type="button" data-shown="best" class="small ${shown === "best" ? "" : "secondary"}">suggested ${thr(r.suggested_threshold)}</button>
            <button type="button" data-shown="current" class="small ${shown === "current" ? "" : "secondary"}">in use ${thr(r.threshold)}</button>
          </div>
        </div>
        <div id="confusion"></div>
        <figcaption><b>Fig. 1.</b> ${confusionCaption}</figcaption>
      </figure>
      ${section("Save the threshold", `
        <div class="row save-threshold">
          <label for="threshold-input">Movement threshold</label>
          <input id="threshold-input" type="number" step="0.01" min="0" value="${thr(r.suggested_threshold)}">
          <button type="button" id="save-threshold">Save to config.yaml</button>
        </div>
        <p id="save-status" class="hint">Saves the movement score <code>${esc(scoreText(r.metric, r.metric_params))}</code> along with the threshold.</p>
        <p class="hint">The suggestion maximises the fraction of moving labels called moving plus the fraction of still labels called still,
          and sits halfway between the two nearest scores. Every analysis started after saving uses the new value.
          Check it with the <b>Test</b> report on a <em>different</em> recording: on this one it looks better than it will be.</p>
        ${comparisonTable(r)}`)}
    </div>

    <div class="grid-2">
      ${figure("chart-over-time", 2, "Mites moving: ground truth and the detector", overTimeCaption(r))}
      ${figure("chart-roc", 3, "ROC curve", rocCaption(r))}
    </div>

    ${figure("chart-strip", 4, "Motion score distribution", stripCaption)}`;
}

function comparisonTable(r) {
  // The values as shown everywhere else, so the same threshold never rounds two ways.
  const rows = [["in use", r.threshold, r.current], ...(r.best ? [["suggested", r.suggested_threshold, r.best]] : [])];
  return `<div class="table-wrap"><table>
    <thead><tr><th>Threshold</th><th class="num">Value</th><th class="num">Called right</th>
      <th class="num">Moving called still</th><th class="num">Still called moving</th></tr></thead>
    <tbody>${rows.map(([name, value, c]) => `<tr>
      <td>${name}</td><td class="num">${thr(value)}</td><td class="num">${pct(c.accuracy)}</td>
      <td class="num">${c.moving_called_still}</td><td class="num">${c.still_called_moving}</td></tr>`).join("")}</tbody>
  </table></div>`;
}

function drawCalibrateFigures(r) {
  const marks = thresholdMarks(r);
  drawOverTime($("chart-over-time"), r.moving_over_time, r.times, marks);
  if (r.suggested_threshold == null) {
    $("confusion").innerHTML = confusionTable(r.current);
    return;
  }
  $("confusion").innerHTML = confusionTable(cal.shownThreshold === "current" ? r.current : r.best);
  document.querySelectorAll("[data-shown]").forEach((button) => button.addEventListener("click", () => {
    cal.shownThreshold = button.dataset.shown;
    document.querySelectorAll("[data-shown]").forEach((b) => b.classList.toggle("secondary", b !== button));
    $("confusion").innerHTML = confusionTable(button.dataset.shown === "current" ? r.current : r.best);
  }));
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
    // The threshold only fits the scores it was chosen on, so the movement score
    // of this report is saved with it.
    const r = cal.report;
    const saved = await post("/api/movement-score", { metric: r.metric, params: r.metric_params, threshold: value });
    if (cal.data) cal.data.threshold = saved.threshold;
    // Evaluate again, so "in use" is what was just saved.
    cal.report = await requestReport();
    cal.reportStale = false;
    cal.stamp = Date.now();
    drawReport();
    $("save-status").className = "hint";
    $("save-status").textContent = `Saved ${scoreText(saved.metric, saved.params)} with threshold ${thr(saved.threshold)} to config.yaml. Analyses started from now on use them.`;
  } catch (error) {
    status.className = "hint error";
    status.textContent = error.message;
  }
}

// --- test: how good is the threshold in use, and where does it go wrong

function testReport(r) {
  const c = r.current;
  return `
    <div class="stats">
      ${stat("Called right", pct(c.accuracy), `${c.n_wrong} wrong · threshold ${thr(r.threshold)}`)}
      ${outcomeStat("Moving called moving", c, "moving", "still")}
      ${outcomeStat("Still called still", c, "still", "moving")}
      ${stat("AUC", aucText(r), r.auc == null ? "needs moving and still labels" : "1 = perfect separation, 0.5 = chance")}
    </div>

    <div class="grid-2">
      ${figure("confusion", 1, "Confusion matrix at the threshold in use", confusionCaption)}
      ${figure("chart-over-time", 2, "Mites moving: ground truth and the detector", overTimeCaption(r))}
    </div>

    <div class="grid-2">
      <figure class="fig">
        <div class="fig-title fig-title-row">Where the errors are
          <span class="row">
          ${pooled(r) ? `<select id="map-dataset" aria-label="Recording folder">
            ${r.datasets.map((d) => `<option value="${esc(d.id)}" ${d.id === mapDataset(r) ? "selected" : ""}>${esc(d.name)}</option>`).join("")}
          </select>` : ""}
          <select id="map-recording" aria-label="Recording">
            <option value="">all recordings</option>
            ${r.times.map((time, i) => `<option value="${i}">${minutes(time)}</option>`).join("")}
          </select>
          </span>
        </div>
        <div id="outcome-map" class="plate outcome-map"></div>
        <div id="outcome-legend" class="legend map-legend"></div>
        <figcaption><b>Fig. 3.</b> Every labelled mite on the first frame. Mites called right in every selected recording are faint rings;
          a mite called wrong at least once is coloured by its more frequent error. Hover a mite for its recordings, select it to see it.
          ${pooled(r) ? "One recording folder at a time: choose it above." : ""}</figcaption>
      </figure>
      ${r.roc ? figure("chart-roc", 4, "ROC curve", rocCaption(r)) : section("ROC curve", `<p class="hint">${oneClassNote(r)}</p>`)}
    </div>

    ${r.roc ? figure("chart-strip", 5, "Motion score distribution", stripCaption) : ""}

    ${section("Per zone", `<div class="table-wrap"><table class="clickable" id="zone-errors"></table></div>
      <p class="caption">Counts are mite-recordings, at the threshold in use. Select a zone to review its labels.</p>`)}`;
}

function drawTestFigures(r) {
  const marks = thresholdMarks(r).slice(0, 1);
  $("confusion").innerHTML = confusionTable(r.current);
  drawOverTime($("chart-over-time"), r.moving_over_time, r.times, marks);
  const drawMap = () => {
    if ($("map-dataset")) cal.mapDataset = $("map-dataset").value;
    drawOutcomeMap(r, mapDataset(r), $("map-recording").value);
  };
  $("map-recording").addEventListener("change", drawMap);
  $("map-dataset")?.addEventListener("change", drawMap);
  drawMap();
  if (r.roc) {
    drawRoc($("chart-roc"), r, marks);
    drawStrip($("chart-strip"), r, marks);
  }
  drawZoneErrors(r);
}

// --- charts shared by both tabs

// The ground truth (black) against the detector's calls, one line per threshold.
// The labels' line comes last so it is drawn on top where the lines coincide.
function overTimeSeries(curves, marks, { legend = true } = {}) {
  const asPercent = (values) => values.map((v) => (v == null ? null : v * 100));
  return [
    ...marks.map((mark) => ({
      name: `detector, ${mark.name} ${thr(mark.value)}`,
      values: asPercent(curves[mark.key]),
      color: mark.color, dashed: true, legend,
    })),
    { name: "ground truth", values: asPercent(curves.truth), color: token("--ink"), width: 2.25, legend },
  ];
}

function drawOverTime(container, curves, times, marks) {
  Charts.line(container, {
    x: times,
    yLabel: "Mites moving (%)",
    yMin: 0, yMax: 100,
    yFormat: (v) => `${Math.round(v)}`,
    noDirectLabels: true,
    series: overTimeSeries(curves, marks),
    tooltipExtra: (i) => `<div class="tip-note">${curves.n[i]} mites labelled</div>`,
  });
}

// Small multiples: one chart per group, sharing one legend.
function drawGroupMoving(r, marks) {
  $("group-legend").innerHTML = Charts.legendHtml(overTimeSeries(r.moving_over_time, marks).map((s) => ({
    name: s.name, color: s.color, ...(s.dashed ? { dashed: true } : { shape: "line" }),
  })));
  const container = $("group-moving");
  r.groups.forEach((group, index) => {
    const card = document.createElement("div");
    card.className = "group-card fig";
    const id = `group-moving-${index}`;
    card.innerHTML = `<div class="group-card-head">${groupTag(group.group, token(group.group === "unlabeled" ? "--series-other" : "--muted"))}
      <span class="hint">${group.n_mites} mite${group.n_mites === 1 ? "" : "s"}</span>
      ${downloadButtons(id, `Mites moving · ${group.group} (${group.n_mites} mites)`, "group-legend")}</div>`;
    const plot = document.createElement("div");
    plot.id = id;
    card.appendChild(plot);
    container.appendChild(card);
    Charts.line(plot, {
      x: r.times,
      height: 190,
      yLabel: "Moving (%)",
      yMin: 0, yMax: 100,
      yFormat: (v) => `${Math.round(v)}`,
      series: overTimeSeries(group, marks, { legend: false }),
      tooltipExtra: (i) => `<div class="tip-note">${group.n[i]} mites labelled</div>`,
    });
  });
}

// Moving labels in one row, still in the other, jittered so equal scores stay visible.
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
      y: (row.movement === "moving" ? 1 : 0) + jitter(`${row.dataset}/${row.mite_id}/${row.recording}`),
      color: token(row.movement === "moving" ? "--moving" : "--still"),
      shape: row.movement === "moving" ? "circle" : "cross",
      r: 3.5,
      tip: observationTip(row, r),
      onClick: openObservation(row),
    })),
    refX: marks.map((mark) => ({ value: mark.value, label: `${mark.name} ${thr(mark.value)}` })),
    yCategories: [{ value: 0, label: "○ still" }, { value: 1, label: "● moving" }],
    yMin: -0.5, yMax: 1.5,
    xMin: 0,
    xLabel: "Motion score in that recording",
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
    xLabel: "Still called moving (false positive rate)",
    yLabel: "Moving called moving",
    lines: [
      { points: [[0, 0], [1, 1]], color: token("--muted"), width: 1, dashed: true },
      { points: fpr.map((f, i) => [f, tpr[i]]), color: token("--ink"), width: 2 },
    ],
    points: [
      // Every step of the curve can be hovered for its threshold.
      ...fpr.slice(1).map((f, i) => ({
        x: f, y: tpr[i + 1], r: 3, hidden: true,
        tip: `<div class="tip-title">threshold ${thr(thresholds[i + 1])}</div>
          <div>${percentFormat(tpr[i + 1])} of moving labels called moving</div>
          <div>${percentFormat(f)} of still labels called moving</div>`,
      })),
      ...marks.map((mark, i) => {
        const c = mark.confusion;
        const f = c.still_called_moving / c.n_still;
        return {
          // the second label goes under its point, so close thresholds stay readable
          x: f, y: c.sensitivity, r: 6, color: mark.color, label: `${mark.name} ${thr(mark.value)}`, labelDy: i ? 16 : 0,
          tip: `<div class="tip-title">${mark.name}: ${thr(mark.value)}</div>
            <div>${percentFormat(c.sensitivity)} of moving labels called moving</div>
            <div>${percentFormat(f)} of still labels called moving</div>`,
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

// The dataset the error map shows: the last one chosen, else the one on the
// ground-truth page, else the first in the report.
function mapDataset(r) {
  const ids = r.datasets.map((d) => d.id);
  return [cal.mapDataset, cal.datasetId].find((id) => ids.includes(id)) || ids[0];
}

function drawOutcomeMap(r, datasetId, recordingValue) {
  const container = $("outcome-map");
  const dataset = r.datasets.find((d) => d.id === datasetId);
  const here = r.observations.filter((row) => row.dataset === datasetId);
  const rows = recordingValue === "" ? here : here.filter((row) => row.recording === Number(recordingValue));
  const preview = `/api/calibration/datasets/${encodeURIComponent(datasetId)}/preview?t=${cal.stamp}`;
  const place = plateOverlay(container, preview, dataset.image);
  dataset.zones.forEach((zone) => {
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
  const counts = { correct: 0, "missed-positive": 0, "missed-negative": 0 };
  byMite.forEach((miteRows) => {
    const first = miteRows[0];
    const movingMissed = miteRows.filter((row) => row.outcome === "moving_called_still");
    const stillMissed = miteRows.filter((row) => row.outcome === "still_called_moving");
    const kind = !movingMissed.length && !stillMissed.length ? "correct"
      : movingMissed.length >= stillMissed.length ? "missed-positive" : "missed-negative";
    counts[kind] += 1;

    const dot = document.createElement("span");
    dot.className = `outcome-dot ${kind}`;
    dot.style.left = percent(first.x, dataset.image.width);
    dot.style.top = percent(first.y, dataset.image.height);
    const list = (errors) => errors.map((row) => `${minutes(row.time)}${row.recording_name ? ` (${esc(row.recording_name)})` : ""}`).join(", ");
    dot.addEventListener("mousemove", (event) => Charts.showTooltip(event,
      `<div class="tip-title">Mite ${esc(first.mite_id)} · zone ${first.zone_id}</div>
       <div class="tip-note">${esc(first.dataset_name)}</div>
       <div>${movingMissed.length + stillMissed.length} of ${miteRows.length} recordings called wrong</div>
       ${movingMissed.length ? `<div class="tip-note">moving called still: ${list(movingMissed)}</div>` : ""}
       ${stillMissed.length ? `<div class="tip-note">still called moving: ${list(stillMissed)}</div>` : ""}
       <div class="tip-hint">Click to see it in its recording</div>`));
    dot.addEventListener("mouseleave", Charts.hideTooltip);
    dot.addEventListener("click", openObservation([...movingMissed, ...stillMissed][0] || first));
    container.appendChild(dot);
  });

  $("outcome-legend").innerHTML = Charts.legendHtml([
    { name: `always right (${counts.correct})`, color: token("--muted"), shape: "ring" },
    { name: `moving called still (${counts["missed-positive"]})`, color: token("--series-2"), shape: "circle" },
    { name: `still called moving (${counts["missed-negative"]})`, color: token("--series-7"), shape: "square" },
  ]);
}

// Every zone of every pooled dataset, each opening its own recording folder.
function drawZoneErrors(r) {
  const table = $("zone-errors");
  const wrong = (n) => `<td class="num${n ? " error" : ""}">${n}</td>`;
  const folders = new Map(r.datasets.map((d) => [d.id, d.data_dir]));
  table.innerHTML = `
    <thead><tr><th>Recording folder</th><th>Zone</th><th>Label</th><th class="num">Mites</th>
      <th class="num">Moving</th><th class="num">Still</th>
      <th class="num">Moving called still</th><th class="num">Still called moving</th></tr></thead>
    <tbody>${r.zones.map((zone, index) => `
      <tr data-index="${index}" tabindex="0">
        <td title="${esc(folders.get(zone.dataset))}">${esc(zone.dataset_name)}</td>
        <td><a href="#" data-index="${index}">Zone ${zone.id}</a></td>
        <td>${zone.group === "unlabeled" ? "" : esc(zone.group)}</td>
        <td class="num">${zone.n_mites}</td>
        <td class="num">${zone.n_moving}</td><td class="num">${zone.n_still}</td>
        ${wrong(zone.moving_called_still)}${wrong(zone.still_called_moving)}
      </tr>`).join("")}</tbody>`;
  const open = (event, index) => {
    event.preventDefault();
    const zone = r.zones[index];
    goToMite(zone.dataset, zone.id, 0);
  };
  table.querySelectorAll("tr[data-index]").forEach((row) => {
    row.addEventListener("click", (event) => open(event, Number(row.dataset.index)));
    row.addEventListener("keydown", (event) => { if (event.key === "Enter") open(event, Number(row.dataset.index)); });
  });
}

// app.js and this file are both loaded: start.
route();
