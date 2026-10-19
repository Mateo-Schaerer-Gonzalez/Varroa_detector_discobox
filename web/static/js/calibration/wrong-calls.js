// The calibration report's wrong calls, to check by eye that the ground truth is
// right: every labelled mite-recording the detector called the other way, at the
// threshold the confusion matrix shows. The outcomes are the server's (each
// observation's "outcome" at the threshold in use, "outcome_suggested" at the
// suggested one); this only lists them. As with the close calls of the result
// pages (ReviewCheck), a row opens its mite in its recording on the ground-truth
// page, which asks there whether the mite moves; the answer is its label (M and S
// as usual), and the next wrong call not checked yet comes up, of any dataset the
// report pools. A bar says how far the checking has got.

class WrongCalls {
  static KINDS = [
    { key: "all", name: "all" },
    { key: "moving_called_still", name: "moving called still" },
    { key: "still_called_moving", name: "still called moving" },
  ];

  constructor() {
    this.shown = false;        // the list is open; it stays open when the report is drawn again
    this.kind = "all";         // which wrong calls the list shows, a key of KINDS
    this.rows = [];            // the wrong calls listed, in their order, to check one after another
    this.where = "";           // the threshold they are wrong at, in words
    this.checking = false;     // a wrong call was opened from the list: the ground-truth page asks about them
    this.checked = new Set();  // the wrong calls answered (WrongCalls.key), kept while the app is open
  }

  // `suggested`: the calls at the suggested threshold, else at the one in use.
  static outcomeKey(suggested) {
    return suggested ? "outcome_suggested" : "outcome";
  }

  static key(dataset, miteId, recording) {
    return `${dataset}|${miteId}|${recording}`;
  }

  static rowKey(row) {
    return WrongCalls.key(row.dataset, row.mite_id, row.recording);
  }

  // The section's skeleton; draw() fills it.
  html() {
    return Markup.section("Wrong calls", `<div id="wrong-calls"></div>`);
  }

  // How many of the wrong calls listed are checked, as a bar.
  progress() {
    const done = this.rows.filter((row) => this.checked.has(WrongCalls.rowKey(row))).length;
    return `<div class="review-progress" role="progressbar" aria-valuemin="0" aria-valuemax="${this.rows.length}" aria-valuenow="${done}">
      <div class="progress-bar"><div style="width: ${percent(done, this.rows.length)}"></div></div>
      <span class="hint">${done} of ${plural(this.rows.length, "wrong call")} checked</span></div>`;
  }

  // `c`: the confusion counts at the threshold whose calls are listed (the server's).
  draw(r, c, suggested) {
    const { thr } = ReportPage;
    const box = $("wrong-calls");
    if (!box) return;
    const threshold = suggested ? r.suggested_threshold : r.threshold;
    this.where = `at the ${suggested ? "suggested" : "in-use"} threshold ${thr(threshold)}`;
    const count = (key) => (key === "all" ? c.n_wrong : c[key]);
    if (!count(this.kind)) this.kind = "all";  // e.g. no still called moving left at the other threshold
    const key = WrongCalls.outcomeKey(suggested);
    this.rows = r.observations.filter((row) => row[key] !== `${row.movement}_called_${row.movement}`
      && (this.kind === "all" || row[key] === this.kind));
    if (!c.n_wrong) {
      box.innerHTML = `<p class="hint">Every labelled mite-recording is called right ${this.where}.</p>`;
      return;
    }
    const toggle = `<button type="button" id="wrong-toggle" class="small ${this.shown ? "secondary" : ""}">
      ${this.shown ? "Hide" : "Show"} the ${plural(c.n_wrong, "wrong call")}</button>`;
    if (!this.shown) {
      box.innerHTML = `<div class="row">${toggle}<span class="hint">${c.moving_called_still} moving called still · ${c.still_called_moving} still called moving, ${this.where}</span></div>`;
    } else {
      const next = this.next();
      box.innerHTML = `<p class="caption review-intro">Each mite-recording the detector called the other way ${this.where}, by its score in that recording.
        A wrong call may be the ground truth's: check them by eye, one after another. Each opens the mite in its recording and asks
        whether it moves; the answer is its label, and the next one comes up.</p>
      ${this.progress()}
      <div class="row">${toggle}
        <div class="segmented" role="group" aria-label="Wrong calls shown">
          ${WrongCalls.KINDS.map((kind) => `<button type="button" data-wrong="${kind.key}" class="small ${kind.key === this.kind ? "" : "secondary"}"
            ${count(kind.key) ? "" : "disabled"}>${kind.name} (${count(kind.key)})</button>`).join("")}
        </div>
        ${next ? `<button type="button" id="wrong-check" class="small">Check ${next === this.rows[0] ? "them" : "the rest"} one by one</button>` : ""}</div>
      <div class="table-wrap"><table class="clickable" id="wrong-table">
        <thead><tr>${ReportPage.pooled(r) ? "<th>Recording folder</th>" : ""}<th>Mite</th><th>Zone</th><th>Recording</th>
          <th>Ground truth</th><th>Called</th><th class="num">Score</th></tr></thead>
        <tbody>${this.rows.map((row, index) => `<tr data-index="${index}" tabindex="0" title="Open this mite in its recording to check">
          ${ReportPage.pooled(r) ? `<td>${esc(row.dataset_name)}</td>` : ""}
          <td>${esc(row.mite_id)}</td><td>${row.zone_id}</td>
          <td>${row.recording + 1} · ${minutes(row.time)}${row.recording_name ? ` <span class="muted">${esc(row.recording_name)}</span>` : ""}</td>
          <td>${Markup.movingBadge(row.movement === "moving")}${this.mark(row)}</td>
          <td>${Markup.movingBadge(row.movement !== "moving")}</td>
          <td class="num">${thr(row.score)}</td></tr>`).join("")}</tbody>
      </table></div>
      <p class="caption">The ground truth is as it was for this report; a label changed since shows once the report is updated.</p>`;
      box.querySelectorAll("tr[data-index]").forEach((tr) => {
        const row = this.rows[Number(tr.dataset.index)];
        tr.addEventListener("click", () => this.open(row));
        tr.addEventListener("keydown", (event) => { if (event.key === "Enter") this.open(row); });
      });
      box.querySelectorAll("[data-wrong]").forEach((button) => button.addEventListener("click", () => {
        this.kind = button.dataset.wrong;
        this.draw(r, c, suggested);
      }));
      $("wrong-check")?.addEventListener("click", () => this.open(next));
    }
    $("wrong-toggle").addEventListener("click", () => {
      this.shown = !this.shown;
      this.draw(r, c, suggested);
    });
  }

  // "checked" beside a wrong call's ground truth once it is answered.
  mark(row) {
    return this.checked.has(WrongCalls.rowKey(row)) ? ` <span class="check-mark" title="Checked by eye">checked</span>` : "";
  }

  // The first wrong call listed not checked yet, after `after` (a row) if given.
  next(after = null) {
    const left = (row) => !this.checked.has(WrongCalls.rowKey(row));
    const from = after ? this.rows.indexOf(after) + 1 : 0;
    return this.rows.slice(from).find(left) || this.rows.slice(0, from).find(left) || null;
  }

  open(row) {
    this.checking = true;
    cal.goToMite(row.dataset, row.zone_id, row.recording, row.mite_id);
  }

  // --- the ground-truth page

  // The wrong call of the mite and recording on the ground-truth page, while checking.
  rowAt(miteId, recording) {
    if (!this.checking) return null;
    const key = WrongCalls.key(cal.datasetId, miteId, recording);
    return this.rows.find((row) => WrongCalls.rowKey(row) === key) || null;
  }

  // The question above the ground-truth page, on a wrong call being checked.
  note(miteId, recording) {
    if (!this.checking) return "";
    const row = this.rowAt(miteId, recording);
    const back = `<a class="button small secondary" href="#/cal/report">Back to the report</a>`;
    if (!row) {
      const next = this.next();
      return `<div class="banner review-note"><span>${next ? "This recording is not one of the wrong calls." : "Every wrong call is checked."}</span>
        ${next ? `<button type="button" class="small secondary" data-wrong-next>Next wrong call: mite ${esc(next.mite_id)}, recording ${next.recording + 1}</button>` : ""}
        ${back}${this.progress()}</div>`;
    }
    const truth = row.movement;
    const called = truth === "moving" ? "still" : "moving";
    return `<div class="banner review-note"><span><b>Wrong call ${this.rows.indexOf(row) + 1} of ${this.rows.length}:</b>
        labelled ${truth}, the detector called it ${called} (score ${ReportPage.thr(row.score)}, ${this.where}).
        ${this.checked.has(WrongCalls.rowKey(row)) ? "Checked already." : ""}</span>
      <span class="review-now">Is the mite moving in this recording?
        <button type="button" class="small" data-truth-answer="moving" title="Key: M">Moving <kbd>M</kbd></button>
        <button type="button" class="small" data-truth-answer="still" title="Key: S">Still <kbd>S</kbd></button></span>
      ${back}${this.progress()}</div>`;
  }

  // The clip the answer about the wrong call shown brings up next, fetched ahead.
  warmNext(miteId, recording) {
    const row = this.rowAt(miteId, recording);
    const next = row && this.next(row);
    if (next && next.dataset === cal.datasetId) truthPage.warm(next.mite_id, next.recording);
  }

  wireNote(holder) {
    holder.querySelectorAll("[data-truth-answer]").forEach((button) => button.addEventListener("click", () => {
      button.blur();
      truthPage.label(button.dataset.truthAnswer);
    }));
    holder.querySelector("[data-wrong-next]")?.addEventListener("click", () => this.open(this.next()));
  }

  // The mite and recording on the ground-truth page were labelled: if a wrong call
  // being checked, it is checked; returns whether the next one is shown for it.
  answered(miteId, recording) {
    const row = this.rowAt(miteId, recording);
    if (!row) return false;
    this.checked.add(WrongCalls.rowKey(row));
    const next = this.next(row);
    if (next) this.open(next);
    else router.go("#/cal/report");  // all checked
    return true;
  }
}
