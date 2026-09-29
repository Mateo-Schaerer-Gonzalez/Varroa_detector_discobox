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
      const data = await readJson(await fetch(url), "Could not load the recording");
      const frames = data.frames.map(frameUrl);
      await Promise.all(frames.map((src) => new Promise((resolve) => {
        const image = new Image();
        image.onload = image.onerror = resolve;
        image.src = src;
      })));
      return token === this.token ? { ...data, frames } : null;
    } catch (error) {
      if (token !== this.token) return null;
      throw error;
    }
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
