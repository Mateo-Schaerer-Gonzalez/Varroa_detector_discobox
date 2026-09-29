// Small helpers every page uses: finding elements, talking to the server,
// formatting numbers and colours. The browser side talks to the server over the
// /api endpoints and knows nothing about how the analysis works.

const $ = (id) => document.getElementById(id);
const esc = (text) => Charts.escape(text ?? "");

// A reply's JSON, or an error with the server's reason; `fallback` when it gives
// none, e.g. a reply that is not JSON at all, such as a crashed server's error page.
async function readJson(response, fallback = "Request failed") {
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    // A request the server could not read has its reasons as a list.
    const detail = data && (Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("; ") : data.detail);
    throw new Error(detail || `${fallback} (${response.status} ${response.statusText})`);
  }
  if (data === null) throw new Error(`${fallback}: the server's reply could not be read`);
  return data;
}

// POST `body` as JSON; the reply's JSON, or an error with the server's reason.
async function post(path, body = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readJson(response);
}

// GET JSON, never from the browser's cache.
async function getJson(path, fallback = "Request failed") {
  return readJson(await fetch(path, { cache: "no-store" }), fallback);
}

// --- formatting ----------------------------------------------------------------

const percent = (value, total) => `${(value / total) * 100}%`;
const pct = (fraction) => (fraction == null ? "–" : `${Math.round(fraction * 100)}%`);
const minutes = (value) => `${+Number(value).toFixed(1)} min`;
const score = (value) => (value == null ? "–" : Number(value).toFixed(1));
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const shorten = (text, length) => (text.length > length ? `${text.slice(0, length - 1)}…` : text);
const slug = (text) => String(text).toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const folderOf = (path) => String(path || "").split(/[\\/]/).filter(Boolean).pop() || "";

// "12 min", "1 h 5 min", "40 s".
function duration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}`;
}

// --- colours -------------------------------------------------------------------

// Read colour tokens from the stylesheet so charts follow light/dark mode.
const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// Groups get categorical colours in alphabetical order; "unlabeled" and any
// ninth group onwards are grey rather than an invented hue.
function groupColor(group, groups) {
  const named = groups.filter((g) => g !== "unlabeled");
  const index = named.indexOf(group);
  return index >= 0 && index < 8 ? token(`--series-${index + 1}`) : token("--series-other");
}
