// The survival of every group, its zones pooled, against the zones ticked as
// negative controls, pooled: the log-rank tests the server worked out
// (results.survival.log_rank, see classes/survival.py).

class SurvivalTable {
  constructor(page, groups) {
    this.page = page;
    this.groups = groups;
  }

  tag(group) {
    return Markup.groupTag(group, groupColor(group, this.groups));
  }

  // The zones `ids` as links that open them: "1, 4".
  zoneLinks(ids) {
    return ids.map((id) => `<a href="${ctx.href(`zone/${id}`)}">${id}</a>`).join(", ");
  }

  // An LT50 in minutes with its 95% interval, "20 (15–25)"; one not reached by
  // the last recording, at 25 min, is "> 25".
  lt50({ estimate, low, high }) {
    const { times } = this.page.results;
    const at = (time) => (time == null ? `&gt;${+times[times.length - 1].toFixed(1)}` : `${+time.toFixed(1)}`);
    return low == null ? at(estimate) : `${at(estimate)} <span class="muted">(${at(low)}–${at(high)})</span>`;
  }

  draw(table, caption) {
    const test = this.page.results.survival.log_rank;
    if (!test.n_control_mites) {
      table.hidden = true;
      caption.innerHTML = test.controls.length
        ? "The zones ticked as negative control hold no mites, so there is nothing to compare with."
        : `No zone is ticked as negative control. On the <a href="${ctx.href("label")}">label page</a>, click a plate and tick <i>negative control</i>
        to compare the survival of every group with it.`;
      return;
    }

    table.hidden = false;
    table.innerHTML = `
    <thead><tr><th>Group</th><th>Zones</th><th class="num">Mites</th><th class="num">Dead</th><th class="num">LT50 (min)</th>
      <th class="num">Expected dead</th><th class="num">χ²</th><th class="num">p</th></tr></thead>
    <tbody>
      <tr class="control-row"><td>Negative control ${test.control_groups.map((group) => this.tag(group)).join(" ")}</td>
        <td>${this.zoneLinks(test.control_zones)}</td>
        <td class="num">${test.n_control_mites}</td>
        <td class="num">${test.n_control_dead}</td>
        <td class="num">${test.control_lt50 ? this.lt50(test.control_lt50) : ""}</td><td></td><td></td><td></td></tr>
      ${test.rows.map((row) => this.row(row)).join("")}
    </tbody>`;
    caption.innerHTML = `The survival of each group's mites, pooling every zone with that label, against that of the negative control's, pooled, by the log-rank test.
    Zones ticked as negative control are left out of their group's row.
    ${this.page.deathRule()} A mite alive in the last recording counts as alive at least until then.
    <b>Dead</b> is how many of the group's mites died; <b>expected dead</b> how many would have, had they died at the rate of the control's.
    <b>LT50</b> is the time from the first recording by which half the mites are dead: the first recording in which the Kaplan–Meier curve of Fig. 2
    is at 50% or below, with its 95% confidence interval from where the curve's band first reaches 50%; <i>&gt;</i> marks one not reached by the last recording.
    The p values are not corrected for testing several groups.${this.page.timeDomain() ? " While the run goes on, the test takes the recordings so far." : ""}
    Select a zone number to open the zone.`;
  }

  row(row) {
    const pValue = row.p == null ? "–" : row.p < 0.001 ? "&lt; 0.001" : row.p.toFixed(3);
    return `<tr>
      <td>${this.tag(row.group)}</td>
      <td>${this.zoneLinks(row.zones)}</td>
      <td class="num">${row.n_mites}</td>
      <td class="num">${row.observed}</td>
      <td class="num">${row.lt50 ? this.lt50(row.lt50) : ""}</td>
      <td class="num">${row.expected.toFixed(1)}</td>
      <td class="num">${row.chi2 == null ? "–" : row.chi2.toFixed(2)}</td>
      <td class="num">${pValue}</td></tr>`;
  }
}
