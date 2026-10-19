// The report's wrong calls, to inspect one by one: every labelled mite-recording
// the detector called the other way, at the threshold the confusion matrix shows.
// The outcomes are the server's (each observation's "outcome" at the threshold in
// use, "outcome_suggested" at the suggested one); this only lists them, and each
// row opens its mite in its own recording.

class WrongCalls {
  static KINDS = [
    { key: "all", name: "all" },
    { key: "moving_called_still", name: "moving called still" },
    { key: "still_called_moving", name: "still called moving" },
  ];

  constructor() {
    this.shown = false;  // the list is open; it stays open when the report is drawn again
    this.kind = "all";   // which wrong calls the list shows, a key of KINDS
  }

  // `suggested`: the calls at the suggested threshold, else at the one in use.
  static outcomeKey(suggested) {
    return suggested ? "outcome_suggested" : "outcome";
  }

  // The section's skeleton; draw() fills it.
  html() {
    return Markup.section("Wrong calls", `<div id="wrong-calls"></div>`);
  }

  // `c`: the confusion counts at the threshold whose calls are listed (the server's).
  draw(r, c, suggested) {
    const { thr } = ReportPage;
    const box = $("wrong-calls");
    if (!box) return;
    const threshold = suggested ? r.suggested_threshold : r.threshold;
    const where = `at the ${suggested ? "suggested" : "in-use"} threshold ${thr(threshold)}`;
    if (!c.n_wrong) {
      box.innerHTML = `<p class="hint">Every labelled mite-recording is called right ${where}.</p>`;
      return;
    }
    const toggle = `<button type="button" id="wrong-toggle" class="small ${this.shown ? "secondary" : ""}">
      ${this.shown ? "Hide" : "Show"} the ${plural(c.n_wrong, "wrong call")}</button>`;
    if (!this.shown) {
      box.innerHTML = `<div class="row">${toggle}<span class="hint">${c.moving_called_still} moving called still · ${c.still_called_moving} still called moving, ${where}</span></div>`;
    } else {
      const count = (key) => (key === "all" ? c.n_wrong : c[key]);
      // e.g. no still called moving left at the other threshold
      if (!count(this.kind)) this.kind = "all";
      const key = WrongCalls.outcomeKey(suggested);
      const rows = r.observations.filter((row) => row[key] !== `${row.movement}_called_${row.movement}`
        && (this.kind === "all" || row[key] === this.kind));
      box.innerHTML = `<div class="row">${toggle}
        <div class="segmented" role="group" aria-label="Wrong calls shown">
          ${WrongCalls.KINDS.map((kind) => `<button type="button" data-wrong="${kind.key}" class="small ${kind.key === this.kind ? "" : "secondary"}"
            ${count(kind.key) ? "" : "disabled"}>${kind.name} (${count(kind.key)})</button>`).join("")}
        </div></div>
      <div class="table-wrap"><table class="clickable" id="wrong-table">
        <thead><tr>${ReportPage.pooled(r) ? "<th>Recording folder</th>" : ""}<th>Mite</th><th>Zone</th><th>Recording</th>
          <th>Ground truth</th><th>Called</th><th class="num">Score</th></tr></thead>
        <tbody>${rows.map((row, index) => `<tr data-index="${index}" tabindex="0">
          ${ReportPage.pooled(r) ? `<td>${esc(row.dataset_name)}</td>` : ""}
          <td>${esc(row.mite_id)}</td><td>${row.zone_id}</td>
          <td>${row.recording + 1} · ${minutes(row.time)}${row.recording_name ? ` <span class="muted">${esc(row.recording_name)}</span>` : ""}</td>
          <td>${Markup.movingBadge(row.movement === "moving")}</td>
          <td>${Markup.movingBadge(row.movement !== "moving")}</td>
          <td class="num">${thr(row.score)}</td></tr>`).join("")}</tbody>
      </table></div>
      <p class="caption">Each mite-recording the detector called the other way ${where}, by its score in that recording.
        Select one to see the mite in its recording, and correct its label there if the ground truth is wrong.</p>`;
      const open = (event, row) => {
        event.preventDefault();
        cal.goToMite(row.dataset, row.zone_id, row.recording, row.mite_id);
      };
      box.querySelectorAll("tr[data-index]").forEach((tr) => {
        const row = rows[Number(tr.dataset.index)];
        tr.addEventListener("click", (event) => open(event, row));
        tr.addEventListener("keydown", (event) => { if (event.key === "Enter") open(event, row); });
      });
      box.querySelectorAll("[data-wrong]").forEach((button) => button.addEventListener("click", () => {
        this.kind = button.dataset.wrong;
        this.draw(r, c, suggested);
      }));
    }
    $("wrong-toggle").addEventListener("click", () => {
      this.shown = !this.shown;
      this.draw(r, c, suggested);
    });
  }
}
