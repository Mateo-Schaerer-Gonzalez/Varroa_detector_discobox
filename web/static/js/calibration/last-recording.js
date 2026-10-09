// The test report's last recording, looped twice over the whole plate: once with
// every mite's box coloured by the detector's call at the threshold in use, once
// with what the benchmark draws on it, its circles as they are, over the mites'
// boxes coloured by its call. The calls, boxes and circles are the server's
// (pipeline._last_recording); this draws them.

class LastRecording {
  static CIRCLE_COLOR = "#ff5fa2";

  // The dataset shown: the last one chosen, else the one on the ground-truth
  // page, else the first in the report.
  static dataset(r) {
    const ids = r.datasets.map((d) => d.id);
    const id = [cal.lastDataset, cal.datasetId].find((known) => ids.includes(known)) || ids[0];
    return r.datasets.find((d) => d.id === id);
  }

  // Two figures, numbered from `number` on.
  html(r, number) {
    const dataset = LastRecording.dataset(r);
    const picker = ReportPage.pooled(r) ? `<select id="last-dataset" aria-label="Recording folder">
      ${r.datasets.map((d) => `<option value="${esc(d.id)}" ${d === dataset ? "selected" : ""}>${esc(d.name)}</option>`).join("")}
    </select>` : "";
    const figure = (id, n, title, caption) => `<figure class="fig">
      <div class="fig-title fig-title-row">${title}${picker && id === "last-detector" ? `<span class="row">${picker}</span>` : ""}</div>
      <div id="${id}" class="crop-wrap plate-calls"></div>
      <div id="${id}-legend" class="legend map-legend"></div>
      <figcaption><b>Fig. ${n}.</b> <span id="${id}-caption"></span> ${caption}</figcaption>
    </figure>`;
    return `<p id="last-status" class="hint clip-status"></p>
    ${figure("last-detector", number, "The last recording, as the detector calls it",
      `Each box is a detected mite, as the detector cuts it out, coloured by its call: moving when its score in this recording reaches the threshold in use.
      Mites marked not a mite are left out. Hover a mite for its score and its label, select it to see it.`)}
    ${figure("last-benchmark", number + 1, "The last recording, as the benchmark draws it",
      `The benchmark's own output: a circle around every spot of its mask, each of which it counts as one mite alive. It never finds the mites;
      the boxes are the detector's, coloured by the call the report takes from the benchmark, moving when a spot of its mask lies on the box.
      A circle on no box is movement where no mite was detected.`)}`;
  }

  draw(r) {
    const dataset = LastRecording.dataset(r);
    const last = dataset.last_recording;
    const preview = `/api/calibration/datasets/${encodeURIComponent(dataset.id)}/preview?t=${cal.stamp}`;
    const where = `${esc(dataset.name)}${last.recording_name ? ` / ${esc(last.recording_name)}` : ""}, at ${minutes(last.time)}`;
    const count = (key) => last.mites.filter((mite) => mite[key] === "moving").length;
    const plate = (id) => {
      const svg = PlateView.crop(0, 0, dataset.image.width, dataset.image.height, preview, dataset.image);
      $(id).innerHTML = "";
      $(id).appendChild(svg);
      return svg;
    };
    const legend = (id, items) => { $(`${id}-legend`).innerHTML = Charts.legendHtml(items); };
    const calls = (by) => [
      { name: `called moving${by} (${count(by ? "benchmark_call" : "call")})`, color: token("--moving"), shape: "square" },
      { name: `called still${by} (${last.mites.length - count(by ? "benchmark_call" : "call")})`, color: token("--still"), shape: "square" },
    ];

    const detector = plate("last-detector");
    last.mites.forEach((mite) => detector.appendChild(this.box(r, dataset, mite, mite.call,
      `called ${mite.call} · score ${ReportPage.thr(mite.score)} · threshold ${ReportPage.thr(r.threshold)}`)));
    $("last-detector-caption").innerHTML = `${where}: ${count("call")} of ${last.mites.length} mites called moving.`;
    legend("last-detector", calls(""));

    const svgs = [detector];
    if (last.circles) {
      const benchmark = plate("last-benchmark");
      last.mites.forEach((mite) => benchmark.appendChild(this.box(r, dataset, mite, mite.benchmark_call,
        `called ${mite.benchmark_call} by the benchmark · the detector calls it ${mite.call}`)));
      last.circles.forEach(([cx, cy]) => benchmark.appendChild(
        PlateView.svgEl("circle", { cx, cy, r: last.circle_radius, class: "benchmark-circle" })));
      $("last-benchmark-caption").innerHTML = `${where}: ${last.circles.length} circle${last.circles.length === 1 ? "" : "s"}, the benchmark's count of mites alive;
        ${count("benchmark_call")} of ${last.mites.length} detected mites called moving.`;
      legend("last-benchmark", [
        { name: `the benchmark's circles (${last.circles.length})`, color: LastRecording.CIRCLE_COLOR, shape: "ring" },
        ...calls(" by the benchmark"),
      ]);
      svgs.push(benchmark);
    } else {
      $("last-benchmark").innerHTML = "";
      $("last-benchmark-caption").innerHTML = r.benchmark
        ? "The frames of this recording are gone, so the benchmark has nothing to draw on."
        : "The benchmark has not been run on these datasets.";
    }

    $("last-dataset")?.addEventListener("change", (event) => {
      cal.lastDataset = event.target.value;
      $("last-recording").innerHTML = this.html(r, Number($("last-recording").dataset.number));
      this.draw(r);
    });
    this.play(dataset, last, svgs);
  }

  // A mite's box, coloured by `call`; hovering says `how` it was called and what
  // the ground truth says, selecting opens it in this recording.
  box(r, dataset, mite, call, how) {
    const [x1, y1, x2, y2] = mite.box;
    const g = PlateView.svgEl("g", { class: `call-mite ${call}` });
    g.append(
      PlateView.svgEl("rect", { x: x1 - 4, y: y1 - 4, width: x2 - x1 + 8, height: y2 - y1 + 8, class: "hit" }),
      PlateView.svgEl("rect", { x: x1, y: y1, width: x2 - x1, height: y2 - y1, class: "box" }),
    );
    g.addEventListener("mousemove", (event) => Charts.showTooltip(event,
      `<div class="tip-title">Mite ${esc(mite.id)} · zone ${mite.zone_id}</div>
      <div>${how}</div>
      <div class="tip-note">${mite.movement ? `labelled ${mite.movement}` : "not labelled in this recording"}</div>
      <div class="tip-hint">Click to see it in its recording</div>`));
    g.addEventListener("mouseleave", Charts.hideTooltip);
    g.addEventListener("click", () => cal.goToMite(dataset.id, mite.zone_id, dataset.last_recording.recording, mite.id));
    return g;
  }

  // The recording's frames, looped under both drawings; until they are in, the
  // first frame of the dataset stays.
  async play(dataset, last, svgs) {
    const status = $("last-status");
    status.className = "hint clip-status";
    status.innerHTML = `<span class="spinner"></span> Loading the last recording…`;
    try {
      // The frames of a recording never change, so they need no cache-buster.
      const clip = await player.load(`/api/calibration/${cal.id}/plate-clip/${encodeURIComponent(dataset.id)}/${last.recording}`,
        (name) => `/api/session/${cal.id}/file/${name}`);
      if (!clip) return;  // another clip was asked for meanwhile
      const shows = svgs.map((svg) => ClipPlayer.onSvg(svg, clip));
      status.textContent = `${clip.frames.length} frames, looped in real time.`;
      player.playing = true;
      player.start(clip, (src) => shows.forEach((show) => show(src)));
    } catch (error) {
      status.className = "hint clip-status error";
      status.textContent = `${error.message} Showing the first frame.`;
    }
  }
}
