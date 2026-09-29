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
    } catch (error) {
      $("open-status").className = "hint error";
      $("open-status").textContent = error.message;
    }
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
    this.status("hint", `<span class="spinner"></span> Running… the frames are being decoded, this takes a while.`);

    try {
      const { workspace } = this;
      const request = { labels: workspace.collectLabels() };
      if (this.poolSize() != null) request.pool_size = this.poolSize();
      const ran = await post(`/api/session/${workspace.sessionId}/run`, request);
      Object.assign(workspace, { results: ran, runStamp: Date.now(), shown: ran.times.length - 1, labelsChanged: false });
      this.status("hint", "Done.");
      router.go("#/results");
    } catch (error) {
      this.status("hint error", esc(error.message));
      if (!location.hash.startsWith("#/label")) router.go("#/label");
    } finally {
      this.running = false;
      buttons.forEach((b) => { b.disabled = false; });
      if (ctx.mode === "live") live.drawRunButton();  // the button is the live run's meanwhile
    }
  }
}
