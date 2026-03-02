const PIRSCH_API_BASE = "https://api.pirsch.io/api/v1";

function getCorsOrigin(request, env) {
  const origin = request.headers.get("Origin");
  const allowedOrigins = String(env.ALLOWED_ORIGINS || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  if (!origin || allowedOrigins.length === 0) {
    return "*";
  }

  return allowedOrigins.includes(origin) ? origin : "null";
}

function buildHeaders(request, env) {
  return {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "public, max-age=300",
    "Access-Control-Allow-Origin": getCorsOrigin(request, env),
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    Vary: "Origin",
  };
}

function jsonResponse(request, env, payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: buildHeaders(request, env),
  });
}

function parseNumber(value, defaultValue = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : defaultValue;
}

function formatDateInTimezone(date, timezone) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function subtractDays(date, days) {
  return new Date(date.getTime() - days * 24 * 60 * 60 * 1000);
}

async function getAccessToken(env) {
  const clientId = String(env.PIRSCH_CLIENT_ID || "").trim();
  const clientSecret = String(env.PIRSCH_CLIENT_SECRET || "").trim();

  if (!clientId || !clientSecret) {
    throw new Error("Missing Pirsch credentials.");
  }

  const response = await fetch(`${PIRSCH_API_BASE}/token`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      client_id: clientId,
      client_secret: clientSecret,
    }),
  });

  if (!response.ok) {
    throw new Error(`Pirsch token request failed with status ${response.status}.`);
  }

  const payload = await response.json();
  const token = String(payload.access_token || "").trim();

  if (!token) {
    throw new Error("Pirsch token response did not include access_token.");
  }

  return token;
}

async function fetchPirschJson(path, token) {
  const response = await fetch(`${PIRSCH_API_BASE}${path}`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`Pirsch request failed for ${path} with status ${response.status}.`);
  }

  return await response.json();
}

function resolveCountryName(code, explicitName) {
  if (explicitName) {
    return explicitName;
  }

  const normalizedCode = String(code || "")
    .trim()
    .toUpperCase();
  if (!normalizedCode) {
    return "Unknown";
  }

  if (typeof Intl !== "undefined" && typeof Intl.DisplayNames === "function") {
    try {
      const regionNames = new Intl.DisplayNames(["en"], { type: "region" });
      return regionNames.of(normalizedCode) || normalizedCode;
    } catch (error) {
      return normalizedCode;
    }
  }

  return normalizedCode;
}

function normalizeCountries(rawCountries) {
  if (!Array.isArray(rawCountries)) {
    return [];
  }

  return rawCountries
    .map((country) => {
      const code = String(country.country_code || country.code || "")
        .trim()
        .toUpperCase();
      const name = String(country.country || country.name || "").trim();
      const visits = parseNumber(country.visitors ?? country.visits, 0);

      if (!code || visits <= 0) {
        return null;
      }

      return {
        code,
        name: resolveCountryName(code, name),
        visits,
      };
    })
    .filter(Boolean)
    .sort((left, right) => right.visits - left.visits)
    .slice(0, 60);
}

function parseTodayVisitors(rawVisitorSeries) {
  if (Array.isArray(rawVisitorSeries) && rawVisitorSeries.length > 0) {
    const firstEntry = rawVisitorSeries[0];
    return parseNumber(firstEntry.visitors ?? firstEntry.visits, 0);
  }

  return parseNumber(rawVisitorSeries?.visitors ?? rawVisitorSeries?.visits, 0);
}

function parseTotalVisitors(rawOverview) {
  return parseNumber(rawOverview?.visitors ?? rawOverview?.visits, 0);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: buildHeaders(request, env),
      });
    }

    if (request.method !== "GET" || url.pathname !== "/stats") {
      return jsonResponse(request, env, { error: "Not found." }, 404);
    }

    try {
      const domainId = String(env.PIRSCH_DOMAIN_ID || "").trim();
      if (!domainId) {
        throw new Error("Missing PIRSCH_DOMAIN_ID.");
      }

      const timezone = String(env.TIMEZONE || "America/Detroit").trim() || "America/Detroit";
      const lookbackDays = Math.max(1, parseInt(env.COUNTRY_LOOKBACK_DAYS || "30", 10));

      const now = new Date();
      const toDate = formatDateInTimezone(now, timezone);
      const fromDate = formatDateInTimezone(subtractDays(now, lookbackDays - 1), timezone);

      const token = await getAccessToken(env);

      const [overview, visitorSeries, countrySeries] = await Promise.all([
        fetchPirschJson(`/statistics/overview?id=${encodeURIComponent(domainId)}`, token),
        fetchPirschJson(
          `/statistics/visitor?id=${encodeURIComponent(domainId)}&from=${encodeURIComponent(toDate)}&to=${encodeURIComponent(toDate)}&tz=${encodeURIComponent(timezone)}`,
          token
        ),
        fetchPirschJson(
          `/statistics/country?id=${encodeURIComponent(domainId)}&from=${encodeURIComponent(fromDate)}&to=${encodeURIComponent(toDate)}&tz=${encodeURIComponent(timezone)}`,
          token
        ),
      ]);

      const payload = {
        today_visits: parseTodayVisitors(visitorSeries),
        total_visits: parseTotalVisitors(overview),
        countries: normalizeCountries(countrySeries),
        generated_at: new Date().toISOString(),
      };

      return jsonResponse(request, env, payload, 200);
    } catch (error) {
      return jsonResponse(
        request,
        env,
        {
          error: "Unable to fetch visitor stats.",
          message: error instanceof Error ? error.message : "Unknown error.",
          generated_at: new Date().toISOString(),
        },
        502
      );
    }
  },
};
