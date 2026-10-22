// The live mode's first page: the camera, the test run's settings, the fan and
// LEDs. One button connects: the camera and the Discobox's Arduino are found by
// themselves. The run's name, whether it is saved and every setting can change
// before and after connecting, until the run starts. How long the run takes
// comes from the server (Settings.plan in classes/live/settings.py).

class LiveSetupPage {
  static FIELDS = ["run_minutes", "death_minutes", "follow_px", "recording_timeout", "vent_time", "led1_time", "led2_time"];
  static DEVICES = [["vent", "Fan"], ["led1", "LED 1"], ["led2", "LED 2"]];

  constructor() {
    this.settingsTimers = new Map();  // setting -> its save to come: a change of one setting never puts off another's
    this.optionsTimer = null;
    this.optionsChanged = false;  // the name or the saving of the connected run, not yet told to the server
    // Once connected, the run's name and whether it is saved are the server's to keep: told as they change.
    $("live-run-name").addEventListener("input", () => this.changeOptions());
    $("live-save").addEventListener("change", () => this.changeOptions());
    // Settings are saved as they change, like the Discobox settings window does.
    document.addEventListener("input", (event) => {
      const input = event.target.closest("[data-setting]");
      if (!input) return;
      if (input.dataset.device) $(`live-level-${input.dataset.device}`).textContent = input.value;
      const name = input.dataset.setting;
      clearTimeout(this.settingsTimers.get(name));
      this.settingsTimers.set(name, setTimeout(() => this.saveSetting(input), input.type === "range" ? 150 : 500));
    });
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-light]");
      if (button && live.id) this.toggleLight(button.dataset.light, button.getAttribute("aria-pressed") !== "true");
    });
  }

  async draw() {
    recordings.refresh();
    if (!live.options) {
      $("live-open-status").innerHTML = `<span class="spinner"></span> Looking for cameras…`;
      try {
        live.options = await getJson("/api/live/options", "Could not list the cameras");
      } catch (error) {
        Hint.error($("live-open-status"), `Could not ask the server: ${error.message}`);
        return;
      }
      this.fill(live.notice);
      live.notice = null;
      const open = live.options.open.find((run) => run.state !== "finished") || live.options.open[0];
      if (open && !live.id) { await live.attach(open.live_id); return; }
    }
    this.drawForm();
  }

  // `notice`: what to say first, e.g. that the last run was lost.
  fill(notice = null) {
    const { cameras, camera_error: cameraError, run_name: runName } = live.options;
    if (!live.id) $("live-run-name").value = runName;
    const noCamera = cameras.length ? "" : cameraError || "No camera found.";
    $("live-open-status").className = notice ? "hint error" : "hint";
    $("live-open-status").textContent = [notice, noCamera].filter(Boolean).join(" ");
    this.drawSettings();
  }

  drawSettings() {
    const { settings, ranges } = live.options;
    $("live-settings").innerHTML = LiveSetupPage.FIELDS.map((name) => {
      const { label, unit, min, max } = ranges[name];
      return `<label for="live-set-${name}">${esc(label)}${unit ? ` <span class="muted">(${unit})</span>` : ""}</label>
      <input id="live-set-${name}" data-setting="${name}" type="number" min="${min}" max="${max}" step="1"
        value="${settings[name]}" class="number-input" title="${min} to ${max}">`;
    }).join("");
    $("live-lights").innerHTML = LiveSetupPage.DEVICES.map(([device, name]) => `
    <div class="light-row">
      <label for="live-set-${device}">${name}</label>
      <input id="live-set-${device}" data-setting="${device}" data-device="${device}" type="range" min="0" max="255" value="${settings[device]}">
      <output id="live-level-${device}">${settings[device]}</output>
      ${device === "vent" ? `<button type="button" class="secondary small light-toggle" data-light="${device}" aria-pressed="false">Off</button>` : ""}
    </div>`).join("");
    this.drawRecordingTime();
  }

  drawRecordingTime() {
    const { settings: s, plan } = live.options;
    const { recordings: count, minutes: length } = plan;
    // The run ends once every mite is dead, which needs a time to count one as dead.
    const whole = !s.death_minutes
      ? `Set how long a mite must be still to count as dead: the run needs it to stop following dead mites, and ends once every mite is dead.`
      : `The run ends once every mite of every zone is dead, at most after the experiment's ${duration(s.run_minutes * 60)} and `
        + `${duration(s.death_minutes * 60)} to tell a mite still at its end from a dead one: ${duration(length * 60)}, ${count} recordings.`;
    const follow = s.follow_px ? ` Each mite is followed up to ${s.follow_px} px from one recording to the next.` : " The mites are not followed: their boxes stay where they were found.";
    $("live-recording-time").textContent = `Each recording: ${+plan.recording_seconds.toFixed(2)} s of frames; with the fan and LEDs, ${+plan.cycle_seconds.toFixed(1)} s `
      + `of every ${s.recording_timeout} min. ${whole}${follow}`;
    $("live-recording-time").classList.toggle("error", !s.death_minutes);
  }

  // What can be changed now: the run's name, whether it is saved and its settings, all until the run starts.
  drawForm() {
    const connected = Boolean(live.id);
    const ready = !live.started;
    document.querySelectorAll(".live-form input").forEach((input) => { input.disabled = !ready; });
    $("live-connect-btn").hidden = connected;
    $("live-close-btn").hidden = !connected;
    $("live-close-btn").disabled = live.running;
    document.querySelectorAll("[data-setting]").forEach((input) => { input.disabled = !ready; });
    const lights = live.status && live.status.lights;
    document.querySelectorAll("[data-light]").forEach((button) => {
      const state = lights && lights[button.dataset.light];
      button.disabled = !connected || !ready || !lights;
      button.classList.toggle("on", Boolean(state && state.on));
      button.textContent = state && state.on ? "On" : "Off";
      button.setAttribute("aria-pressed", String(Boolean(state && state.on)));
    });
    $("live-label-btn").disabled = !connected;
    $("live-label-btn").textContent = live.started ? "Show the live results" : "Next: label the plates";
    $("live-feed-note").textContent = connected ? "" : "Connect to see the camera.";
    const shown = connected && $("live-feed").src;
    $("live-feed").hidden = !shown;
    $("live-feed").parentElement.classList.toggle("filled", Boolean(shown));
    if (connected && lights && !lights.connected && !$("live-settings-status").textContent) {
      Hint.note($("live-settings-status"), "No fan/LED controller found: the run goes ahead without them.");
    }
  }

  // The name or the saving of a connected run changed: tell the server once the typing pauses.
  changeOptions() {
    if (!live.id || live.started) return;  // before connecting, connecting sends them
    this.optionsChanged = true;
    clearTimeout(this.optionsTimer);
    this.optionsTimer = setTimeout(() => this.saveOptions().catch(() => {}), 500);
  }

  // Tell the server the name and the saving typed last, if it does not have them
  // yet. Fails, having said why, when it refuses them, e.g. a name already taken.
  async saveOptions() {
    clearTimeout(this.optionsTimer);
    if (!this.optionsChanged || !live.id || live.started) return;
    const status = $("live-open-status");
    this.optionsChanged = false;
    try {
      const saved = await post(`/api/live/${live.id}/options`, { run_name: $("live-run-name").value.trim(), save_frames: $("live-save").checked });
      live.status = saved;
      router.setFolder("live", saved.run_name, saved.run_dir);
      Hint.note(status, LiveRun.connectedText(saved));
    } catch (error) {
      this.optionsChanged = true;
      Hint.error(status, error.message);
      throw error;
    }
  }

  async saveSetting(input) {
    const name = input.dataset.setting;
    const value = input.type === "checkbox" ? Number(input.checked) : Number(input.value);
    const status = $("live-settings-status");
    try {
      const saved = await post("/api/live/settings", { settings: { [name]: value }, session_id: live.id });
      Object.assign(live.options, { settings: saved.settings, plan: saved.plan });
      Hint.note(status, "Saved to settings.txt.");
      this.drawRecordingTime();
      // A device switched on to check it follows its slider at once.
      const device = input.dataset.device;
      if (device && live.id && live.status.lights && live.status.lights[device].on) {
        await post(`/api/live/${live.id}/light`, { device, level: value });
      }
    } catch (error) {
      Hint.error(status, error.message);
    }
  }

  async toggleLight(device, on) {
    try {
      const { lights } = await post(`/api/live/${live.id}/light`, { device, on, level: Number($(`live-set-${device}`).value) });
      live.status.lights = lights;
      this.drawForm();
    } catch (error) {
      Hint.error($("live-settings-status"), error.message);
    }
  }
}
