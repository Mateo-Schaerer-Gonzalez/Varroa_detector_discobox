// The box for naming a plate on the label page, opened in the plate's label area,
// with the tick for a negative control. One is open at a time; closing it saves
// and redraws the page.

class ZoneEditor {
  constructor(page) {
    this.page = page;
    this.zoneId = null;   // the plate being named
    this.finish = null;   // saves and closes the open editor, if there is one
  }

  // Save and close the open editor, if there is one.
  close() {
    if (this.finish) this.finish();
  }

  start(zoneId) {
    const box = document.querySelector(`.zone.labelling[data-zone-id="${zoneId}"]`);
    const host = document.querySelector(`.text-zone[data-zone-id="${zoneId}"]`);
    if (!box || !host || host.classList.contains("editing")) return;
    if (this.finish) {
      // Closing the other editor redraws the plate, so look this one up again after.
      this.finish();
      this.start(zoneId);
      return;
    }

    const zone = ctx.session.zones.find((z) => z.id === zoneId);
    this.zoneId = zoneId;
    box.classList.add("editing");
    host.classList.add("editing");

    const input = document.createElement("input");
    input.type = "text";
    input.value = zone.label;
    input.placeholder = `Zone ${zone.id}`;
    input.setAttribute("list", "known-labels");
    input.setAttribute("aria-label", `Label for zone ${zone.id}`);
    // Ticking the plate as a negative control saves at once. A click on it keeps the
    // focus in the name, so the editor stays open.
    const control = document.createElement("label");
    control.className = "control-check";
    control.innerHTML = `<input type="checkbox"${zone.control ? " checked" : ""}> negative control`;
    control.addEventListener("mousedown", (event) => event.preventDefault());
    control.querySelector("input").addEventListener("change", (event) => {
      sessionLabels.setControl(zone, event.target.checked);
      this.page.drawGroupList();
    });
    const editor = document.createElement("div");
    editor.className = "zone-editor";
    editor.append(input, control);
    host.appendChild(editor);
    input.focus();
    input.select();

    let done = false;
    const finish = (save, next = null, refocus = true) => {
      if (done) return;
      done = true;
      this.zoneId = null;
      this.finish = null;
      if (save) sessionLabels.setLabel(zone, input.value);
      this.page.draw();
      if (next != null) this.start(next);
      else if (refocus) document.querySelector(`.zone.labelling[data-zone-id="${zoneId}"]`)?.focus();
    };
    this.finish = () => finish(true, null, false);

    input.addEventListener("keydown", (event) => {
      event.stopPropagation();
      if (event.key === "Enter") finish(true);
      else if (event.key === "Escape") finish(false);
      else if (event.key === "Tab") {
        event.preventDefault();
        const ids = ctx.labelZones().map((z) => z.id);
        const next = ids[ids.indexOf(zoneId) + (event.shiftKey ? -1 : 1)];
        if (next == null) { finish(true); $("run-btn").focus(); }
        else finish(true, next);
      }
    });
    input.addEventListener("blur", () => {
      // Clicking a datalist suggestion blurs briefly; let the value land first.
      setTimeout(() => { if (document.activeElement !== input) finish(true); }, 0);
    });
  }
}
