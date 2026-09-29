// What the user sets on the label page, saved to the session as it changes: each
// plate's label, the plates ticked as negative controls, and the detections
// marked "not a mite". Works on `ctx`, the workspace shown.

class SessionLabels {
  // A change after a run leaves the analysis's results out of date.
  static markChanged() {
    if (ctx.results && ctx.mode === "analysis") ctx.labelsChanged = true;
  }

  setLabel(zone, value) {
    const label = value.trim();
    if (label === zone.label) return;
    zone.label = label;
    SessionLabels.markChanged();
    this.saveLabels();
  }

  // The results compare every other zone with the negative controls; they take a
  // change at once, with no need to run again: the server sends the survival
  // numbers back with the change (a live run's come as new results).
  setControl(zone, checked) {
    zone.control = checked;
    this.saveControls();
  }

  async saveLabels() {
    if (!ctx.sessionId) return;
    try {
      await post(`/api/session/${ctx.sessionId}/labels`, { labels: ctx.collectLabels() });
    } catch (error) {
      $("run-status").textContent = `Could not save labels: ${error.message}`;
    }
  }

  async saveControls() {
    const workspace = ctx;
    const { results } = workspace;
    if (!workspace.sessionId) return;
    try {
      const saved = await post(`/api/session/${workspace.sessionId}/controls`, { controls: workspace.controlIds() });
      // Only for the results they were worked out from, not those of a run since.
      if (saved.survival && results && workspace.results === results) results.survival = saved.survival;
    } catch (error) {
      $("run-status").textContent = `Could not save the negative controls: ${error.message}`;
    }
  }

  // A false detection is marked "not a mite" in the session's ground truth, which
  // every later run leaves out; clicking it again takes the mark back and the
  // server puts back the movement labels a calibration gave it, so a click by
  // mistake loses nothing (pipeline.mark_detection). The mark shows at once; the
  // server's reply says how many mites each zone has left. A mite's requests go
  // one at a time. `changed` is called whenever what the page shows changes.
  toggleMite(mite, changed) {
    const rejected = !mite.rejected;
    const { session, sessionId: id } = ctx;
    const shown = () => ctx.session === session;  // not another folder or mode by now
    mite.rejected = rejected;
    SessionLabels.markChanged();
    changed();
    mite.saving = (mite.saving || Promise.resolve()).then(async () => {
      try {
        const marks = await post(`/api/session/${id}/reject`, { mite: mite.id, rejected });
        mite.rejected = marks.mites[mite.id];
        session.zones.forEach((zone) => { zone.n_mites = marks.zones[zone.id] ?? 0; });
        if (shown()) changed();
      } catch (error) {
        mite.rejected = !rejected;
        if (!shown()) return;
        changed();
        $("run-status").className = "hint error";
        $("run-status").textContent = `Could not save that detection: ${error.message}`;
      }
    });
  }
}
