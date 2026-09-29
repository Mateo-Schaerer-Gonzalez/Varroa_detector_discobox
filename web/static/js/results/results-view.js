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

  // Open a mite's page, in the recording `recording` when given.
  openMite(mite, recording = null) {
    if (recording != null) this.setShown(recording);
    router.go(ctx.href(`mite/${encodeURIComponent(mite.id)}`));
  }
}
