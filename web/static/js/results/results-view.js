// The result pages, of the analysis of a folder and of a live run alike: the
// overview, a zone or a mite, as the address bar says. They show `ctx`'s results,
// in the recording `ctx.shown`.

class ResultsView {
  constructor() {
    this.overview = new OverviewPage();
    this.zone = new ZonePage();
    this.mite = new MitePage();
    // The index of the first recording new since the page was last drawn, set by
    // the live run for the one drawing that shows it: its points are drawn in.
    this.enterFrom = null;
    document.addEventListener("keydown", (event) => this.onKey(event));
  }

  // M and S answer the close call asked on a mite's page (ReviewCheck).
  onKey(event) {
    if (!/^#\/(live\/)?mite\//.test(location.hash) || $("view-results").hidden) return;
    if (event.altKey || event.ctrlKey || event.metaKey || event.repeat) return;
    if (["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName) && event.target.type !== "range") return;
    const state = { m: "moving", s: "still" }[event.key.toLowerCase()];
    const button = state && document.querySelector(`#results-body [data-answer="${state}"]:not(:disabled)`);
    if (button) { event.preventDefault(); button.click(); }
  }

  draw() {
    const [view, id] = location.hash.replace(/^#\/(live\/)?/, "").split("/");
    player.stop();
    Charts.hideTooltip();
    if (view === "zone") this.zone.show(Number(id));
    else if (view === "mite") this.mite.show(decodeURIComponent(id));
    else this.overview.show();
  }

  // Draw the page with the recordings from `from` on drawn in; null for none.
  drawEntering(from) {
    this.enterFrom = from;
    try {
      this.draw();
    } finally {
      this.enterFrom = null;
    }
  }

  // Show another recording on the page on screen, from the slider, a chart or a table.
  showRecording(index) {
    const { results } = ctx;
    if (index === ctx.shown || !(index >= 0 && index < results.times.length)) return;
    this.setShown(index);
    this.draw();
  }

  setShown(index) {
    ctx.shown = index;
    if (ctx.mode === "live") live.setFollow(index === ctx.results.times.length - 1);
  }

  // Open a mite's page, in the recording `recording` when given; with `replace`,
  // in place of the page shown, so Back does not go through every mite checked.
  openMite(mite, recording = null, replace = false) {
    if (recording != null) this.setShown(recording);
    const hash = ctx.href(`mite/${encodeURIComponent(mite.id)}`);
    if (replace && location.hash !== hash) location.replace(hash);
    else router.go(hash);
  }
}
