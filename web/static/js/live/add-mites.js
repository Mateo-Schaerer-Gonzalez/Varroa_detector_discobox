// Adding mites during a test run, from the live panel: the server lights the
// plates between two recordings and detects the mites not followed yet
// (pipeline.live_find_mites). They show on the label page, over that frame, as
// the detections did before the run: a ring each, all kept, and a click on one
// crosses it out; a plate a new mite is on can be named there. The page's button
// adds the ones kept: they are followed from the next recording on
// (pipeline.live_add_mites), numbered after the mites of their zone.

class AddMites {
  constructor(holder) {
    this.holder = holder;
    this.before = null;  // the label page's session, shown again once done
    this.busy = false;
    this.message = "";
    holder.addEventListener("click", (event) => {
      const button = event.target.closest("[data-add-action]");
      if (button) this[button.dataset.addAction]();
    });
  }

  // The label page shows the mites found, not the run's own.
  get active() {
    return Boolean(live.workspace.session && live.workspace.session.adding);
  }

  // The mites kept, of those found.
  get chosen() {
    return live.workspace.session.mites.filter((mite) => !mite.rejected);
  }

  // Light the plates and look for mites; refused while a recording is due or going on.
  async find() {
    Object.assign(this, { busy: true, message: "" });
    this.draw();
    livePanel.draw();
    try {
      const found = await post(`/api/live/${live.id}/find-mites`);
      if (!found.mites.length) this.message = "No mite found that is not followed already.";
      else {
        const { workspace } = live;
        this.before = workspace.session;
        workspace.session = { ...workspace.session, ...found, adding: true };
        workspace.runStamp = Date.now();  // the image is written anew each time
        router.go("#/live/label");
      }
    } catch (error) {
      this.message = error.message;
    } finally {
      this.busy = false;
      this.draw();
      livePanel.draw();
    }
  }

  // A click on a ring: leave that mite out, or add it again.
  toggle(mite) {
    mite.rejected = !mite.rejected;
    const { session } = live.workspace;
    session.zones.forEach((zone) => {
      zone.n_mites = zone.followed + session.mites.filter((m) => m.zone_id === zone.id && !m.rejected).length;
    });
  }

  async add() {
    const boxes = this.chosen.map((m) => [m.x1, m.y1, m.x2, m.y2]);
    const status = $("run-status");
    this.busy = true;
    labelPage.drawRunButton();
    try {
      live.status = await post(`/api/live/${live.id}/add-mites`, { boxes });
      this.message = `${plural(boxes.length, "mite")} will be followed from the next recording on.`;
      this.finish();
    } catch (error) {
      status.className = "hint error";
      status.textContent = error.message;
    } finally {
      this.busy = false;
      if (this.active) labelPage.drawRunButton();
    }
  }

  cancel() {
    this.message = "";
    this.finish();
  }

  // Back to the run's own session (its labels read again: some may have been
  // given here) and to the results.
  finish() {
    const { workspace } = live;
    if (this.active) workspace.session = this.before;
    this.before = null;
    $("run-status").textContent = "";
    live.loadPreview().catch(() => {});
    router.go("#/live/results");
    this.draw();
    livePanel.draw();
  }

  // On the live panel: looking for mites, what came of it, or the way back to the mites found.
  draw() {
    const holder = this.holder;
    holder.hidden = !this.message && !this.busy && !this.active;
    holder.innerHTML = this.busy && !this.active ? `<p class="hint"><span class="spinner"></span> Lighting the plates and looking for mites…</p>`
      : this.active ? `<p class="hint">Mites found that are not followed yet: <a href="#/live/label">choose those to add</a>.
          <button type="button" class="secondary small" data-add-action="cancel">Cancel</button></p>`
      : `<p class="hint">${esc(this.message)}</p>`;
  }
}
