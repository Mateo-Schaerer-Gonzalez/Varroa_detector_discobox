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
let shown = 0;           // the recording the result pages show; the last after a run
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

// Only zones with a detected mite can be labelled; the others have nothing to analyse.
const labelZones = () => session.zones.filter((zone) => zone.n_mites > 0);
const labelGroups = () =>
  [...new Set(labelZones().map((zone) => zone.label.trim()).filter(Boolean))].sort();
// Every labelled zone counts, including groups where no mite was found, so a
// group keeps the same colour here as on the labelling page.
const resultGroups = () =>
  [...new Set([...results.groups.map((g) => g.group), ...results.zones.map((z) => z.label).filter(Boolean)])].sort();

// Moving or still in one recording: always a glyph and a word, never colour alone.
function movingBadge(moving) {
  return moving
    ? `<span class="status moving"><span aria-hidden="true">●</span> moving</span>`
    : `<span class="status still"><span aria-hidden="true">○</span> still</span>`;
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
  stopPlayer();
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
  if (step === "results") drawResults();
  window.scrollTo(0, 0);
}

// The results page in the address bar: the overview, a zone or a mite.
function drawResults() {
  const [, view, id] = location.hash.split("/");
  stopPlayer();
  Charts.hideTooltip();
  if (view === "zone") showZone(Number(id));
  else if (view === "mite") showMite(decodeURIComponent(id));
  else showOverview();
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
    const withMites = labelZones().length;
    $("run-status").textContent = `${session.n_recordings} recordings loaded · mites detected in ${withMites} of ${session.zones.length} zones.`;
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

  session.zones.filter((zone) => !zone.n_mites).forEach((zone) => {
    const box = document.createElement("div");
    box.className = "zone no-mites";
    box.title = `Zone ${zone.id}: no mites detected, nothing to label`;
    Object.assign(box.style, place(zone.x1, zone.y1, zone.x2, zone.y2));
    box.innerHTML = `<span class="zone-num">${zone.id}</span>`;
    plate.appendChild(box);
  });

  labelZones().forEach((zone) => {
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
    box.setAttribute("aria-label", `Zone ${zone.id}, ${zone.n_mites} mite${zone.n_mites === 1 ? "" : "s"}: ${label || "no label"}. Click to edit.`);
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
      const ids = labelZones().map((z) => z.id);
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
  labelZones().forEach((zone) => { if (zone.label.trim()) labels[zone.id] = zone.label.trim(); });
  return labels;
}

// Offer labels already typed as autocomplete, so repeating a group is one keystroke.
function refreshSuggestions() {
  $("known-labels").innerHTML = labelGroups().map((label) => `<option value="${esc(label)}">`).join("");
}

function drawGroupList() {
  const groups = labelGroups();
  const rows = groups.map((group) => {
    const ids = labelZones().filter((z) => z.label.trim() === group).map((z) => z.id);
    return `<li><i class="swatch" style="background:${groupColor(group, groups)}"></i>
      <span class="group-name">${esc(group)}</span>
      <span class="hint">zone${ids.length > 1 ? "s" : ""} ${ids.join(", ")}</span></li>`;
  });
  const unlabeled = labelZones().filter((z) => !z.label.trim()).map((z) => z.id);
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
    shown = results.times.length - 1;
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

// --- playing a recording ------------------------------------------------------
//
// One clip plays at a time, in a loop, on any page: the frames of one recording,
// of one zone or of the whole plate. Used by the result pages and by the
// ground-truth page of the calibration window.

const player = { timer: null, token: 0, frames: [], index: 0, show: null, interval: 100, playing: true };

function stopPlayer() {
  clearInterval(player.timer);
  player.timer = null;
  player.token += 1;
}

function startPlayerTimer() {
  clearInterval(player.timer);
  if (!player.playing || player.frames.length < 2) return;
  player.timer = setInterval(() => {
    player.index = (player.index + 1) % player.frames.length;
    player.show(player.frames[player.index]);
  }, player.interval);
}

// Play or pause; returns whether it now plays.
function togglePlaying() {
  player.playing = !player.playing;
  if (player.playing) startPlayerTimer();
  else clearInterval(player.timer);
  return player.playing;
}

// Fetch a clip's description from `url` and preload its frames, whose URLs
// `frameUrl` makes from their names. Null when another clip was asked for meanwhile.
async function loadClip(url, frameUrl) {
  stopPlayer();
  const token = player.token;
  try {
    const response = await fetch(url);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Could not load the recording");
    const frames = data.frames.map(frameUrl);
    await Promise.all(frames.map((src) => new Promise((resolve) => {
      const image = new Image();
      image.onload = image.onerror = resolve;
      image.src = src;
    })));
    return token === player.token ? { ...data, frames } : null;
  } catch (error) {
    if (token !== player.token) return null;
    throw error;
  }
}

// Show a loaded clip's frames in turn through `show(src)`.
function startPlayer(clip, show) {
  Object.assign(player, { frames: clip.frames, index: 0, show, interval: clip.interval_ms });
  show(clip.frames[0]);
  startPlayerTimer();
}

// Put a clip over the full-image coordinates of an SVG crop; returns its `show`.
function clipOnSvg(svg, clip) {
  const image = svg.querySelector("image");
  Object.entries({ x: clip.x, y: clip.y, width: clip.width, height: clip.height })
    .forEach(([key, value]) => image.setAttribute(key, value));
  return (src) => image.setAttribute("href", src);
}

// --- 3 · results ------------------------------------------------------------

const zoneById = (id) => results.zones.find((zone) => zone.id === id);
const mitesIn = (zoneId) => results.mites.filter((mite) => mite.zone_id === zoneId);
const zoneName = (zone) => `Zone ${zone.id}${zone.label ? ` · ${zone.label}` : ""}`;
const lastIndex = () => results.times.length - 1;
const movingLast = (mite) => mite.moving[lastIndex()];
const nMoving = (mite) => mite.moving.filter(Boolean).length;
// Time of the last recording in which the mite moved.
const lastMovementText = (mite) => {
  const last = mite.moving.lastIndexOf(true);
  return last < 0 ? "never" : minutes(results.times[last]);
};

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
      <div class="fig-title fig-title-row">${title}${downloadButtons(id, title)}</div>
      <div id="${id}" class="${extraClass}"></div>
      <figcaption><b>Fig. ${number}.</b> ${caption}</figcaption>
    </figure>`;
}

// SVG and PNG buttons for the chart in the element `id`; hidden by the stylesheet
// when that element holds no chart (a table, a map).
// `legendId`: the element holding the legend, when it is shared and not in the chart.
function downloadButtons(id, title, legendId = "") {
  const data = `data-download="${id}" data-title="${esc(title)}"${legendId ? ` data-legend="${legendId}"` : ""}`;
  return `<span class="fig-download" role="group" aria-label="Download ${esc(title)}">
      <button type="button" class="secondary small" ${data} data-format="svg" title="Download as SVG, for editing or print">SVG</button>
      <button type="button" class="secondary small" ${data} data-format="png" title="Download as PNG">PNG</button>
    </span>`;
}

const slug = (text) => String(text).toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// Files are named after the recording folder, the page and the chart,
// e.g. sample_data_zone-4_mites-moving.png.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-download]");
  if (!button) return;
  const container = $(button.dataset.download);
  const view = document.querySelector("main > .view:not([hidden])");
  const page = view?.querySelector("h1")?.textContent || "";
  const folder = $("folder-name").textContent;
  const filename = [folder, page, button.dataset.title].map(slug).filter(Boolean).join("_");
  Charts.download(container, {
    title: [page, button.dataset.title].filter(Boolean).join(" · "),
    filename,
    format: button.dataset.format,
    legend: button.dataset.legend ? $(button.dataset.legend) : null,
  }).catch((error) => alert(`Could not save the chart: ${error.message}`));
});

// A figure playing the recording shown, with a tab per recording above it; the
// clip goes in the element with `id`, its loading status below it.
function clipFigure(id, number, title, caption, extraClass = "") {
  return `<figure class="fig">
      <div class="fig-title">${title}</div>
      ${recordingBar()}
      <div id="${id}" class="${extraClass}"></div>
      <p class="hint clip-status"></p>
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

const movingNote =
  "A mite counts as moving in a recording when its motion score in that recording reaches the threshold.";

// --- the recording on screen

const shownTime = () => minutes(results.times[shown]);
const movingShown = (mite) => mite.moving[shown];
const nMovingShown = (zone) => mitesIn(zone.id).filter(movingShown).length;
// Zones worth a look: those with a detected mite.
const zonesWithMites = () => results.zones.filter((zone) => zone.n_mites);

// One tab per recording, as on the ground-truth page. The clip always loops.
function recordingBar() {
  return `<div class="rec-bar">
    <nav class="rec-tabs" aria-label="Recording shown">${results.times.map((time, i) => `
      <a href="#" class="rec-tab${i === shown ? " current" : ""}" data-recording="${i}" ${i === shown ? 'aria-current="true"' : ""}
        title="Show the recording at ${minutes(time)}">${minutes(time)}</a>`).join("")}</nav>
  </div>`;
}

function wireRecordingBar(body) {
  body.querySelectorAll("[data-recording]").forEach((tab) => tab.addEventListener("click", (event) => {
    event.preventDefault();
    showRecording(Number(tab.dataset.recording));
  }));
}

// Show another recording on the page on screen, from a tab, a chart or a table.
function showRecording(index) {
  if (index === shown || !(index >= 0 && index < results.times.length)) return;
  shown = index;
  drawResults();
}

// Load a clip of the recording shown and play it; `place(clip)` returns its `show`.
// Until it plays, `wrap` shows the first frame dimmed.
async function playResultClip(url, wrap, status, place) {
  wrap.classList.add("loading");
  status.className = "hint clip-status";
  status.innerHTML = `<span class="spinner"></span> Loading the recording at ${shownTime()}…`;
  try {
    // The frames of a recording never change, so they need no cache-buster.
    const clip = await loadClip(url, (name) => `/api/session/${sessionId}/file/${name}`);
    if (!clip) return;
    wrap.classList.remove("loading");
    status.textContent = `Recording at ${shownTime()}: ${clip.frames.length} frames, looped in real time.`;
    player.playing = true;
    startPlayer(clip, place(clip));
  } catch (error) {
    wrap.classList.remove("loading");
    status.className = "hint clip-status error";
    status.textContent = `${error.message} Showing the first frame.`;
  }
}

// ● and ○ per recording, the one on screen underlined.
function movementGlyphs(mite) {
  return `<div class="tip-glyphs">${mite.moving.map((moving, i) =>
    `<span class="${moving ? "moving" : "still"}${i === shown ? " current" : ""}">${moving ? "●" : "○"}</span>`).join("")}</div>`;
}

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
      ${stat("Moving in the last recording", `${summary.n_moving_last} <small>(${pct(summary.n_moving_last / summary.n_mites)})</small>`)}
      ${stat("Groups", summary.n_groups)}
      ${stat("Recordings", results.n_recordings, span)}
    </div>

    <div class="clip-block">
      ${clipFigure("result-plate", 1, `Plate map · recording at ${shownTime()}`,
        `The recording at ${shownTime()}, looped, with every detected mite ${movingBadge(true)} or ${movingBadge(false)} in it.
        Choose a recording above, or click a time in a chart. Select a zone to open it.`, "plate")}
    </div>

    <div class="block">
      ${figure("chart-group-moving", 2, "Mites moving by group",
        `Fraction of each group's mites moving in each recording. ${movingNote} Click a time to show that recording.`)}
    </div>

    ${section("Movement per zone", `<div id="zone-cards" class="zone-cards"></div>
      <p class="caption">Fraction of each zone's mites moving in each recording, on a 0–100% scale; the number is how many moved in the last recording.
        Zones without mites are left out. Select a zone to open it.</p>`)}

    ${section("Group summary", `<div class="table-wrap"><table id="group-table"></table></div>
      <p class="caption"><b>Moving</b> is the share of all mite-recordings in which the mite moved.</p>`)}

    <div class="block">${figure("chart-group-scores", 3, "Motion scores by group",
      `Every mite in every recording at its motion score, one row per group, pooling every zone with that label: ${movingBadge(true)} at or above the threshold (dashed line),
      ${movingBadge(false)} below it. The box spans the middle half of the zone's scores with a line at the median; the whiskers reach the
      furthest scores within 1.5 box lengths. The box and whiskers are over all the group's mite-recordings. Points of the recording shown are drawn larger. Select a point to open that mite in that recording.`)}</div>

    ${section("Files", `<ul class="files">
        <li><a href="${fileUrl(results.excel)}" download>${esc(results.excel)}</a> <span class="muted">measurements, group summary and movement over time</span></li>
      </ul>
      <p class="caption">Every chart above can be downloaded as SVG or PNG from the buttons beside its title.</p>`)}`;
  wireRunAgain(body);
  wireRecordingBar(body);

  Charts.line($("chart-group-moving"), {
    x: times,
    selected: shown,
    onXClick: showRecording,
    yLabel: "Mites moving (%)",
    yMin: 0, yMax: 100,
    yFormat: (v) => `${Math.round(v)}`,
    series: results.groups.map((g) => ({
      name: g.group,
      values: g.moving.map((v) => (v == null ? null : v * 100)),
      color: groupColor(g.group, groups),
    })),
  });

  drawResultPlate(groups);
  drawZoneCards(groups);
  drawGroupTable(groups);
  drawGroupScores(groups);
}

// Quartiles and Tukey whiskers of a list of numbers.
function boxStats(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const at = (q) => {
    const i = (sorted.length - 1) * q;
    const lo = Math.floor(i);
    return sorted[lo] + (sorted[Math.min(lo + 1, sorted.length - 1)] - sorted[lo]) * (i - lo);
  };
  const [q1, median, q3] = [at(0.25), at(0.5), at(0.75)];
  const reach = 1.5 * (q3 - q1);
  return {
    q1, median, q3,
    lo: sorted.find((v) => v >= q1 - reach),
    hi: [...sorted].reverse().find((v) => v <= q3 + reach),
  };
}

// Like the calibration's "Scores by your label": each mite-recording at its
// score, one row per group (every zone with the same label), against the
// threshold, with a box plot per group.
function drawGroupScores(groups) {
  const byGroup = new Map();
  zonesWithMites().forEach((zone) => {
    const group = zone.label || "unlabeled";
    if (!byGroup.has(group)) byGroup.set(group, []);
    byGroup.get(group).push(zone);
  });
  // Named groups alphabetically, "unlabeled" last; the first on top.
  const names = [...byGroup.keys()].sort((a, b) => (a === "unlabeled") - (b === "unlabeled") || a.localeCompare(b));
  const row = (index) => names.length - 1 - index;
  const jitter = (key) => {
    let hash = 7;
    for (const char of key) hash = (hash * 31 + char.charCodeAt(0)) % 1009;
    return (hash / 1009 - 0.5) * 0.5;
  };
  const points = [];
  const boxes = [];
  const categories = [];
  names.forEach((group, index) => {
    const zones = byGroup.get(group);
    const mites = zones.flatMap((zone) => mitesIn(zone.id));
    boxes.push({ y: row(index), color: groupColor(group, groups), ...boxStats(mites.flatMap((m) => m.scores)) });
    categories.push({ value: row(index), label: `${group} (${mites.length})` });
    mites.forEach((mite) => mite.scores.forEach((value, recording) => {
      const moving = mite.moving[recording];
      points.push({
        x: value,
        y: row(index) + jitter(`${mite.id}/${recording}`),
        color: token(moving ? "--moving" : "--still"),
        shape: moving ? "circle" : "cross",
        r: recording === shown ? 4.5 : 2.75,
        tip: `<div class="tip-title">Mite ${esc(mite.id)} · zone ${mite.zone_id} · ${minutes(results.times[recording])}</div>
          <div class="tip-note">${esc(group)} · zones ${zones.map((z) => z.id).join(", ")}</div>
          <div>${movingBadge(moving)} · score ${score(value)}</div>${movementGlyphs(mite)}
          <div class="tip-hint">Click to open this mite in this recording</div>`,
        onClick: () => { shown = recording; go(`#/mite/${encodeURIComponent(mite.id)}`); },
      });
    }));
  });
  // On paper there is no recording on screen: every point the same size.
  $("chart-group-scores").exportAdjust = (options) => ({
    ...options, points: options.points.map((point) => ({ ...point, r: 3 })),
  });
  Charts.scatter($("chart-group-scores"), {
    height: Math.max(180, names.length * 44 + 60),
    padLeft: 150,
    points,
    boxes,
    refX: [{ value: results.threshold, label: `threshold ${score(results.threshold)}` }],
    yCategories: categories,
    yMin: -0.6, yMax: names.length - 0.4,
    xMin: 0,
    xLabel: "Motion score",
    legend: [
      { name: "moving", color: token("--moving"), shape: "circle" },
      { name: "still", color: token("--still"), shape: "cross" },
    ],
  });
}

function drawResultPlate(groups) {
  const plate = $("result-plate");
  const place = plateOverlay(plate, fileUrl(results.preview), results.image);

  // A zone without mites is only a faint outline: nothing to open or read there.
  results.zones.filter((zone) => !zone.n_mites).forEach((zone) => {
    const box = document.createElement("div");
    box.className = "zone no-mites";
    box.title = `Zone ${zone.id}: no mites detected`;
    Object.assign(box.style, place(zone.x1, zone.y1, zone.x2, zone.y2));
    plate.appendChild(box);
  });

  zonesWithMites().forEach((zone) => {
    const color = groupColor(zone.label || "unlabeled", groups);
    const link = document.createElement("a");
    link.className = "zone result";
    link.href = `#/zone/${zone.id}`;
    link.setAttribute("aria-label", `Zone ${zone.id}, ${zone.label || "unlabeled"}, ${zone.n_mites ? `${nMovingShown(zone)} of ${zone.n_mites} mites moving at ${shownTime()}` : "no mites"}`);
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
    const count = zone.n_mites ? `${nMovingShown(zone)}/${zone.n_mites} moving at ${shownTime()}` : "no mites";
    text.title = `Zone ${zone.id} · ${zone.label || "unlabeled"} · ${count}`;
    text.innerHTML = `<span class="text-tag">${esc(zone.label || "unlabeled")}
      <small>${zone.n_mites ? `${nMovingShown(zone)}/${zone.n_mites}` : "–"}</small></span>`;

    linkHover([link, text]);
    plate.append(link, text);
  });

  // A dot per mite: moving or still in the recording shown.
  results.mites.forEach((mite) => {
    const dot = document.createElement("span");
    dot.className = `mite-dot ${movingShown(mite) ? "moving" : "still"}`;
    dot.style.left = percent(mite.x, results.image.width);
    dot.style.top = percent(mite.y, results.image.height);
    plate.appendChild(dot);
  });

  // The whole plate, scaled down; the zones and dots sit on it in percent.
  const img = plate.querySelector("img");
  playResultClip(`/api/session/${sessionId}/clip/${shown}`, plate, plate.nextElementSibling, () => (src) => { img.src = src; });
}

// Small multiples: one framed mini plot of the fraction moving per zone.
function drawZoneCards(groups) {
  const container = $("zone-cards");
  zonesWithMites().forEach((zone) => {
    const color = groupColor(zone.label || "unlabeled", groups);
    const card = document.createElement("a");
    card.className = "zone-card";
    card.href = `#/zone/${zone.id}`;
    card.innerHTML = `
      <div class="zone-card-head">
        <span class="zone-card-id">Zone ${zone.id}</span>
        <span class="zone-card-value" title="moving in the last recording">${zone.n_mites ? `${zone.n_moving_last}/${zone.n_mites}` : "–"}</span>
      </div>
      <div class="zone-card-group">${groupTag(zone.label || "unlabeled", color)}</div>`;
    const plot = document.createElement("div");
    plot.className = "zone-card-plot";
    Charts.spark(plot, { values: zone.moving, color, step: false });
    card.appendChild(plot);
    container.appendChild(card);
  });
}

function drawGroupTable(groups) {
  const columns = [
    ["group", "Group"], ["n_mites", "Mites"], ["fraction_moving", "Moving"],
    ["n_moving_last_recording", "Moving in last recording"],
    ["mean_score", "Mean score"], ["std_score", "SD"], ["median_score", "Median"],
  ];
  const format = (key, value) => (key === "fraction_moving" ? pct(value) : key.endsWith("score") ? score(value) : esc(value));
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

// A ring around a mite, coloured by its movement in the recording shown. The
// whole disc inside the ring is its hover and click target; the label is not.
function miteMarker(svg, mite, radius, { withLabel = true, onClick = null } = {}) {
  const ns = "http://www.w3.org/2000/svg";
  const g = document.createElementNS(ns, "g");
  g.setAttribute("class", `mite-marker ${movingShown(mite) ? "moving" : "still"}`);
  const hit = document.createElementNS(ns, "circle");
  Object.entries({ cx: mite.x, cy: mite.y, r: radius + 3, class: "hit" }).forEach(([k, v]) => hit.setAttribute(k, v));
  const circle = document.createElementNS(ns, "circle");
  Object.entries({ cx: mite.x, cy: mite.y, r: radius, class: "ring" }).forEach(([k, v]) => circle.setAttribute(k, v));
  g.append(hit, circle);
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
      `<div class="tip-title">Mite ${esc(mite.id)}</div>${movingBadge(movingShown(mite))} at ${shownTime()}
       ${movementGlyphs(mite)}<div class="tip-hint">Click to open</div>`));
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

  const movingObservations = mites.reduce((sum, mite) => sum + nMoving(mite), 0);
  const neverMoved = mites.filter((mite) => nMoving(mite) === 0).length;
  const meanScore = mites.length ? mites.flatMap((m) => m.scores).reduce((a, b) => a + b, 0) / (mites.length * times.length) : null;
  // Step through the zones with mites; an empty zone, opened from the plate map, among all.
  const siblings = zone.n_mites ? zonesWithMites() : results.zones;
  const body = $("results-body");

  body.innerHTML = `
    ${staleBanner()}
    <header class="page-head">
      <div>
        <h1>Zone ${zone.id}</h1>
        <p class="meta">${groupTag(group, color)}</p>
      </div>
      ${pager(siblings, siblings.indexOf(zone), (z) => `#/zone/${z.id}`, (z) => `Zone ${z.id}`)}
    </header>

    <div class="stats">
      ${stat("Mites", mites.length)}
      ${stat("Moving in the last recording", mites.length ? `${zone.n_moving_last} <small>(${pct(zone.n_moving_last / mites.length)})</small>` : "–")}
      ${stat("Moving mite-recordings", mites.length ? `${movingObservations} <small>of ${mites.length * times.length}</small>` : "–",
        neverMoved ? `${neverMoved} mite${neverMoved === 1 ? "" : "s"} never seen moving` : "")}
      ${stat("Mean motion score", score(meanScore), `threshold ${score(results.threshold)}`)}
    </div>

    <div class="clip-block">
      ${clipFigure("zone-crop", 1, `Zone ${zone.id} · recording at ${shownTime()}`,
        `The recording, looped, with each detected mite ${movingBadge(true)} or ${movingBadge(false)} in it. Hover a mite for every recording, select it to open it.`, "crop-wrap truth-crop")}
    </div>

    ${mites.length ? `<div class="block">${figure("chart-zone-moving", 2, "Mites moving", "Fraction of this zone's mites moving in each recording, with the whole group for comparison where the group spans several zones. Click a time to show that recording.")}</div>` : ""}

    ${mites.length ? `
    <div class="grid-2">
      ${figure("chart-zone-scores", 3, "Motion score per mite",
        "Thin lines are single mites; the black line is the mean. The dashed line is the threshold. Hover to identify a mite, select to open it; click elsewhere to show that recording.")}
      ${section("Mites", `<div class="table-wrap"><table class="clickable" id="mite-table"></table></div>`)}
    </div>` : `<p class="muted">No mites were detected in this zone.</p>`}`;
  wireRunAgain(body);
  wireRecordingBar(body);

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
  playResultClip(`/api/session/${sessionId}/clip/${shown}/${zone.id}`, $("zone-crop"), $("zone-crop").nextElementSibling,
    (clip) => clipOnSvg(crop, clip));

  if (!mites.length) return;

  const groupCurve = results.groups.find((g) => g.group === group);
  Charts.line($("chart-zone-moving"), {
    x: times,
    selected: shown,
    onXClick: showRecording,
    yLabel: "Mites moving (%)",
    yMin: 0, yMax: 100,
    yFormat: (v) => `${Math.round(v)}`,
    series: [
      { name: `Zone ${zone.id}`, values: zone.moving.map((v) => v * 100), color },
      ...(groupCurve && results.zones.filter((z) => (z.label || "unlabeled") === group && z.n_mites).length > 1
        ? [{ name: `all “${group}”`, values: groupCurve.moving.map((v) => (v == null ? null : v * 100)), color: token("--muted"), dashed: true, markers: false }]
        : []),
    ],
    tooltipExtra: (i) => {
      const moving = mites.filter((m) => m.moving[i]).length;
      return `<div class="tip-note">${moving} of ${mites.length} mites moving</div>`;
    },
  });

  Charts.line($("chart-zone-scores"), {
    x: times,
    selected: shown,
    onXClick: showRecording,
    yLabel: "Motion score",
    noDirectLabels: true,
    threshold: { value: results.threshold, label: "threshold" },
    series: [
      ...mites.map((mite) => ({
        name: `Mite ${mite.id}`,
        values: mite.scores,
        color: token("--series-1"),
        width: 1,
        faint: true,
        legend: false,
        tooltip: false,
        onClick: () => go(`#/mite/${encodeURIComponent(mite.id)}`),
      })),
      { name: "mean", values: zone.mean_score, color: token("--ink"), width: 2 },
    ],
  });

  const table = $("mite-table");
  table.innerHTML = `
    <thead><tr><th>Mite</th><th>At ${shownTime()}</th><th class="num">Last movement</th><th class="num">Moving</th><th class="num">Mean</th><th class="num">Max</th></tr></thead>
    <tbody>${mites.map((mite) => `
      <tr data-href="#/mite/${encodeURIComponent(mite.id)}" tabindex="0">
        <td><a href="#/mite/${encodeURIComponent(mite.id)}">${esc(mite.id)}</a></td>
        <td>${movingBadge(movingShown(mite))}</td>
        <td class="num">${lastMovementText(mite)}</td>
        <td class="num">${nMoving(mite)}/${times.length}</td>
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

  const body = $("results-body");
  body.innerHTML = `
    ${staleBanner()}
    <header class="page-head">
      <div>
        <h1>Mite ${esc(mite.id)}</h1>
        <p class="meta">${movingBadge(movingLast(mite))} in the last recording · <a href="#/zone/${zone.id}">Zone ${zone.id}</a> · ${groupTag(zone.label || "unlabeled", color)}</p>
      </div>
      ${pager(siblings, siblings.indexOf(mite), (m) => `#/mite/${encodeURIComponent(m.id)}`, (m) => `Mite ${m.id}`)}
    </header>

    <div class="stats">
      ${stat("Moving in", `${nMoving(mite)}/${times.length}`, "recordings above the threshold")}
      ${stat("Last movement", lastMovementText(mite), nMoving(mite) ? "last recording with movement" : "no movement in any recording")}
      ${stat("Max motion score", score(Math.max(...mite.scores)), `threshold ${score(results.threshold)}`)}
      ${stat("Mean motion score", score(mite.scores.reduce((a, b) => a + b, 0) / mite.scores.length))}
    </div>

    <div class="grid-mite">
      ${clipFigure("mite-crop", 1, "Close-up",
        `The recording at ${shownTime()}, looped, 140 × 140 px around the mite: ${movingBadge(movingShown(mite))} in it.`, "crop-wrap square")}
      ${figure("chart-mite", 2, "Motion score over time",
        `${movingBadge(true)} at or above the threshold, ${movingBadge(false)} below it. ${movingNote} Click a time to show that recording.`)}
    </div>

    ${section("Recordings", `<div class="table-wrap"><table class="clickable" id="recording-table">
        <thead><tr><th class="num">Time</th><th class="num">Motion score</th><th>Movement</th></tr></thead>
        <tbody>${times.map((t, i) => `<tr data-recording-row="${i}" tabindex="0" class="${i === shown ? "current" : ""}"
          title="Show this recording above">
          <td class="num">${minutes(t)}</td>
          <td class="num">${score(mite.scores[i])}</td>
          <td>${movingBadge(mite.moving[i])}</td></tr>`).join("")}</tbody>
      </table></div>`)}`;
  wireRunAgain(body);
  wireRecordingBar(body);
  body.querySelectorAll("[data-recording-row]").forEach((row) => {
    const index = Number(row.dataset.recordingRow);
    row.addEventListener("click", () => showRecording(index));
    row.addEventListener("keydown", (event) => { if (event.key === "Enter") showRecording(index); });
  });

  const size = 140;
  const crop = cropSvg(mite.x - size / 2, mite.y - size / 2, size, size);
  miteMarker(crop, mite, 22, { withLabel: false });
  $("mite-crop").appendChild(crop);
  // The zone's clip; the crop's view box shows only the part around the mite.
  playResultClip(`/api/session/${sessionId}/clip/${shown}/${zone.id}`, $("mite-crop"), $("mite-crop").nextElementSibling,
    (clip) => clipOnSvg(crop, clip));

  Charts.line($("chart-mite"), {
    x: times,
    selected: shown,
    onXClick: showRecording,
    yLabel: "Motion score",
    noDirectLabels: true,
    threshold: { value: results.threshold, label: "threshold" },
    series: [{
      name: `Mite ${mite.id}`,
      values: mite.scores,
      color: token("--ink"),
      width: 1.5,
      pointColors: mite.moving.map((moving) => token(moving ? "--moving" : "--still")),
    }],
    tooltipExtra: (i) => `<div class="tip-note">${mite.moving[i] ? "moving" : "still"}</div>`,
  });
}

// route() is first called from calibration.js, which loads last.
