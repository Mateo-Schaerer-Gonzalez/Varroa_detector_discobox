// TEMPORARY, with overlap.html. The mite-recordings to check, as the server lists
// them (pipeline.truth_overlap(): which they are and where the overlap lies is
// its business), and the labels changed here: each change goes to the server at
// once, one after another, and can be taken back.

class OverlapCheck {
  constructor() {
    this.data = null;                // the server's reply; null before the first one
    // what the list is asked with: the datasets pooled, the overlap's edges (null: the suggested ones), and beyond it too
    this.request = { datasets: null, low: null, high: null, beyond: true };
    this.show = "all";               // "all", "moving", "still" (as labelled when listed) or "changed"
    this.order = "mite";             // "mite", "high" or "low" (by score)
    this.original = new Map();       // datapoint key -> its label when this page first listed it
    this.labels = new Map();         // datapoint key -> its label now
    this.changes = [];               // the labels set here, oldest first, to take back
    this.queue = Promise.resolve();  // the changes, sent one after another
  }

  static key(point) {
    return `${point.dataset}/${point.mite_id}/${point.recording}`;
  }

  // Ask for the list again, with `change` to what it is asked with. On failure
  // the list and what it was asked with stay as they were.
  async load(change = {}) {
    const request = { ...this.request, ...change };
    const data = await post("/api/overlap", request);
    data.datapoints.forEach((point) => {
      const key = OverlapCheck.key(point);
      if (!this.original.has(key)) this.original.set(key, point.movement);
      this.labels.set(key, point.movement);
      point.listed = point.movement;
    });
    Object.assign(this, { request, data });
    return data;
  }

  // The mite of a datapoint: { states, scores }, one of each per recording.
  mite(point) {
    return this.data.mites[`${point.dataset}/${point.mite_id}`];
  }

  find(key) {
    return this.data.datapoints.find((point) => OverlapCheck.key(point) === key) || null;
  }

  // What a datapoint was labelled when first listed, if it is labelled otherwise now.
  was(point) {
    const original = this.original.get(OverlapCheck.key(point));
    return original === point.movement ? null : { label: original };
  }

  // How many labels differ from what they were when first listed.
  changedCount() {
    let count = 0;
    this.labels.forEach((label, key) => { if (label !== this.original.get(key)) count += 1; });
    return count;
  }

  // The datapoints to show, in the order to go through them.
  points() {
    const datasets = this.data.datasets.map((dataset) => dataset.id);
    const shown = this.data.datapoints.filter((point) => (
      this.show === "all" || (this.show === "changed" ? this.was(point) : point.listed === this.show)));
    const byMite = (a, b) => datasets.indexOf(a.dataset) - datasets.indexOf(b.dataset)
      || Number(a.mite_id) - Number(b.mite_id) || a.recording - b.recording;
    return shown.sort({ mite: byMite, high: (a, b) => b.score - a.score || byMite(a, b), low: (a, b) => a.score - b.score || byMite(a, b) }[this.order]);
  }

  // Save `state` ("moving", "still" or null: unlabelled) as the label of the mite
  // and recording of `target` (a datapoint, or what one was). Resolves with the
  // datapoint as listed now, null when it no longer is.
  label(target, state, takenBack = false) {
    const key = OverlapCheck.key(target);
    const sent = this.queue.then(async () => {
      const before = this.labels.get(key);
      const saved = await post("/api/overlap/label", { dataset: target.dataset, mite: target.mite_id, recording: target.recording, state });
      this.labels.set(key, saved.movement);
      if (!takenBack) this.changes.push({ dataset: target.dataset, mite_id: target.mite_id, recording: target.recording, before });
      const point = this.find(key);
      if (point) {
        point.movement = saved.movement;
        this.mite(point).states = saved.states;
      }
      return point;
    });
    this.queue = sent.catch(() => {});
    return sent;
  }

  // Take back the last label set here; resolves as label() does, with null when there is none.
  undo() {
    const last = this.changes.pop();
    if (!last) return Promise.resolve(null);
    return this.label(last, last.before, true).catch((error) => {
      this.changes.push(last);
      throw error;
    });
  }
}
