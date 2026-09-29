// Live from the Discobox, the mode the app opens on:
//   #/live/open      the camera (or a replay), the test run's settings, the fan and LEDs,
//                    and under them the recordings kept (LiveSetupPage)
//   #/live/label     the label page; its button starts the test run
//   #/live/results   the result pages -- the very ones a folder gets -- under a
//                    small panel with how the run is going (LivePanel), filling in as it goes
//
// Talks to /api/live/... . The page asks for the run's status about twice a second
// and fetches the results only when they changed (after each recording), so
// drawing never holds up the camera: capture runs on the server, on its own threads.

class LiveRun {
  static POLL_MS = 500;
  static ACTIVE_STATES = ["running", "paused", "stopping"];

  static clock(seconds) {
    return new Date(seconds * 1000).toLocaleTimeString();
  }

  constructor() {
    this.id = null;          // the live run's session id
    this.status = null;      // what /status said last
    this.options = null;     // cameras, serial ports, saved settings and their ranges, the run plan
    this.version = 0;        // version of the results shown
    this.follow = true;      // show each new recording as it comes in
    this.polling = false;
    this.feedBusy = false;
    this.notice = null;      // what the camera page should say when it shows next, e.g. that the run was lost

    $("live-connect-btn").addEventListener("click", () => this.connect("camera"));
    $("live-replay-btn").addEventListener("click", () => this.connect("replay"));
    $("live-close-btn").addEventListener("click", () => this.close());
    $("live-label-btn").addEventListener("click", () => this.labelPlates());
    setInterval(() => this.poll(), LiveRun.POLL_MS);
    // Closing or reloading the page does not stop the run; say so before it goes.
    window.addEventListener("beforeunload", (event) => {
      if (this.running) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
  }

  get workspace() {
    return workspaces.get("live");
  }

  get started() {
    return Boolean(this.status && this.status.state !== "ready");
  }

  get running() {
    return Boolean(this.status && LiveRun.ACTIVE_STATES.includes(this.status.state));
  }

  get onResultsPage() {
    return router.shownMode === "live" && /^#\/live\/(results|zone|mite)/.test(location.hash);
  }

  get onOpenPage() {
    return router.shownMode === "live" && location.hash.startsWith("#/live/open");
  }

  // --- routing

  route(sub = "open") {
    const wanted = { open: "open", label: "label", results: "results", zone: "results", mite: "results" }[sub] || "open";
    let step = wanted;
    if (step === "results" && !this.started) step = ctx.session ? "label" : "open";
    if (step === "label" && !ctx.session) step = "open";
    if (step !== wanted) { location.replace(`#/live/${step}`); return; }

    this.drawSteps(step);
    Charts.hideTooltip();
    $("live-panel").hidden = step !== "results";
    if (step === "open") { router.showView("live-open"); liveSetup.draw(); }
    if (step === "label") { router.showView("label"); labelPage.draw(); }
    if (step === "results") {
      router.showView("results");
      livePanel.draw();
      if (ctx.results) resultsView.draw();
      else this.drawWaiting();
    }
    window.scrollTo(0, 0);
  }

  drawSteps(step = null) {
    // The Live tab says a run is being recorded, whichever mode is shown.
    $("live-link").classList.toggle("recording", this.running);
    $("live-link").title = this.running ? "A test run is being recorded" : "";
    Router.markSteps("steps-live", step, { open: true, label: this.workspace.session, results: this.started });
  }

  // Before the first recording is analysed, the result pages have nothing to show.
  drawWaiting() {
    $("breadcrumb").hidden = true;
    const s = this.status || {};
    const next = s.next_recording ? `The first recording starts at ${LiveRun.clock(s.next_recording)}; its results` : "The results of the first recording";
    $("results-body").innerHTML = `
    <header class="page-head"><div><h1>Results</h1>
      <p class="meta">${esc(s.run_name || "")}</p></div></header>
    <p class="live-waiting">${s.state === "finished"
      ? "The test run ended before a recording was analysed, so there are no results."
      : `${next} appear here as soon as it is analysed, and the pages fill in with every recording after it.`}</p>`;
  }

  // --- connecting

  // `source`: "camera", or "replay" for the folder under "No camera?".
  async connect(source) {
    const status = $("live-open-status");
    status.className = "hint";
    status.innerHTML = source === "camera"
      ? `<span class="spinner"></span> Connecting to the camera and switching the LEDs on…`
      : `<span class="spinner"></span> Opening the replay…`;
    const poolSize = $("live-pool-size").value.trim();
    // The camera found when the page opened saves looking for it again.
    const cameras = this.options ? this.options.cameras : [];
    const body = {
      source,
      run_name: $("live-run-name").value.trim(),
      save_frames: $("live-save").checked,
      pool_size: poolSize ? Number(poolSize) : null,
      camera_id: source === "camera" && cameras.length === 1 ? cameras[0].id : null,
      serial_port: "auto",
      replay_dir: $("live-replay-dir").value.trim(),
      replay_gap: Number($("live-replay-gap").value || 0),
    };
    try {
      const opened = await post("/api/live", body);
      this.start(opened.session_id, opened);
      status.textContent = `Connected: ${opened.camera}. Recordings go to ${opened.save_frames ? opened.run_dir : "nowhere: they are not saved"}.`;
    } catch (error) {
      status.className = "hint error";
      status.textContent = error.message;
    }
  }

  start(id, status) {
    Object.assign(this, { id, status, version: 0, follow: true, feedBusy: false });
    this.workspace.clear();
    this.workspace.sessionId = id;
    router.setFolder("live", status.run_name, status.run_dir);
    $("live-feed").removeAttribute("src");
    $("live-thumb").removeAttribute("src");
    liveSetup.drawForm();
    this.drawSteps();
    this.poll();
  }

  // A run left open by a page that was closed or reloaded.
  async attach(id) {
    try {
      const status = await post(`/api/live/${id}/attach`);
      this.start(id, status);
      if (status.state !== "ready") await this.loadPreview();
      await this.fetchResults();
      $("live-open-status").className = "hint";
      $("live-open-status").textContent = `Reconnected to the test run ${status.run_name}.`;
      if (this.started) router.go("#/live/results");
    } catch (error) {
      $("live-open-status").className = "hint error";
      $("live-open-status").textContent = error.message;
    }
  }

  async close() {
    if (!this.id) return;
    try {
      await post(`/api/live/${this.id}/close`);
    } catch { /* already gone */ }
    this.forget();
  }

  // The server no longer has the run, e.g. it restarted after an update: say so,
  // and go back to connecting. Its recordings are kept in recordings/.
  lost() {
    const name = this.status ? this.status.run_name : "";
    // Shown by the camera page once it has looked for cameras again.
    this.notice = `The test run ${name} is no longer open on the server, which may have restarted. `
      + "Its recordings so far are in the list below.";
    this.forget();
  }

  // Drop the run on this page and show the camera page again.
  forget() {
    Object.assign(this, { id: null, status: null, version: 0 });
    this.workspace.clear();
    router.setFolder("live", "");
    this.options = null;  // the run name is free again, a camera may have come or gone
    $("live-feed").removeAttribute("src");
    $("live-open-status").textContent = "";
    this.drawSteps();
    if (router.shownMode === "live") location.hash === "#/live/open" ? liveSetup.draw() : router.go("#/live/open");
  }

  // --- labelling, and the start of the run

  async loadPreview() {
    const preview = await post(`/api/live/${this.id}/preview`);
    preview.zones.forEach((zone) => { zone.label = zone.label || ""; });
    Object.assign(this.workspace, { session: preview, sessionId: this.id });
    if (ctx.mode === "live") {
      labelPage.showLoadedStatus();
      if (location.hash.startsWith("#/live/label")) labelPage.draw();
    }
    this.drawSteps();
  }

  async labelPlates() {
    if (this.started) { router.go("#/live/results"); return; }
    const status = $("live-open-status");
    status.className = "hint";
    status.innerHTML = `<span class="spinner"></span> Finding the mites on the newest frame…`;
    try {
      await this.loadPreview();
      status.textContent = "";
      router.go("#/live/label");
    } catch (error) {
      status.className = "hint error";
      status.textContent = error.message;
    }
  }

  drawRunButton() {
    $("run-btn").textContent = this.started ? "Show the live results" : "Start test run";
    $("run-btn").disabled = !this.id;
  }

  async startRun() {
    if (this.started) { router.go("#/live/results"); return; }
    const status = $("run-status");
    $("run-btn").disabled = true;
    status.className = "hint";
    status.innerHTML = `<span class="spinner"></span> Starting the test run…`;
    try {
      this.status = await post(`/api/live/${this.id}/start`, { labels: this.workspace.collectLabels() });
      status.textContent = "The test run is going; the labels can still change and the results follow them.";
      router.go("#/live/results");
    } catch (error) {
      status.className = "hint error";
      status.textContent = error.message;
    } finally {
      this.drawRunButton();
    }
  }

  // Show each new recording as it comes in, or stay on the one shown.
  setFollow(on) {
    this.follow = on;
    $("live-follow").checked = on;
  }

  // --- polling

  async poll() {
    if (!this.id || this.polling) return;
    this.polling = true;
    const id = this.id;
    try {
      const response = await fetch(`/api/live/${id}/status`, { cache: "no-store" });
      if (id !== this.id) return;
      if (response.status === 404) {
        this.lost();
        return;
      }
      if (!response.ok) return;
      const wasRunning = this.running;
      const was = this.status;
      this.status = await response.json();
      // The list of recordings on the camera page shows the run from its first recording on.
      const changed = !was || was.state !== this.status.state || was.analysed !== this.status.analysed;
      if (changed && this.onOpenPage) recordings.refresh();
      // How the run is going first: the progress bar and the feed never wait on the results.
      livePanel.draw();
      this.drawSteps();
      this.refreshFeed();
      try {
        if (this.status.version !== this.version) await this.fetchResults();
        // Once the run is over, the charts' time axis is what was recorded, no longer the whole run.
        else if (wasRunning && !this.running && ctx.results && this.onResultsPage) resultsView.draw();
      } catch (error) {
        // Said, not swallowed: the next poll tries again.
        console.error("Could not show the live results", error);
        if (this.onResultsPage) $("live-error").textContent = `Could not show the results: ${error.message}`;
      }
    } catch {
      // the server is busy or restarting: try again at the next tick
    } finally {
      this.polling = false;
    }
  }

  // The results changed: show them, on whatever result page is open, without
  // moving the page. With "follow" on, the page moves on to the newest recording.
  async fetchResults() {
    const id = this.id;
    const data = await getJson(`/api/live/${id}/results`, "the server could not give the results");
    if (id !== this.id) return;
    this.version = data.version;
    if (!data.results) return;
    const { workspace } = this;
    const before = workspace.results;
    const latest = data.results.times.length - 1;
    const next = this.follow || !before ? latest : Math.min(workspace.shown, latest);
    Object.assign(workspace, { results: data.results, runStamp: Date.now(), shown: next });
    // The first recording is where the run's mites are found: label those.
    if (!before) this.loadPreview().catch(() => {});
    if (this.onResultsPage) {
      // The charts keep their axes; what the new recordings add is drawn in.
      const had = before ? before.times.length : 0;
      resultsView.drawEntering(had && latest + 1 > had ? had : null);
    }
  }

  // The newest frame, fetched only when there is a newer one and the last has loaded.
  refreshFeed() {
    const s = this.status;
    if (!s || router.shownMode !== "live") return;
    const big = location.hash.startsWith("#/live/open");
    const img = big ? $("live-feed") : this.onResultsPage ? $("live-thumb") : null;
    if (!img || this.feedBusy || String(s.feed) === img.dataset.count || !s.feed) return;
    if (s.state === "finished" && img.src) return;
    this.feedBusy = true;
    const next = new Image();
    next.onload = () => {
      img.src = next.src;
      img.dataset.count = String(s.feed);
      img.hidden = false;
      if (big) img.parentElement.classList.add("filled");
      this.feedBusy = false;
    };
    next.onerror = () => { this.feedBusy = false; };
    next.src = `/api/live/${this.id}/frame.jpg?w=${big ? 960 : 360}&n=${s.feed}`;
  }
}
