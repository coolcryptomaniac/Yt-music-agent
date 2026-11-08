-- Private data only lives in Cloudflare D1, never in the public Git repository.
CREATE TABLE IF NOT EXISTS payouts (
  id TEXT PRIMARY KEY,
  payment_date TEXT NOT NULL,
  gross_paise INTEGER NOT NULL,
  tds_paise INTEGER NOT NULL,
  net_paise INTEGER NOT NULL,
  bank_verified INTEGER NOT NULL DEFAULT 0,
  transaction_reference TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS royalty_lines (
  id TEXT PRIMARY KEY,
  period TEXT NOT NULL,
  platform TEXT NOT NULL,
  isrc TEXT,
  title TEXT,
  streams INTEGER,
  platform_gross_paise INTEGER,
  artist_reported_paise INTEGER,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_royalties_period ON royalty_lines(period, platform);
CREATE TABLE IF NOT EXISTS audit_flags (
  id TEXT PRIMARY KEY,
  category TEXT NOT NULL,
  severity TEXT NOT NULL,
  explanation TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS observed_videos (
  id TEXT PRIMARY KEY,
  topic TEXT NOT NULL,
  title TEXT NOT NULL,
  channel TEXT,
  published_at TEXT,
  views INTEGER,
  captured_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_videos_topic ON observed_videos(topic, captured_at);
CREATE TABLE IF NOT EXISTS channel_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  subscribers INTEGER,
  views INTEGER,
  videos INTEGER,
  captured_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS publish_queue (
  id TEXT PRIMARY KEY,
  platform TEXT NOT NULL CHECK(platform IN ('instagram', 'youtube')),
  title TEXT NOT NULL,
  caption TEXT NOT NULL,
  media_url TEXT,
  r2_key TEXT,
  scheduled_at TEXT NOT NULL,
  rights_verified INTEGER NOT NULL DEFAULT 0,
  approved_by TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  provider_job_id TEXT,
  provider_post_id TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_publish_due ON publish_queue(status, scheduled_at);
CREATE TABLE IF NOT EXISTS autopilot_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task TEXT NOT NULL,
  status TEXT NOT NULL,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
