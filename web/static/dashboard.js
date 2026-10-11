/* Tableau-style home charts + drill-through */
(function () {
  const el = document.getElementById("dash-data");
  if (!el || typeof Chart === "undefined") return;

  let data;
  try {
    data = JSON.parse(el.textContent);
  } catch (_) {
    return;
  }

  const ink = "#0b1220";
  const muted = "#5b6573";
  const accent = "#c2410c";
  const ok = "#15803d";
  const warn = "#a16207";
  const danger = "#b91c1c";
  const grid = "#e8eaee";

  Chart.defaults.font.family = "'IBM Plex Sans', system-ui, sans-serif";
  Chart.defaults.color = muted;
  Chart.defaults.plugins.legend.display = false;
  Chart.defaults.plugins.tooltip.backgroundColor = ink;
  Chart.defaults.plugins.tooltip.titleColor = "#fff";
  Chart.defaults.plugins.tooltip.bodyColor = "#fff";
  Chart.defaults.plugins.tooltip.cornerRadius = 4;
  Chart.defaults.plugins.tooltip.padding = 10;

  function drill(url) {
    if (url) window.location.href = url;
  }

  /* Funnel — horizontal bar */
  const funnelCanvas = document.getElementById("chart-funnel");
  if (funnelCanvas && data.funnel) {
    const labels = data.funnel.map((f) => f.label);
    const counts = data.funnel.map((f) => f.count);
    const hrefs = data.funnel.map((f) => f.href);
    new Chart(funnelCanvas, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            data: counts,
            backgroundColor: [ink, accent, warn, ok],
            borderWidth: 0,
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
            ticks: { precision: 0 },
            grid: { color: grid },
            border: { display: false },
          },
          y: { grid: { display: false }, border: { display: false } },
        },
        onClick: (_e, els) => {
          if (els[0]) {
            const href = hrefs[els[0].index];
            if (href) drill(href);
          }
        },
        onHover: (e, els) => {
          const href = els[0] ? hrefs[els[0].index] : null;
          e.native.target.style.cursor = href ? "pointer" : "default";
        },
      },
    });
  }

  /* Vendor exposure */
  const vendorCanvas = document.getElementById("chart-vendors");
  if (vendorCanvas && data.vendors) {
    const labels = data.vendors.map((v) => v.vendor);
    const amounts = data.vendors.map((v) => v.amount);
    new Chart(vendorCanvas, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            data: amounts,
            backgroundColor: ink,
            borderWidth: 0,
            borderRadius: 3,
            barPercentage: 0.7,
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
            ticks: {
              callback: (v) => "$" + Number(v).toLocaleString(),
            },
            grid: { color: grid },
            border: { display: false },
          },
          y: { grid: { display: false }, border: { display: false } },
        },
        onClick: () => drill("/exceptions"),
        onHover: (e, els) => {
          e.native.target.style.cursor = els.length ? "pointer" : "default";
        },
      },
    });
  }

  /* Issue mix doughnut */
  const issueCanvas = document.getElementById("chart-issues");
  if (issueCanvas && data.issues) {
    const labels = data.issues.map((i) => i.label);
    const counts = data.issues.map((i) => i.count);
    const colors = {
      "unknown SKU": danger,
      stock: warn,
      "amount/qty": accent,
      other: muted,
      clean: ok,
    };
    new Chart(issueCanvas, {
      type: "doughnut",
      data: {
        labels,
        datasets: [
          {
            data: counts,
            backgroundColor: labels.map((l) => colors[l] || muted),
            borderWidth: 2,
            borderColor: "#fff",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "62%",
        plugins: {
          legend: {
            display: true,
            position: "right",
            labels: { boxWidth: 10, padding: 10, font: { size: 11 } },
          },
        },
        onClick: (_e, els) => {
          if (!els[0]) return;
          const label = labels[els[0].index];
          if (label === "clean") drill("/exceptions?findings=0");
          else drill("/exceptions?findings=1");
        },
        onHover: (e, els) => {
          e.native.target.style.cursor = els.length ? "pointer" : "default";
        },
      },
    });
  }

  /* Confidence × amount scatter */
  const scatterCanvas = document.getElementById("chart-scatter");
  if (scatterCanvas && data.scatter) {
    const riskColor = { high: danger, medium: warn, low: ok };
    const points = data.scatter.map((p) => ({
      x: p.x,
      y: p.y,
      href: p.href,
      risk: p.risk,
    }));
    new Chart(scatterCanvas, {
      type: "scatter",
      data: {
        datasets: [
          {
            data: points,
            pointRadius: 5,
            pointHoverRadius: 7,
            backgroundColor: points.map((p) => riskColor[p.risk] || ink),
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            title: { display: true, text: "Amount ($)", color: muted },
            ticks: {
              callback: (v) => "$" + Number(v).toLocaleString(),
            },
            grid: { color: grid },
            border: { display: false },
          },
          y: {
            min: 0,
            max: 100,
            title: { display: true, text: "Confidence %", color: muted },
            grid: { color: grid },
            border: { display: false },
          },
        },
        onClick: (_e, els) => {
          if (els[0]) {
            const pt = points[els[0].index];
            if (pt) drill(pt.href);
          }
        },
        onHover: (e, els) => {
          e.native.target.style.cursor = els.length ? "pointer" : "default";
        },
      },
    });
  }
})();
