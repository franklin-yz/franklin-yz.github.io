(() => {
  const ROOT_SELECTOR = "[data-footer-stats-endpoint]";
  const DEFAULT_PLOTLY_URL = "https://cdn.plot.ly/plotly-2.27.0.min.js";
  const REQUEST_TIMEOUT_MS = 8000;

  let plotlyLoader;

  function formatNumber(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return "--";
    }
    return new Intl.NumberFormat("en-US").format(number);
  }

  function setText(element, value) {
    if (element) {
      element.textContent = value;
    }
  }

  function setStatus(statusElement, text, isError = false) {
    if (!statusElement) {
      return;
    }
    statusElement.textContent = text;
    statusElement.classList.toggle("is-error", isError);
  }

  function getRegionName(code) {
    const normalized = String(code || "").trim().toUpperCase();
    if (!normalized) {
      return "Unknown";
    }

    if (typeof Intl !== "undefined" && typeof Intl.DisplayNames === "function") {
      const regionNames = new Intl.DisplayNames(["en"], { type: "region" });
      return regionNames.of(normalized) || normalized;
    }

    return normalized;
  }

  function normalizeCountries(countries) {
    if (!Array.isArray(countries)) {
      return [];
    }

    return countries
      .map((item) => {
        const code = String(item.code || "").trim().toUpperCase();
        const visits = Number(item.visits);
        const name = String(item.name || "").trim();

        if (!code || !Number.isFinite(visits) || visits <= 0) {
          return null;
        }

        return {
          code,
          visits,
          name: name || getRegionName(code),
        };
      })
      .filter(Boolean)
      .sort((a, b) => b.visits - a.visits);
  }

  function renderCountryList(listElement, countries) {
    if (!listElement) {
      return;
    }

    listElement.innerHTML = "";

    const topCountries = countries.slice(0, 8);
    topCountries.forEach((country) => {
      const item = document.createElement("li");
      item.className = "footer-stats-country-item";
      item.textContent = `${country.name}: ${formatNumber(country.visits)}`;
      listElement.appendChild(item);
    });
  }

  async function loadPlotly(url) {
    if (window.Plotly) {
      return window.Plotly;
    }

    if (!plotlyLoader) {
      plotlyLoader = new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = url || DEFAULT_PLOTLY_URL;
        script.async = true;
        script.onload = () => resolve(window.Plotly);
        script.onerror = () => reject(new Error("Unable to load Plotly."));
        document.head.appendChild(script);
      });
    }

    return plotlyLoader;
  }

  async function renderMap(mapElement, countries) {
    if (!mapElement || countries.length === 0) {
      return;
    }

    const plotly = await loadPlotly();

    const locations = countries.map((country) => country.name);
    const values = countries.map((country) => country.visits);

    const trace = {
      type: "choropleth",
      locationmode: "country names",
      locations,
      z: values,
      colorscale: [
        [0, "#c5d7e8"],
        [1, "#00274c"],
      ],
      showscale: false,
      marker: {
        line: {
          color: "#f2f2f2",
          width: 0.5,
        },
      },
      hovertemplate: "%{location}<br>Visits: %{z}<extra></extra>",
    };

    const layout = {
      margin: { l: 0, r: 0, t: 0, b: 0 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      geo: {
        projection: { type: "natural earth" },
        showframe: false,
        showcoastlines: false,
        bgcolor: "rgba(0,0,0,0)",
      },
    };

    const config = {
      displayModeBar: false,
      responsive: true,
      staticPlot: true,
    };

    await plotly.react(mapElement, [trace], layout, config);
  }

  function formatUpdatedTime(isoDate, timezone) {
    if (!isoDate) {
      return "";
    }

    const parsed = new Date(isoDate);
    if (Number.isNaN(parsed.valueOf())) {
      return "";
    }

    return new Intl.DateTimeFormat("en-US", {
      timeZone: timezone || "America/Detroit",
      dateStyle: "medium",
      timeStyle: "short",
    }).format(parsed);
  }

  async function fetchStats(endpoint) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
      const response = await fetch(endpoint, {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      return await response.json();
    } finally {
      clearTimeout(timeout);
    }
  }

  async function initFooterStats() {
    const root = document.querySelector(ROOT_SELECTOR);
    if (!root) {
      return;
    }

    const endpoint = root.dataset.footerStatsEndpoint;
    const timezone = root.dataset.footerStatsTimezone || "America/Detroit";

    const todayElement = root.querySelector("[data-footer-stats-today]");
    const totalElement = root.querySelector("[data-footer-stats-total]");
    const countriesElement = root.querySelector("[data-footer-stats-countries]");
    const mapElement = root.querySelector("[data-footer-stats-map]");
    const statusElement = root.querySelector("[data-footer-stats-status]");
    const updatedElement = root.querySelector("[data-footer-stats-updated]");

    if (!endpoint) {
      setStatus(statusElement, "Stats endpoint is not configured.", true);
      return;
    }

    try {
      const payload = await fetchStats(endpoint);
      const todayVisits = Number(payload.today_visits);
      const totalVisits = Number(payload.total_visits);
      const countries = normalizeCountries(payload.countries);

      setText(todayElement, formatNumber(todayVisits));
      setText(totalElement, formatNumber(totalVisits));
      setText(updatedElement, `Updated: ${formatUpdatedTime(payload.generated_at, timezone)}`);

      if (countries.length > 0) {
        renderCountryList(countriesElement, countries);
        await renderMap(mapElement, countries);
        setStatus(statusElement, "Country-level visitor data based on aggregated analytics.");
      } else {
        if (mapElement) {
          mapElement.classList.add("is-empty");
          mapElement.textContent = "No geo data yet.";
        }
        setStatus(statusElement, "No geo data yet.");
      }
    } catch (error) {
      setText(todayElement, "--");
      setText(totalElement, "--");
      setText(updatedElement, "");

      if (mapElement) {
        mapElement.classList.add("is-empty");
        mapElement.textContent = "Stats temporarily unavailable.";
      }

      if (countriesElement) {
        countriesElement.innerHTML = "";
      }

      setStatus(statusElement, "Stats temporarily unavailable.", true);
    }
  }

  document.addEventListener("DOMContentLoaded", initFooterStats);
})();
