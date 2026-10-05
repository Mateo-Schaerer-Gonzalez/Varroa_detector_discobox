// The recordings kept in recordings/: every live test run and every folder dropped
// into the page. They are listed on the first page of each mode (Live, Analysis,
// Calibration) with when and how they were recorded, to analyse or calibrate on
// again: opening one goes through the analysis or calibration. What is said about
// each is the server's (pipeline.describe_recording, classes/recording_info.py).

class RecordingsList {
  static date(iso) {
    return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
  }

  static time(iso) {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  constructor() {
    this.recordings = null;
    this.root = "";
    this.resultsRoot = "";
    this.loading = null;
    // Analyse or calibrate on a recording from any mode's list: that mode's first
    // page shows at once, with the opening under way, and moves on once it is open.
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-open-recording]");
      if (!button) return;
      const path = button.dataset.path;
      if (button.dataset.openRecording === "cal") {
        if (location.hash !== "#/cal/open") location.hash = "#/cal/open";
        cal.openFolder(path);
      } else {
        if (location.hash !== "#/open") location.hash = "#/open";
        analysis.openFolder(path);
      }
      window.scrollTo(0, 0);
    });
  }

  async refresh() {
    // Several pages may ask at once; one request answers them all.
    if (!this.loading) {
      this.loading = (async () => {
        const data = await getJson("/api/recordings", "Could not list the recordings");
        Object.assign(this, { recordings: data.recordings, root: data.root, resultsRoot: data.results_root });
      })().finally(() => { this.loading = null; });
    }
    let failed = null;
    try {
      await this.loading;
    } catch (error) {
      failed = error;
    }
    document.querySelectorAll("[data-recordings]").forEach((block) => this.draw(block, failed));
  }

  draw(block, failed) {
    const list = this.recordings || [];
    block.innerHTML = `
    <h2>Previous recordings <span class="hint">${list.length ? plural(list.length, "recording") : ""}</span></h2>
    <p class="hint">Every test run recorded here, and every folder dropped into the page, is kept in
      <code title="${esc(this.root)}">recordings/</code>. Analyse one again or calibrate on it;
      its results go to <code title="${esc(this.resultsRoot)}">results/&lt;name&gt;/</code>.</p>
    ${failed ? `<p class="hint error">${esc(failed.message)}</p>`
      : !list.length ? `<p class="muted">Nothing recorded yet. A test run appears here once its first recording is saved.</p>`
        : `<div class="table-wrap"><table class="recordings">
            <thead><tr><th>Recording</th><th>Recorded</th><th class="num">Recordings</th><th>Settings</th>
              <th>Plates</th><th>Results</th><th></th></tr></thead>
            <tbody>${list.map((r) => this.row(r)).join("")}</tbody>
          </table></div>`}`;
  }

  row(r) {
    const busy = r.recording_now ? ` disabled title="Being recorded: open it once the test run is over."` : "";
    return `<tr>
    <td class="name" title="${esc(r.path)}"><span class="rec-name">${esc(r.name)}</span>${this.stateBadge(r)}${this.howRecorded(r)}</td>
    <td class="nowrap">${this.recordedText(r)}</td>
    <td class="num">${this.recordingCount(r)}</td>
    <td class="settings">${this.settingsText(r)}</td>
    <td class="plates">${this.platesText(r)}</td>
    <td class="nowrap">${this.resultsText(r)}</td>
    <td class="row-actions">
      <button type="button" class="secondary small" data-open-recording="analysis" data-path="${esc(r.path)}"${busy}>Analyse</button>
      <button type="button" class="secondary small" data-open-recording="cal" data-path="${esc(r.path)}"${busy}>Calibrate</button>
    </td>
  </tr>`;
  }

  // Whether a live run is still being recorded, or ended before it was through.
  stateBadge(r) {
    if (r.state === "recording") return ` <span class="rec-state now">recording now</span>`;
    if (r.state === "interrupted") return ` <span class="rec-state cut" title="The app stopped while the test run was going on.">interrupted</span>`;
    if (r.state === "stopped") {
      return ` <span class="rec-state cut" title="Stopped after ${r.run.recordings_analysed} of ${r.run.recordings_planned} recordings.">stopped</span>`;
    }
    return "";
  }

  // For a live run: the camera (or the folder replayed), the pools, and what went wrong.
  howRecorded(r) {
    const run = r.run;
    if (!run) return "";
    const parts = [esc(run.camera), `pools of ${esc(run.pool_size_text)}`];
    if (run.frames_dropped) parts.push(`<span class="error">${plural(run.frames_dropped, "frame")} dropped</span>`);
    if (run.frames_incomplete) parts.push(`${run.frames_incomplete} incomplete`);
    const error = run.error ? `<span class="sub error">${esc(run.error)}</span>` : "";
    return `<span class="sub">${parts.join(" · ")}</span>${error}`;
  }

  recordedText(r) {
    const { date, time } = RecordingsList;
    const sameDay = r.started.slice(0, 10) === r.ended.slice(0, 10);
    const span = sameDay ? `${time(r.started)}–${time(r.ended)}` : `${time(r.started)} – ${date(r.ended)} ${time(r.ended)}`;
    return `${date(r.started)}<span class="sub">${span} · ${duration(r.seconds)}</span>`;
  }

  // "6", or "4 of 6" when fewer were recorded than planned.
  recordingCount(r) {
    const { planned } = r;
    return planned && planned !== r.n_recordings ? `${r.n_recordings} <span class="muted">of ${planned}</span>` : `${r.n_recordings}`;
  }

  // The Discobox settings it was recorded with: each recording, the time between
  // them, and the fan and LEDs, as the Discobox app's settings window has them.
  settingsText(r) {
    const zones = r.zones_per_plate > 1 ? `, ${r.zones_per_plate} zones per plate` : "";
    const burst = `${plural(r.frames, "frame")} at ${r.fps} fps (${+(r.frames / r.fps).toFixed(1)} s)${zones}`;
    const s = r.settings;
    if (!s) return `${burst}<span class="sub">no settings saved with it</span>`;
    const every = s.recording_timeout != null ? `, every ${s.recording_timeout} min` : "";
    const death = s.death_minutes ? `, dead when still ${s.death_minutes} min${s.death_reset ? " (run until all dead)" : ""}` : "";
    return `${burst}${every}${death}<span class="sub">${this.lightsText(r.lights)}</span>`;
  }

  // "Fan and LEDs 20 s, intensity 255" when all three are alike; each on its own otherwise.
  lightsText(lights) {
    const oneLevel = lights.level != null ? `, intensity ${lights.level}` : "";
    if (lights.all_alike) return `Fan and LEDs ${lights.all_alike.seconds} s${oneLevel}`;
    const each = lights.devices.map(({ name, seconds, level }) => (!seconds ? `${name} off`
      : `${name} ${seconds} s${oneLevel || level == null ? "" : ` at ${level}`}`));
    return `${each.join(" · ")}${oneLevel}`;
  }

  // The plate labels, the "not a mite" marks and the ground truth kept with it.
  platesText(r) {
    const main = r.n_labelled_plates ? `${plural(r.n_labelled_plates, "plate")} labelled` : `<span class="muted">not labelled</span>`;
    const sub = [];
    if (r.groups.length) {
      const groups = r.groups.join(", ");
      sub.push(`<span title="${esc(groups)}">${esc(shorten(groups, 40))}</span>`);
    }
    if (r.n_not_a_mite) sub.push(`${r.n_not_a_mite} not a mite`);
    if (r.n_ground_truth) sub.push(`ground truth for ${plural(r.n_ground_truth, "mite")}`);
    return `${main}${sub.length ? `<span class="sub">${sub.join(" · ")}</span>` : ""}`;
  }

  resultsText(r) {
    const { date, time } = RecordingsList;
    if (!r.results) return `<span class="muted">not analysed</span>`;
    const url = `/api/recordings/${encodeURIComponent(r.name)}/results/${encodeURIComponent(r.results.file)}`;
    return `<a href="${url}" download>${esc(r.results.file)}</a><span class="sub">${date(r.results.saved_at)} ${time(r.results.saved_at)}</span>`;
  }
}
