/* Case Lab — stage failure / terminal charts */
(function () {
  const el = document.getElementById("sim-chart-data");
  if (!el || typeof Chart === "undefined") return;
  let data;
  try {
    data = JSON.parse(el.textContent);
  } catch (_) {
    return;
  }

  const labels = data.labels || [
    "1 Ingestion",
    "2 Validation",
    "3 Approval",
    "4 Payment",
  ];
  const failMap = data.fail_by_stage || {};
  const termMap = data.terminal_by_stage || {};
  const fails = labels.map((l) => failMap[l] || 0);
  const terms = labels.map((l) => termMap[l] || 0);

  const ink = "#0b1220";
  const danger = "#b91c1c";
  const muted = "#5b6573";
  const grid = "#e8eaee";
  const stageColors = ["#0f172a", "#c2410c", "#a16207", "#15803d"];

  Chart.defaults.font.family = "'IBM Plex Sans', system-ui, sans-serif";
  Chart.defaults.color = muted;
  Chart.defaults.plugins.legend.display = false;

  const failCanvas = document.getElementById("chart-fail-stages");
  if (failCanvas) {
    new Chart(failCanvas, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            data: fails,
            backgroundColor: danger,
            borderRadius: 3,
            barPercentage: 0.65,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            beginAtZero: true,
            ticks: { precision: 0, stepSize: 1 },
            grid: { color: grid },
            border: { display: false },
          },
          y: { grid: { display: false }, border: { display: false } },
        },
        plugins: {
          tooltip: {
            callbacks: {
              label: (ctx) =>
                ctx.parsed.x === 1
                  ? "1 failure at this stage"
                  : ctx.parsed.x + " failures at this stage",
            },
          },
        },
      },
    });
  }

  const termCanvas = document.getElementById("chart-terminal-stages");
  if (termCanvas) {
    new Chart(termCanvas, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            data: terms,
            backgroundColor: stageColors,
            borderRadius: 3,
            barPercentage: 0.65,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            beginAtZero: true,
            ticks: { precision: 0, stepSize: 1 },
            grid: { color: grid },
            border: { display: false },
          },
          y: { grid: { display: false }, border: { display: false } },
        },
      },
    });
  }
})();
