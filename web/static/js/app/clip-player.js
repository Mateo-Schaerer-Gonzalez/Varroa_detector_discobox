// Playing a recording. One clip plays at a time, in a loop, on any page: the
// frames of one recording, of one zone or of the whole plate. Used by the result
// pages and by the ground-truth page of calibration.

class ClipPlayer {
  constructor() {
    this.timer = null;
    this.token = 0;       // counts the clips asked for, so a late one is dropped
    this.frames = [];
    this.index = 0;
    this.show = null;
    this.interval = 100;
    this.playing = true;
    this.warmed = new Map();  // url -> a clip being fetched ahead (warm)
  }

  stop() {
    clearInterval(this.timer);
    this.timer = null;
    this.token += 1;
  }

  startTimer() {
    clearInterval(this.timer);
    if (!this.playing || this.frames.length < 2) return;
    this.timer = setInterval(() => {
      this.index = (this.index + 1) % this.frames.length;
      this.show(this.frames[this.index]);
    }, this.interval);
  }

  // Play or pause; returns whether it now plays.
  toggle() {
    this.playing = !this.playing;
    if (this.playing) this.startTimer();
    else clearInterval(this.timer);
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

  // Show a loaded clip's frames in turn through `show(src)`.
  start(clip, show) {
    Object.assign(this, { frames: clip.frames, index: 0, show, interval: clip.interval_ms });
    show(clip.frames[0]);
    this.startTimer();
  }

  // Put a clip over the full-image coordinates of an SVG crop; returns its `show`.
  static onSvg(svg, clip) {
    const image = svg.querySelector("image");
    Object.entries({ x: clip.x, y: clip.y, width: clip.width, height: clip.height })
      .forEach(([key, value]) => image.setAttribute(key, value));
    return (src) => image.setAttribute("href", src);
  }
}
