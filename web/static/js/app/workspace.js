// The analysis of a folder and a live run each have their own session and
// results: a Workspace each. The label and result pages show those of `ctx`, the
// workspace of the mode shown last; the other mode's waits. The status line under
// the label page's button goes with them, since both modes use that page.

class Workspace {
  constructor(mode) {
    this.mode = mode;          // "analysis" or "live"
    this.runStatus = null;     // the status line under the label page's button, while another mode is shown
    this.clear();
  }

  clear() {
    this.sessionId = null;
    this.session = null;       // what opening a folder returned: preview, zones, labels
    this.results = null;       // what the last analysis run returned
    this.runStamp = 0;         // cache-buster so a re-run never shows old images
    this.shown = 0;            // the recording the result pages show; the last after a run
    this.labelsChanged = false;
  }

  // A label or result page of this mode: "results" -> "#/results" in the
  // analysis, "#/live/results" live.
  href(path) {
    return (this.mode === "live" ? "#/live/" : "#/") + path;
  }

  fileUrl(name) {
    return `/api/session/${this.sessionId}/file/${name}?t=${this.runStamp}`;
  }

  // --- the session: plates and their labels

  // Only zones with a detected mite can be labelled; the others have nothing to analyse.
  labelZones() {
    return this.session.zones.filter((zone) => zone.n_mites > 0);
  }

  labelGroups() {
    return [...new Set(this.labelZones().map((zone) => zone.label.trim()).filter(Boolean))].sort();
  }

  // The labels to save or run with: zone id -> label, for labelled zones with mites.
  collectLabels() {
    const labels = {};
    this.labelZones().forEach((zone) => { if (zone.label.trim()) labels[zone.id] = zone.label.trim(); });
    return labels;
  }

  controlIds() {
    return this.session.zones.filter((zone) => zone.control).map((zone) => zone.id);
  }

  // --- the results

  zone(id) {
    return this.results.zones.find((zone) => zone.id === id);
  }

  mitesIn(zoneId) {
    return this.results.mites.filter((mite) => mite.zone_id === zoneId);
  }

  // Zones worth a look: those with a detected mite.
  zonesWithMites() {
    return this.results.zones.filter((zone) => zone.n_mites);
  }

  // Every labelled zone counts, including groups where no mite was found, so a
  // group keeps the same colour here as on the labelling page.
  resultGroups() {
    const { results } = this;
    return [...new Set([...results.groups.map((g) => g.group), ...results.zones.map((z) => z.label).filter(Boolean)])].sort();
  }

  // The groups with a detected mite, in the server's order (named groups
  // alphabetically, "unlabeled" last), each with its zones and mites.
  groupRows() {
    return this.results.group_rows.map((row) => ({
      ...row,
      zones: row.zones.map((id) => this.zone(id)),
      mites: row.zones.flatMap((id) => this.mitesIn(id)),
    }));
  }

  // The group row of `group`, or undefined when it has no mites.
  groupRow(group) {
    return this.groupRows().find((row) => row.group === group);
  }

  lastIndex() {
    return this.results.times.length - 1;
  }
}

// The workspace of the mode whose label and result pages are shown.
let ctx = null;

class Workspaces {
  constructor() {
    this.byMode = { analysis: new Workspace("analysis"), live: new Workspace("live") };
    ctx = this.byMode.analysis;
  }

  get(mode) {
    return this.byMode[mode];
  }

  // Show `mode`'s session and results on the label and result pages.
  use(mode) {
    if (ctx.mode === mode) return;
    const status = $("run-status");
    ctx.runStatus = { className: status.className, html: status.innerHTML };
    ctx = this.byMode[mode];
    const saved = ctx.runStatus || { className: "hint", html: "" };
    status.className = saved.className;
    status.innerHTML = saved.html;
  }

  // The status line under the label page's button, of `mode` even while
  // another mode is shown.
  setStatus(mode, className, html) {
    if (ctx.mode === mode) {
      $("run-status").className = className;
      $("run-status").innerHTML = html;
    } else this.byMode[mode].runStatus = { className, html };
  }
}
