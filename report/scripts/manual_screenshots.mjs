// The user manual's screenshots (report/1_user_manual.md), taken from a running
// copy of the app with headless Chrome (Node 22: global fetch and WebSocket). Each
// is cut round the part of the page the manual's text is about, found by its title
// on screen, so the pictures follow the pages when they change.
//
// Like scripts/readme_screenshots.mjs, the copy holds only the 2025 test sessions
// (sample_data, ground_truth_60min, ground_truth_90min) and the demos made from them
// (demo_late_mites, demo_poke_test_added, and demo_faint_mites, which
// report/scripts/faint_mites_demo.py makes in the copy from demo_hand_mites): the other
// recordings are real experiments. Start the copy with the simulated Discobox, playing
// demo_late_mites:
//
//   set DISCOBOX_CONFIG=<copy>\config.yaml
//   python report/scripts/live_demo.py <copy>\recordings\demo_late_mites --port 8765 --gap 75
//   "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --remote-debugging-port=9333
//      --user-data-dir=<scratch>\chrome --window-size=1440,1100 --hide-scrollbars about:blank
//   node report/scripts/manual_screenshots.mjs <out dir> <copy> [stage ...]
//
// The stages, in the order they must first run (the live run makes recordings the
// later ones show): live, list, hand, late, results, mite, playback, zones,
// calibrate, test, poke. "real" comes last, once the long run
// (test_run_2026-09-08_Mathis_last_dsRNA) is linked into the copy without its labels and
// controls: its high plate shake and its fly-offs, in parts that show no group, label or
// recording list (the fly-off figure cut round the track, clear of the slides' handwriting).
//
// Then python report/scripts/manual_images.py <out dir> writes report/images/man_*.png.
import { writeFileSync, mkdirSync } from "node:fs";

const [, , out, copy, ...asked] = process.argv;
const BASE = process.env.BASE || "http://127.0.0.1:8765/";
const REC = (name) => `${copy.replace(/\\/g, "/")}/recordings/${name}`;
mkdirSync(out, { recursive: true });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const page = (await (await fetch("http://127.0.0.1:9333/json")).json()).find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve) => ws.addEventListener("open", resolve));
let id = 0;
const waiting = new Map();
ws.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (waiting.has(message.id)) { waiting.get(message.id)(message); waiting.delete(message.id); }
});
const send = (method, params = {}) => new Promise((resolve) => {
  waiting.set(++id, resolve);
  ws.send(JSON.stringify({ id, method, params }));
});
const run = async (expression) => {
  const reply = await send("Runtime.evaluate", { expression: `(async () => { ${expression} })()`, awaitPromise: true, returnByValue: true });
  if (reply.result?.exceptionDetails) {
    throw new Error(`in ${expression.slice(0, 200)}: ${JSON.stringify(reply.result.exceptionDetails).slice(0, 500)}`);
  }
  return reply.result?.result?.value;
};
const go = async (hash, wait = 2000) => { await run(`location.hash = ${JSON.stringify(hash)};`); await sleep(wait); };
const until = async (condition, timeout = 600000, every = 1000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await run(`return Boolean(${condition});`)) return;
    await sleep(every);
  }
  throw new Error(`waited in vain for ${condition}`);
};

// In the page: the figure or section whose title on screen starts with `title`.
const PART = `const part = (title, root = document) => [...root.querySelectorAll(".fig, section.block, figure")]
  .filter((e) => e.offsetParent)
  .find((e) => ((e.querySelector(".fig-title, h2, figcaption b")?.textContent || "").replace(/\\s+/g, " ").trim()).startsWith(title));`;

// A picture of the elements `find` (page JS returning an element or a list) covers,
// with `pad` px round them; `extra` grows the cut {top, bottom, left, right}.
const shot = async (name, find, { pad = 12, extra = {}, wait = 1200 } = {}) => {
  await run(`${PART} const found = [].concat(${find}).filter(Boolean);
    if (!found.length) throw new Error("nothing for ${name}"); found[0].scrollIntoView({ block: "start" });`);
  await sleep(wait);
  await run("window.scrollTo(0, 0);");
  await sleep(300);
  const box = await run(`${PART} const found = [].concat(${find}).filter(Boolean);
    const boxes = found.map((e) => e.getBoundingClientRect());
    const x1 = Math.min(...boxes.map((b) => b.left)), y1 = Math.min(...boxes.map((b) => b.top));
    const x2 = Math.max(...boxes.map((b) => b.right)), y2 = Math.max(...boxes.map((b) => b.bottom));
    return { x: x1 + scrollX, y: y1 + scrollY, x2: x2 + scrollX, y2: y2 + scrollY };`);
  const x = Math.max(0, box.x - pad - (extra.left || 0));
  const y = Math.max(0, box.y - pad - (extra.top || 0));
  const clip = { x, y, width: Math.min(1440, box.x2 + pad + (extra.right || 0)) - x, height: box.y2 + pad + (extra.bottom || 0) - y, scale: 1 };
  const reply = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip });
  writeFileSync(`${out}/${name}.png`, Buffer.from(reply.result.data, "base64"));
  console.log("shot", name, Math.round(clip.width), "x", Math.round(clip.height));
};
// The page as on screen, from its top.
const screen = async (name) => {
  await run("window.scrollTo(0, 0);");
  await sleep(800);
  const reply = await send("Page.captureScreenshot", { format: "png", clip: { x: 0, y: 0, width: 1440, height: 1100, scale: 1 } });
  writeFileSync(`${out}/${name}.png`, Buffer.from(reply.result.data, "base64"));
  console.log("shot", name);
};
// A real click at the middle of an element, as the mouse makes it.
const click = async (find) => {
  await run(`${PART} [].concat(${find})[0].scrollIntoView({ block: "center" });`);
  await sleep(400);
  const at = await run(`${PART} const b = [].concat(${find})[0].getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 };`);
  for (const type of ["mousePressed", "mouseReleased"]) {
    await send("Input.dispatchMouseEvent", { type, x: at.x, y: at.y, button: "left", clickCount: 1 });
  }
  await sleep(800);
};
const setInput = (elementId, value) => run(`const e = document.getElementById(${JSON.stringify(elementId)});
  e.value = ${JSON.stringify(String(value))}; e.dispatchEvent(new Event("input", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 1300));`);
const byId = (elementId) => `document.getElementById(${JSON.stringify(elementId)})`;
const aside = (elementId) => `${byId(elementId)}.closest("aside")`;

await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: BASE });
await sleep(4000);

const stages = {
  // --- section 2: a live run on the simulated Discobox --------------------------------
  async live() {
    await go("#/live/open", 3000);
    await shot("live_settings", byId("live-settings-block"));
    await run(`${byId("live-run-name")}.value = "demo_live_run";`);
    for (const [name, value] of [["death_minutes", 10], ["run_minutes", 25], ["recording_timeout", 5],
      ["vent_time", 20], ["led1_time", 20], ["led2_time", 20]]) await setInput(`live-set-${name}`, value);
    await run("await live.connect();");
    await go("#/live/open", 5000);
    await screen("live_connected");

    // The slides: one zone per slide, as the demo's late mites are on a slide the automatic mask leaves out.
    await run("await live.labelPlates();");
    await sleep(3000);
    await run(`await live.setZoneMask("1");`);
    await sleep(4000);
    const labels = { 4: ["dead", false], 7: ["control", true], 10: ["alive", false], 13: ["alive", false] };
    for (const [zone, [label, control]] of Object.entries(labels)) {
      // one at a time, as typed: each save rewrites the run's labels file
      await run(`const z = workspaces.get("live").session.zones.find((z) => z.id === ${zone});
        sessionLabels.setLabel(z, ${JSON.stringify(label)}); ${control ? "sessionLabels.setControl(z, true);" : ""}
        await new Promise((r) => setTimeout(r, 1500)); labelPage.draw();`);
    }
    // A detection on the support plate beside a slide, not a mite: crossed out.
    const debris = await run(`const m = workspaces.get("live").session.mites.find((m) => Math.abs(m.x - 1300) < 15 && Math.abs(m.y - 454) < 15);
      if (m) { labelPage.toggleMite(m); await new Promise((r) => setTimeout(r, 1500)); labelPage.draw(); } return m ? m.id : null;`);
    console.log("crossed out", debris);
    await run("labelPage.editor.start(7);");
    await sleep(800);
    await shot("live_labels", [byId("label-plate"), aside("run-btn")]);
    await run("labelPage.editor.close();");
    await sleep(1000);

    await run("await live.startRun();");
    await until("live.status && live.status.analysed >= 1", 120000);
    await sleep(4000);
    await shot("live_panel_first", byId("live-panel"));
    // Add mites, between recordings 2 and 3: the demo's late mites are on the slides by then.
    await until("live.status && live.status.analysed >= 2 && !live.status.recording_name && live.status.progress.next_seconds > 55", 400000);
    await run("await livePanel.adding.find();");
    await until(`location.hash.includes("label") && workspaces.get("live").session.adding`, 60000);
    await sleep(2500);
    await shot("live_add_mites", [byId("label-plate"), aside("run-btn")]);
    await run("await livePanel.adding.add();");
    await sleep(3000);
    await shot("live_panel_adding", byId("live-panel"));
    // The poke test and the ground truth, opened from the panel, on the recordings so far.
    await run("await livePanel.calibrate('poke');");
    await sleep(4000);
    await run(`${byId("poke-after")}.value = String(cal.data.times.length - 1); pokePage.addRound();`);
    await sleep(2000);
    // Mites poked between recordings 2 and 3: those of slide 4 did not move, those of 10 did, 13.1 too.
    await run(`pokePage.brush = "unmoved"; pokePage.drawBrush(); pokePage.fillZone(4);`);
    await sleep(1500);
    await run(`pokePage.brush = "moved"; pokePage.drawBrush(); pokePage.fillZone(10);`);
    await sleep(1500);
    await run(`pokePage.poke("13.1");`);
    await sleep(2500);
    await shot("live_poke", byId("view-cal-poke"), { pad: 0 });
    // The ground truth so far: a few labels, so the bar shows how far it is.
    await run("await livePanel.calibrate('truth');");
    await sleep(4000);
    for (const state of ["moving", "moving", "still"]) { await run(`await truthPage.label(${JSON.stringify(state)});`); await sleep(1500); }
    await screen("live_truth");
    await go("#/live/results", 3000);
    // The panel later on: some zones' circles part filled.
    await until("live.status && live.status.analysed >= 4", 600000);
    await sleep(5000);
    await shot("live_panel", byId("live-panel"));
    await until("live.status && live.status.state === 'finished'", 900000);
    await sleep(6000);
    await shot("live_panel_finished", byId("live-panel"));
    // Its comparison of every group with the negative control (slide 7, whose mites move).
    await shot("results_control", `part("Survival against the negative control")`);
  },

  // --- section 3.1: the recordings kept, with Analyse first and settings in red ------
  async list() {
    await go("#/open", 3000);
    await shot("recordings_list", `document.querySelector("#view-open [data-recordings]")`);
  },

  // --- section 3.3: mites placed by hand, on demo_faint_mites (report/scripts/faint_mites_demo.py,
  // made in the copy first: three faint mites the detector misses) --------------------------------
  async hand() {
    await go("#/open", 1500);
    await run(`await analysis.openFolder(${JSON.stringify(REC("demo_faint_mites"))});`);
    await sleep(4000);
    await shot("hand_before", [byId("label-plate"), aside("place-mite-btn")]);
    await run("handMites.setPlacing(true);");
    // a click a few pixels off each mite, as on the screen: the ring goes on the mite
    for (const [x, y] of [[1044, 327], [1013, 793], [1057, 1153]]) {
      await run(`handMites.send({ x: ${x}, y: ${y} }); await handMites.queue;`);
      await sleep(1500);
    }
    await shot("hand_placed", [byId("label-plate"), aside("place-mite-btn")]);
    await run("handMites.setPlacing(false);");
  },

  // --- section 3.4: mites put on later, on demo_late_mites ------------------------------
  async late() {
    await go("#/open", 1500);
    await run(`await analysis.openFolder(${JSON.stringify(REC("demo_late_mites"))});`);
    await sleep(4000);
    await run("await analysis.run();");
    await until(`location.hash.startsWith("#/results") && document.querySelector("#view-results h1")`, 600000);
    await sleep(4000);
    await shot("late_results", `part("Mites put on later")`);
    await go("#/label", 3000);
    await run(`const last = labelPage.steps().length - 1; document.querySelector('#label-steps [data-step="' + last + '"]').click();`);
    await sleep(2500);
    await shot("late_labels", [byId("label-steps"), byId("label-plate"), aside("place-mite-btn")]);
  },

  // --- section 3.5: the results of sample_data ------------------------------------------
  async results() {
    await go("#/open", 1500);
    await run(`await analysis.openFolder(${JSON.stringify(REC("sample_data"))});`);
    await sleep(4000);
    await run("await analysis.run();");
    await until(`location.hash.startsWith("#/results") && document.querySelector("#view-results h1")`, 600000);
    await sleep(5000);
    // A close call of mite 7.3, a mite seen moving, as the page asks it.
    await go("#/mite/7.3", 3000);
    await run(`const m = ctx.results.mites.find((m) => m.id === "7.3"); resultsView.openMite(m, m.to_check[0], true);`);
    await sleep(3500);
    await shot("mite_close_call", [`document.querySelector("#view-results .review-note")`, `part("Close-up")`, `part("Motion score over time")`]);
    // Three mites with one close call each answered, so the bar under "To check by eye" is part full.
    const single = await run(`return ctx.results.mites.filter((m) => m.to_check.length === 1).slice(0, 3).map((m) => m.id);`);
    for (const miteId of single) {
      await run(`const m = ctx.results.mites.find((m) => m.id === ${JSON.stringify(miteId)}); resultsView.openMite(m, m.to_check[0], true);`);
      await sleep(3000);
      await click(`document.querySelector('[data-answer="still"]')`);
      await sleep(3000);
    }
    console.log("answered", single);
    await go("#/results", 3000);
    await shot("results_top", [`document.querySelector("#view-results h1")`, `document.querySelector("#view-results .stats")`]);
    await shot("results_check", `part("To check by eye")`);
    for (const [name, title] of [["results_platemap", "Glass slide map"], ["results_survival", "Survival rate by group"],
      ["results_zones", "Movement per zone"], ["results_summary", "Group summary"], ["results_scores", "Motion scores by group"],
      ["results_moving_scores", "Motion scores of moving mites by group"], ["results_rest", "Rest between movements"],
      ["results_shake", "Plate shake per recording"], ["results_drift", "The 10 mites that drifted furthest"],
      ["results_activity", "Unusual activity"], ["results_files", "Files"]]) {
      await shot(name, `part(${JSON.stringify(title)})`);
    }
    // A zone, and a mite of it.
    await go("#/zone/7", 3500);
    await shot("zone_top", [`document.querySelector("#view-results h1")`, `part("Zone 7")`]);
    for (const [name, title] of [["zone_moving", "Mites moving"], ["zone_survival", "Survival rate"], ["zone_lifelines", "Lifelines"],
      ["zone_scores", "Motion score per mite"], ["zone_mites", "Mites"]]) await shot(name, `part(${JSON.stringify(title)})`);
    await go("#/mite/7.1", 3500);
    await shot("mite_top", [`document.querySelector("#view-results h1")`, `part("Close-up")`, `part("Motion score over time")`]);
    await shot("mite_recordings", `part("Recordings")`);
  },

  // --- section 3.6: a call corrected by hand, then put back ------------------------------
  async mite() {
    await go("#/mite/7.3", 3500);
    const last = await run("return ctx.lastIndex();");
    const correct = (state) => run(`const s = document.querySelector('[data-correct="${last}"]'); s.value = "${state}";
      s.dispatchEvent(new Event("change", { bubbles: true })); await new Promise((r) => setTimeout(r, 4000));`);
    await correct("moving");
    await run(`resultsView.setShown(${last}); resultsView.draw(); await new Promise((r) => setTimeout(r, 3000));`);
    await shot("mite_corrected", [`document.querySelector("#view-results h1")`, `part("Close-up")`, `part("Recordings")`]);
    await correct("still");
  },

  // --- sections 3.7 and 3.9 ----------------------------------------------------------------
  async playback() {
    await go("#/playback", 6000);
    await screen("playback");
  },
  async zones() {
    await go("#/zones", 2000);
    await run(`zoneMaker.usePicture("sample_data"); zoneMaker.open("1"); zoneMaker.selected = 0; zoneMaker.draw();`);
    await sleep(2500);
    await shot("zones", byId("view-zones"), { pad: 0 });
  },

  // --- section 4: calibrate on ground_truth_60min, test on ground_truth_90min -------------
  async calibrate() {
    await go("#/cal/open", 2500);
    await run(`cal.setMode("calibrate");`);
    await screen("cal_open");
    await run(`await datasetLibrary.open("ground_truth_60min");`);
    await sleep(4000);
    await run("await cal.evaluate();");
    await until(`location.hash.startsWith("#/cal/report") && document.querySelector("#view-cal-report h1")`, 900000);
    await sleep(5000);
    await screen("cal_report");
    for (const [name, title] of [["cal_confusion", "Confusion matrix"], ["cal_survival", "Survival rate"], ["cal_strip", "Motion score distribution"],
      ["cal_pr", "Precision-recall curve"]]) await shot(name, `part(${JSON.stringify(title)})`);
    // The wrong calls: the first checked (its label kept), the second shown, then the list.
    await click(`[...document.querySelectorAll("#view-cal-report button")].find((b) => /wrong calls/i.test(b.textContent))`);
    await sleep(2500);
    await click(`[...document.querySelectorAll("#view-cal-report button, #view-cal-report a")].find((b) => /one by one/i.test(b.textContent))`);
    await sleep(4000);
    await click(`[...document.querySelectorAll("#view-cal-truth button")].find((b) => /^\\s*Moving/.test(b.textContent))`);
    await sleep(4000);
    await shot("cal_check", `document.querySelector("#view-cal-truth .split-main")`);
    await click(`[...document.querySelectorAll("#view-cal-truth button, #view-cal-truth a")].find((b) => /back to the report/i.test(b.textContent))`);
    await sleep(4000);
    await run(`const shown = [...document.querySelectorAll("#view-cal-report button")].find((b) => /^\\s*Show the .*wrong calls/i.test(b.textContent));
      if (shown) { shown.click(); await new Promise((r) => setTimeout(r, 2500)); }`);
    await shot("cal_wrong", `[...document.querySelectorAll("#view-cal-report section.block")].find((e) => /wrong call/i.test(e.textContent) && e.querySelector("table"))`);
    await run("cal.quit();");
    await sleep(2000);
  },

  async test() {
    await go("#/cal/open", 2500);
    await run(`cal.setMode("test");`);
    await run(`await datasetLibrary.open("ground_truth_90min");`);
    await sleep(4000);
    await run("await cal.evaluate();");
    await until(`location.hash.startsWith("#/cal/report") && document.querySelector("#view-cal-report h1")`, 900000);
    await sleep(6000);
    await screen("test_top");
    for (const [name, title] of [["test_confusion", "Confusion matrix"], ["test_survival", "Survival rate: ground truth"],
      ["test_benchmark", "Against the benchmark"], ["test_errors", "Where the errors are"], ["test_pr", "Precision-recall curve"],
      ["test_strip", "Motion score distribution"], ["test_last", "The last recording"], ["test_zones", "Per zone"],
      ["test_between", "Outline change between recordings"], ["test_groups", "Survival rate per group"]]) await shot(name, `part(${JSON.stringify(title)})`);
    await run("cal.quit();");
    await sleep(2000);
  },

  // The poke test of a saved run, entered from its ground-truth page, and its test report.
  async poke() {
    await go("#/cal/open", 2500);
    await run(`cal.setMode("test");`);
    await run(`await datasetLibrary.open("demo_poke_test_added");`);
    await sleep(5000);
    await click(`[...document.querySelectorAll("#view-cal-truth a, #view-cal-truth button")].find((b) => /poke test/i.test(b.textContent))`);
    await sleep(4000);
    await shot("poke_page", byId("view-cal-poke"), { pad: 0 });
    await run("await pokePage.showReport();");
    await until(`location.hash.startsWith("#/cal/report") && document.querySelector("#view-cal-report h1")`, 1800000);
    await sleep(6000);
    await shot("test_poke", `part("Survival rate of the poked mites")`);
    await run("cal.quit();");
  },

  // --- the long run (49 h): its plate shook more, and mites flew off. Only parts with no
  // group, label or recording list: the fly-off figure is cut round the track, clear of
  // the handwriting on the slides ------------------------------------------------------------
  async real() {
    await go("#/open", 1500);
    await run(`await analysis.openFolder(${JSON.stringify(REC("test_run_2026-09-08_Mathis_last_dsRNA"))});`);
    await sleep(5000);
    await run("await analysis.run();");
    await until(`location.hash.startsWith("#/results") && document.querySelector("#view-results h1")`, 3600000, 5000);
    await sleep(8000);
    await shot("real_shake_high", `part("Plate shake per recording")`);
    await shot("real_activity_counts", `part("Unusual activity").querySelector(".stats")`);
    // a box over the track alone, its marks and ids, 20 px round them
    await run(`${PART} const fig = part("Fly-off tracks"); const svg = fig.querySelector("svg"); const sb = svg.getBoundingClientRect();
      const bs = [...svg.querySelectorAll("path, polyline, circle, text, line")].map((e) => e.getBoundingClientRect())
        .filter((b) => b.width < sb.width * 0.6 && b.height < sb.height * 0.6 && b.width + b.height > 0);
      const x1 = Math.min(...bs.map((b) => b.left)) - 20, y1 = Math.min(...bs.map((b) => b.top)) - 20;
      const x2 = Math.max(...bs.map((b) => b.right)) + 20, y2 = Math.max(...bs.map((b) => b.bottom)) + 20;
      const box = document.createElement("div"); box.id = "manual-track";
      Object.assign(box.style, { position: "absolute", left: (x1 + scrollX) + "px", top: (y1 + scrollY) + "px",
        width: (x2 - x1) + "px", height: (y2 - y1) + "px", pointerEvents: "none" });
      document.body.appendChild(box);`);
    await shot("real_flyoff", byId("manual-track"), { pad: 0 });
    await run(`${byId("manual-track")}.remove();`);
    await shot("real_rotators", `part("Rotators")`);
    await shot("real_setaside", `part("Recordings set aside")`);
  },
};

for (const stage of asked) {
  if (!stages[stage]) { console.log("no stage", stage); continue; }
  console.log("--", stage);
  await stages[stage]();
}
ws.close();
process.exit(0);
