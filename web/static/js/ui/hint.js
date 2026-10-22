// The hint line under a control: a note, work going on (a spinner before it) or
// an error. `extra`: a class the line keeps beside "hint", e.g. clip-status.

class Hint {
  static note(element, text = "", extra = "") {
    Hint.classes(element, extra, false);
    element.textContent = text;
  }

  // `html` is the page's own text, never the server's.
  static busy(element, html, extra = "") {
    Hint.classes(element, extra, false);
    element.innerHTML = `<span class="spinner"></span> ${html}`;
  }

  static error(element, text, extra = "") {
    Hint.classes(element, extra, true);
    element.textContent = text;
  }

  static classes(element, extra, error) {
    element.className = ["hint", extra, error ? "error" : ""].filter(Boolean).join(" ");
  }
}
