// The analysis of a folder: opening it (#/open), then running the analysis from
// the label page (#/label), whose results the result pages show (#/results).

class AnalysisMode {
  constructor() {
    this.running = false;
    this.picker = new FolderPicker("", (dataDir) => this.openFolder(dataDir));
  }

  get workspace() {
    return workspaces.get("analysis");
  }

  async openFolder(dataDir) {
    $("open-status").className = "hint";
    $("open-status").textContent = "Opening…";
    try {
      const opened = await post("/api/session", { data_dir: dataDir });
      opened.zones.forEach((zone) => { zone.label = zone.label || ""; });
      Object.assign(this.workspace, { session: opened, sessionId: opened.session_id, results: null, labelsChanged: false });
      router.setFolder("analysis", folderOf(opened.data_dir), opened.data_dir);
      $("open-status").textContent = "";
      if (ctx.mode === "analysis") labelPage.showLoadedStatus();
      router.go("#/label");
      labelReader.read(this.workspace);
    } catch (error) {
      $("open-status").className = "hint error";
      $("open-status").textContent = error.message;
    }
  }

  // The Back button: close the folder. An analysis still running goes on on the
  // server, but its results are dropped (see run).
  quit() {
    if (this.running && !confirm("The analysis is still running. Go back anyway? Its results are dropped.")) return;
    this.workspace.clear();
    router.setFolder("analysis", "");
    this.status("hint", "");
    router.go("#/open");
  }

  // The label page's "Zones per plate": saved with the recordings, for every
  // later analysis of them. The server finds the mites again in the new zones;
  // the results shown are of the other zones, so they go.
  async setZonesPerPlate(zones) {
    const { workspace } = this;
    const { sessionId } = workspace;
    labelPage.editor.close();
    $("zones-per-plate").disabled = true;
    this.status("hint", `<span class="spinner"></span> Finding the mites in the new zones…`);
    try {
      const opened = await post(`/api/session/${sessionId}/zones`, { zones_per_plate: zones });
      if (workspace.sessionId !== sessionId) return;  // the folder was closed meanwhile
      opened.zones.forEach((zone) => { zone.label = zone.label || ""; });
      Object.assign(workspace, { session: opened, results: null, runStamp: Date.now(), labelsChanged: false });
      this.status("hint", `${opened.n_recordings} recordings loaded · mites detected in ${workspace.labelZones().length} of ${opened.zones.length} zones.`);
    } catch (error) {
      if (workspace.sessionId !== sessionId) return;
      this.status("hint error", esc(error.message));
    }
    router.go("#/label");  // drawn again, with the zones saved
    if (workspace.sessionId === sessionId) labelReader.read(workspace);
  }

  // Frames scored together, from the label page's option; null for a whole recording.
  poolSize() {
    const value = $("pool-size").value.trim();
    return value ? Number(value) : null;
  }

  status(className, html) {
    workspaces.setStatus("analysis", className, html);
  }

  async run() {
    const buttons = document.querySelectorAll(".run-trigger, #run-btn");
    buttons.forEach((b) => { b.disabled = true; });
    this.running = true;
    $("zones-per-plate").disabled = true;  // the run is of the zones it starts with
    this.status("hint", `<span class="spinner"></span> Running… the frames are being decoded, this takes a while.`);

    const { workspace } = this;
    const { sessionId } = workspace;
    try {
      const request = { labels: workspace.collectLabels() };
      if (this.poolSize() != null) request.pool_size = this.poolSize();
      const ran = await post(`/api/session/${sessionId}/run`, request);
      if (workspace.sessionId !== sessionId) return;  // the folder was closed meanwhile
      Object.assign(workspace, { results: ran, runStamp: Date.now(), shown: ran.times.length - 1, labelsChanged: false });
      this.status("hint", "Done.");
      router.go("#/results");
    } catch (error) {
      if (workspace.sessionId !== sessionId) return;
      this.status("hint error", esc(error.message));
      if (!location.hash.startsWith("#/label")) router.go("#/label");
    } finally {
      this.running = false;
      $("zones-per-plate").disabled = false;
      buttons.forEach((b) => { b.disabled = false; });
      if (ctx.mode === "live") live.drawRunButton();  // the button is the live run's meanwhile
    }
  }
}
