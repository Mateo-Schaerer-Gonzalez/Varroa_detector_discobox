// The app's screenshots in README.md and report/1_user_manual.md, taken from a
// running app with headless Chrome (Node 22: global fetch and WebSocket).
//
// They show only the 2025 test sessions: the other recordings are real experiments,
// and the page would show what they test. So run the app from a copy that holds only
// those sessions, e.g. a worktree in a short path:
//
//   git worktree add --detach %TEMP%\zzrc\showcase HEAD
//   (hard-link recordings/sample_data, ground_truth_60min and ground_truth_90min into
//    its recordings/, copy config.default.yaml to its config.yaml, and set
//    death_minutes=10 in recordings/sample_data/.settings.txt)
//   cd %TEMP%\zzrc\showcase && set DISCOBOX_CONFIG=%CD%\config.yaml
//   python -m uvicorn web.server:app --port 8765
//
//   node scripts/readme_screenshots.mjs <out dir> <the copy's recordings\sample_data>
//
// Writes <out dir>/<page>.png, whole pages 1440 px wide (cal_* the calibration pages,
// which need ground_truth_60min and ground_truth_90min); scripts/readme_images.py
// cuts them into docs/images/ and report/images/. Analysing the folder writes
// results/sample_data/ in the copy, never in this app.
import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";

const [, , out, dataDir, base = "http://127.0.0.1:8765/"] = process.argv;
const CHROME = process.env.CHROME || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=9333", `--user-data-dir=${out}/profile`,
  "--window-size=1440,1100", "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let ws;
for (let i = 0; i < 30 && !ws; i++) {
  await sleep(500);
  try {
    const page = (await (await fetch("http://127.0.0.1:9333/json")).json()).find((t) => t.type === "page");
    ws = new WebSocket(page.webSocketDebuggerUrl);
  } catch { /* Chrome not up yet */ }
}
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
  const reply = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (reply.result?.exceptionDetails) console.log("error in", expression, JSON.stringify(reply.result.exceptionDetails).slice(0, 400));
  return reply.result?.result?.value;
};
const shot = async (name, whole = true) => {
  await sleep(2500);  // charts and the looping clips settle
  const height = whole ? await run("document.documentElement.scrollHeight") : 1100;
  const reply = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: whole,
    clip: { x: 0, y: 0, width: 1440, height, scale: 1 } });
  writeFileSync(`${out}/${name}.png`, Buffer.from(reply.result.data, "base64"));
  console.log("shot", name, height);
};
const go = async (hash) => { await run(`location.hash = ${JSON.stringify(hash)}`); await sleep(1500); };

await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: base });
await sleep(4000);
await go("#/live"); await shot("live", false);
await go("#/cal"); await shot("cal_open");
await go("#/open");
await run(`analysis.openFolder(${JSON.stringify(dataDir)})`); await sleep(3000); await shot("labels", false);
await run("analysis.run()"); await sleep(3000); await shot("results");
await go("#/zone/7"); await shot("zone");
await go("#/mite/7.1"); await shot("mite");            // moving in the last recording
await go("#/mite/4.1"); await shot("mite_still");      // a negative control, still
await go("#/playback"); await sleep(4000); await shot("playback");
// Calibration as the manual walks through it: calibrate on ground_truth_60min, then
// test the threshold on another recording, ground_truth_90min. Nothing is saved.
await go("#/cal/open");
await run(`cal.setMode("calibrate")`);
await run(`datasetLibrary.open("ground_truth_60min")`); await sleep(3000); await shot("cal_truth", false);
await run("cal.evaluate()"); await sleep(3000); await shot("cal_report");
await run("cal.quit()"); await sleep(1500);
await run(`cal.setMode("test")`);
await run(`datasetLibrary.open("ground_truth_90min")`); await sleep(3000);
await run("cal.evaluate()"); await sleep(5000); await shot("cal_test");
ws.close();
chrome.kill();
