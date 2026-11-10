# Vusic Music Career Autopilot (Cloudflare Worker)

**Status: deployment-ready skeleton; not deployed, not connected to private accounts.**
Extends the existing Python `Yt-music-agent` video-production pipeline with a low-cost Cloudflare edge scheduler.
It runs every **two hours**; it does not pretend that streaming services update royalty reports that frequently.

## Supported

- Import Vusic monthly **payout records** and detailed per-ISRC/territory royalty records from authorized CSV/JSON exports. Import is an authenticated JSON endpoint, NOT a login scraper.
- Flag any payout whose gross minus TDS differs from net, and unusual deduction rates for **review** (not allegations of fraud). Bank credits must be confirmed separately.
- Track public YouTube search trends in the niches you choose and public channel statistics, using the official YouTube Data API (optional).
- Queue owned/rights-cleared **pre-rendered** reels and music videos. Explicit human approval + `AUTO_PUBLISH=true` is required to publish.
- Instagram professional account reels: official Meta Graph API multi-step container publishing with a public HTTPS video URL.
- YouTube: official OAuth upload of R2-hosted MP4, initially **private**; review in YouTube Studio before making public. Rights verification required.
- Prevent unintentional duplicate posts: after ambiguous publish responses, a queued item becomes `needs_review`, not automatically retried.

## Not supported / deliberately excluded

- No CAPTCHAs, anti-bot, 2FA, or login controls are bypassed. **Never upload usernames, passwords, browser cookies or 2FA recovery codes.**
- No Suno browser scraping or unofficial client impersonation from a data center. Suno now has an **official MCP beta**: `https://api.suno.com/mcp`. Connect via its supported OAuth sign-in, and keep song-creation rights/proof in a separate approved content pipeline. It is not a generic unauthenticated REST endpoint.
- No unauthorized Vusic access: no documented public Vusic royalty API was established. Request authenticated CSV exports or an official partner API. Future supported connectors can call `POST /ingest/*`.
- No purchased/faked listens, accounts, comments, bot engagement, mass following, misleading metadata or repetitive spam uploads.
- No assumption of a fixed royalty-per-stream price. Rates depend on territory, revenue type and your signed Vusic plan.
- No public upload until you have inspected the clip and verified music rights, especially for Suno AI audio and Content ID eligibility.

## Deployment (requires your Cloudflare and OAuth authorization)

```bash
cd autopilot
npx wrangler d1 create vusic-music-autopilot
# Replace REPLACE_WITH_YOUR_D1_DATABASE_ID in wrangler.toml with generated ID
npx wrangler r2 bucket create music-autopilot-videos
npx wrangler d1 execute vusic-music-autopilot --remote --file=schema.sql
npx wrangler secret put ADMIN_TOKEN      # long random secret; never commit it
npx wrangler secret put YOUTUBE_API_KEY  # optional read-only trends
npx wrangler deploy
```

To read YouTube channel statistics set `YOUTUBE_CHANNEL_ID` as a Worker configuration variable.
To enable YouTube MP4 uploads set secrets `YOUTUBE_REFRESH_TOKEN`, `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`; the refresh token must have been obtained by your own OAuth consent with `youtube.upload` scope. YouTube videos are initially private.

For Instagram, use an Instagram **Professional** account and Meta's supported official connection flow. Set `INSTAGRAM_USER_ID` and secret `META_ACCESS_TOKEN`, with suitable content publishing permissions. The video must already exist at a publicly reachable HTTPS URL; URL authentication or browser sessions will not work. `META_GRAPH_VERSION` is optional; default `v25.0`. Test scopes and eligibility before enabling publishing.

Once OAuth access is verified, and you explicitly wish to activate approved-queue publishing, set `AUTO_PUBLISH = "true"` in the Worker configuration and redeploy. Queue jobs still require explicit `rights_verified: true` and approver metadata. Nothing publishes automatically from this repository alone.

## API examples (ADMIN_TOKEN must remain private)

Import monthly payouts:

```bash
curl -X POST "https://YOUR-WORKER.workers.dev/ingest/payouts" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"records":[{"id":"example-2026-10","payment_date":"2026-10-05","royalty":"100.00","tds":"10.00","net":"90.00"}]}'
```

Import royalty details (source must be a trusted platform or Vusic report, not estimated streams):

```json
{"records":[{"id":"ytugc-2026-09-ISRCEXAMPLE","period":"2026-09","platform":"YouTube UGC","isrc":"ISRCEXAMPLE","title":"Example","streams":10000,"platform_gross":"200.00","artist_reported":"160.00","source":"authorized-vusic-export"}]}
```

`GET /audit`, `GET /trends`, `GET /queue` all require the same Bearer authorization.

Add a post to the queue:

```json
{"platform":"instagram","title":"Original Rave Reel","caption":"New original music by Mohit Pandey","media_url":"https://YOUR-CDN/reel.mp4","scheduled_at":"2026-11-15T12:00:00Z"}
```

An authenticated `POST /queue/<ID>/approve` with
`{"rights_verified":true,"approved_by":"account-owner"}` marks it ready. YouTube jobs use `platform:"youtube"` and `r2_key:"music/reel.mp4"` rather than `media_url`.


## Automated creative planning, media generation and publishing path

Every two-hour cycle generates **at most one new original music/video brief per UTC day** by default (maximum two configured via `DAILY_IDEA_LIMIT`). Repeated cycle invocations are idempotent. An authorized call to `GET /creative/briefs` shows the latest Suno-style music prompts, video prompts, hooks, 9:16 Short/Reel specifications and 16:9 full-length specifications.

These ideas require **zero AI-generation credits**. Creating a prompt is not creating an audio recording or film. For each proposed track, the operator or an authorized Suno MCP client must generate a small number of candidates, check music rights, download the finished track using Suno's approved flow and hand it to the existing `Yt-music-agent` Python/FFmpeg renderer for a story-led video. The finished file can be uploaded to Cloudflare R2 and added via the authenticated `POST /queue` endpoint, reviewed, then published through the already-integrated YouTube/Meta official APIs after proper OAuth and `AUTO_PUBLISH=true`.

**Suno MCP requires user authorization** using `https://api.suno.com/mcp`. It is not yet connected to Cloudflare Workers; no MCP proxy credentials or undocumented API endpoints should be assumed. Suno uses plan credits and paid-plan output licensing for commercial releases. Avoid free-tier commercial releases and AI covers that lack rights.

**Vusic:** Until Vusic confirms an official royalty export or API, import authorized reports manually through authenticated `POST /ingest/payouts` and `POST /ingest/royalties`. Automatic third-party account login, CAPTCHA bypass, and scrape-based release submission are deliberately excluded.

**Instagram:** Linking a professional account and app publishing permissions is mandatory; the user's currently connected Metricool plugin has no linked social accounts. Connect them in Metricool or create official Meta OAuth credentials if using this Worker directly.

**YouTube:** Uploaded videos are first created private and require review. Every music upload needs correct rights and disclosure decisions. Long videos should be rendered on a machine or job runner with FFmpeg; the Worker is a scheduler and API orchestrator, not a GPU renderer.

Budget discipline: Generate one genuine music experiment at a time, reuse existing commercially authorized tracks when possible, and review metrics before spending Suno credits or booking paid media.

## Contract-rate review and bank confirmation

Only if you know your **signed** Vusic plan and know that the exported `platform_gross` is before the contractual distributor share, set `CONTRACT_SHARE_STREAMING` and `CONTRACT_SHARE_CONTENT_ID` in the Worker configuration (for example `0.85` for an 85% artist share). The Worker compares these indicative expectations against imported artist royalties with a 2.5% or ₹1 tolerance and marks discrepancies for investigation. These rates are deliberately unset by default; foreign exchange, returns, withheld amounts, or a differently defined gross base can explain a flag.

To mark an individual payment as received **after checking a bank statement**, call authenticated `POST /payouts/<ID>/verify-bank` with `{"receipt_confirmed":true}`. Never automatically equate Vusic's `net payable` with cash received.

## Vusic audit request and research requirements

Collect **all** monthly statement exports with: original platform, store product, month earned, month reported, ISRC, UPC, country, usage type, paid stream count, gross platform amount, deductions, exchange rate, Vusic commission, artist share, Content ID claim ID, payment ID and TDS proof (Form 16A / Form 26AS / AIS as relevant). Only then compare against independent Spotify for Artists, YouTube Studio / Analytics or other authorized reports. Some aggregator data is delayed and may not exactly mirror platform dashboards.

Vusic's publicly listed streaming revenue shares vary by plan (roughly 80–90%). Do not calculate claims using an assumed plan or apply a second commission against already-net dashboard revenue.

## Operating policy

Two-hour checks are for new trends, queued approved posts and operational health. Royalty reconciliation should occur on **new statements** or monthly, not every two hours. Keep an independent reconciliation ledger, minimize API calls, and treat suspicious data as a review item until evidence is available. Keep your existing Python visualizer/FFmpeg pipeline for media rendering and use R2 only for finished approved video uploads.

## Important security details

Use Cloudflare Worker secrets or an OAuth connector. Limit sharing to account owner. Never store passwords in source, D1, R2 or GitHub Actions. Rotate access tokens as necessary, separate production and test environments, and enable API logs with privacy protections. For stronger controls later add Cloudflare Access authentication, per-platform scopes and D1 migration versioning.
