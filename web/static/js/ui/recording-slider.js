// A slider over the recordings, the same size however many there are: on the
// result pages and the ground-truth page. `done`, when given, marks each
// recording finished in a strip under the track; without it, a tick under the
// track marks each recording.

class RecordingSlider {
  // The page redraws the slider, so one moved from the keyboard gets the focus back.
  static refocus = false;

  // Past this many recordings, only every so many has a tick, so they stay apart.
  static MAX_TICKS = 60;

  static html({ times, current, done = null, label = "Recording shown" }) {
    const n = times.length;
    const strip = done
      ? `<div class="rec-done" aria-hidden="true">${done.map((d) => `<i${d ? ' class="done"' : ""}></i>`).join("")}</div>`
      : RecordingSlider.ticks(n);
    return `<div class="rec-slider" style="--n:${Math.max(2, n)}">
    <div class="rec-track">
      <input type="range" min="0" max="${Math.max(0, n - 1)}" step="1" value="${current}" aria-label="${label}"
        aria-valuetext="${RecordingSlider.text(times, current, done)}"${n < 2 ? " disabled" : ""}>
      ${strip}
    </div>
    <output class="rec-readout">${RecordingSlider.readout(times, current, done)}</output>
  </div>`;
  }

  // A tick at the thumb's place for each recording (or every `every`-th, and the last).
  static ticks(n) {
    if (n < 2) return "";
    const every = Math.ceil((n - 1) / RecordingSlider.MAX_TICKS);
    const marks = [];
    for (let i = 0; i < n; i++) {
      if (i % every === 0 || i === n - 1) marks.push(`<i style="left:${(100 * i) / (n - 1)}%"></i>`);
    }
    return `<div class="rec-ticks" aria-hidden="true">${marks.join("")}</div>`;
  }

  static text(times, i, done) {
    return `${minutes(times[i])}, recording ${i + 1} of ${times.length}${done && done[i] ? ", labelled" : ""}`;
  }

  static readout(times, i, done) {
    return `<b>${minutes(times[i])}</b> <span>${i + 1} / ${times.length}${done && done[i] ? ' <span class="rec-tick">✓ labelled</span>' : ""}</span>`;
  }

  // Dragging shows the time at once; the recording is picked on release, so a
  // large run is not redrawn at every step.
  static wire(root, times, done, pick) {
    const input = root.querySelector(".rec-slider input");
    if (!input) return;
    const readout = root.querySelector(".rec-readout");
    input.addEventListener("input", () => {
      const i = Number(input.value);
      readout.innerHTML = RecordingSlider.readout(times, i, done);
      input.setAttribute("aria-valuetext", RecordingSlider.text(times, i, done));
    });
    input.addEventListener("change", () => {
      RecordingSlider.refocus = document.activeElement === input;
      pick(Number(input.value));
    });
    if (RecordingSlider.refocus) { RecordingSlider.refocus = false; input.focus(); }
  }
}
