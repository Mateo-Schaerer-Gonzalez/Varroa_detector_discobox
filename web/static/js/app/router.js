// Navigation is hash-based so the browser's back/forward buttons work. Three modes
// share the window, each with a tab in the header. Live from the Discobox camera
// (LiveRun), the page the app opens on, with the label and result pages below:
//   #/live/open  #/live/label  #/live/results  #/live/zone/<id>  #/live/mite/<id>
// the analysis of a folder:
//   #/open  #/label  #/results  #/zone/<id>  #/mite/<id>
// and calibration (Calibration):
//   #/cal/open  #/cal/truth/<zone id>/<recording>  #/cal/report
// The recordings kept (RecordingsList) are listed on each mode's first page.

class Router {
  constructor() {
    // Each mode keeps its own folder in the header and the page it was left on,
    // which its tab goes back to.
    this.modes = {
      live: { page: "#/live/open", folder: "", path: "", title: "Live" },
      analysis: { page: "#/open", folder: "", path: "", title: "Analysis" },
      cal: { page: "#/cal/open", folder: "", path: "", title: "Calibration" },
    };
    this.home = this.modes.live.page;
    this.shownMode = null;
    window.addEventListener("hashchange", () => this.route());
  }

  static modeOf(hash) {
    return hash.startsWith("#/cal") ? "cal" : hash.startsWith("#/live") ? "live" : "analysis";
  }

  // A page of the mode not on screen, e.g. the results of a run that finished
  // while calibrating, waits until the user goes back to it.
  go(hash) {
    const mode = Router.modeOf(hash);
    if (this.shownMode && mode !== this.shownMode) {
      this.modes[mode].page = hash;
      this.drawModeLinks();
    } else if (location.hash === hash) this.route();
    else location.hash = hash;
  }

  // Show one <section class="view"> and hide the others.
  showView(name) {
    document.querySelectorAll("main > .view").forEach((view) => { view.hidden = view.id !== `view-${name}`; });
  }

  // Mark the stage shown among a mode's steps in the header (unless `step` is
  // null) and grey out those without data yet; `available` maps a step to
  // whether it has any.
  static markSteps(navId, step, available) {
    document.querySelectorAll(`#${navId} a[data-step]`).forEach((link) => {
      if (step) link.classList.toggle("active", link.dataset.step === step);
      link.classList.toggle("disabled", !available[link.dataset.step]);
    });
  }

  // The folder a mode has open; the header shows the one of the mode on screen.
  setFolder(mode, name, path = "") {
    Object.assign(this.modes[mode], { folder: name, path });
    if (mode === this.shownMode) {
      $("folder-name").textContent = name;
      $("folder-name").title = path;
    }
  }

  drawModeLinks() {
    document.querySelectorAll(".modes a[data-mode]").forEach((link) => { link.href = this.modes[link.dataset.mode].page; });
  }

  // Each mode has its own steps in the header.
  setMode(mode) {
    const switched = mode !== this.shownMode;
    this.shownMode = mode;
    $("steps-analysis").hidden = mode !== "analysis";
    $("steps-cal").hidden = mode !== "cal";
    $("steps-live").hidden = mode !== "live";
    $("live-panel").hidden = true;  // the live panel shows itself over the live result pages
    document.querySelectorAll(".modes a[data-mode]").forEach((link) => {
      const active = link.dataset.mode === mode;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.title = `${this.modes[mode].title} · Varroa discobox`;
    this.setFolder(mode, this.modes[mode].folder, this.modes[mode].path);
    // The analysis may have marked a detection "not a mite" meanwhile.
    if (mode === "cal" && switched) groundTruth.reload();
  }

  route() {
    // The app opens on the camera.
    if (!/^#\/./.test(location.hash)) { location.replace(this.home); return; }
    const [, view = "open", id, ...rest] = location.hash.split("/");
    const mode = view === "cal" ? "cal" : view === "live" ? "live" : "analysis";
    player.stop();
    this.modes[mode].page = location.hash || this.modes[mode].page;
    this.drawModeLinks();
    this.setMode(mode);
    if (view === "cal") { cal.route(id, ...rest); return; }
    workspaces.use(mode);
    if (view === "live") { live.route(id, ...rest); return; }
    this.routeAnalysis(view);
  }

  routeAnalysis(view) {
    const wanted = { open: "open", label: "label", results: "results", zone: "results", mite: "results" }[view] || "open";

    // Fall back to the furthest stage that has data.
    let step = wanted;
    if (step === "results" && !ctx.results) step = ctx.session ? "label" : "open";
    if (step === "label" && !ctx.session) step = "open";
    if (step !== wanted) { location.replace("#/" + step); return; }

    this.showView(step);
    Router.markSteps("steps-analysis", step, { open: true, label: ctx.session, results: ctx.results });
    Charts.hideTooltip();

    if (step === "open") recordings.refresh();
    if (step === "label") labelPage.draw();
    if (step === "results") resultsView.draw();
    window.scrollTo(0, 0);
  }
}
