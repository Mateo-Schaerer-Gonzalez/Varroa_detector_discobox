// The live mode's first page: the camera, the test run's settings, the fan and
// LEDs. One button connects: the camera and the Discobox's Arduino are found by
// themselves. Replaying a folder instead is folded away below it. How long the
// run takes comes from the server (Settings.plan in classes/live/settings.py).

class LiveSetupPage {
  static FIELDS = ["run_minutes", "death_minutes", "death_reset", "recording_timeout", "vent_time", "led1_time", "led2_time", "frame_count", "fps"];
  static DEVICES = [["vent", "Fan"], ["led1", "LED 1"], ["led2", "LED 2"]];

  constructor() {
    this.settingsTimer = null;
    // Settings are saved as they change, like the Discobox settings window does.
    document.addEventListener("input", (event) => {
      const input = event.target.closest("[data-setting]");
      if (!input) return;
      if (input.dataset.device) $(`live-level-${input.dataset.device}`).textContent = input.value;
      clearTimeout(this.settingsTimer);
      this.settingsTimer = setTimeout(() => this.saveSetting(input), input.type === "range" ? 150 : 500);
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
        $("live-open-status").className = "hint error";
        $("live-open-status").textContent = `Could not ask the server: ${error.message}`;
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
    $("live-run-name").value = runName;
    if (!cameras.length) $("live-replay").open = true;
    const noCamera = cameras.length ? "" : `${cameraError || "No camera found."} You can replay a recorded folder instead.`;
    $("live-open-status").className = notice ? "hint error" : "hint";
    $("live-open-status").textContent = [notice, noCamera].filter(Boolean).join(" ");
    this.drawSettings();
  }

  drawSettings() {
    const { settings, ranges } = live.options;
    $("live-settings").innerHTML = LiveSetupPage.FIELDS.map((name) => {
      const { label, unit, min, max } = ranges[name];
      if (name === "death_reset") {
        return `<label class="live-check" for="live-set-${name}">
        <input id="live-set-${name}" data-setting="${name}" type="checkbox"${settings[name] ? " checked" : ""}>${esc(label)}
        <span class="hint">Each time a mite moves, the time it takes to count as dead starts again, so the run ends only once no mite has moved for that long.</span>
      </label>`;
      }
      return `<label for="live-set-${name}">${esc(label)}${unit ? ` <span class="muted">(${unit})</span>` : ""}</label>
      <input id="live-set-${name}" data-setting="${name}" type="number" min="${min}" max="${max}" step="1"
        value="${settings[name]}" class="number-input" title="${min} to ${max}">`;
    }).join("");
    $("live-lights").innerHTML = LiveSetupPage.DEVICES.map(([device, name]) => `
    <div class="light-row">
      <label for="live-set-${device}">${name}</label>
      <input id="live-set-${device}" data-setting="${device}" data-device="${device}" type="range" min="0" max="255" value="${settings[device]}">
      <output id="live-level-${device}">${settings[device]}</output>
      <button type="button" class="secondary small light-toggle" data-light="${device}" aria-pressed="false">Off</button>
    </div>`).join("");
    this.drawRecordingTime();
  }

  drawRecordingTime() {
    const { settings: s, plan } = live.options;
    // Until every mite is dead, the mites alone decide how long the run lasts: no experiment duration.
    const untilAllDead = plan.until_all_dead;
    const { recordings: count, minutes: length } = plan;
    const whole = untilAllDead
      ? `The run goes on until no mite has moved for ${duration(s.death_minutes * 60)}: at least ${duration(length * 60)} and ${count} recordings.`
      : !s.death_minutes
        ? `The whole run: ${duration(length * 60)}, ${count} recordings.`
        : `The whole run: the experiment's ${duration(s.run_minutes * 60)} and ${duration(s.death_minutes * 60)} to tell a mite still at its end from a dead one, `
          + `${duration(length * 60)}, ${count} recordings.`;
    $("live-recording-time").textContent = `Each recording: ${+plan.recording_seconds.toFixed(2)} s of frames; with the fan and LEDs, ${+plan.cycle_seconds.toFixed(1)} s `
      + `of every ${s.recording_timeout} min. ${whole}`;
    $("live-set-run_minutes").hidden = untilAllDead;
    document.querySelector('label[for="live-set-run_minutes"]').hidden = untilAllDead;
    // Going on until every mite is dead needs a time to count one as dead.
    $("live-set-death_reset").disabled = !plan.can_run_until_all_dead || live.started;
  }

  // What can be changed now: how to connect before connecting, the settings until the run starts.
  drawForm() {
    const connected = Boolean(live.id);
    const ready = !live.started;
    // A replay has no settings of its own: its folder's recordings are what they are.
    $("live-settings-block").hidden = connected && live.status && live.status.source === "replay";
    $("live-replay").hidden = connected;
    document.querySelectorAll(".live-form input").forEach((input) => { input.disabled = connected; });
    $("live-connect-btn").hidden = connected;
    $("live-close-btn").hidden = !connected;
    $("live-close-btn").disabled = live.running;
    document.querySelectorAll("[data-setting]").forEach((input) => {
      input.disabled = !ready || (input.dataset.setting === "death_reset" && !(live.options && live.options.plan.can_run_until_all_dead));
    });
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
    $("live-feed").hidden = !connected || !$("live-feed").src;
    if (connected && lights && !lights.connected && !$("live-settings-status").textContent) {
      $("live-settings-status").className = "hint";
      $("live-settings-status").textContent = "No fan/LED controller found: the run goes ahead without them.";
    }
  }

  async saveSetting(input) {
    const name = input.dataset.setting;
    const value = input.type === "checkbox" ? Number(input.checked) : Number(input.value);
    const status = $("live-settings-status");
    try {
      const saved = await post("/api/live/settings", { settings: { [name]: value }, session_id: live.id });
      Object.assign(live.options, { settings: saved.settings, plan: saved.plan });
      status.className = "hint";
      status.textContent = "Saved to settings.txt.";
      this.drawRecordingTime();
      // A device switched on to check it follows its slider at once.
      const device = input.dataset.device;
      if (device && live.id && live.status.lights && live.status.lights[device].on) {
        await post(`/api/live/${live.id}/light`, { device, level: value });
      }
    } catch (error) {
      status.className = "hint error";
      status.textContent = error.message;
    }
  }

  async toggleLight(device, on) {
    try {
      const { lights } = await post(`/api/live/${live.id}/light`, { device, on, level: Number($(`live-set-${device}`).value) });
      live.status.lights = lights;
      this.drawForm();
    } catch (error) {
      $("live-settings-status").className = "hint error";
      $("live-settings-status").textContent = error.message;
    }
  }
}
