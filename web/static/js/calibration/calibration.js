// Calibration, in the same window as the analysis. The user marks, for each detected
// mite and each recording, whether it moves, and the detector's calls are compared with theirs.
//
//   #/cal/open                              choose calibrate or test, then the recordings
//   #/cal/truth/<zone id>/<recording>       enter the ground truth, zone by zone (TruthPage)
//   #/cal/report                            the calibration or the test report (ReportPage)
//
// The ground truth itself, and saving it, is GroundTruth's; the saved datasets
// are DatasetLibrary's.

class Calibration {
  constructor() {
    this.mode = "calibrate";      // "calibrate" or "test"
    this.id = null;               // server session id
    this.data = null;             // the opened folder: zones, mite positions, times -- no scores; null when only pooling saved data
    this.datasetId = null;        // the saved dataset the opened folder's ground truth goes to
    this.datasets = [];           // every saved dataset, as listed by the server
    this.selected = [];           // ids of the saved datasets the report pools
    this.report = null;           // what the last evaluation returned
    this.reportStale = false;     // the ground truth changed after that evaluation
    this.zoneId = null;           // the zone shown on the ground-truth page
    this.recording = 0;           // the recording shown on the ground-truth page
    this.shownThreshold = "best"; // confusion matrix of the calibration tab: "best" or "current"
    this.stamp = 0;               // cache-buster for files that change between evaluations
    this.scores = null;           // the movement scores the server offers, and the one in config.yaml
    this.metric = null;           // the movement score to report with, { name, params }; null: config.yaml's
    this.mapDataset = null;       // the dataset the error map of a pooled report shows

    this.modeRadios = document.querySelectorAll('input[name="cal-mode"]');
    this.modeRadios.forEach((radio) => radio.addEventListener("change", () => { this.mode = radio.value; }));
    // The browser may restore the last choice on reload.
    this.mode = document.querySelector('input[name="cal-mode"]:checked').value;
    this.picker = new FolderPicker("cal-", (dataDir) => this.openFolder(dataDir));
    $("evaluate-btn").addEventListener("click", () => this.evaluate());
  }

  // --- the opened folder

  fileUrl(name) {
    return `/api/session/${this.id}/file/${name}?t=${this.stamp}`;
  }

  get nRecordings() {
    return this.data.n_recordings;
  }

  mites(zoneId) {
    return this.data.mites.filter((mite) => mite.zone_id === zoneId);
  }

  // The zones to visit, those with a detected mite, in the server's order.
  zones() {
    return groundTruth.view.zones_with_mites.map((id) => this.data.zones.find((zone) => zone.id === id));
  }

  recordingName(recording) {
    return `recording ${recording + 1} (${minutes(this.data.times[recording])})`;
  }

  truthHref(zoneId, recording = this.recording) {
    return `#/cal/truth/${zoneId}/${recording}`;
  }

  // --- routing

  route(sub, ...args) {
    const wanted = ["open", "truth", "report"].includes(sub) ? sub : "open";
    let step = wanted;
    if (step === "report" && !this.report) step = this.data ? "truth" : "open";
    if (step === "truth" && !this.data) step = "open";
    if (step !== wanted) { location.replace(`#/cal/${step}`); return; }

    router.showView(`cal-${step}`);
    Router.markSteps("steps-cal", step, { open: true, truth: this.data, report: this.report });
    Charts.hideTooltip();

    if (step === "open") { datasetLibrary.refresh(); recordings.refresh(); }
    if (step === "truth") truthPage.draw(...args);
    if (step === "report") reportPage.draw();
    window.scrollTo(0, 0);
  }

  setMode(mode) {
    this.mode = mode;
    this.modeRadios.forEach((radio) => { radio.checked = radio.value === mode; });
  }

  // --- opening

  // Start labelling what the server opened: a folder just detected, or a saved dataset.
  // Callers first save or drop the unsaved changes (openWithTruthSaved), so that
  // reopening the dataset just edited shows what was saved.
  start(data) {
    Object.assign(this, { id: data.session_id, report: null, reportStale: false, selected: [data.dataset_id] });
    this.showDataset(data);
    router.go("#/cal/truth");
  }

  // Put a dataset on the ground-truth page; the report and the pooled datasets stay.
  showDataset(data) {
    Object.assign(this, { data, datasetId: data.dataset_id, zoneId: null, recording: 0, stamp: Date.now() });
    groundTruth.load(data.truth_view);
    router.setFolder("cal", folderOf(data.data_dir), data.data_dir);
  }

  // Go to one mite in one recording of any saved dataset, e.g. a point of a pooled
  // report. Another dataset than the one on the ground-truth page is opened in its
  // place, in the same session, so the report stays.
  async goToMite(datasetId, zoneId, recording) {
    if (!(this.data && this.datasetId === datasetId)) {
      try {
        await this.saveOrDropChanges();
        this.showDataset(await post(`/api/calibration/${this.id}/dataset/${encodeURIComponent(datasetId)}`, {}));
      } catch (error) {
        alert(`Could not open that recording: ${error.message}`);
        return;
      }
    }
    router.go(this.truthHref(zoneId, recording));
  }

  // Before another dataset replaces the one on screen: ask whether to save its
  // unsaved changes, and wait for the changes and a save under way, so the server
  // reads the ground truth with them. Throws when the save fails; the changes then
  // stay on screen. Changes not saved go with the dataset they were made on.
  async saveOrDropChanges() {
    await groundTruth.settled();
    if (groundTruth.hasUnsaved() && confirm("Save your changes to the ground truth first?\n\nOK saves them, Cancel discards them.")) {
      await groundTruth.save();
    } else {
      await groundTruth.saves;
    }
  }

  async openWithTruthSaved(status, open) {
    try {
      await this.saveOrDropChanges();
    } catch (error) {
      status.className = "hint error";
      status.textContent = `Not opened: the last changes could not be saved (${error.message}).`;
      return;
    }
    await open();
  }

  // The Back button: close the dataset or the pooled report, after saving or
  // dropping the unsaved changes. What was saved stays in the saved ground truth.
  async quit() {
    try {
      await this.saveOrDropChanges();
    } catch (error) {
      alert(`Not closed: the last changes could not be saved (${error.message}).`);
      return;
    }
    Object.assign(this, { id: null, data: null, datasetId: null, selected: [], report: null, reportStale: false, zoneId: null, recording: 0 });
    groundTruth.load(null);
    router.setFolder("cal", "");
    router.go("#/cal/open");
  }

  openFolder(dataDir) {
    return this.openWithTruthSaved($("cal-open-status"), async () => {
      const status = $("cal-open-status");
      status.className = "hint";
      status.innerHTML = `<span class="spinner"></span> Detecting and scoring the mites… every frame is decoded, this takes a while.`;
      try {
        const data = await post("/api/calibration", { data_dir: dataDir });
        status.textContent = "";
        this.start(data);
      } catch (error) {
        status.className = "hint error";
        status.textContent = error.message;
      }
    });
  }

  async fetchDatasets() {
    const data = await getJson("/api/calibration/datasets", "Could not list the saved ground truth");
    this.datasets = data.datasets;
    return this.datasets;
  }

  // --- evaluating

  async evaluate() {
    const button = $("evaluate-btn");
    const status = $("evaluate-status");
    button.disabled = true;
    status.className = "hint";
    status.innerHTML = `<span class="spinner"></span> Comparing…${this.mode === "test" ? " the first time a dataset meets the benchmark this takes about a minute." : ""}`;
    try {
      this.takeReport(await this.requestReport());
      status.textContent = "";
      router.go("#/cal/report");
    } catch (error) {
      status.className = "hint error";
      status.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }

  takeReport(report) {
    Object.assign(this, { report, reportStale: false, stamp: Date.now() });
  }

  // The ground truth changed since the report shown.
  markReportStale() {
    if (this.report) this.reportStale = true;
  }

  // Save the changes still unsaved and compare the saved ground truth, pooled over
  // the chosen datasets and scored with the chosen movement score. The saved
  // datasets and the movement scores on offer are refreshed alongside, for the
  // report's pickers.
  async requestReport() {
    await groundTruth.save();
    const [report] = await Promise.all([
      post(`/api/calibration/${this.id}/evaluate`, {
        datasets: this.selected, metric: this.metric?.name ?? null, params: this.metric?.params ?? null,
        stabilize: this.metric?.stabilize ?? null,
        normalize_brightness: this.metric?.normalizeBrightness ?? null, normalize_floor: this.metric?.normalizeFloor ?? null,
        // The test report compares with the benchmark, which is slow the first time.
        benchmark: this.mode === "test",
      }),
      this.fetchDatasets().catch(() => this.datasets),
      this.fetchScores().catch(() => this.scores),
    ]);
    return report;
  }

  async fetchScores() {
    const data = await getJson("/api/calibration/metrics", "Could not list the movement scores");
    this.scores = data;
    return data;
  }

  // Evaluate again after changing what the report uses. On failure `undo` puts the
  // choice back and the error shows in the element `statusId`.
  async reportAgain(statusId, undo, message = "Scoring and comparing… the first time a dataset meets a movement score its recordings are decoded, which takes a while.") {
    $(statusId).className = "hint";
    $(statusId).innerHTML = `<span class="spinner"></span> ${message}`;
    try {
      this.takeReport(await this.requestReport());
      reportPage.draw();
    } catch (error) {
      undo();
      reportPage.draw();
      $(statusId).className = "hint error";
      $(statusId).textContent = error.message;
    }
  }
}
