// Page building blocks as HTML: stat tiles, numbered figures, sections, group
// tags, the moving/still badge and the previous/next pager. Used by the result
// pages and the calibration report.

class Markup {
  static stat(label, value, note = "") {
    return `<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${value}</div>${note ? `<div class="stat-note">${note}</div>` : ""}</div>`;
  }

  static groupTag(group, color) {
    return `<span class="grp"><i style="background:${color}"></i>${esc(group)}</span>`;
  }

  static section(title, inner) {
    return `<section class="block"><h2>${title}</h2>${inner}</section>`;
  }

  // Moving or still in one recording: always a glyph and a word, never colour alone.
  static movingBadge(moving) {
    return moving
      ? `<span class="status moving"><span aria-hidden="true">●</span> moving</span>`
      : `<span class="status still"><span aria-hidden="true">○</span> still</span>`;
  }

  // A numbered figure: the content goes in the element with `id`, the caption below;
  // `controls`, if any, between the title and the content.
  static figure(id, number, title, caption, extraClass = "", controls = "") {
    return `<figure class="fig">
      <div class="fig-title fig-title-row">${title}${ChartDownloads.buttons(id, title)}</div>
      ${controls ? `<div class="fig-controls">${controls}</div>` : ""}
      <div id="${id}" class="${extraClass}"></div>
      <figcaption><b>Fig. ${number}.</b> ${caption}</figcaption>
    </figure>`;
  }

  // Links to the items before and after `items[index]`.
  static pager(items, index, hrefOf, labelOf) {
    const prev = items[index - 1];
    const next = items[index + 1];
    return `<nav class="pager" aria-label="Previous and next">
    ${prev ? `<a class="button secondary small" href="${hrefOf(prev)}">← ${esc(labelOf(prev))}</a>` : ""}
    ${next ? `<a class="button secondary small" href="${hrefOf(next)}">${esc(labelOf(next))} →</a>` : ""}
  </nav>`;
  }

  // Rows of a table that open `data-href` on click or Enter.
  static wireRowLinks(table, open = (href) => router.go(href)) {
    table.querySelectorAll("tr[data-href]").forEach((row) => {
      row.addEventListener("click", () => open(row.dataset.href));
      row.addEventListener("keydown", (event) => { if (event.key === "Enter") open(row.dataset.href); });
    });
  }
}

// SVG and PNG buttons beside a chart's title, and saving the chart from them.
class ChartDownloads {
  // Buttons for the chart in the element `id`; hidden by the stylesheet when that
  // element holds no chart (a table, a map). `legendId`: the element holding the
  // legend, when it is shared and not in the chart.
  static buttons(id, title, legendId = "") {
    const data = `data-download="${id}" data-title="${esc(title)}"${legendId ? ` data-legend="${legendId}"` : ""}`;
    return `<span class="fig-download" role="group" aria-label="Download ${esc(title)}">
      <button type="button" class="secondary small" ${data} data-format="svg" title="Download as SVG, for editing or print">SVG</button>
      <button type="button" class="secondary small" ${data} data-format="png" title="Download as PNG">PNG</button>
    </span>`;
  }

  // Files are named after the recording folder, the page and the chart,
  // e.g. sample_data_zone-4_mites-moving.png.
  static wire() {
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
  }
}
