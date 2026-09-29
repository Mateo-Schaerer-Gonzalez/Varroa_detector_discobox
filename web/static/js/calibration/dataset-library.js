// The saved ground truth, on calibration's first page: reopen a dataset, delete
// one, or pool several into a report with no recording opened for labelling.

class DatasetLibrary {
  static savedDate(iso) {
    return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }

  static labelsText(d) {
    return `${d.n_moving} moving · ${d.n_still} still`;
  }

  constructor() {
    $("pool-btn").addEventListener("click", () => this.pool());
  }

  async refresh() {
    const table = $("dataset-table");
    try {
      await cal.fetchDatasets();
    } catch (error) {
      table.innerHTML = `<tbody><tr><td class="error">${esc(error.message)}</td></tr></tbody>`;
      return;
    }
    if (!cal.datasets.length) {
      table.innerHTML = `<tbody><tr><td class="muted">Nothing saved yet. Label a calibration recording and it appears here.</td></tr></tbody>`;
      $("pool-btn").disabled = true;
      return;
    }
    const { savedDate, labelsText } = DatasetLibrary;
    table.innerHTML = `
    <thead><tr><th aria-label="Pool"></th><th>Recording</th><th>Saved</th>
      <th class="num">Recordings</th><th class="num">Mites</th><th>Labels</th><th></th></tr></thead>
    <tbody>${cal.datasets.map((d) => `
      <tr>
        <td><input type="checkbox" class="pool-check" value="${esc(d.id)}" aria-label="Pool ${esc(d.name)}"></td>
        <td title="${esc(d.data_dir)}">${esc(d.name)}${d.recordings_available ? "" : ' <span class="muted">· recordings moved and not copied, no clips or new scores</span>'}</td>
        <td>${savedDate(d.saved_at)}</td>
        <td class="num">${d.n_recordings}</td>
        <td class="num">${d.n_mites}</td>
        <td>${labelsText(d)}</td>
        <td class="row-actions">
          <button type="button" class="secondary small" data-open="${esc(d.id)}">Open</button>
          <button type="button" class="secondary small" data-delete="${esc(d.id)}">Delete</button>
        </td>
      </tr>`).join("")}</tbody>`;

    const checks = [...table.querySelectorAll(".pool-check")];
    const update = () => { $("pool-btn").disabled = !checks.some((c) => c.checked); };
    checks.forEach((check) => check.addEventListener("change", update));
    update();
    table.querySelectorAll("[data-open]").forEach((button) => button.addEventListener("click", () => this.open(button.dataset.open)));
    table.querySelectorAll("[data-delete]").forEach((button) => button.addEventListener("click", () => this.delete(button.dataset.delete)));
  }

  open(id) {
    return cal.openWithTruthSaved($("pool-status"), async () => {
      const status = $("pool-status");
      status.className = "hint";
      status.innerHTML = `<span class="spinner"></span> Opening…`;
      try {
        const data = await post(`/api/calibration/datasets/${encodeURIComponent(id)}/open`, {});
        status.textContent = "";
        cal.start(data);
      } catch (error) {
        status.className = "hint error";
        status.textContent = error.message;
      }
    });
  }

  async delete(id) {
    const dataset = cal.datasets.find((d) => d.id === id);
    const question = `Delete the saved ground truth of "${dataset.name}"?\n\n`
      + "The ground_truth.json next to its recordings stays, so opening that folder again brings the labels back.";
    if (!confirm(question)) return;
    const status = $("pool-status");
    try {
      await readJson(await fetch(`/api/calibration/datasets/${encodeURIComponent(id)}`, { method: "DELETE" }), "Could not delete");
      cal.selected = cal.selected.filter((s) => s !== id);
      status.textContent = "";
      this.refresh();
    } catch (error) {
      status.className = "hint error";
      status.textContent = error.message;
    }
  }

  // A report on saved datasets alone, with no recording opened for labelling.
  pool() {
    return cal.openWithTruthSaved($("pool-status"), async () => {
      const ids = [...document.querySelectorAll(".pool-check:checked")].map((c) => c.value);
      const status = $("pool-status");
      status.className = "hint";
      status.innerHTML = `<span class="spinner"></span> Comparing…`;
      try {
        const { session_id: sessionId } = await post("/api/calibration/pooled", {});
        Object.assign(cal, {
          id: sessionId, data: null, datasetId: null, selected: ids,
          report: null, reportStale: false, stamp: Date.now(),
        });
        groundTruth.load(null);
        cal.report = await cal.requestReport();
        router.setFolder("cal", `${ids.length} saved dataset${ids.length === 1 ? "" : "s"}`);
        status.textContent = "";
        router.go("#/cal/report");
      } catch (error) {
        status.className = "hint error";
        status.textContent = error.message;
      }
    });
  }
}
