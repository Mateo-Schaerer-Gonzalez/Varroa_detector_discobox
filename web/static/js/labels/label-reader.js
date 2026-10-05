// The label page's "Read the names from the plates": the server reads what is
// written beside each plate (Google Gemini, pipeline.read_labels) and the names
// are filled in where none is typed yet, for the user to check. A setting: off
// until its box is ticked, and the tick is saved on the server (config.yaml). It
// takes an API key on the server.

class LabelReader {
  constructor() {
    this.on = null;  // the box as changed on this page; before, as the session says it is saved
    $("read-labels").addEventListener("change", (event) => this.set(event.target.checked));
  }

  // Tick or untick the box: saved for the next time, and the names are read at once.
  async set(on) {
    this.on = on;
    if (on) this.read(ctx);
    try {
      await post("/api/label-reading", { enabled: on });
    } catch (error) {
      workspaces.setStatus(ctx.mode, "hint error", esc(`Could not save that setting: ${error.message}`));
    }
  }

  wanted(session) {
    const { available, enabled } = session.label_reading;
    return available && (this.on ?? enabled);
  }

  draw() {
    const { available } = ctx.session.label_reading;
    $("read-labels").checked = this.wanted(ctx.session);
    $("read-labels").disabled = !available;
    $("read-labels-hint").textContent = available
      ? "Google Gemini reads the writing beside each plate with no name yet (it takes the internet). Check what it read."
      : "Takes a free Google Gemini API key (aistudio.google.com/apikey): put GEMINI_API_KEY=… in the file .env in the app's folder and start the app again.";
  }

  // Read the names of `workspace`'s plates with mites and no name, and fill them in.
  async read(workspace) {
    const { session, sessionId } = workspace;
    if (!session || !this.wanted(session) || this.reading === session) return;
    if (!workspace.labelZones().some((zone) => !zone.label.trim())) return;
    this.reading = session;
    this.status(workspace, "hint", `<span class="spinner"></span> Reading the names on the plates…`);
    try {
      const { labels } = await post(`/api/session/${sessionId}/read-labels`);
      if (workspace.session !== session) return;  // another folder, or other zones, by now
      // Not a plate named meanwhile, nor the one being named.
      const named = workspace.labelZones().filter((zone) => !zone.label.trim() && labels[zone.id]
        && !(ctx === workspace && labelPage.editor.zoneId === zone.id));
      named.forEach((zone) => { zone.label = labels[zone.id]; });
      if (named.length) await post(`/api/session/${sessionId}/labels`, { labels: workspace.collectLabels() });
      if (workspace.session !== session) return;
      this.status(workspace, "hint", named.length
        ? `${plural(named.length, "name")} read from the plates: check ${named.length === 1 ? "it" : "them"}.`
        : "No name could be read from the plates.");
      if (ctx === workspace && named.length && location.hash.includes("/label")) labelPage.draw();
    } catch (error) {
      if (workspace.session === session) this.status(workspace, "hint error", esc(`The names were not read: ${error.message}`));
    } finally {
      if (this.reading === session) this.reading = null;
    }
  }

  status(workspace, className, html) {
    workspaces.setStatus(workspace.mode, className, html);
  }
}
