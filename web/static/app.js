// Browser side. Talks to the server over the /api endpoints and knows nothing
// about how the analysis works.
//
// Navigation is hash-based so the browser's back/forward buttons work:
//   #/open  #/label  #/results  #/zone/<id>  #/mite/<id>
// and, in the calibration window (calibration.js):
//   #/cal/open  #/cal/truth/<zone id>/<recording>  #/cal/report

let sessionId = null;
let session = null;      // what opening a folder returned: preview, zones, labels
let results = null;      // what the last analysis run returned
let runStamp = 0;        // cache-buster so a re-run never shows old images
let labelsChanged = false;

const $ = (id) => document.getElementById(id);
const esc = (text) => Charts.escape(text ?? "");

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Request failed");
  return data;
}

const fileUrl = (name) => `/api/session/${sessionId}/file/${name}?t=${runStamp}`;
const percent = (value, total) => `${(value / total) * 100}%`;
const pct = (fraction) => (fraction == null ? "–" : `${Math.round(fraction * 100)}%`);
const minutes = (value) => `${+Number(value).toFixed(1)} min`;
const score = (value) => (value == null ? "–" : Number(value).toFixed(1));

// --- colours ---------------------------------------------------------------

// Read colour tokens from the stylesheet so charts follow light/dark mode.
const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// Groups get categorical colours in alphabetical order; "unlabeled" and any
// ninth group onwards are grey rather than an invented hue.
function groupColor(group, groups) {
  const named = groups.filter((g) => g !== "unlabeled");
  const index = named.indexOf(group);
  return index >= 0 && index < 8 ? token(`--series-${index + 1}`) : token("--series-other");
}

const labelGroups = () =>
  [...new Set(session.zones.map((zone) => zone.label.trim()).filter(Boolean))].sort();
// Every labelled zone counts, including groups where no mite was found, so a
// group keeps the same colour here as on the labelling page.
const resultGroups = () =>
  [...new Set([...results.groups.map((g) => g.group), ...results.zones.map((z) => z.label).filter(Boolean)])].sort();

function statusBadge(alive) {
  return alive
    ? `<span class="status alive"><span aria-hidden="true">●</span> alive</span>`
    : `<span class="status dead"><span aria-hidden="true">✕</span> dead</span>`;
}

// --- routing ---------------------------------------------------------------

function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

// Show one <section class="view"> and hide the others.
function showView(name) {
  document.querySelectorAll("main > .view").forEach((view) => { view.hidden = view.id !== `view-${name}`; });
}

// The calibration window uses its own steps in the header.
function setMode(calibrating) {
  $("steps-analysis").hidden = calibrating;
  $("steps-cal").hidden = !calibrating;
  $("mode-link").hidden = calibrating;
  $("brand-mode").hidden = !calibrating;
  document.title = calibrating ? "Calibration · Varroa discobox" : "Varroa discobox";
}

function route() {
  const [, view = "open", id, ...rest] = location.hash.split("/");
  setMode(view === "cal");
  if (view === "cal") { routeCalibration(id, ...rest); return; }
  const wanted = { open: "open", label: "label", results: "results", zone: "results", mite: "results" }[view] || "open";

  // Fall back to the furthest stage that has data.
  let step = wanted;
  if (step === "results" && !results) step = session ? "label" : "open";
  if (step === "label" && !session) step = "open";
  if (step !== wanted) { location.replace("#/" + step); return; }

  showView(step);
  document.querySelectorAll("#steps-analysis a[data-step]").forEach((link) => {
    link.classList.toggle("active", link.dataset.step === step);
    const available = link.dataset.step === "open" || (link.dataset.step === "label" && session) || (link.dataset.step === "results" && results);
    link.classList.toggle("disabled", !available);
  });
  Charts.hideTooltip();

  if (step === "label") drawLabelView();
  if (step === "results") {
    if (view === "zone") showZone(Number(id));
    else if (view === "mite") showMite(decodeURIComponent(id));
    else showOverview();
  }
  window.scrollTo(0, 0);
}

window.addEventListener("hashchange", route);

// --- 1 · opening a folder ---------------------------------------------------

async function openFolder(dataDir) {
  $("open-status").className = "hint";
  $("open-status").textContent = "Opening…";
  try {
    session = await post("/api/session", { data_dir: dataDir });
    sessionId = session.session_id;
    results = null;
    labelsChanged = false;
    session.zones.forEach((zone) => { zone.label = zone.label || ""; });
    $("folder-name").textContent = session.data_dir.split(/[\\/]/).filter(Boolean).pop();
    $("folder-name").title = session.data_dir;
    $("open-status").textContent = "";
    $("run-status").textContent = `${session.n_recordings} recordings loaded.`;
    go("#/label");
  } catch (error) {
    $("open-status").className = "hint error";
    $("open-status").textContent = error.message;
  }
}

// Only these files matter to the analysis; everything else stays on disk.
const wanted = (path) =>
  /\.bmp$/i.test(path) || /(^|\/)\.settings\.txt$/.test(path) || /(^|\/)(labels|ground_truth)\.json$/.test(path);

// Walk a dropped folder into a flat list of { path, file }, paths relative to it.
async function filesFromDrop(dataTransfer) {
  const entries = [...dataTransfer.items].map((item) => item.webkitGetAsEntry && item.webkitGetAsEntry()).filter(Boolean);
  if (entries.length !== 1 || !entries[0].isDirectory) {
    throw new Error("Drop one folder: the one that holds the recording folders.");
  }
  const root = entries[0];
  const files = [];
  const walk = async (dir, prefix) => {
    const reader = dir.createReader();
    let batch;
    do {
      batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
      for (const entry of batch) {
        if (entry.isDirectory) await walk(entry, `${prefix}${entry.name}/`);
        else files.push({ path: prefix + entry.name, file: await new Promise((res, rej) => entry.file(res, rej)) });
      }
    } while (batch.length);
  };
  await walk(root, "");
  return { name: root.name, files };
}

function filesFromPicker(fileList) {
  const all = [...fileList];
  if (!all.length) throw new Error("That folder is empty.");
  const name = all[0].webkitRelativePath.split("/")[0];
  return { name, files: all.map((file) => ({ path: file.webkitRelativePath.split("/").slice(1).join("/"), file })) };
}

// `prefix` picks the drop zone's elements ("" here, "cal-" in the calibration
// window) and `open` is called with the server-side folder once it is copied.
async function uploadFolder({ name, files }, prefix, open) {
  // A single recording folder dropped on its own becomes a one-recording session.
  if (/_fps-\d+/.test(name)) {
    files = files.map((f) => ({ ...f, path: `${name}/${f.path}` }));
    name = `${name}_session`;
  }
  files = files.filter((f) => wanted(f.path));
  if (!files.some((f) => /\.bmp$/i.test(f.path))) {
    throw new Error(`No .bmp images found in “${name}”. Drop the folder that holds the ..._fps-30 folders.`);
  }

  const progress = $(`${prefix}upload-progress`);
  const bar = $(`${prefix}upload-bar`);
  const text = $(`${prefix}upload-text`);
  progress.hidden = false;
  bar.style.width = "0%";
  text.textContent = `Checking ${files.length} files…`;

  const manifest = await post(`/api/uploads/${encodeURIComponent(name)}/manifest`, {
    files: files.map((f) => ({ path: f.path, size: f.file.size })),
  });
  const missing = new Set(manifest.missing);
  const queue = files.filter((f) => missing.has(f.path));
  const totalBytes = queue.reduce((sum, f) => sum + f.file.size, 0);
  const totalFiles = queue.length;
  let sentBytes = 0;
  let sentFiles = 0;

  const report = () => {
    const fraction = totalBytes ? sentBytes / totalBytes : 1;
    bar.style.width = `${fraction * 100}%`;
    text.textContent = totalFiles
      ? `Copying “${name}”: ${sentFiles} of ${totalFiles} files (${(sentBytes / 1e6).toFixed(0)} of ${(totalBytes / 1e6).toFixed(0)} MB)`
      : `“${name}” is already here.`;
  };
  report();

  // A few uploads in flight at once keeps the local disk busy without flooding it.
  const worker = async () => {
    while (queue.length) {
      const item = queue.shift();
      const response = await fetch(
        `/api/uploads/${encodeURIComponent(name)}/file?path=${encodeURIComponent(item.path)}`,
        { method: "PUT", body: item.file },
      );
      if (!response.ok) throw new Error(`Upload failed for ${item.path}`);
      sentBytes += item.file.size;
      sentFiles += 1;
      report();
    }
  };
  await Promise.all([worker(), worker(), worker(), worker()]);
  text.textContent = `Copied “${name}”. Opening…`;
  await open(manifest.data_dir);
  progress.hidden = true;
}

// Wire up a drop zone, its "Choose folder" button and its typed-path box.
function wireFolderPicker(prefix, open) {
  const status = $(`${prefix}open-status`);
  const handleFolder = async (getFolder) => {
    status.className = "hint";
    status.textContent = "";
    try {
      await uploadFolder(await getFolder(), prefix, open);
    } catch (error) {
      $(`${prefix}upload-progress`).hidden = true;
      status.className = "hint error";
      status.textContent = error.message;
    }
  };

  const dropZone = $(`${prefix}drop-zone`);
  const input = $(`${prefix}folder-input`);
  const path = $(`${prefix}data-dir`);
  ["dragenter", "dragover"].forEach((type) =>
    dropZone.addEventListener(type, (event) => { event.preventDefault(); dropZone.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((type) =>
    dropZone.addEventListener(type, (event) => {
      if (type === "dragleave" && dropZone.contains(event.relatedTarget)) return;
      dropZone.classList.remove("dragging");
    }));
  dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    const transfer = event.dataTransfer;
    handleFolder(() => filesFromDrop(transfer));
  });

  $(`${prefix}browse-btn`).addEventListener("click", () => input.click());
  dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target === dropZone) input.click();
  });
  input.addEventListener("change", (event) => {
    const list = event.target.files;
    handleFolder(async () => filesFromPicker(list));
    event.target.value = "";
  });
  $(`${prefix}open-btn`).addEventListener("click", () => open(path.value.trim()));
  path.addEventListener("keydown", (event) => {
    if (event.key === "Enter") open(path.value.trim());
  });
}

wireFolderPicker("", openFolder);
// Dropping a folder anywhere else on the page should not navigate away to it.
window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => event.preventDefault());

// --- 2 · labelling the plates -----------------------------------------------

// Plates are laid over the preview image in percent, so they track it as it scales.
function plateOverlay(container, src, image) {
  container.innerHTML = "";
  const img = document.createElement("img");
  img.src = src;
  img.alt = "First frame of the recording";
  container.appendChild(img);
  return (x1, y1, x2, y2) => ({
    left: percent(x1, image.width),
    top: percent(y1, image.height),
    width: percent(x2 - x1, image.width),
    height: percent(y2 - y1, image.height),
  });
}

let editingZoneId = null;
let finishEditing = null;  // saves and closes the open editor, if there is one

// Where a plate's name goes: its printed-label area, or, for a plate without one,
// a strip along its top edge.
function textRect(zone) {
  if (zone.text_zone) return zone.text_zone;
  return { x1: zone.x1, y1: zone.y1, x2: zone.x2, y2: zone.y1 + (zone.y2 - zone.y1) * 0.2 };
}

// Hovering either the plate or its name highlights both, so the pairing is visible.
function linkHover(elements) {
  elements.forEach((element) => {
    element.addEventListener("mouseenter", () => elements.forEach((e) => e.classList.add("hot")));
    element.addEventListener("mouseleave", () => elements.forEach((e) => e.classList.remove("hot")));
  });
}

function drawLabelView() {
  const plate = $("label-plate");
  const place = plateOverlay(plate, fileUrl(session.preview), session.image);
  const groups = labelGroups();

  session.zones.forEach((zone) => {
    const label = zone.label.trim();
    const color = label ? groupColor(label, groups) : null;

    // The plate itself is only an outline, so nothing covers the mites.
    const box = document.createElement("div");
    box.className = "zone labelling";
    box.tabIndex = 0;
    box.setAttribute("role", "button");
    box.dataset.zoneId = zone.id;
    Object.assign(box.style, place(zone.x1, zone.y1, zone.x2, zone.y2));
    if (color) box.style.setProperty("--zone-color", color);
    box.classList.toggle("empty", !label);
    box.setAttribute("aria-label", `Zone ${zone.id}: ${label || "no label"}. Click to edit.`);
    box.innerHTML = `<span class="zone-num">${zone.id}</span>`;

    const rect = textRect(zone);
    const text = document.createElement("div");
    text.className = "text-zone";
    text.dataset.zoneId = zone.id;
    Object.assign(text.style, place(rect.x1, rect.y1, rect.x2, rect.y2));
    if (color) text.style.setProperty("--zone-color", color);
    // The editor may be wider than the label area; let it grow away from the plate.
    text.classList.toggle("grows-left", rect.x2 <= (zone.x1 + zone.x2) / 2);
    text.innerHTML = label
      ? `<span class="text-tag">${esc(label)}</span>`
      : `<span class="text-tag empty">+ label</span>`;

    // Open on mousedown and keep the focus where it is: a blur would redraw the
    // plate under the pointer, and the click on another plate would be lost.
    for (const element of [box, text]) {
      element.addEventListener("mousedown", (event) => {
        if (event.button !== 0 || event.target.tagName === "INPUT") return;
        event.preventDefault();
        startEdit(zone.id);
      });
    }
    box.addEventListener("keydown", (event) => {
      if ((event.key === "Enter" || event.key === " ") && event.target === box) {
        event.preventDefault();
        startEdit(zone.id);
      }
    });
    linkHover([box, text]);
    plate.append(box, text);
  });

  drawGroupList();
  refreshSuggestions();
  if (editingZoneId != null) startEdit(editingZoneId);
}

function startEdit(zoneId) {
  const box = document.querySelector(`.zone.labelling[data-zone-id="${zoneId}"]`);
  const host = document.querySelector(`.text-zone[data-zone-id="${zoneId}"]`);
  if (!box || !host || host.classList.contains("editing")) return;
  if (finishEditing) {
    // Closing the other editor redraws the plate, so look this one up again after.
    finishEditing();
    startEdit(zoneId);
    return;
  }

  const zone = session.zones.find((z) => z.id === zoneId);
  editingZoneId = zoneId;
  box.classList.add("editing");
  host.classList.add("editing");

  const input = document.createElement("input");
  input.type = "text";
  input.value = zone.label;
  input.placeholder = `Zone ${zone.id}`;
  input.setAttribute("list", "known-labels");
  input.setAttribute("aria-label", `Label for zone ${zone.id}`);
  host.appendChild(input);
  input.focus();
  input.select();

  let done = false;
  const finish = (save, next = null, refocus = true) => {
    if (done) return;
    done = true;
    editingZoneId = null;
    finishEditing = null;
    if (save) setLabel(zone, input.value);
    drawLabelView();
    if (next != null) startEdit(next);
    else if (refocus) document.querySelector(`.zone.labelling[data-zone-id="${zoneId}"]`)?.focus();
  };
  finishEditing = () => finish(true, null, false);

  input.addEventListener("keydown", (event) => {
    event.stopPropagation();
    if (event.key === "Enter") finish(true);
    else if (event.key === "Escape") finish(false);
    else if (event.key === "Tab") {
      event.preventDefault();
      const ids = session.zones.map((z) => z.id);
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

function setLabel(zone, value) {
  const label = value.trim();
  if (label === zone.label) return;
  zone.label = label;
  if (results) labelsChanged = true;
  saveLabels();
}

function collectLabels() {
  const labels = {};
  session.zones.forEach((zone) => { if (zone.label.trim()) labels[zone.id] = zone.label.trim(); });
  return labels;
}

// Offer labels already typed as autocomplete, so repeating a group is one keystroke.
function refreshSuggestions() {
  $("known-labels").innerHTML = labelGroups().map((label) => `<option value="${esc(label)}">`).join("");
}

function drawGroupList() {
  const groups = labelGroups();
  const rows = groups.map((group) => {
    const ids = session.zones.filter((z) => z.label.trim() === group).map((z) => z.id);
    return `<li><i class="swatch" style="background:${groupColor(group, groups)}"></i>
      <span class="group-name">${esc(group)}</span>
      <span class="hint">zone${ids.length > 1 ? "s" : ""} ${ids.join(", ")}</span></li>`;
  });
  const unlabeled = session.zones.filter((z) => !z.label.trim()).map((z) => z.id);
  if (unlabeled.length) {
    rows.push(`<li><i class="swatch" style="background:${token("--series-other")}"></i>
      <span class="group-name muted">unlabeled</span>
      <span class="hint">zone${unlabeled.length > 1 ? "s" : ""} ${unlabeled.join(", ")}</span></li>`);
  }
  $("group-list").innerHTML = rows.join("");
}

async function saveLabels() {
  if (!sessionId) return;
  try {
    await post(`/api/session/${sessionId}/labels`, { labels: collectLabels() });
  } catch (error) {
    $("run-status").textContent = `Could not save labels: ${error.message}`;
  }
}

async function run() {
  const buttons = document.querySelectorAll(".run-trigger, #run-btn");
  const status = $("run-status");
  buttons.forEach((b) => { b.disabled = true; });
  status.className = "hint";
  status.innerHTML = `<span class="spinner"></span> Running… the frames are being decoded, this takes a while.`;

  try {
    results = await post(`/api/session/${sessionId}/run`, { labels: collectLabels() });
    runStamp = Date.now();
    labelsChanged = false;
    status.textContent = "Done.";
    go("#/results");
  } catch (error) {
    status.className = "hint error";
    status.textContent = error.message;
    if (!location.hash.startsWith("#/label")) go("#/label");
  } finally {
    buttons.forEach((b) => { b.disabled = false; });
  }
}

$("run-btn").addEventListener("click", run);

// --- 3 · results ------------------------------------------------------------

const zoneById = (id) => results.zones.find((zone) => zone.id === id);
const mitesIn = (zoneId) => results.mites.filter((mite) => mite.zone_id === zoneId);
const zoneName = (zone) => `Zone ${zone.id}${zone.label ? ` · ${zone.label}` : ""}`;
const lastIndex = () => results.times.length - 1;
const aliveAtEnd = (mite) => mite.alive[lastIndex()];
// Dead from the first recording means it never moved above the threshold at all.
const diedText = (mite) => (mite.died_at == null ? "–" : mite.died_at <= results.times[0] ? "never moved" : minutes(mite.died_at));

function breadcrumb(parts) {
  // The overview is the top level, so it needs no trail.
  $("breadcrumb").hidden = parts.length < 2;
  $("breadcrumb").innerHTML = parts
    .map(([text, href], i) =>
      i === parts.length - 1 ? `<span aria-current="page">${esc(text)}</span>` : `<a href="${href}">${esc(text)}</a>`)
    .join(`<span class="crumb-sep" aria-hidden="true">/</span>`);
}

// --- page building blocks ----------------------------------------------------

function stat(label, value, note = "") {
  return `<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${value}</div>${note ? `<div class="stat-note">${note}</div>` : ""}</div>`;
}

const groupTag = (group, color) => `<span class="grp"><i style="background:${color}"></i>${esc(group)}</span>`;

// A numbered figure: the content goes in the element with `id`, the caption below.
function figure(id, number, title, caption, extraClass = "") {
  return `<figure class="fig">
      <div class="fig-title">${title}</div>
      <div id="${id}" class="${extraClass}"></div>
      <figcaption><b>Fig. ${number}.</b> ${caption}</figcaption>
    </figure>`;
}

const section = (title, inner) => `<section class="block"><h2>${title}</h2>${inner}</section>`;

function staleBanner() {
  if (!labelsChanged) return "";
  return `<div class="banner">Labels changed since this run, so the groups below are out of date.
    <button type="button" class="run-trigger small">Run again</button></div>`;
}

function wireRunAgain(body) {
  body.querySelectorAll(".run-trigger").forEach((button) => button.addEventListener("click", () => {
    go("#/label");
    run();
  }));
}

const survivalNote =
  "A mite counts as alive up to its last recording with movement above the threshold, and dead from then on, so a mite that rests for one recording is not counted as dead.";

// --- overview ------------------------------------------------------------------

function showOverview() {
  breadcrumb([["Results", "#/results"]]);
  const { summary, times } = results;
  const groups = resultGroups();
  const body = $("results-body");
  const span = times.length > 1 ? `over ${minutes(times[times.length - 1] - times[0])}` : "";

  body.innerHTML = `
    ${staleBanner()}
    <header class="page-head">
      <div>
        <h1>Results</h1>
        <p class="meta">${esc($("folder-name").textContent)} · ${results.n_recordings} recordings ${span} · movement threshold ${score(results.threshold)}</p>
      </div>
    </header>

    <div class="stats">
      ${stat("Mites detected", summary.n_mites)}
      ${stat("Alive at end", `${summary.n_alive_at_end} <small>(${pct(summary.n_alive_at_end / summary.n_mites)})</small>`)}
      ${stat("Groups", summary.n_groups)}
      ${stat("Recordings", results.n_recordings, span)}
    </div>

    <div class="grid-2">
      ${figure("chart-group-survival", 1, "Survival by group", `Fraction of mites alive at each recording. ${survivalNote}`)}
      ${figure("result-plate", 2, "Plate map",
        `First frame with every detected mite, <span class="status alive">● alive</span> or <span class="status dead">✕ dead</span> at the end of the session. Select a zone to open it.`, "plate")}
    </div>

    ${section("Survival per zone", `<div id="zone-cards" class="zone-cards"></div>
      <p class="caption">Fraction of each zone's mites alive over the session, on a 0–100% scale. Select a zone to open it.</p>`)}

    ${section("Group summary", `<div class="table-wrap"><table id="group-table"></table></div>`)}

    ${section("Files", `<ul class="files">
        <li><a href="${fileUrl(results.excel)}" download>${esc(results.excel)}</a> <span class="muted">measurements, group summary and survival</span></li>
        ${[...results.figures, results.detections]
          .map((name) => `<li><a href="${fileUrl(name)}" target="_blank" rel="noopener">${esc(name)}</a></li>`).join("")}
      </ul>`)}`;
  wireRunAgain(body);

  Charts.line($("chart-group-survival"), {
    x: times,
    yLabel: "Mites alive (%)",
    yMin: 0, yMax: 100,
    yFormat: (v) => `${Math.round(v)}`,
    series: results.groups.map((g) => ({
      name: g.group,
      values: g.survival.map((v) => (v == null ? null : v * 100)),
      color: groupColor(g.group, groups),
      step: true,
    })),
  });

  drawResultPlate(groups);
  drawZoneCards(groups);
  drawGroupTable(groups);
}

function drawResultPlate(groups) {
  const plate = $("result-plate");
  const place = plateOverlay(plate, fileUrl(results.preview), results.image);

  results.zones.forEach((zone) => {
    const color = groupColor(zone.label || "unlabeled", groups);
    const link = document.createElement("a");
    link.className = "zone result";
    link.href = `#/zone/${zone.id}`;
    link.setAttribute("aria-label", `Zone ${zone.id}, ${zone.label || "unlabeled"}, ${zone.n_mites ? `${zone.n_alive_at_end} of ${zone.n_mites} mites alive` : "no mites"}`);
    Object.assign(link.style, place(zone.x1, zone.y1, zone.x2, zone.y2));
    link.style.setProperty("--zone-color", color);
    link.innerHTML = `<span class="zone-num">${zone.id}</span>`;

    // Name and count go in the plate's label area, clear of the mite dots.
    const rect = textRect(zone);
    const text = document.createElement("a");
    text.className = "text-zone";
    text.href = link.href;
    text.tabIndex = -1;
    Object.assign(text.style, place(rect.x1, rect.y1, rect.x2, rect.y2));
    text.style.setProperty("--zone-color", color);
    const count = zone.n_mites ? `${zone.n_alive_at_end}/${zone.n_mites} alive` : "no mites";
    text.title = `Zone ${zone.id} · ${zone.label || "unlabeled"} · ${count}`;
    text.innerHTML = `<span class="text-tag">${esc(zone.label || "unlabeled")}
      <small>${zone.n_mites ? `${zone.n_alive_at_end}/${zone.n_mites}` : "–"}</small></span>`;

    linkHover([link, text]);
    plate.append(link, text);
  });

  // A dot per mite, coloured by whether it is alive at the end.
  results.mites.forEach((mite) => {
    const dot = document.createElement("span");
    dot.className = `mite-dot ${aliveAtEnd(mite) ? "alive" : "dead"}`;
    dot.style.left = percent(mite.x, results.image.width);
    dot.style.top = percent(mite.y, results.image.height);
    plate.appendChild(dot);
  });
}

// Small multiples: one framed mini survival plot per zone.
function drawZoneCards(groups) {
  const container = $("zone-cards");
  results.zones.forEach((zone) => {
    const color = groupColor(zone.label || "unlabeled", groups);
    const card = document.createElement("a");
    card.className = "zone-card";
    card.href = `#/zone/${zone.id}`;
    card.innerHTML = `
      <div class="zone-card-head">
        <span class="zone-card-id">Zone ${zone.id}</span>
        <span class="zone-card-value">${zone.n_mites ? `${zone.n_alive_at_end}/${zone.n_mites}` : "–"}</span>
      </div>
      <div class="zone-card-group">${groupTag(zone.label || "unlabeled", color)}</div>`;
    const plot = document.createElement("div");
    plot.className = "zone-card-plot";
    if (zone.survival) Charts.spark(plot, { values: zone.survival, color });
    else plot.innerHTML = `<span class="muted">no mites detected</span>`;
    card.appendChild(plot);
    container.appendChild(card);
  });
}

function drawGroupTable(groups) {
  const columns = [
    ["group", "Group"], ["n_mites", "Mites"], ["n_alive_at_end", "Alive at end"],
    ["survival_at_end", "Survival"], ["mean_score", "Mean score"], ["std_score", "SD"], ["median_score", "Median"],
  ];
  const format = (key, value) => (key === "survival_at_end" ? pct(value) : key.endsWith("score") ? score(value) : esc(value));
  $("group-table").innerHTML = `
    <thead><tr>${columns.map(([key, name]) => `<th class="${key === "group" ? "" : "num"}">${name}</th>`).join("")}</tr></thead>
    <tbody>${results.summary.groups.map((row) => `<tr>${columns.map(([key]) =>
      key === "group"
        ? `<td>${groupTag(row.group, groupColor(row.group, groups))}</td>`
        : `<td class="num">${format(key, row[key])}</td>`).join("")}</tr>`).join("")}</tbody>`;
}

// --- zone and mite pages -------------------------------------------------------

// A crop of the first frame, drawn as SVG so the viewBox does the cropping.
function cropSvg(x, y, w, h, src = fileUrl(results.preview), size = results.image) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `${x} ${y} ${w} ${h}`);
  svg.setAttribute("class", "crop");
  const image = document.createElementNS("http://www.w3.org/2000/svg", "image");
  image.setAttribute("href", src);
  image.setAttribute("width", size.width);
  image.setAttribute("height", size.height);
  svg.appendChild(image);
  return svg;
}

function miteMarker(svg, mite, radius, { withLabel = true, onClick = null } = {}) {
  const ns = "http://www.w3.org/2000/svg";
  const g = document.createElementNS(ns, "g");
  g.setAttribute("class", `mite-marker ${aliveAtEnd(mite) ? "alive" : "dead"}`);
  const circle = document.createElementNS(ns, "circle");
  circle.setAttribute("cx", mite.x);
  circle.setAttribute("cy", mite.y);
  circle.setAttribute("r", radius);
  g.appendChild(circle);
  if (withLabel) {
    const text = document.createElementNS(ns, "text");
    text.setAttribute("x", mite.x + radius + 4);
    text.setAttribute("y", mite.y - radius);
    text.setAttribute("font-size", radius * 1.1);
    text.textContent = mite.id;
    g.appendChild(text);
  }
  if (onClick) {
    g.style.cursor = "pointer";
    g.addEventListener("click", onClick);
    g.addEventListener("mousemove", (event) => Charts.showTooltip(event,
      `<div class="tip-title">Mite ${esc(mite.id)}</div>${statusBadge(aliveAtEnd(mite))} at end<div class="tip-hint">Click to open</div>`));
    g.addEventListener("mouseleave", Charts.hideTooltip);
  }
  svg.appendChild(g);
}

function pager(items, index, hrefOf, labelOf) {
  const prev = items[index - 1];
  const next = items[index + 1];
  return `<nav class="pager" aria-label="Previous and next">
    ${prev ? `<a class="button secondary small" href="${hrefOf(prev)}">← ${esc(labelOf(prev))}</a>` : ""}
    ${next ? `<a class="button secondary small" href="${hrefOf(next)}">${esc(labelOf(next))} →</a>` : ""}
  </nav>`;
}

function showZone(zoneId) {
  const zone = zoneById(zoneId);
  if (!zone) { location.replace("#/results"); return; }
  const groups = resultGroups();
  const group = zone.label || "unlabeled";
  const color = groupColor(group, groups);
  const mites = mitesIn(zone.id);
  const { times } = results;
  breadcrumb([["Results", "#/results"], [zoneName(zone), `#/zone/${zone.id}`]]);

  // Deaths during the session; mites that never moved are counted separately.
  const deaths = mites.map((m) => m.died_at).filter((t) => t != null && t > times[0]);
  const neverMoved = mites.filter((m) => m.died_at != null && m.died_at <= times[0]).length;
  const meanScore = mites.length ? mites.flatMap((m) => m.scores).reduce((a, b) => a + b, 0) / (mites.length * times.length) : null;
  const zoneIndex = results.zones.indexOf(zone);
  const body = $("results-body");

  body.innerHTML = `
    ${staleBanner()}
    <header class="page-head">
      <div>
        <h1>Zone ${zone.id}</h1>
        <p class="meta">${groupTag(group, color)}</p>
      </div>
      ${pager(results.zones, zoneIndex, (z) => `#/zone/${z.id}`, (z) => `Zone ${z.id}`)}
    </header>

    <div class="stats">
      ${stat("Mites", mites.length)}
      ${stat("Alive at end", mites.length ? `${zone.n_alive_at_end} <small>(${pct(zone.n_alive_at_end / mites.length)})</small>` : "–")}
      ${stat("First death", deaths.length ? minutes(Math.min(...deaths)) : "–",
        [deaths.length ? `${deaths.length} died during the session` : "", neverMoved ? `${neverMoved} never moved` : ""].filter(Boolean).join(", "))}
      ${stat("Mean motion score", score(meanScore), `threshold ${score(results.threshold)}`)}
    </div>

    <div class="grid-2">
      ${figure("zone-crop", 1, "Plate, first frame",
        `Detected mites, <span class="status alive">● alive</span> or <span class="status dead">✕ dead</span> at the end of the session. Select a mite to open it.`, "crop-wrap")}
      ${mites.length ? figure("chart-zone-survival", 2, "Survival", "Fraction of this zone's mites alive at each recording, with the whole group for comparison where the group spans several zones.") : ""}
    </div>

    ${mites.length ? `
    <div class="grid-2">
      ${figure("chart-zone-scores", 3, "Motion score per mite",
        "Thin lines are single mites, coloured by their status at the end; the black line is the mean. Hover to identify a mite, select to open it.")}
      ${section("Mites", `<div class="table-wrap"><table class="clickable" id="mite-table"></table></div>`)}
    </div>` : `<p class="muted">No mites were detected in this zone.</p>`}`;
  wireRunAgain(body);

  // Crop with some margin, then mark each mite.
  const margin = 20;
  const crop = cropSvg(zone.x1 - margin, zone.y1 - margin, zone.x2 - zone.x1 + 2 * margin, zone.y2 - zone.y1 + 2 * margin);
  const outline = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  Object.entries({ x: zone.x1, y: zone.y1, width: zone.x2 - zone.x1, height: zone.y2 - zone.y1, class: "zone-outline" })
    .forEach(([k, v]) => outline.setAttribute(k, v));
  outline.style.stroke = color;
  crop.appendChild(outline);
  const radius = Math.max(10, (zone.x2 - zone.x1) / 28);
  mites.forEach((mite) => miteMarker(crop, mite, radius, { onClick: () => go(`#/mite/${encodeURIComponent(mite.id)}`) }));
  $("zone-crop").appendChild(crop);

  if (!mites.length) return;

  const groupCurve = results.groups.find((g) => g.group === group);
  Charts.line($("chart-zone-survival"), {
    x: times,
    yLabel: "Mites alive (%)",
    yMin: 0, yMax: 100,
    yFormat: (v) => `${Math.round(v)}`,
    series: [
      { name: `Zone ${zone.id}`, values: zone.survival.map((v) => v * 100), color, step: true },
      ...(groupCurve && results.zones.filter((z) => (z.label || "unlabeled") === group && z.n_mites).length > 1
        ? [{ name: `all “${group}”`, values: groupCurve.survival.map((v) => (v == null ? null : v * 100)), color: token("--muted"), step: true, dashed: true, markers: false }]
        : []),
    ],
    tooltipExtra: (i) => {
      const alive = mites.filter((m) => m.alive[i]).length;
      return `<div class="tip-note">${alive} of ${mites.length} mites alive</div>`;
    },
  });

  const alive = token("--good");
  const dead = token("--critical");
  Charts.line($("chart-zone-scores"), {
    x: times,
    yLabel: "Motion score",
    forceLegend: true,
    noDirectLabels: true,
    threshold: { value: results.threshold, label: "threshold" },
    series: [
      ...mites.map((mite) => ({
        name: `Mite ${mite.id}`,
        values: mite.scores,
        color: aliveAtEnd(mite) ? alive : dead,
        width: 1,
        faint: true,
        legend: false,
        tooltip: false,
        onClick: () => go(`#/mite/${encodeURIComponent(mite.id)}`),
      })),
      { name: "mean", values: zone.mean_score, color: token("--ink"), width: 2 },
      { name: "alive at end", values: times.map(() => null), color: alive },
      { name: "dead by end", values: times.map(() => null), color: dead },
    ],
  });

  const table = $("mite-table");
  table.innerHTML = `
    <thead><tr><th>Mite</th><th>At end</th><th class="num">Died at</th><th class="num">Moving</th><th class="num">Mean</th><th class="num">Max</th></tr></thead>
    <tbody>${mites.map((mite) => `
      <tr data-href="#/mite/${encodeURIComponent(mite.id)}" tabindex="0">
        <td><a href="#/mite/${encodeURIComponent(mite.id)}">${esc(mite.id)}</a></td>
        <td>${statusBadge(aliveAtEnd(mite))}</td>
        <td class="num">${diedText(mite)}</td>
        <td class="num">${mite.moving.filter(Boolean).length}/${times.length}</td>
        <td class="num">${score(mite.scores.reduce((a, b) => a + b, 0) / mite.scores.length)}</td>
        <td class="num">${score(Math.max(...mite.scores))}</td>
      </tr>`).join("")}</tbody>`;
  table.querySelectorAll("tr[data-href]").forEach((row) => {
    row.addEventListener("click", () => go(row.dataset.href));
    row.addEventListener("keydown", (event) => { if (event.key === "Enter") go(row.dataset.href); });
  });
}

function showMite(miteId) {
  const mite = results.mites.find((m) => m.id === miteId);
  if (!mite) { location.replace("#/results"); return; }
  const zone = zoneById(mite.zone_id);
  const siblings = mitesIn(zone.id);
  const { times } = results;
  const groups = resultGroups();
  const color = groupColor(zone.label || "unlabeled", groups);
  breadcrumb([["Results", "#/results"], [zoneName(zone), `#/zone/${zone.id}`], [`Mite ${mite.id}`, ""]]);

  const nMoving = mite.moving.filter(Boolean).length;
  const body = $("results-body");
  body.innerHTML = `
    ${staleBanner()}
    <header class="page-head">
      <div>
        <h1>Mite ${esc(mite.id)}</h1>
        <p class="meta">${statusBadge(aliveAtEnd(mite))} at end · <a href="#/zone/${zone.id}">Zone ${zone.id}</a> · ${groupTag(zone.label || "unlabeled", color)}</p>
      </div>
      ${pager(siblings, siblings.indexOf(mite), (m) => `#/mite/${encodeURIComponent(m.id)}`, (m) => `Mite ${m.id}`)}
    </header>

    <div class="stats">
      ${stat("Status at end", aliveAtEnd(mite) ? "Alive" : "Dead")}
      ${stat("Died at", diedText(mite), mite.died_at == null ? "alive throughout" : mite.died_at <= times[0] ? "no movement in any recording" : "first recording counted dead")}
      ${stat("Moving in", `${nMoving}/${times.length}`, "recordings above threshold")}
      ${stat("Max motion score", score(Math.max(...mite.scores)), `threshold ${score(results.threshold)}`)}
    </div>

    <div class="grid-mite">
      ${figure("mite-crop", 1, "Close-up", "First frame, 140 × 140 px around the mite.", "crop-wrap square")}
      ${figure("chart-mite", 2, "Motion score over time",
        `<span class="status alive">●</span> moving (at or above the threshold), <span class="status dead">●</span> still. ${survivalNote}`)}
    </div>

    ${section("Recordings", `<div class="table-wrap"><table>
        <thead><tr><th class="num">Time</th><th class="num">Motion score</th><th>Moving</th><th>Counted as</th></tr></thead>
        <tbody>${times.map((t, i) => `<tr>
          <td class="num">${minutes(t)}</td>
          <td class="num">${score(mite.scores[i])}</td>
          <td>${mite.moving[i] ? "yes" : "no"}</td>
          <td>${statusBadge(mite.alive[i])}</td></tr>`).join("")}</tbody>
      </table></div>`)}`;
  wireRunAgain(body);

  const size = 140;
  const crop = cropSvg(mite.x - size / 2, mite.y - size / 2, size, size);
  miteMarker(crop, mite, 22, { withLabel: false });
  $("mite-crop").appendChild(crop);

  const good = token("--good");
  const critical = token("--critical");
  Charts.line($("chart-mite"), {
    x: times,
    yLabel: "Motion score",
    noDirectLabels: true,
    threshold: { value: results.threshold, label: "threshold" },
    series: [{
      name: `Mite ${mite.id}`,
      values: mite.scores,
      color: token("--ink"),
      width: 1.5,
      pointColors: mite.moving.map((moving) => (moving ? good : critical)),
    }],
    tooltipExtra: (i) => `<div class="tip-note">${mite.moving[i] ? "moving" : "still"} · counted ${mite.alive[i] ? "alive" : "dead"}</div>`,
  });
}

// route() is first called from calibration.js, which loads last.
