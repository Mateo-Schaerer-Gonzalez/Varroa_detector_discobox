// Live from the Discobox, in the same window as the analysis:
//   #/live/open      the camera (or a replay), the test run's settings, the fan and LEDs
//   #/live/label     app.js's label page; its button starts the test run
//   #/live/results   app.js's result pages -- the very ones a folder gets -- under a
//                    small panel with how the run is going, filling in as it goes
//
// Talks to /api/live/... . The page asks for the run's status about twice a second
// and fetches the results only when they changed (after each recording), so
// drawing never holds up the camera: capture runs on the server, on its own threads.

const LIVE_POLL_MS = 500;
const LIVE_STATES = ["running", "paused", "stopping"];

const live = {
  id: null,          // the live run's session id
  status: null,      // what /status said last
  options: null,     // cameras, serial ports, saved settings and their ranges
  version: 0,        // version of the results shown
  follow: true,      // show each new recording as it comes in
  polling: false,
  feedBusy: false,
  settingsTimer: null,
};

const liveStarted = () => Boolean(live.status && live.status.state !== "ready");
const liveRunning = () => Boolean(live.status && LIVE_STATES.includes(live.status.state));
const onLiveResults = () => shownMode === "live" && /^#\/live\/(results|zone|mite)/.test(location.hash);
const clock = (seconds) => new Date(seconds * 1000).toLocaleTimeString();

async function liveRequest(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Request failed");
  return data;
}

// --- routing -------------------------------------------------------------------------

function routeLive(sub = "open") {
  const wanted = { open: "open", label: "label", results: "results", zone: "results", mite: "results" }[sub] || "open";
  let step = wanted;
  if (step === "results" && !liveStarted()) step = session ? "label" : "open";
  if (step === "label" && !session) step = "open";
  if (step !== wanted) { location.replace(`#/live/${step}`); return; }

  drawLiveSteps(step);
  Charts.hideTooltip();
  $("live-panel").hidden = step !== "results";
  if (step === "open") { showView("live-open"); drawLiveOpen(); }
  if (step === "label") { showView("label"); drawLabelView(); }
  if (step === "results") {
    showView("results");
    drawLiveStatus();
    if (results) drawResults();
    else drawLiveWaiting();
  }
  window.scrollTo(0, 0);
}

function drawLiveSteps(step = null) {
  document.querySelectorAll("#steps-live a[data-step]").forEach((link) => {
    if (step) link.classList.toggle("active", link.dataset.step === step);
    const liveSession = loadedContext === "live" ? session : contexts.live.session;
    const available = link.dataset.step === "open" || (link.dataset.step === "label" && liveSession)
      || (link.dataset.step === "results" && liveStarted());
    link.classList.toggle("disabled", !available);
  });
}

// Before the first recording is analysed, the result pages have nothing to show.
function drawLiveWaiting() {
  $("breadcrumb").hidden = true;
  const s = live.status || {};
  const next = s.next_recording ? `The first recording starts at ${clock(s.next_recording)}; its results` : "The results of the first recording";
  $("results-body").innerHTML = `
    <header class="page-head"><div><h1>Results</h1>
      <p class="meta">${esc(s.run_name || "")}</p></div></header>
    <p class="live-waiting">${s.state === "finished"
      ? "The test run ended before a recording was analysed, so there are no results."
      : `${next} appear here as soon as it is analysed, and the pages fill in with every recording after it.`}</p>`;
}

// --- 1 · camera, settings, fan and LEDs ----------------------------------------------

const liveSource = () => document.querySelector("input[name=live-source]:checked").value;

async function drawLiveOpen() {
  if (!live.options) {
    $("live-open-status").innerHTML = `<span class="spinner"></span> Looking for cameras…`;
    try {
      live.options = await (await fetch("/api/live/options", { cache: "no-store" })).json();
    } catch (error) {
      $("live-open-status").className = "hint error";
      $("live-open-status").textContent = `Could not ask the server: ${error.message}`;
      return;
    }
    $("live-open-status").textContent = "";
    fillLiveForm();
    const open = live.options.open.find((run) => run.state !== "finished") || live.options.open[0];
    if (open && !live.id) { await attachLive(open.live_id); return; }
  }
  drawLiveForm();
}

function fillLiveForm() {
  const { cameras, camera_error: cameraError, serial_ports: ports, run_name: runName } = live.options;
  $("live-camera").innerHTML = cameras.length
    ? cameras.map((cam) => `<option value="${esc(cam.id)}">${esc(cam.model)} ${esc(cam.id)}</option>`).join("")
    : `<option value="">No camera found</option>`;
  $("live-serial").innerHTML = [
    `<option value="auto">Automatic: the Discobox's Arduino</option>`,
    ...ports.map((port) => `<option value="${esc(port.device)}">${esc(port.device)} · ${esc(port.description)}</option>`),
    `<option value="none">None: run without the fan and LEDs</option>`,
  ].join("");
  $("live-run-name").value = runName;
  if (!cameras.length) {
    document.querySelector("input[name=live-source][value=replay]").checked = true;
    $("live-open-status").className = "hint";
    $("live-open-status").textContent = cameraError || "No camera is connected; you can replay a recorded folder instead.";
  }
  drawLiveSettings();
}

function drawLiveSettings() {
  const { settings, ranges } = live.options;
  const fields = ["recording_count", "recording_timeout", "vent_time", "led1_time", "led2_time", "frame_count", "fps"];
  $("live-settings").innerHTML = fields.map((name) => {
    const { label, unit, min, max } = ranges[name];
    return `<label for="live-set-${name}">${esc(label)}${unit ? ` <span class="muted">(${unit})</span>` : ""}</label>
      <input id="live-set-${name}" data-setting="${name}" type="number" min="${min}" max="${max}" step="1"
        value="${settings[name]}" class="number-input" title="${min} to ${max}">`;
  }).join("");
  $("live-lights").innerHTML = [["vent", "Fan"], ["led1", "LED 1"], ["led2", "LED 2"]].map(([device, name]) => `
    <div class="light-row">
      <label for="live-set-${device}">${name}</label>
      <input id="live-set-${device}" data-setting="${device}" data-device="${device}" type="range" min="0" max="255" value="${settings[device]}">
      <output id="live-level-${device}">${settings[device]}</output>
      <button type="button" class="secondary small light-toggle" data-light="${device}" aria-pressed="false">Off</button>
    </div>`).join("");
  drawRecordingTime();
}

function drawRecordingTime() {
  const s = live.options.settings;
  const burst = s.frame_count / s.fps;
  const cycle = Math.max(s.vent_time, s.led1_time, s.led2_time, burst) + 1;
  $("live-recording-time").textContent = `Each recording: ${+burst.toFixed(2)} s of frames; with the fan and LEDs, ${+cycle.toFixed(1)} s `
    + `of every ${s.recording_timeout} min. The whole run: about ${+(s.recording_count * s.recording_timeout).toFixed(0)} min.`;
}

// What can be changed now: the source before connecting, the settings until the run starts.
function drawLiveForm() {
  const connected = Boolean(live.id);
  const replay = liveSource() === "replay";
  const ready = !liveStarted();
  $("live-camera-fields").hidden = replay;
  $("live-replay-fields").hidden = !replay;
  $("live-settings-block").hidden = replay;
  document.querySelectorAll(".live-form input, .live-form select").forEach((input) => { input.disabled = connected; });
  $("live-connect-btn").hidden = connected;
  $("live-close-btn").hidden = !connected;
  $("live-close-btn").disabled = liveRunning();
  document.querySelectorAll("[data-setting]").forEach((input) => { input.disabled = !ready; });
  const lights = live.status && live.status.lights;
  document.querySelectorAll("[data-light]").forEach((button) => {
    const state = lights && lights[button.dataset.light];
    button.disabled = !connected || !ready || !lights;
    button.classList.toggle("on", Boolean(state && state.on));
    button.textContent = state && state.on ? "On" : "Off";
    button.setAttribute("aria-pressed", String(Boolean(state && state.on)));
  });
  $("live-label-btn").disabled = !connected;
  $("live-label-btn").textContent = liveStarted() ? "Show the live results" : "Next: label the plates";
  $("live-feed-note").textContent = connected ? "" : "Connect to see the camera.";
  $("live-feed").hidden = !connected || !$("live-feed").src;
  if (connected && lights && !lights.connected && !$("live-settings-status").textContent) {
    $("live-settings-status").className = "hint";
    $("live-settings-status").textContent = "No fan/LED controller found: the run goes ahead without them.";
  }
}

document.querySelectorAll("input[name=live-source]").forEach((radio) => radio.addEventListener("change", drawLiveForm));

async function connectLive() {
  const status = $("live-open-status");
  status.className = "hint";
  status.innerHTML = `<span class="spinner"></span> Connecting…`;
  const poolSize = $("live-pool-size").value.trim();
  const body = {
    source: liveSource(),
    run_name: $("live-run-name").value.trim(),
    save_frames: $("live-save").checked,
    pool_size: poolSize ? Number(poolSize) : null,
    camera_id: $("live-camera").value || null,
    serial_port: $("live-serial").value,
    replay_dir: $("live-replay-dir").value.trim(),
    replay_gap: Number($("live-replay-gap").value || 0),
  };
  try {
    const opened = await liveRequest("/api/live", body);
    startLive(opened.session_id, opened);
    status.textContent = `Connected: ${opened.camera}. Recordings go to ${opened.save_frames ? opened.run_dir : "nowhere: they are not saved"}.`;
  } catch (error) {
    status.className = "hint error";
    status.textContent = error.message;
  }
}

function startLive(id, status) {
  Object.assign(live, { id, status, version: 0, follow: true, feedBusy: false });
  setContext("live", { sessionId: id, session: null, results: null, runStamp: 0, shown: 0, labelsChanged: false });
  setFolder("live", status.run_name, status.run_dir);
  $("live-feed").removeAttribute("src");
  $("live-thumb").removeAttribute("src");
  drawLiveForm();
  drawLiveSteps();
  pollLive();
}

// A run left open by a page that was closed or reloaded.
async function attachLive(id) {
  try {
    const status = await liveRequest(`/api/live/${id}/attach`);
    startLive(id, status);
    if (status.state !== "ready") await loadLivePreview();
    await fetchLiveResults();
    $("live-open-status").className = "hint";
    $("live-open-status").textContent = `Reconnected to the test run ${status.run_name}.`;
    if (liveStarted()) go("#/live/results");
  } catch (error) {
    $("live-open-status").className = "hint error";
    $("live-open-status").textContent = error.message;
  }
}

async function closeLive() {
  if (!live.id) return;
  const id = live.id;
  try {
    await liveRequest(`/api/live/${id}/close`);
  } catch { /* already gone */ }
  Object.assign(live, { id: null, status: null, version: 0 });
  setContext("live", { sessionId: null, session: null, results: null, runStamp: 0, shown: 0, labelsChanged: false });
  setFolder("live", "");
  live.options = null;  // the run name is free again, a camera may have come or gone
  $("live-feed").removeAttribute("src");
  $("live-open-status").textContent = "";
  if (shownMode === "live") location.hash === "#/live/open" ? drawLiveOpen() : go("#/live/open");
}

$("live-connect-btn").addEventListener("click", connectLive);
$("live-close-btn").addEventListener("click", closeLive);

// Settings are saved as they change, like the Discobox settings window does.
document.addEventListener("input", (event) => {
  const input = event.target.closest("[data-setting]");
  if (!input) return;
  if (input.dataset.device) $(`live-level-${input.dataset.device}`).textContent = input.value;
  clearTimeout(live.settingsTimer);
  live.settingsTimer = setTimeout(() => saveLiveSetting(input), input.type === "range" ? 150 : 500);
});

async function saveLiveSetting(input) {
  const name = input.dataset.setting;
  const value = Number(input.value);
  const status = $("live-settings-status");
  try {
    const saved = await liveRequest("/api/live/settings", { settings: { [name]: value }, session_id: live.id });
    live.options.settings = saved.settings;
    status.className = "hint";
    status.textContent = "Saved to settings.txt.";
    drawRecordingTime();
    // A device switched on to check it follows its slider at once.
    const device = input.dataset.device;
    if (device && live.id && live.status.lights && live.status.lights[device].on) {
      await liveRequest(`/api/live/${live.id}/light`, { device, level: value });
    }
  } catch (error) {
    status.className = "hint error";
    status.textContent = error.message;
  }
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-light]");
  if (!button || !live.id) return;
  const device = button.dataset.light;
  const on = button.getAttribute("aria-pressed") !== "true";
  try {
    const { lights } = await liveRequest(`/api/live/${live.id}/light`, { device, on, level: Number($(`live-set-${device}`).value) });
    live.status.lights = lights;
    drawLiveForm();
  } catch (error) {
    $("live-settings-status").className = "hint error";
    $("live-settings-status").textContent = error.message;
  }
});

// --- 2 · labelling, and the start of the run -------------------------------------------

async function loadLivePreview() {
  const preview = await liveRequest(`/api/live/${live.id}/preview`);
  preview.zones.forEach((zone) => { zone.label = zone.label || ""; });
  setContext("live", { session: preview, sessionId: live.id });
  if (loadedContext === "live") {
    showLoadedStatus();
    if (location.hash.startsWith("#/live/label")) drawLabelView();
  }
  drawLiveSteps();
}

$("live-label-btn").addEventListener("click", async () => {
  if (liveStarted()) { go("#/live/results"); return; }
  const status = $("live-open-status");
  status.className = "hint";
  status.innerHTML = `<span class="spinner"></span> Finding the mites on the newest frame…`;
  try {
    await loadLivePreview();
    status.textContent = "";
    go("#/live/label");
  } catch (error) {
    status.className = "hint error";
    status.textContent = error.message;
  }
});

function drawLiveRunButton() {
  $("run-btn").textContent = liveStarted() ? "Show the live results" : "Start test run";
  $("run-btn").disabled = !live.id;
}

async function startLiveRun() {
  if (liveStarted()) { go("#/live/results"); return; }
  const status = $("run-status");
  $("run-btn").disabled = true;
  status.className = "hint";
  status.innerHTML = `<span class="spinner"></span> Starting the test run…`;
  try {
    live.status = await liveRequest(`/api/live/${live.id}/start`, { labels: collectLabels() });
    status.textContent = "The test run is going; the labels can still change and the results follow them.";
    go("#/live/results");
  } catch (error) {
    status.className = "hint error";
    status.textContent = error.message;
  } finally {
    drawLiveRunButton();
  }
}

// --- 3 · the status panel over the result pages -----------------------------------------

$("live-panel").innerHTML = `
  <div class="live-thumb-wrap"><img id="live-thumb" alt="The camera's newest frame" hidden></div>
  <div class="live-facts">
    <div class="live-title"><span id="live-state" class="live-state"></span><span id="live-run"></span></div>
    <div id="live-progress"></div>
    <div id="live-acquisition"></div>
    <div id="live-devices"></div>
    <div id="live-saving"></div>
    <div id="live-error" class="error"></div>
  </div>
  <div class="live-actions">
    <label class="live-check"><input id="live-follow" type="checkbox" checked> Follow the latest recording</label>
    <div class="row">
      <button id="live-pause-btn" type="button" class="secondary small">Pause</button>
      <button id="live-stop-btn" type="button" class="small">Stop test run</button>
      <button id="live-new-btn" type="button" class="secondary small" hidden>New test run</button>
    </div>
  </div>`;

const STATE_NAMES = { ready: "Connected", running: "Recording", paused: "Paused", stopping: "Stopping", finished: "Finished" };

function drawLiveStatus() {
  const s = live.status;
  if (!s) return;
  if (shownMode === "live" && location.hash.startsWith("#/live/open")) drawLiveForm();
  if (!onLiveResults()) return;
  $("live-panel").hidden = false;
  $("live-state").textContent = STATE_NAMES[s.state] || s.state;
  $("live-state").className = `live-state ${s.state}`;
  $("live-run").textContent = ` ${s.run_name} · ${s.camera} · pools of ${s.pool_size_text}`;

  const parts = [`Recording ${s.recording} of ${s.recordings}`];
  if (s.recording_name) parts.push(`capturing frame ${s.frame}${s.frames ? ` of ${s.frames}` : ""}`);
  parts.push(`${s.analysed} analysed`);
  if (s.next_recording && s.state !== "finished") parts.push(`next recording at ${clock(s.next_recording)}`);
  if (s.state === "paused") parts.push("paused until you resume: the next recording waits");
  $("live-progress").textContent = parts.join(" · ");

  $("live-acquisition").textContent = (s.state === "finished" ? "Acquisition ended" : `Acquisition ${s.fps.toFixed(1)} fps${s.fps_set ? ` (set to ${s.fps_set})` : ""}`)
    + ` · ${s.dropped} frame${s.dropped === 1 ? "" : "s"} dropped · ${s.incomplete} incomplete`;
  $("live-acquisition").classList.toggle("error", s.dropped > 0);

  const lights = s.lights;
  $("live-devices").textContent = !lights ? "A replay: no fan or LEDs."
    : !lights.connected ? "No fan/LED controller: the run goes on without them."
      : [["vent", "Fan"], ["led1", "LED 1"], ["led2", "LED 2"]]
        .map(([device, name]) => `${name} ${lights[device].on ? "on" : "off"}`).join(" · ");

  $("live-saving").textContent = s.saving || s.save_frames
    ? `${s.saved_frames} frames saved to ${s.run_dir}` : "Recordings are not saved.";
  $("live-error").textContent = [s.error, s.save_error].filter(Boolean).join(" · ");

  const finished = s.state === "finished";
  $("live-pause-btn").hidden = finished;
  $("live-pause-btn").textContent = s.state === "paused" ? "Resume" : "Pause";
  $("live-pause-btn").disabled = !["running", "paused"].includes(s.state);
  $("live-stop-btn").hidden = finished;
  $("live-stop-btn").disabled = s.state === "stopping";
  $("live-new-btn").hidden = !finished;
  $("live-follow").checked = live.follow;
}

function liveFollow(on) {
  live.follow = on;
  $("live-follow").checked = on;
}

$("live-follow").addEventListener("change", (event) => {
  live.follow = event.target.checked;
  if (live.follow && results && shown !== results.times.length - 1) {
    shown = results.times.length - 1;
    if (onLiveResults()) drawResults();
  }
});

$("live-pause-btn").addEventListener("click", async () => {
  const action = live.status.state === "paused" ? "resume" : "pause";
  try {
    live.status = await liveRequest(`/api/live/${live.id}/${action}`);
    drawLiveStatus();
  } catch (error) { $("live-error").textContent = error.message; }
});

$("live-stop-btn").addEventListener("click", async () => {
  if (!confirm("Stop the test run? The recording being captured ends with the frames already in; it is analysed and the results are written.")) return;
  try {
    live.status = await liveRequest(`/api/live/${live.id}/stop`);
    drawLiveStatus();
  } catch (error) { $("live-error").textContent = error.message; }
});

$("live-new-btn").addEventListener("click", closeLive);

// --- polling -------------------------------------------------------------------------------

async function pollLive() {
  if (!live.id || live.polling) return;
  live.polling = true;
  const id = live.id;
  try {
    const response = await fetch(`/api/live/${id}/status`, { cache: "no-store" });
    if (id !== live.id) return;
    if (!response.ok) return;
    live.status = await response.json();
    if (live.status.version !== live.version) await fetchLiveResults();
    drawLiveStatus();
    drawLiveSteps();
    refreshFeed();
  } catch {
    // the server is busy or restarting: try again at the next tick
  } finally {
    live.polling = false;
  }
}

setInterval(pollLive, LIVE_POLL_MS);

// The results changed: show them, on whatever result page is open, without
// moving the page. With "follow" on, the page moves on to the newest recording.
async function fetchLiveResults() {
  const id = live.id;
  const data = await (await fetch(`/api/live/${id}/results`, { cache: "no-store" })).json();
  if (id !== live.id) return;
  live.version = data.version;
  if (!data.results) return;
  const before = loadedContext === "live" ? { results, shown } : contexts.live;
  const latest = data.results.times.length - 1;
  const next = live.follow || !before.results ? latest : Math.min(before.shown, latest);
  setContext("live", { results: data.results, runStamp: Date.now(), shown: next });
  // The first recording is where the run's mites are found: label those.
  if (!before.results) loadLivePreview().catch(() => {});
  if (onLiveResults()) drawResults();
}

// The newest frame, fetched only when there is a newer one and the last has loaded.
function refreshFeed() {
  const s = live.status;
  if (!s || shownMode !== "live") return;
  const big = location.hash.startsWith("#/live/open");
  const img = big ? $("live-feed") : onLiveResults() ? $("live-thumb") : null;
  if (!img || live.feedBusy || String(s.feed) === img.dataset.count || !s.feed) return;
  if (s.state === "finished" && img.src) return;
  live.feedBusy = true;
  const next = new Image();
  next.onload = () => {
    img.src = next.src;
    img.dataset.count = String(s.feed);
    img.hidden = false;
    live.feedBusy = false;
  };
  next.onerror = () => { live.feedBusy = false; };
  next.src = `/api/live/${live.id}/frame.jpg?w=${big ? 960 : 360}&n=${s.feed}`;
}

// Closing or reloading the page does not stop the run; say so before it goes.
window.addEventListener("beforeunload", (event) => {
  if (liveRunning()) {
    event.preventDefault();
    event.returnValue = "";
  }
});
