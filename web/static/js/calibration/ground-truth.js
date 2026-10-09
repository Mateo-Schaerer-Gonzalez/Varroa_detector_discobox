// The ground truth of the dataset on the ground-truth page, as the server's draft
// describes it (classes/truth_draft.py): every mite's statuses, what is done, and
// how many mites have changes waiting for "Save changes". A click or a fill
// button goes to the server, one after another, and the page shows the view it
// sends back; each view has a version, so a late reply never replaces a newer one.

class GroundTruth {
  constructor() {
    this.view = null;                // the server's view of the draft; null without a dataset
    this.version = 0;                // the version of the view shown
    this.queue = Promise.resolve();  // the changes, sent one after another
    this.saves = Promise.resolve();  // the saves, one after another
    this.savesUnderWay = 0;

    $("save-truth-btn").addEventListener("click", () => this.save().catch(() => {}));
    // Closing or reloading the window with changes not saved yet, or still saving, asks first.
    window.addEventListener("beforeunload", (event) => {
      if (!this.hasUnsaved() && !this.savesUnderWay) return;
      event.preventDefault();
      event.returnValue = "";
    });
    // Coming back to this window, or to calibration from the analysis: show the
    // ground truth as saved, which the analysis or another window, e.g. marking a
    // detection "not a mite" before a run, may have changed.
    window.addEventListener("focus", () => this.reload());
    document.addEventListener("visibilitychange", () => this.reload());
  }

  // Another dataset replaces the one on screen: its view as the server opened it.
  load(view) {
    this.view = view;
    this.version = view ? view.version : 0;
    this.drawSaveButton();
  }

  // Show a view the server sent, unless a newer one is shown; returns whether it was.
  take(view) {
    if (!view || view.version <= this.version) return false;
    this.view = view;
    this.version = view.version;
    if (view.changed) cal.markReportStale();
    this.drawSaveButton();
    return true;
  }

  statesOf(mite) {
    return this.view.states[mite.id] || Array(cal.nRecordings).fill(null);
  }

  stateAt(mite, recording) {
    return this.statesOf(mite)[recording] || null;
  }

  // The view's numbers of one zone: done per recording, counts per recording.
  zone(zoneId) {
    return this.view.zones[zoneId];
  }

  hasUnsaved() {
    return Boolean(this.view && this.view.unsaved);
  }

  // A click ({ action: "cycle", mite, recording, backwards }) or a fill button
  // ({ action: "fill", zone, recording, kind }), after the changes before it.
  // Resolves with whether its view is the one shown now.
  edit(change) {
    const id = cal.id;
    const sent = this.queue.then(() => post(`/api/calibration/${id}/truth/edit`, change))
      .then((view) => id === cal.id && this.take(view));
    this.queue = sent.catch(() => {});
    return sent;
  }

  // Resolves once every change sent so far has its reply.
  settled() {
    return this.queue;
  }

  drawSaveButton() {
    const button = $("save-truth-btn");
    const n = this.view ? this.view.unsaved : 0;
    button.disabled = !n || this.savesUnderWay > 0;
    button.textContent = this.savesUnderWay ? "Saving…"
      : n ? `Save changes (${n} mite${n === 1 ? "" : "s"})` : "All changes saved";
  }

  // Save the changes made so far, after any save under way; resolves once saved,
  // or throws, the changes then still waiting on the server for the next try.
  save() {
    const id = cal.id;
    const run = Promise.all([this.queue, this.saves]).then(async () => {
      if (!this.hasUnsaved() || id !== cal.id) return;
      const status = $("evaluate-status");
      this.savesUnderWay++;
      this.drawSaveButton();
      let view;
      let taken = false;
      try {
        // keepalive: a save under way still lands when the window reloads or closes
        view = await readJson(await fetch(`/api/calibration/${id}/truth`, { method: "POST", keepalive: true }));
        taken = id === cal.id && this.take(view);
      } catch (error) {
        status.className = "hint error";
        status.dataset.saveError = "1";
        status.textContent = `Could not save the ground truth: ${error.message}. Click "Save changes" to try again.`;
        throw error;
      } finally {
        this.savesUnderWay--;
        this.drawSaveButton();
      }
      if (status.classList.contains("error") && status.dataset.saveError) {
        status.className = "hint";
        delete status.dataset.saveError;
        if (cal.data && id === cal.id) truthPage.drawCounts();
      }
      // Saved on top of a change made elsewhere meanwhile: show it.
      if (taken && view.changed && location.hash.startsWith("#/cal/truth")) truthPage.draw(String(cal.miteId), String(cal.recording));
    });
    this.saves = run.catch(() => {});
    return run;
  }

  async reload() {
    if (!cal.data || !cal.id || document.visibilityState !== "visible") return;
    const id = cal.id;
    try {
      const view = await getJson(`/api/calibration/${id}/truth`, "Could not load the ground truth");
      if (id === cal.id && this.take(view) && view.changed && location.hash.startsWith("#/cal/truth")) {
        truthPage.draw(String(cal.miteId), String(cal.recording));
      }
    } catch {
      // the page keeps what it shows; the next change goes through as usual
    }
  }
}
