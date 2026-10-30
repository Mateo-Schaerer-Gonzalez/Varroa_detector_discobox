// Mites placed by hand on the label page, where the detector missed them. With
// "Place a mite by hand" on, a click on a plate puts one there: the server moves
// it onto the darkest spot near the click, and refuses one off the plates or on
// another mite. A click on a ring placed so (dashed) takes it away. Of a folder,
// and of a test run until it starts, they are kept with the recordings, and every
// later detection finds them (pipeline.place_mite); while mites are added to a
// run, they join those found to add (pipeline.live_hand_mite).

class HandMites {
  constructor() {
    this.placing = false;
    this.queue = Promise.resolve();  // one change at a time: each is made on the mites the one before left
    $("place-mite-btn").addEventListener("click", () => this.setPlacing(!this.placing));
    // Caught before the plates' own mousedown, which opens a plate's name.
    $("label-plate").addEventListener("mousedown", (event) => this.click(event), true);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.placing && !$("view-label").hidden) this.setPlacing(false);
    });
  }

  // Of a folder of whole frames, of a test run not started, and among the mites found to add.
  get offered() {
    const { session } = ctx;
    return Boolean(session && (session.adding || session.place_by_hand));
  }

  setPlacing(on) {
    if (on) labelPage.editor.close();
    this.placing = on;
    this.draw();
  }

  draw() {
    const button = $("place-mite-btn");
    $("hand-mites-option").hidden = !this.offered;
    if (!this.offered) this.placing = false;
    button.textContent = this.placing ? "Done placing mites" : "Place a mite by hand";
    button.setAttribute("aria-pressed", String(this.placing));
    $("label-plate").classList.toggle("placing", this.placing);
  }

  // A click on the plate, in image pixels.
  click(event) {
    if (!this.placing || event.button !== 0 || event.target.closest(".label-mite")) return;
    const img = $("label-plate").querySelector("img");
    if (!img) return;
    event.preventDefault();
    event.stopPropagation();
    const box = img.getBoundingClientRect();
    const { image } = ctx.session;
    this.send({
      x: ((event.clientX - box.left) / box.width) * image.width,
      y: ((event.clientY - box.top) / box.height) * image.height,
    });
  }

  remove(mite) {
    this.send({ x: mite.x, y: mite.y, remove: true });
  }

  send(point) {
    const workspace = ctx;
    const { session } = workspace;
    const status = $("run-status");
    Hint.busy(status, point.remove ? "Taking the mite away…" : "Placing the mite…");
    this.queue = this.queue.then(async () => {
      try {
        if (session.adding) {
          const found = await post(`/api/live/${live.id}/hand-mite`, { ...point, mites: session.mites });
          if (workspace.session !== session) return;
          Object.assign(session, found);
          labelPage.draw();
          labelPage.showLoadedStatus();
        } else {
          const opened = await post(`/api/session/${workspace.sessionId}/hand-mite`, point);
          if (workspace.session !== session) return;
          SessionLabels.markChanged();
          if (workspace.mode === "live") live.takePreview(opened);
          else analysis.takeSession(opened);
        }
      } catch (error) {
        if (workspace.session === session) Hint.error(status, error.message);
      }
    });
  }
}
