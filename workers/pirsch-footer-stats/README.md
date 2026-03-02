# Pirsch Footer Stats Worker

This Cloudflare Worker exposes a public read-only `/stats` endpoint for your Jekyll footer widget.

## What it returns

`GET /stats`

```json
{
  "today_visits": 0,
  "total_visits": 0,
  "countries": [
    { "code": "US", "name": "United States", "visits": 0 }
  ],
  "generated_at": "2026-03-02T00:00:00.000Z"
}
```

## Setup

1. Install Wrangler and log in.
2. From this folder, configure secrets:

```bash
wrangler secret put PIRSCH_CLIENT_ID
wrangler secret put PIRSCH_CLIENT_SECRET
wrangler secret put PIRSCH_DOMAIN_ID
```

3. Optional vars in `wrangler.toml`:
- `TIMEZONE` (default: `America/Detroit`)
- `COUNTRY_LOOKBACK_DAYS` (default: `30`)
- `ALLOWED_ORIGINS` (optional comma-separated origin allowlist)

4. Deploy:

```bash
wrangler deploy
```

5. Take your worker URL, append `/stats`, then update your site config:

```yaml
enable_footer_stats: true
footer_stats_endpoint: https://<your-worker-domain>/stats
footer_stats_timezone: America/Detroit
```

## How to get Pirsch domain ID

Use your Pirsch API token flow and query domains:

```bash
curl -s -H "Authorization: Bearer <ACCESS_TOKEN>" https://api.pirsch.io/api/v1/domain
```

Use the correct domain ID from that response as `PIRSCH_DOMAIN_ID`.

## Privacy

This worker only returns aggregated analytics metrics.
It does not return or store raw IP addresses.
