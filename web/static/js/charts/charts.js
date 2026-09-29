// What the pages call to draw a chart, whichever class draws it:
// Charts.line (time series with axes, legend, hover tooltip), Charts.scatter
// (x-y points, lines and boxes), Charts.ridgeline (one smoothed distribution per
// row, overlapping) and Charts.spark (a bare mini line for the zone cards).

const Charts = {
  line: (container, options) => LineChart.show(container, options),
  scatter: (container, options) => ScatterChart.show(container, options),
  ridgeline: (container, options) => RidgelineChart.show(container, options),
  spark: (container, options) => SparkLine.draw(container, options),
  legendHtml: ChartKit.legendHtml,
  showTooltip: ChartKit.showTooltip,
  hideTooltip: ChartKit.hideTooltip,
  escape: ChartKit.escape,
  quantile: ChartKit.quantile,
  exportSvg: ChartExport.svg,
  download: ChartExport.download,
};
