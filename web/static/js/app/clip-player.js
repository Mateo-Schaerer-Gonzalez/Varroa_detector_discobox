// Playing a recording. One clip plays at a time on any page: the frames of one
// recording, of one zone or of the whole plate. Used by the result pages and by
// the ground-truth page of calibration. A clip plays once and stops on its last
// frame, or loops when Loop is ticked: a loop jumping back to the first frame can
// look like movement. Every clip shows the same controls (controls()), and the
// choice to loop is kept in the browser.

class ClipPlayer {
  constructor() {
    this.timer = null;
    this.token = 0;       // counts the clips asked for, so a late one is dropped
    this.frames = [];
    this.index = 0;
    this.show = null;
    this.interval = 100;
    this.playing = false;
    this.loop = ClipPlayer.savedLoop();
    this.warmed = new Map();  // url -> a clip being fetched ahead (warm)
    // The controls are redrawn with their pages, so one listener serves them all.
    document.addEventListener("click", (event) => {
      if (event.target.closest("[data-clip-play]")) this.toggle();
    });
    document.addEventListener("change", (event) => {
      if (event.target.matches("[data-clip-loop]")) this.setLoop(event.target.checked);
    });
  }

  static LOOP_KEY = "clipLoop";

  static savedLoop() {
    try { return localStorage.getItem(ClipPlayer.LOOP_KEY) === "1"; } catch { return false; }
  }

  // The Play/Pause button and the Loop box, for under any clip.
  controls() {
    return `<span class="clip-controls">
      <button type="button" class="secondary small" data-clip-play ${this.playable() ? "" : "disabled"}>${this.playing ? "Pause" : "Play"}</button>
      <label title="Play the recording over and over. Its jump from the last frame back to the first can look like movement.">
        <input type="checkbox" data-clip-loop ${this.loop ? "checked" : ""}> Loop</label>
    </span>`;
  }

  // Every control on the page showing what the player does now.
  syncControls() {
    document.querySelectorAll("[data-clip-play]").forEach((button) => {
      button.textContent = this.playing ? "Pause" : "Play";
      button.disabled = !this.playable();
    });
    document.querySelectorAll("[data-clip-loop]").forEach((box) => { box.checked = this.loop; });
  }

  setLoop(loop) {
    this.loop = loop;
    try { localStorage.setItem(ClipPlayer.LOOP_KEY, loop ? "1" : "0"); } catch { /* kept for this page only */ }
    this.syncControls();
  }

  // Stop and drop the clip: until the next one starts there is nothing to play.
  stop() {
    clearInterval(this.timer);
    this.timer = null;
    this.token += 1;
    Object.assign(this, { frames: [], show: null, playing: false });
    this.syncControls();
  }

  playable() {
    return this.frames.length > 1;
  }

  startTimer() {
    clearInterval(this.timer);
    if (!this.playing || !this.playable()) return;
    this.timer = setInterval(() => {
      this.index = (this.index + 1) % this.frames.length;
      this.show(this.frames[this.index]);
      // Played once: it stays on its last frame.
      if (this.index === this.frames.length - 1 && !this.loop) {
        clearInterval(this.timer);
        this.playing = false;
        this.syncControls();
      }
    }, this.interval);
  }

  // Play or pause; a clip played to its end plays again from the start. Returns
  // whether it now plays.
  toggle() {
    if (!this.playable()) return false;
    this.playing = !this.playing;
    if (this.playing) {
      if (this.index === this.frames.length - 1) {
        this.index = 0;
        this.show(this.frames[0]);
      }
      this.startTimer();
    } else clearInterval(this.timer);
    this.syncControls();
    return this.playing;
  }

  // Fetch a clip's description from `url` and preload its frames, whose URLs
  // `frameUrl` makes from their names. Null when another clip was asked for meanwhile.
  async load(url, frameUrl) {
    this.stop();
    const token = this.token;
    try {
      // A clip fetched ahead is used once: the server may make it anew later.
      const ahead = this.warmed.get(url);
      this.warmed.delete(url);
      const clip = (ahead && await ahead) || await this.fetchClip(url, frameUrl);
      return token === this.token ? clip : null;
    } catch (error) {
      if (token !== this.token) return null;
      throw error;
    }
  }

  async fetchClip(url, frameUrl) {
    const data = await readJson(await fetch(url), "Could not load the recording");
    const frames = data.frames.map(frameUrl);
    await Promise.all(frames.map((src) => new Promise((resolve) => {
      const image = new Image();
      image.onload = image.onerror = resolve;
      image.src = src;
    })));
    return { ...data, frames };
  }

  // Fetch a clip ahead of its being shown, so load() has it at once. The few
  // fetched last are kept; one that fails is fetched again by load().
  warm(url, frameUrl) {
    if (this.warmed.has(url)) return;
    this.warmed.set(url, this.fetchClip(url, frameUrl).catch(() => null));
    if (this.warmed.size > 4) this.warmed.delete(this.warmed.keys().next().value);
  }

  // Show a loaded clip's frames in turn through `show(src)`, from the start.
  start(clip, show) {
    Object.assign(this, { frames: clip.frames, index: 0, show, interval: clip.interval_ms, playing: clip.frames.length > 1 });
    show(clip.frames[0]);
    this.startTimer();
    this.syncControls();
  }

  // Put a clip over the full-image coordinates of an SVG crop; returns its `show`.
  static onSvg(svg, clip) {
    const image = svg.querySelector("image");
    Object.entries({ x: clip.x, y: clip.y, width: clip.width, height: clip.height })
      .forEach(([key, value]) => image.setAttribute(key, value));
    return (src) => image.setAttribute("href", src);
  }
}
