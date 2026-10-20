// Draws the dashboard charts from the JSON embedded in the page (no network).
(function () {
  "use strict";
  var holder = document.getElementById("chart-data");
  if (!holder || typeof Chart === "undefined") { return; }
  var data = JSON.parse(holder.textContent);
  var COLOURS = {
    fuel: "#2a6fdb", maintenance: "#e08a1e", insurance: "#2e9e5b",
    registration: "#8e5bd0", other: "#7f8c8d"
  };
  var LINE_COLOURS = ["#2a6fdb", "#e08a1e", "#2e9e5b", "#8e5bd0", "#c0392b"];

  function formatDay(ms) { return new Date(ms).toISOString().slice(0, 10); }

  function costChart(canvasId, series) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) { return; }
    new Chart(canvas, {
      type: "bar",
      data: {
        labels: series.labels,
        datasets: series.datasets.map(function (d) {
          return { label: d.key, data: d.data, backgroundColor: COLOURS[d.key], stack: "cost" };
        })
      },
      options: {
        maintainAspectRatio: false,
        scales: {
          x: { stacked: true },
          y: { stacked: true, title: { display: true, text: data.currency } }
        }
      }
    });
  }

  function consumptionChart() {
    var canvas = document.getElementById("chart-consumption");
    if (!canvas) { return; }
    var datasets = data.consumption.segments.map(function (s, i) {
      return {
        type: "scatter", label: s.label, data: s.data,
        backgroundColor: LINE_COLOURS[i % LINE_COLOURS.length]
      };
    });
    datasets.push({
      type: "line", label: "Monthly average (distance-weighted)",
      data: data.consumption.monthly, borderColor: "#c0392b",
      backgroundColor: "#c0392b", pointRadius: 3, tension: 0
    });
    new Chart(canvas, {
      type: "scatter",
      data: { datasets: datasets },
      options: {
        maintainAspectRatio: false,
        scales: {
          x: { type: "linear", ticks: { callback: formatDay, maxTicksLimit: 6 } },
          y: { title: { display: true, text: "L/100 km" } }
        },
        plugins: {
          tooltip: {
            callbacks: {
              label: function (c) { return c.dataset.label + ": " + c.parsed.y + " L/100 km (" + formatDay(c.parsed.x) + ")"; }
            }
          }
        }
      }
    });
  }

  consumptionChart();
  costChart("chart-monthly", data.monthly);
  costChart("chart-yearly", data.yearly);
})();
