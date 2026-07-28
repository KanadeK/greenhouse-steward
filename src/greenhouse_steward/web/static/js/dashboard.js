(() => {
  "use strict";

  const errorSummary = document.querySelector("#error-summary");
  if (errorSummary instanceof HTMLElement) {
    errorSummary.focus();
  }

  const loadingStatus = document.querySelector("[data-loading-status]");
  document.querySelectorAll("[data-loading-form]").forEach((form) => {
    form.addEventListener("submit", () => {
      const button = form.querySelector("button[type='submit']");
      if (!(button instanceof HTMLButtonElement)) {
        return;
      }
      button.disabled = true;
      const label = button.dataset.loadingLabel || "Working";
      button.textContent = label;
      if (loadingStatus instanceof HTMLElement) {
        loadingStatus.textContent = `${label}. Please wait.`;
      }
    });
  });

  const payloadElement = document.querySelector("#trend-plot-data");
  const chart = document.querySelector("[data-trend-chart]");
  const chartStatus = document.querySelector("[data-chart-status]");
  const buttons = Array.from(document.querySelectorAll("[data-trend-button]"));
  if (!(payloadElement instanceof HTMLScriptElement) || !(chart instanceof HTMLElement)) {
    return;
  }

  let payload;
  try {
    payload = JSON.parse(payloadElement.textContent || "{}");
  } catch {
    if (chartStatus instanceof HTMLElement) {
      chartStatus.textContent = "Trend chart data could not be parsed. Use the tables below.";
    }
    return;
  }

  const render = (period) => {
    const figure = payload[period];
    if (!figure || !window.Plotly) {
      if (chartStatus instanceof HTMLElement) {
        chartStatus.textContent = "Interactive chart unavailable. Full trend data is in the tables below.";
      }
      return;
    }
    window.Plotly.react(chart, figure.data, figure.layout, {
      responsive: true,
      displayModeBar: false,
      staticPlot: false,
    });
    chart.setAttribute(
      "aria-label",
      `${period === "daily" ? "Daily" : "Weekly"} greenhouse metric means. Full values are in the following tables.`,
    );
    if (chartStatus instanceof HTMLElement) {
      chartStatus.textContent = `${period === "daily" ? "Daily" : "Weekly"} chart rendered from local analysis data.`;
    }
  };

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const period = button.getAttribute("data-trend-button") || "daily";
      buttons.forEach((candidate) => {
        candidate.setAttribute("aria-pressed", candidate === button ? "true" : "false");
      });
      document.querySelectorAll("[data-trend-table]").forEach((details) => {
        if (details instanceof HTMLDetailsElement) {
          details.open = details.dataset.trendTable === period;
        }
      });
      render(period);
    });
  });

  render("daily");
})();
