// The panel over the live result pages: the camera's newest frame, how capture
// and the fan and LEDs are doing, the whole run as a progress bar, and the
// buttons to pause, stop or start a new run.

class LivePanel {
  static STATE_NAMES = { ready: "Connected", running: "Recording", paused: "Paused", stopping: "Stopping", finished: "Finished" };
  static MARK_NAMES = { analysed: "analysed", captured: "being analysed", capturing: "being recorded", planned: "to come" };

  constructor() {
    $("live-panel").innerHTML = `
  <div class="live-thumb-wrap"><img id="live-thumb" alt="The camera's newest frame" hidden></div>
  <div class="live-facts">
    <div class="live-title"><span id="live-state" class="live-state"></span><span id="live-run"></span></div>
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
  </div>
  <div class="run-progress">
    <div id="run-bar" class="run-bar" role="progressbar" aria-label="The test run" aria-valuemin="0" aria-valuemax="100">
      <div id="run-bar-fill" class="run-bar-fill"></div>
    </div>
    <div id="run-marks" class="run-marks" aria-hidden="true"></div>
    <div class="run-progress-text"><span id="live-progress"></span><span id="run-left"></span></div>
  </div>`;

    $("live-follow").addEventListener("change", (event) => this.follow(event.target.checked));
    $("live-pause-btn").addEventListener("click", () => this.act(live.status.state === "paused" ? "resume" : "pause"));
    $("live-stop-btn").addEventListener("click", () => {
      if (confirm("Stop the test run? The recording being captured ends with the frames already in; it is analysed and the results are written.")) this.act("stop");
    });
    $("live-new-btn").addEventListener("click", () => live.close());
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
    $("live-run").textContent = ` ${s.run_name} · ${s.camera} · pools of ${s.pool_size_text}`;

    $("live-acquisition").textContent = (s.state === "finished" ? "Acquisition ended" : `Acquisition ${s.fps.toFixed(1)} fps${s.fps_set ? ` (set to ${s.fps_set})` : ""}`)
      + ` · ${s.dropped} frame${s.dropped === 1 ? "" : "s"} dropped · ${s.incomplete} incomplete`;
    $("live-acquisition").classList.toggle("error", s.dropped > 0);

    const lights = s.lights;
    $("live-devices").textContent = !lights ? "A replay: no fan or LEDs."
      : !lights.connected ? "No fan/LED controller: the run goes on without them."
        : LiveSetupPage.DEVICES.map(([device, name]) => `${name} ${lights[device].on ? "on" : "off"}`).join(" · ");

    $("live-saving").textContent = s.saving || s.save_frames
      ? `${s.saved_frames} frames saved to ${s.run_dir}` : "Recordings are not saved.";
    $("live-error").textContent = [s.error, s.save_error].filter(Boolean).join(" · ");

    this.drawProgress(s);

    const finished = s.state === "finished";
    $("live-pause-btn").hidden = finished;
    $("live-pause-btn").textContent = s.state === "paused" ? "Resume" : "Pause";
    $("live-pause-btn").disabled = !["running", "paused"].includes(s.state);
    $("live-stop-btn").hidden = finished;
    $("live-stop-btn").disabled = s.state === "stopping";
    $("live-new-btn").hidden = !finished;
    $("live-follow").checked = live.follow;
  }

  // The whole test run as one bar: filled as far as the run has got, with a tick
  // under it for each recording, dark once analysed. Polled twice a second, it
  // moves on in small steps, with no animation between them. A run going on until
  // every mite is dead has no set length: its bar shows the mites alive instead,
  // in a colour of its own, and it has no ticks. The numbers are the server's
  // (s.progress, classes/live/progress.py).
  drawProgress(s) {
    const line = s.timeline;
    const { fraction, alive_bar: untilAllDead, marks, left_seconds: left } = s.progress;
    const finished = s.state === "finished";
    $("run-bar-fill").style.width = `${fraction * 100}%`;
    $("run-bar").className = `run-bar ${s.state}${untilAllDead ? " alive-bar" : ""}`;
    $("run-bar").setAttribute("aria-label", untilAllDead ? "Mites alive" : "The test run");
    $("run-bar").setAttribute("aria-valuenow", String(Math.round(fraction * 100)));

    this.drawMarks(marks);

    // A run going on until every mite is dead may take more recordings than planned so far.
    const more = untilAllDead && !finished;
    const parts = [`Recording ${s.recording} of ${more ? "at least " : ""}${s.recordings}`];
    if (untilAllDead) {
      parts.unshift(s.alive ? `${s.alive.alive} of ${s.alive.mites} mites alive` : "Mites alive: once the first recording is analysed");
    }
    if (s.recording_name) parts.push(`capturing frame ${s.frame}${s.frames ? ` of ${s.frames}` : ""}`);
    parts.push(`${s.analysed} analysed`);
    if (s.next_recording && !finished) parts.push(`next recording at ${LiveRun.clock(s.next_recording)}`);
    $("live-progress").textContent = parts.join(" · ");

    const ends = new Date(Date.now() + left * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const share = `${Math.round(fraction * 100)}%${untilAllDead ? " alive" : ""}`;
    $("run-left").textContent = !line ? ""
      : finished ? (s.analysed < s.recordings ? `Stopped after ${s.analysed} of ${s.recordings} recordings` : `Finished in ${duration(line.length)}`)
        : s.state === "paused" ? `${share} · paused: the rest of the run waits`
          : untilAllDead ? `${share} · ends once no mite has moved for the time to count as dead, no sooner than ${ends}`
            : `${share} · ${duration(left)} left · ends about ${ends}`;
  }

  // A tick per recording, where the server placed it, in the state it gave it.
  drawMarks(marks) {
    const holder = $("run-marks");
    if (holder.children.length !== marks.length) {
      holder.innerHTML = marks.map(() => `<i></i>`).join("");
    }
    marks.forEach(({ at, state }, i) => {
      const mark = holder.children[i];
      mark.style.left = `${at * 100}%`;
      mark.className = state;
      mark.title = `Recording ${i + 1}: ${LivePanel.MARK_NAMES[state]}`;
    });
  }
}
