// The panel over the live result pages: the camera's newest frame, how capture
// and the fan and LEDs are doing, a circle per zone filled by its mites dead
// (the run stops once every zone is done), the buttons to pause, stop or start a
// new run, to add mites (AddMites), and those to enter the ground truth and the
// poke test of the recordings so far, on the calibration pages (Calibration.openLive).

class LivePanel {
  static STATE_NAMES = { ready: "Connected", running: "Recording", paused: "Paused", stopping: "Stopping", finished: "Finished" };

  constructor() {
    $("live-panel").innerHTML = `
  <div class="live-thumb-wrap"><img id="live-thumb" alt="The camera's newest frame" hidden></div>
  <div class="live-facts">
    <div class="live-title"><span id="live-state" class="live-state"></span><span id="live-run"></span></div>
    <div id="live-next" class="live-next"></div>
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
    <div class="row">
      <button id="live-add-btn" type="button" class="secondary small" title="Light the plates between two recordings and follow mites not found so far">Add mites</button>
      <button id="live-truth-btn" type="button" class="secondary small">Ground truth</button>
      <button id="live-poke-btn" type="button" class="secondary small">Poke test</button>
    </div>
  </div>
  <div id="live-add" class="live-add" hidden></div>
  <div class="run-progress">
    <div id="zone-circles" class="zone-circles"></div>
    <div class="run-progress-text"><span id="live-progress"></span><span id="run-left"></span></div>
  </div>`;

    $("live-follow").addEventListener("change", (event) => this.follow(event.target.checked));
    $("live-pause-btn").addEventListener("click", () => this.act(live.status.state === "paused" ? "resume" : "pause"));
    $("live-stop-btn").addEventListener("click", () => {
      if (confirm("Stop the test run? The recording being captured ends with the frames already in; it is analysed and the results are written.")) this.act("stop");
    });
    $("live-new-btn").addEventListener("click", () => live.close());
    $("live-truth-btn").addEventListener("click", () => this.calibrate("truth"));
    $("live-poke-btn").addEventListener("click", () => this.calibrate("poke"));
    this.adding = new AddMites($("live-add"));
    $("live-add-btn").addEventListener("click", () => this.adding.find());
    this.opening = null;         // the page, "truth" or "poke", the recordings are being opened for
    this.calibrateError = null;  // why they could not be, last time
  }

  // Enter the ground truth or the poke test (`page`) of the recordings so far.
  async calibrate(page) {
    Object.assign(this, { opening: page, calibrateError: null });
    this.draw();
    try {
      await cal.openLive(live.id, page);
    } catch (error) {
      this.calibrateError = `Could not open the recordings for the ${page === "poke" ? "poke test" : "ground truth"}: ${error.message}`;
    } finally {
      this.opening = null;
      this.draw();
    }
  }

  // The ground truth and the poke test need the run's recordings, saved and the first analysed.
  drawCalibrate(s) {
    const why = !s.save_frames ? "This test run does not save its recordings, so there is no clip to judge them on."
      : !s.analysed ? "Once the first recording is analysed." : "";
    [["truth", "Ground truth", "Mark whether each mite moves in each recording, to compare with the detector's calls"],
      ["poke", "Poke test", "Which mites moved when you poked them between two recordings, to compare with the detector's survival"]]
      .forEach(([page, name, title]) => {
        const button = $(`live-${page}-btn`);
        button.disabled = Boolean(why) || Boolean(this.opening);
        button.textContent = this.opening === page ? "Opening…" : name;
        button.title = why || title;
      });
  }

  // Following again moves on to the newest recording at once.
  follow(on) {
    live.follow = on;
    const workspace = workspaces.get("live");
    const latest = workspace.results ? workspace.results.times.length - 1 : null;
    if (on && workspace.results && workspace.shown !== latest) {
      workspace.shown = latest;
      if (live.onResultsPage) resultsView.draw();
    }
  }

  // Pause, resume or stop the run.
  async act(action) {
    try {
      live.status = await post(`/api/live/${live.id}/${action}`);
      this.draw();
    } catch (error) { $("live-error").textContent = error.message; }
  }

  draw() {
    const s = live.status;
    if (!s) return;
    if (live.onOpenPage) liveSetup.drawForm();
    if (!live.onResultsPage) return;
    $("live-panel").hidden = false;
    $("live-state").textContent = LivePanel.STATE_NAMES[s.state] || s.state;
    $("live-state").className = `live-state ${s.state}`;
    $("live-run").textContent = ` ${s.run_name} · ${s.camera}`;

    $("live-acquisition").textContent = (s.state === "finished" ? "Acquisition ended" : `Acquisition ${s.fps.toFixed(1)} fps${s.fps_set ? ` (set to ${s.fps_set})` : ""}`)
      + ` · ${s.dropped} frame${s.dropped === 1 ? "" : "s"} dropped · ${s.incomplete} incomplete`;
    $("live-acquisition").classList.toggle("error", s.dropped > 0);

    const lights = s.lights;
    $("live-devices").textContent = !lights.connected ? "No fan/LED controller: the run goes on without them."
      : LiveSetupPage.DEVICES.map(([device, name]) => `${name} ${lights[device].on ? "on" : "off"}`).join(" · ");

    $("live-saving").textContent = s.saving || s.save_frames
      ? `${s.saved_frames} frames saved to ${s.run_dir}` : "Recordings are not saved.";
    $("live-error").textContent = [s.error, s.save_error, this.calibrateError].filter(Boolean).join(" · ");

    this.drawNext(s);
    this.drawProgress(s);

    const finished = s.state === "finished";
    $("live-pause-btn").hidden = finished;
    $("live-pause-btn").textContent = s.state === "paused" ? "Resume" : "Pause";
    $("live-pause-btn").disabled = !["running", "paused"].includes(s.state);
    $("live-stop-btn").hidden = finished;
    $("live-stop-btn").disabled = s.state === "stopping";
    $("live-new-btn").hidden = !finished;
    $("live-add-btn").hidden = finished;
    $("live-add-btn").disabled = !["running", "paused"].includes(s.state) || !s.analysed || this.adding.busy;
    $("live-follow").checked = live.follow;
    this.drawCalibrate(s);
  }

  // The countdown to the next recording, the server's (s.progress.next_seconds):
  // it comes with every poll, twice a second. A pause holds it where it is.
  drawNext(s) {
    const next = s.progress.next_seconds;
    const holder = $("live-next");
    if (next == null) { holder.textContent = ""; return; }
    holder.innerHTML = `Next recording in <b>${countdown(next)}</b>${s.state === "paused"
      ? " · paused: it waits" : ` · at ${LiveRun.clock((Date.now() + next * 1000) / 1000)}`}`;
  }

  // A circle per zone with mites, filled by the share of its mites (those seen
  // moving) that are dead; a zone none of whose mites moved yet does not count,
  // and is drawn hollow. Once every zone that counts is full the run stops. The
  // numbers are the server's (s.progress.zones, classes/live/progress.py).
  drawProgress(s) {
    const zones = s.progress.zones;
    $("zone-circles").innerHTML = zones.map((zone) => {
      const turn = zone.fraction * 360;
      const name = zone.label ? `${zone.id} · ${zone.label}` : `Zone ${zone.id}`;
      const title = !zone.counts ? `${name}: no mite seen moving yet, so it does not hold the run up`
        : `${name}: ${zone.dead} of ${plural(zone.mites, "mite")} dead${zone.gone ? `, ${zone.gone} gone` : ""}${zone.done ? " · done" : ""}`;
      return `<div class="zone-circle${zone.counts ? "" : " idle"}${zone.done ? " done" : ""}" title="${esc(title)}">
        <span class="circle" style="--turn:${turn}deg" role="img" aria-label="${esc(title)}"></span>
        <span class="zone-circle-name">${esc(String(zone.id))}</span>
        <span class="zone-circle-count">${zone.counts ? `${zone.dead}/${zone.mites}` : "–"}</span>
      </div>`;
    }).join("") || `<span class="hint">The zones show once the first recording is analysed.</span>`;

    const parts = [`Recording ${s.recording} of at most ${s.recordings}`];
    if (s.recording_name) parts.push(`capturing frame ${s.frame}${s.frames ? ` of ${s.frames}` : ""}`);
    parts.push(`${s.analysed} analysed`);
    if (s.pending_mites) parts.push(`${plural(s.pending_mites, "mite")} to add with the next recording`);
    $("live-progress").textContent = parts.join(" · ");

    const counting = zones.filter((zone) => zone.counts);
    const done = counting.filter((zone) => zone.done).length;
    $("run-left").textContent = s.state === "finished" ? (s.stop_reason ? `Stopped: ${s.stop_reason}` : `Finished after ${s.analysed} recordings`)
      : counting.length ? `${done} of ${plural(counting.length, "zone")} done · the run stops once all are` : "";
  }
}
