// The recordings kept in recordings/: every live test run and every folder dropped
// into the page. They are listed on the first page of each mode (Live, Analysis,
// Calibration) with when and how they were recorded, to analyse or calibrate on again.
//
// Loads after app.js and reuses its helpers ($, esc, shorten); opening one goes
// through openFolder() (app.js) or openCalibration() (calibration.js).

const kept = { recordings: null, root: "", resultsRoot: "", loading: null };

const keptDate = (iso) => new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
const keptTime = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

async function refreshRecordings() {
  // Several pages may ask at once; one request answers them all.
  if (!kept.loading) {
    kept.loading = (async () => {
      const response = await fetch("/api/recordings", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not list the recordings");
      Object.assign(kept, { recordings: data.recordings, root: data.root, resultsRoot: data.results_root });
    })().finally(() => { kept.loading = null; });
  }
  let failed = null;
  try {
    await kept.loading;
  } catch (error) {
    failed = error;
  }
  document.querySelectorAll("[data-recordings]").forEach((block) => drawRecordings(block, failed));
}

function drawRecordings(block, failed) {
  const list = kept.recordings || [];
  block.innerHTML = `
    <h2>Previous recordings <span class="hint">${list.length ? plural(list.length, "recording") : ""}</span></h2>
    <p class="hint">Every test run recorded here, and every folder dropped into the page, is kept in
      <code title="${esc(kept.root)}">recordings/</code>. Analyse one again or calibrate on it;
      its results go to <code title="${esc(kept.resultsRoot)}">results/&lt;name&gt;/</code>.</p>
    ${failed ? `<p class="hint error">${esc(failed.message)}</p>`
      : !list.length ? `<p class="muted">Nothing recorded yet. A test run appears here once its first recording is saved.</p>`
        : `<div class="table-wrap"><table class="recordings">
            <thead><tr><th>Recording</th><th>Recorded</th><th class="num">Recordings</th><th>Settings</th>
              <th>Plates</th><th>Results</th><th></th></tr></thead>
            <tbody>${list.map(recordingRow).join("")}</tbody>
          </table></div>`}`;
}

function recordingRow(r) {
  const busy = r.recording_now ? ` disabled title="Being recorded: open it once the test run is over."` : "";
  return `<tr>
    <td class="name" title="${esc(r.path)}"><span class="rec-name">${esc(r.name)}</span>${stateBadge(r)}${howRecorded(r)}</td>
    <td class="nowrap">${recordedText(r)}</td>
    <td class="num">${recordingCount(r)}</td>
    <td class="settings">${settingsText(r)}</td>
    <td class="plates">${platesText(r)}</td>
    <td class="nowrap">${resultsText(r)}</td>
    <td class="row-actions">
      <button type="button" class="secondary small" data-open-recording="analysis" data-path="${esc(r.path)}"${busy}>Analyse</button>
      <button type="button" class="secondary small" data-open-recording="cal" data-path="${esc(r.path)}"${busy}>Calibrate</button>
    </td>
  </tr>`;
}

// Whether a live run is still being recorded, or ended before it was through.
function stateBadge(r) {
  const run = r.run;
  if (r.recording_now) return ` <span class="rec-state now">recording now</span>`;
  if (!run) return "";
  if (!run.ended_at) return ` <span class="rec-state cut" title="The app stopped while the test run was going on.">interrupted</span>`;
  if (run.recordings_analysed < run.recordings_planned) {
    return ` <span class="rec-state cut" title="Stopped after ${run.recordings_analysed} of ${run.recordings_planned} recordings.">stopped</span>`;
  }
  return "";
}

// For a live run: the camera (or the folder replayed), the pools, and what went wrong.
function howRecorded(r) {
  const run = r.run;
  if (!run) return "";
  const parts = [esc(run.camera), `pools of ${esc(run.pool_size_text)}`];
  if (run.frames_dropped) parts.push(`<span class="error">${plural(run.frames_dropped, "frame")} dropped</span>`);
  if (run.frames_incomplete) parts.push(`${run.frames_incomplete} incomplete`);
  const error = run.error ? `<span class="sub error">${esc(run.error)}</span>` : "";
  return `<span class="sub">${parts.join(" · ")}</span>${error}`;
}

function recordedText(r) {
  const seconds = (new Date(r.ended) - new Date(r.started)) / 1000;
  const sameDay = r.started.slice(0, 10) === r.ended.slice(0, 10);
  const span = sameDay ? `${keptTime(r.started)}–${keptTime(r.ended)}` : `${keptTime(r.started)} – ${keptDate(r.ended)} ${keptTime(r.ended)}`;
  return `${keptDate(r.started)}<span class="sub">${span} · ${duration(seconds)}</span>`;
}

// "6", or "4 of 6" when fewer were recorded than planned.
function recordingCount(r) {
  const planned = r.run ? r.run.recordings_planned : r.settings && r.settings.recording_count;
  return planned && planned !== r.n_recordings ? `${r.n_recordings} <span class="muted">of ${planned}</span>` : `${r.n_recordings}`;
}

// The Discobox settings it was recorded with: each recording, the time between
// them, and the fan and LEDs, as the Discobox app's settings window has them.
function settingsText(r) {
  const burst = `${plural(r.frames, "frame")} at ${r.fps} fps (${+(r.frames / r.fps).toFixed(1)} s)`;
  const s = r.settings;
  if (!s) return `${burst}<span class="sub">no settings saved with it</span>`;
  const every = s.recording_timeout != null ? `, every ${s.recording_timeout} min` : "";
  return `${burst}${every}<span class="sub">${lightsText(s)}</span>`;
}

// "Fan and LEDs 20 s, intensity 255" when all three are alike; each on its own otherwise.
function lightsText(s) {
  const devices = [["vent_time", "vent", "Fan"], ["led1_time", "led1", "LED 1"], ["led2_time", "led2", "LED 2"]]
    .filter(([time]) => s[time] != null);
  const on = devices.filter(([time]) => s[time]);
  const levels = new Set(on.map(([, level]) => s[level]));
  const oneLevel = levels.size === 1 && !levels.has(undefined) ? `, intensity ${[...levels][0]}` : "";
  if (devices.length === 3 && on.length === 3 && new Set(on.map(([time]) => s[time])).size === 1 && oneLevel) {
    return `Fan and LEDs ${s.vent_time} s${oneLevel}`;
  }
  const each = devices.map(([time, level, name]) => (!s[time] ? `${name} off`
    : `${name} ${s[time]} s${oneLevel || s[level] == null ? "" : ` at ${s[level]}`}`));
  return `${each.join(" · ")}${oneLevel}`;
}

// The plate labels, the "not a mite" marks and the ground truth kept with it.
function platesText(r) {
  const main = r.n_labelled_plates ? `${plural(r.n_labelled_plates, "plate")} labelled` : `<span class="muted">not labelled</span>`;
  const sub = [];
  if (r.groups.length) {
    const groups = r.groups.join(", ");
    sub.push(`<span title="${esc(groups)}">${esc(shorten(groups, 40))}</span>`);
  }
  if (r.n_not_a_mite) sub.push(`${r.n_not_a_mite} not a mite`);
  if (r.n_ground_truth) sub.push(`ground truth for ${plural(r.n_ground_truth, "mite")}`);
  return `${main}${sub.length ? `<span class="sub">${sub.join(" · ")}</span>` : ""}`;
}

function resultsText(r) {
  if (!r.results) return `<span class="muted">not analysed</span>`;
  const url = `/api/recordings/${encodeURIComponent(r.name)}/results/${encodeURIComponent(r.results.file)}`;
  return `<a href="${url}" download>${esc(r.results.file)}</a><span class="sub">${keptDate(r.results.saved_at)} ${keptTime(r.results.saved_at)}</span>`;
}

// Analyse or calibrate on a recording from any mode's list: that mode's first
// page shows at once, with the opening under way, and moves on once it is open.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-open-recording]");
  if (!button) return;
  const path = button.dataset.path;
  if (button.dataset.openRecording === "cal") {
    if (location.hash !== "#/cal/open") location.hash = "#/cal/open";
    openCalibration(path);
  } else {
    if (location.hash !== "#/open") location.hash = "#/open";
    openFolder(path);
  }
  window.scrollTo(0, 0);
});
