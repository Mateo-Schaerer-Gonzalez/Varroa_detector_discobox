// Keeping the server running. When started from start.bat / start.sh the server
// stops once no page has checked in for a while, so every open tab checks in and
// says when it closes.

class ServerHeartbeat {
  static INTERVAL_MS = 15000;

  constructor() {
    this.pageId = Math.random().toString(36).slice(2);
  }

  checkIn() {
    fetch(`/api/page/${this.pageId}/alive`, { method: "POST" }).catch(() => {});
  }

  start() {
    this.checkIn();
    setInterval(() => this.checkIn(), ServerHeartbeat.INTERVAL_MS);
    window.addEventListener("pagehide", () => navigator.sendBeacon(`/api/page/${this.pageId}/closed`));
    // A page restored from the back/forward cache comes back without reloading.
    window.addEventListener("pageshow", (event) => { if (event.persisted) this.checkIn(); });
  }
}
